import subprocess
import sys

from cross_exam import fixture
from tests.conftest import EXAMPLES, ROOT


def test_docs_embed_the_current_graph():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gen_graph.py"), "--check"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_example_inputs_match_the_demo_fixture():
    demo = EXAMPLES / "demo"
    assert (demo / "criteria.md").read_text() == fixture.CRITERIA
    assert (demo / "summary.md").read_text() == fixture.SUMMARY
    assert (demo / "session.jsonl").read_text() == fixture.transcript()
    assert (demo / "change.diff").read_text() == fixture.diff()


def test_example_repo_matches_the_demo_fixture():
    repo = EXAMPLES / "demo" / "repo"
    files = {
        str(p.relative_to(repo)): p.read_text() for p in repo.rglob("*") if p.is_file() and "__pycache__" not in str(p)
    }
    assert files == fixture.AFTER
