from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from cross_exam import fixture
from cross_exam.graph import ExamDeps
from cross_exam.inputs import parse_criteria
from cross_exam.llm.demo_script import demo_llm
from cross_exam.models import Report
from cross_exam.runner import examine
from cross_exam.store import Board
from cross_exam.verifiers import Sandbox

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


@pytest.fixture
def demo_files(tmp_path: Path) -> dict[str, Path]:
    return fixture.build(tmp_path / "demo")


def run_demo(files: dict[str, Path], llm=None, board: Board | None = None, **kwargs) -> Report:
    """Examine the demo fixture through the real graph (offline, scripted examiner)."""
    diff = files["diff"].read_text()
    node_timeout = kwargs.pop("node_timeout", 60.0)
    resolve = kwargs.pop("resolve", None)
    patch = kwargs.pop("patch", None)
    with Sandbox(files["repo"], diff=diff, timeout=30.0) as sandbox:
        if patch is not None:
            patch(sandbox)
        deps = ExamDeps(llm=llm or demo_llm(), sandbox=sandbox, board=board, node_timeout=node_timeout, **kwargs)
        return asyncio.run(
            examine(
                deps,
                criteria=parse_criteria(fixture.CRITERIA),
                summary=fixture.SUMMARY,
                diff=diff,
                agent="scripted-agent",
                task="demo",
                resolve=resolve,
            )
        )


@pytest.fixture
def demo_report(demo_files: dict[str, Path]) -> Report:
    return run_demo(demo_files)
