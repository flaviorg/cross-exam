from cross_exam.models import Report
from cross_exam.store import Board


def with_agent(report: Report, agent: str, **scores) -> Report:
    return report.model_copy(update={"agent": agent, "scores": report.scores.model_copy(update=scores)})


def test_board_pools_runs_per_agent(demo_report, tmp_path):
    board = Board(tmp_path / "sub" / "board.db")
    board.add(with_agent(demo_report, "liar"), ts=1)
    board.add(with_agent(demo_report, "liar", contradicted=3, verified=1, skipped=0), ts=2)
    board.add(with_agent(demo_report, "honest", contradicted=0, skipped=0, overclaim=0.0), ts=3)
    board.add(with_agent(demo_report, "silent", verified=0, contradicted=0), ts=4)
    rows = {r["agent"]: r for r in board.board()}
    assert rows["liar"]["runs"] == 2
    assert rows["liar"]["lie_rate"] == (1 + 3) / (2 + 1 + 1 + 3)
    assert rows["liar"]["skip_rate"] == 1 / 6
    assert rows["honest"]["lie_rate"] == 0
    assert rows["silent"]["lie_rate"] is None
    assert [r["agent"] for r in board.board()] == ["honest", "liar", "silent"]
    history = board.history(limit=2)
    assert [h["agent"] for h in history] == ["silent", "honest"]
    assert [h["agent"] for h in board.history("liar")] == ["liar", "liar"]
    board.close()


def test_report_round_trips(demo_report):
    board = Board()
    run_id = board.add(demo_report)
    assert board.report(run_id) == demo_report
    assert board.report(999) is None
