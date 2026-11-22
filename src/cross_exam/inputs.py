"""Reading the three inputs: acceptance criteria, the agent's final words, and the diff. All code, no model."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from cross_exam.models import Criterion

_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?(?P<text>\S.*?)\s*$")
_CHECKBOX = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\[[ xX]\]\s+")


def parse_criteria(markdown: str) -> list[Criterion]:
    """Acceptance criteria from a markdown checklist or issue body.

    If the text has any ``- [ ]`` checkboxes, only those count (so an issue body's other bullets are
    ignored). Otherwise every bullet or numbered item counts. Ids are ``C1``..``Cn`` in order.
    """
    lines = markdown.splitlines()
    in_code = False
    kept: list[str] = []
    for line in lines:
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if not in_code:
            kept.append(line)
    boxes = any(_CHECKBOX.match(line) for line in kept)
    items: list[str] = []
    for line in kept:
        if boxes and not _CHECKBOX.match(line):
            continue
        m = _ITEM.match(line)
        if m:
            items.append(m.group("text"))
    return [Criterion(id=f"C{i}", text=t) for i, t in enumerate(items, 1)]


@dataclass
class AgentMessage:
    text: str
    model: str | None = None  # the examined agent's model, when the transcript says


def _text_of(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(p for p in parts if p)
    return ""


def read_transcript(path: Path) -> AgentMessage:
    """The last assistant text in a Claude Code session JSONL (one JSON object per line)."""
    last = AgentMessage("")
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        msg = entry.get("message")
        if entry.get("type") != "assistant" or not isinstance(msg, dict):
            continue
        text = _text_of(msg.get("content")).strip()
        if text:
            last = AgentMessage(text, msg.get("model") or last.model)
    return last


def read_claims(path: Path) -> AgentMessage:
    """``.jsonl`` -> transcript; anything else -> the file is the agent's final message."""
    if path.suffix == ".jsonl":
        return read_transcript(path)
    return AgentMessage(path.read_text(encoding="utf-8"))


def git_diff(repo: Path, base: str) -> str:
    """``git diff <base>`` in ``repo`` (working tree against base, so uncommitted work counts too)."""
    if base.startswith("-"):
        raise ValueError(f"not a git ref: {base!r}")
    out = subprocess.run(
        ["git", "-C", str(repo), "diff", "--no-color", "--no-ext-diff", base, "--"],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        raise ValueError(f"git diff {base} failed: {out.stderr.strip()}")
    return out.stdout


def added_lines(diff: str) -> list[str]:
    return [line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]


def normalise(text: str) -> str:
    return " ".join(text.split()).casefold()


def quoted_in(quote: str, summary: str) -> bool:
    """Does the claim's quote really appear in the summary (whitespace/case-insensitive)?"""
    q = normalise(quote).strip(" .\"'`")
    return bool(q) and q in normalise(summary)
