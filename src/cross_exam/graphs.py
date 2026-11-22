"""The graph as Mermaid, drawn from the compiled graph (used by the docs and a drift check)."""

from __future__ import annotations

from pathlib import Path

from cross_exam.graph import ExamDeps, build_graph
from cross_exam.llm.fake import ScriptedLLM
from cross_exam.verifiers import Sandbox


def mermaid() -> str:
    sandbox = Sandbox.__new__(Sandbox)  # no copy needed just to draw the graph
    sandbox.repo = Path(".")
    sandbox.allowlist = ()
    app = build_graph(ExamDeps(llm=ScriptedLLM(), sandbox=sandbox))
    return app.get_graph().draw_mermaid().strip()
