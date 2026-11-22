"""The cross-examination graph.

    extract ──Send×N──▶ verify (one branch per claim, async, timeout + error_handler)
                           └──▶ collect (deferred fan-in) ──▶ review (interrupt?) ──▶ score ──▶ record

The model only appears in ``extract``: it proposes claims, the claim→criterion mapping and one check
per claim. Everything after that is code: the verifiers run the checks, ``scoring`` decides verdicts,
and a human (never the model) may overrule an UNVERIFIABLE verdict in ``review``.
"""

from __future__ import annotations

import asyncio
import operator
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import NodeError
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt
from pydantic import ValidationError

from cross_exam import prompts
from cross_exam.inputs import quoted_in
from cross_exam.llm.port import LLM, LLMError
from cross_exam.models import (
    Claim,
    ClaimResult,
    Criterion,
    Evidence,
    Extraction,
    OverruleDecision,
    Report,
)
from cross_exam.scoring import judge_criteria, score
from cross_exam.store import Board
from cross_exam.verifiers import Sandbox

Event = Callable[[str, dict[str, Any]], None]


class ExamState(TypedDict, total=False):
    task: str
    agent: str
    criteria: list[dict]
    summary: str
    diff: str
    claims: list[dict]
    dropped: list[str]
    tokens: int
    results: Annotated[list[dict], operator.add]
    final: list[dict]
    report: dict


class VerifyInput(TypedDict):
    claim: dict


@dataclass
class ExamDeps:
    llm: LLM
    sandbox: Sandbox
    board: Board | None = None
    interactive: bool = False
    node_timeout: float = 120.0
    on_event: Event = field(default=lambda kind, data: None)


