"""Run one examination end to end, answering review interrupts through a callback."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from langgraph.types import Command

from cross_exam.graph import ExamDeps, build_graph, initial_state
from cross_exam.models import Criterion, Report

Resolver = Callable[[dict[str, Any]], Any]


async def examine(
    deps: ExamDeps,
    *,
    criteria: list[Criterion],
    summary: str,
    diff: str = "",
    agent: str = "unknown",
    task: str = "",
    resolve: Resolver | None = None,
    max_rounds: int = 5,
) -> Report:
    """``resolve`` gets each review interrupt payload and returns the resume value. Without one (or
    after ``max_rounds`` invalid answers) every UNVERIFIABLE verdict stands."""
    app = build_graph(deps)
    config = {"configurable": {"thread_id": f"exam-{uuid.uuid4().hex[:8]}"}}
    out = await app.ainvoke(initial_state(task, agent, criteria, summary, diff), config)
    rounds = 0
    while out.get("__interrupt__"):
        payload = out["__interrupt__"][0].value
        rounds += 1
        if rounds > max_rounds + 1:
            raise RuntimeError("review interrupt was never answered with a valid decision")
        keep_all = {"overrules": {}}
        answer = resolve(payload) if resolve is not None and rounds <= max_rounds else keep_all
        out = await app.ainvoke(Command(resume=answer or keep_all), config)
    return Report.model_validate(out["report"])
