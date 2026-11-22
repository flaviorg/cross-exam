import json
import subprocess

import pytest

from cross_exam import fixture
from cross_exam.inputs import added_lines, git_diff, parse_criteria, quoted_in, read_claims, read_transcript
from cross_exam.prompts import changed_files


def test_checkboxes_win_over_other_bullets():
    text = "Intro\n\n- not a criterion\n- [ ] first\n- [x] second\n* [ ] third\n"
    assert [(c.id, c.text) for c in parse_criteria(text)] == [("C1", "first"), ("C2", "second"), ("C3", "third")]


def test_plain_bullets_and_numbers_when_no_checkboxes():
    text = "1. one\n2) two\n- three\n+ four\nnot an item\n"
    assert [c.text for c in parse_criteria(text)] == ["one", "two", "three", "four"]


def test_code_blocks_are_ignored():
    text = "- [ ] real\n```\n- [ ] inside code\n```\n"
    assert [c.text for c in parse_criteria(text)] == ["real"]


def test_demo_criteria():
    assert len(parse_criteria(fixture.CRITERIA)) == 3


def test_transcript_takes_last_assistant_text_and_model(tmp_path):
    path = tmp_path / "s.jsonl"
    rows = [
        {"type": "assistant", "message": {"model": "m1", "content": "early"}},
        "not json",
        {"type": "assistant", "message": {"model": "m2", "content": [{"type": "tool_use", "name": "x"}]}},
        {"type": "assistant", "message": {"model": "m2", "content": [{"type": "text", "text": "final words"}]}},
        {"type": "user", "message": {"content": "thanks"}},
    ]
    path.write_text("\n".join(r if isinstance(r, str) else json.dumps(r) for r in rows))
    msg = read_transcript(path)
    assert (msg.text, msg.model) == ("final words", "m2")


def test_read_claims_by_suffix(tmp_path):
    md = tmp_path / "s.md"
    md.write_text("hello")
    assert read_claims(md).text == "hello"
    jl = tmp_path / "s.jsonl"
    jl.write_text(fixture.transcript())
    assert read_claims(jl).text == fixture.SUMMARY.strip()
    assert read_claims(jl).model == fixture.AGENT_MODEL


def test_quotes_must_really_be_in_the_summary():
    assert quoted_in("all  TESTS pass", "Done. All tests pass.")
    assert quoted_in("All tests pass.", "All tests pass!")
    assert not quoted_in("All tests and lint pass", "All tests pass.")
    assert not quoted_in("  ", "anything")


def test_added_lines_and_changed_files():
    diff = fixture.diff()
    assert any("--verbose" in line for line in added_lines(diff))
    assert not any(line.startswith("++") for line in added_lines(diff))
    assert changed_files(diff) == ["slugkit/cli.py", "slugkit/slug.py", "tests/test_slug.py"]


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args], check=True, capture_output=True)


def test_git_diff_includes_uncommitted_work(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "a.txt").write_text("one\n")
    git(repo, "add", ".")
    git(repo, "-c", "user.name=T", "-c", "user.email=t@example.invalid", "commit", "-qm", "init")
    (repo / "a.txt").write_text("one\ntwo\n")
    assert "+two" in git_diff(repo, "HEAD")
    with pytest.raises(ValueError, match="not a git ref"):
        git_diff(repo, "--output=x")
    with pytest.raises(ValueError, match="failed"):
        git_diff(repo, "no-such-ref")