def build_graph(deps: ExamDeps, checkpointer: Any | None = None) -> Any:
    async def extract(state: ExamState) -> dict:
        criteria = [Criterion.model_validate(c) for c in state["criteria"]]
        summary = state["summary"]
        user = prompts.user_prompt(
            criteria, summary, prompts.changed_files(state.get("diff", "")), deps.sandbox.allowlist
        )
        try:
            reply = await asyncio.to_thread(deps.llm.structured, prompts.SYSTEM, user, Extraction)
        except LLMError as exc:
            raise RuntimeError(f"examiner model failed: {exc}") from exc
        known = {c.id for c in criteria}
        claims: list[dict] = []
        dropped: list[str] = []
        for proposed in reply.value.claims:
            if not quoted_in(proposed.quote, summary):
                dropped.append(f"not in the agent's message (model invented it?): {proposed.quote!r}")
                continue
            claim = Claim(
                id=f"K{len(claims) + 1}",
                quote=proposed.quote.strip(),
                text=proposed.text.strip() or proposed.quote.strip(),
                criteria=[c for c in dict.fromkeys(proposed.criteria) if c in known],
                check=proposed.check,
            )
            claims.append(claim.model_dump())
        deps.on_event("extracted", {"claims": len(claims), "dropped": len(dropped), "tokens": reply.tokens})
        return {"claims": claims, "dropped": dropped, "tokens": reply.tokens, "results": []}

    def fan_out(state: ExamState) -> list[Send] | str:
        if not state.get("claims"):
            return "collect"
        return [Send("verify", {"claim": c}) for c in state["claims"]]

    async def verify(arg: VerifyInput) -> dict:
        claim = Claim.model_validate(arg["claim"])
        outcome = await deps.sandbox.run(claim.check)
        result = ClaimResult(claim=claim, verdict=outcome.verdict, evidence=outcome.evidence)
        deps.on_event("verified", result.model_dump())
        return {"results": [result.model_dump()]}

    def verify_failed(arg: VerifyInput, error: NodeError) -> dict:
        """A hung or crashed check is UNVERIFIABLE for that claim only; the other branches carry on."""
        claim = Claim.model_validate(arg["claim"])
        cause = getattr(error, "error", error)
        result = ClaimResult(
            claim=claim,
            verdict="UNVERIFIABLE",
            evidence=Evidence(summary=f"check failed: {type(cause).__name__}: {cause}"[:300]),
            source="error",
        )
        deps.on_event("verified", result.model_dump())
        return {"results": [result.model_dump()]}

    def collect(state: ExamState) -> dict:
        order = {c["id"]: i for i, c in enumerate(state.get("claims", []))}
        results = sorted(state.get("results", []), key=lambda r: order.get(r["claim"]["id"], 1 << 30))
        return {"final": results}

    def review(state: ExamState) -> dict:
        results = [ClaimResult.model_validate(r) for r in state.get("final", [])]
        pending = {r.claim.id: r for r in results if r.verdict == "UNVERIFIABLE"}
        if not deps.interactive or not pending:
            return {}
        error = ""
        while True:
            raw = interrupt(
                {
                    "question": "These claims could not be checked. Overrule any? Omit a claim to keep UNVERIFIABLE.",
                    "claims": [
                        {"id": r.claim.id, "quote": r.claim.quote, "why": r.evidence.summary} for r in pending.values()
                    ],
                    "error": error,
                },
                # a dict schema is shown to clients but not enforced: we validate and re-ask ourselves
                response_schema=OverruleDecision.model_json_schema(),
            )
            try:
                decision = OverruleDecision.model_validate(raw)
            except ValidationError as exc:
                error = f"invalid answer: {exc.errors()[0]['msg']}"
                continue
            unknown = sorted(set(decision.overrules) - set(pending))
            if unknown:
                error = f"only UNVERIFIABLE claims can be overruled, not: {', '.join(unknown)}"
                continue
            break
        updated: list[dict] = []
        for r in results:
            o = decision.overrules.get(r.claim.id)
            if o is not None:
                r = r.model_copy(
                    update={
                        "verdict": o.verdict,
                        "source": "human",
                        "evidence": Evidence(summary=f"overruled by a human: {o.reason}", detail=r.evidence.summary),
                    }
                )
            updated.append(r.model_dump())
        return {"final": updated}

    def score_node(state: ExamState) -> dict:
        criteria = [Criterion.model_validate(c) for c in state["criteria"]]
        results = [ClaimResult.model_validate(r) for r in state.get("final", [])]
        judged = judge_criteria(criteria, results)
        dropped = state.get("dropped", [])
        report = Report(
            agent=state.get("agent", "unknown"),
            examiner=deps.llm.name,
            task=state.get("task", ""),
            claims=results,
            criteria=judged,
            scope_creep=[r.claim.id for r in results if not r.claim.criteria],
            dropped=dropped,
            scores=score(judged, results, dropped=len(dropped)),
        )
        return {"report": report.model_dump()}

    def record(state: ExamState) -> dict:
        if deps.board is not None:
            deps.board.add(Report.model_validate(state["report"]), ts=time.time())
        return {}

    g = StateGraph(ExamState)
    g.add_node("extract", extract)
    g.add_node("verify", verify, input_schema=VerifyInput, timeout=deps.node_timeout, error_handler=verify_failed)
    g.add_node("collect", collect, defer=True)
    g.add_node("review", review)
    g.add_node("score", score_node)
    g.add_node("record", record)
    g.add_edge(START, "extract")
    g.add_conditional_edges("extract", fan_out, ["verify", "collect"])
    g.add_edge("verify", "collect")
    g.add_edge("collect", "review")
    g.add_edge("review", "score")
    g.add_edge("score", "record")
    g.add_edge("record", END)
    return g.compile(checkpointer=checkpointer if checkpointer is not None else InMemorySaver())


def initial_state(task: str, agent: str, criteria: list[Criterion], summary: str, diff: str) -> dict[str, Any]:
    return {
        "task": task,
        "agent": agent,
        "criteria": [c.model_dump() for c in criteria],
        "summary": summary,
        "diff": diff,
    }
