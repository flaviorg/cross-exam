"""Offline stand-ins for the examiner model.

``ScriptedLLM`` answers from rules matched on prompt text (never on call order, so it is stateless and
deterministic). With no matching rule it falls back to ``heuristic_extraction``: bullets/sentences become
claims, criteria are matched by word overlap, "tests pass" becomes ``run_test``, a backticked path becomes
``file_exists`` and everything else is ``none`` (UNVERIFIABLE). That keeps ``--model fake`` useful on any
repo without a key, and honest about what it could not check.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from cross_exam.llm.port import LLMReply, T
from cross_exam.models import Check, Extraction, ProposedClaim


@dataclass(frozen=True)
class Rule:
    respond: dict[str, Any]
    when: tuple[str, ...] = ()

    def matches(self, prompt: str) -> bool:
        return all(s in prompt for s in self.when)


@dataclass
class ScriptedLLM:
    rules: list[Rule] = field(default_factory=list)
    name: str = "fake"
    calls: list[str] = field(default_factory=list)

    def structured(self, system: str, user: str, schema: type[T]) -> LLMReply[T]:
        if schema is not Extraction:
            raise TypeError(f"ScriptedLLM has no answers for {schema.__name__}")
        self.calls.append(user)
        rule = next((r for r in self.rules if r.matches(user)), None)
        data = rule.respond if rule else heuristic_extraction(user).model_dump()
        value = schema.model_validate(data)
        tokens = (len(system) + len(user) + len(json.dumps(value.model_dump()))) // 4
        return LLMReply(value, tokens)


# ---- heuristic fallback ------------------------------------------------------------------------

_STOP = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "to",
    "in",
    "on",
    "for",
    "with",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "it",
    "its",
    "this",
    "that",
    "i",
    "we",
    "you",
    "all",
    "any",
    "as",
    "by",
    "at",
    "from",
    "now",
    "so",
    "also",
    "has",
    "have",
    "had",
    "do",
    "does",
    "did",
    "not",
    "no",
    "can",
    "will",
    "should",
    "must",
    "into",
    "out",
    "up",
}
_TESTS_PASS = re.compile(r"\b(all\s+)?(the\s+)?tests?\b.*\b(pass|passing|passed|green)\b", re.IGNORECASE)
_PATH = re.compile(r"`([\w./-]+\.[A-Za-z0-9]+)`")


def _section(prompt: str, title: str) -> str:
    m = re.search(rf"{title}:\n(.*?)(?:\n\n[A-Z ]+[:]|\Z)", prompt, re.DOTALL)
    return m.group(1) if m else ""


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9_]+", text.lower()) if w not in _STOP and len(w) > 2}


def _sentences(summary: str) -> list[str]:
    out: list[str] = []
    for line in summary.splitlines():
        line = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?", "", line).strip()
        if not line or line.endswith(":") or line.startswith("#"):
            continue
        out.extend(p.strip() for p in re.split(r"(?<=[.!])\s+", line) if len(p.strip()) > 8)
    return out


def _related(a: set[str], b: set[str]) -> bool:
    """Two shared words, or one long distinctive one (e.g. 'changelog')."""
    shared = a & b
    return len(shared) >= 2 or any(len(w) >= 7 for w in shared)


def heuristic_extraction(prompt: str) -> Extraction:
    crit_block = _section(prompt, "ACCEPTANCE CRITERIA")
    criteria = dict(re.findall(r"^- (C\d+): (.+)$", crit_block, re.MULTILINE))
    m = re.search(r"AGENT FINAL MESSAGE:\n<<<\n(.*)\n>>>", prompt, re.DOTALL)
    summary = m.group(1) if m else ""
    claims: list[ProposedClaim] = []
    for sentence in _sentences(summary):
        words = _words(sentence)
        mapped = [cid for cid, text in criteria.items() if _related(words, _words(text))]
        if _TESTS_PASS.search(sentence):
            check = Check(tool="run_test", target="", expect="pass")
            mapped = mapped or [cid for cid, text in criteria.items() if _TESTS_PASS.search(text)]
        elif path := _PATH.search(sentence):
            check = Check(tool="file_exists", target=path.group(1), expect="present")
        else:
            check = Check(tool="none", reason="heuristic examiner: no rule for this kind of claim")
        claims.append(ProposedClaim(quote=sentence, text=sentence, criteria=mapped, check=check))
    return Extraction(claims=claims)
