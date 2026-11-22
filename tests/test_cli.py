import json

import pytest
from typer.testing import CliRunner

from cross_exam import __version__
from cross_exam.cli import app, task_name

runner = CliRunner()


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "CROSS_EXAM_MODEL"):
        monkeypatch.delenv(key, raising=False)


def check_args(files, db, *extra):
    return [
        "check", "--criteria", str(files["criteria"]), "--claims", str(files["transcript"]),
        "--repo", str(files["repo"]), "--diff", str(files["diff"]), "--db", str(db), *extra,
    ]  # fmt: skip


def test_check_fails_on_a_lie_and_records_it(demo_files, tmp_path):
    db = tmp_path / "board.db"
    result = runner.invoke(app, check_args(demo_files, db))
    assert result.exit_code == 1, result.output
    assert "CONTRADICTED" in result.output and "silently skipped" in result.output
    board = runner.invoke(app, ["board", "--db", str(db), "--json", "--history", "5"])
    data = json.loads(board.output)
    assert data["board"][0]["agent"] == "claude-code/scripted-agent"
    assert data["history"][0]["task"] == "add slugify() to slugkit"
    table = runner.invoke(app, ["board", "--db", str(db), "--history", "5"])
    assert table.exit_code == 0 and "Recent runs" in table.output


def test_check_json_no_strict_no_record(demo_files, tmp_path):
    db = tmp_path / "board.db"
    args = check_args(demo_files, db, "--json", "--no-strict", "--no-record", "--agent", "me/model")
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["agent"] == "me/model"
    assert report["scores"]["contradicted"] == 1
    assert not db.exists()


def test_summary_markdown_input(demo_files, tmp_path):
    args = check_args(demo_files, tmp_path / "b.db", "--json", "--no-strict")
    args[args.index(str(demo_files["transcript"]))] = str(demo_files["summary"])
    report = json.loads(runner.invoke(app, args).output)
    assert report["agent"] == "unknown"
    assert len(report["claims"]) == 4


def test_diff_and_base_are_exclusive(demo_files, tmp_path):
    result = runner.invoke(app, [*check_args(demo_files, tmp_path / "b.db"), "--base", "HEAD"])
    assert result.exit_code == 2


def test_bad_base_is_a_clean_error(demo_files, tmp_path):
    args = check_args(demo_files, tmp_path / "b.db")
    i = args.index("--diff")
    del args[i : i + 2]
    result = runner.invoke(app, [*args, "--base", "HEAD"])  # demo repo is not a git repo
    assert result.exit_code == 2
    assert "git diff HEAD failed" in result.output


def test_empty_transcript_is_rejected(demo_files, tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    args = check_args(demo_files, tmp_path / "b.db")
    args[args.index(str(demo_files["transcript"]))] = str(empty)
    assert runner.invoke(app, args).exit_code == 2


def test_board_without_db(tmp_path):
    result = runner.invoke(app, ["board", "--db", str(tmp_path / "none.db")])
    assert result.exit_code == 1


def test_demo_json():
    result = runner.invoke(app, ["demo", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert [c["verdict"] for c in data["report"]["claims"]] == ["VERIFIED", "CONTRADICTED", "VERIFIED", "UNVERIFIABLE"]
    assert data["board"][0]["runs"] == 1


def test_demo_interactive_overrule(tmp_path):
    result = runner.invoke(app, ["demo", "-i", "--keep", str(tmp_path / "d")], input="v\nwatched it in a terminal\n")
    assert result.exit_code == 0, result.output
    assert "VERIFIED (human)" in result.output
    assert (tmp_path / "d" / "criteria.md").exists()


def test_version_and_graph():
    assert runner.invoke(app, ["version"]).output.strip() == __version__
    assert "verify" in runner.invoke(app, ["graph"]).output


def test_task_name():
    assert task_name("# Task: do it\n- [ ] x", "f") == "do it"
    assert task_name("## Fix login\n", "f") == "Fix login"
    assert task_name("- [ ] x", "fallback") == "fallback"
