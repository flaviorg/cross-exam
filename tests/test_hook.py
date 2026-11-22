import json
import os
import subprocess
import sys
from pathlib import Path

from cross_exam import fixture
from tests.conftest import EXAMPLES

HOOK = EXAMPLES / "hooks" / "stop_hook.py"


def git(repo, *args):
    identity = ["-c", "user.name=T", "-c", "user.email=t@example.invalid"]
    cmd = ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *identity, *args]
    subprocess.run(cmd, check=True, capture_output=True)


def hook(event, cwd):
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "CROSS_EXAM_CRITERIA")}
    env["CROSS_EXAM_MODEL"] = "fake"
    env["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{env.get('PATH', '')}"
    out = subprocess.run(
        [sys.executable, str(HOOK)], input=json.dumps(event), capture_output=True, text=True, env=env, cwd=cwd
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def project(tmp_path):
    """A git repo at the 'before' state with the agent's change left uncommitted, plus criteria."""
    repo = tmp_path / "proj"
    for rel, text in fixture.BEFORE.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "before")
    for rel, text in fixture.AFTER.items():
        (repo / rel).write_text(text)
    (repo / ".cross-exam").mkdir()
    (repo / ".cross-exam" / "criteria.md").write_text(fixture.CRITERIA)
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(fixture.transcript())
    return repo, transcript


def test_hook_blocks_a_false_done(tmp_path):
    repo, transcript = project(tmp_path)
    out = hook({"cwd": str(repo), "transcript_path": str(transcript), "stop_hook_active": False}, repo)
    decision = json.loads(out)
    assert decision["decision"] == "block"
    assert "All tests pass." in decision["reason"]
    assert "C3" in decision["reason"]
    assert (repo / ".cross-exam" / "board.db").exists()


def test_hook_never_blocks_twice(tmp_path):
    repo, transcript = project(tmp_path)
    assert hook({"cwd": str(repo), "transcript_path": str(transcript), "stop_hook_active": True}, repo) == ""


def test_hook_is_a_no_op_without_criteria(tmp_path):
    repo, transcript = project(tmp_path)
    (repo / ".cross-exam" / "criteria.md").unlink()
    assert hook({"cwd": str(repo), "transcript_path": str(transcript)}, repo) == ""
