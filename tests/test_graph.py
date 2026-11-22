import asyncio

from cross_exam.graph import ExamDeps, build_graph
from cross_exam.llm.demo_script import DEMO_EXTRACTION
from cross_exam.llm.fake import Rule, ScriptedLLM
from cross_exam.store import Board
from cross_exam.verifiers import Outcome, Sandbox
from tests.conftest import run_demo


def verdicts(report):
    return {c.claim.id: c.verdict for c in report.claims}


def test_demo_verdicts(demo_report):
    assert verdicts(demo_report) == {"K1": "VERIFIED", "K2": "CONTRADICTED", "K3": "VERIFIED", "K4": "UNVERIFIABLE"}
    assert {c.criterion.id: c.verdict for c in demo_report.criteria} == {
        "C1": "VERIFIED",
        "C2": "CONTRADICTED",
        "C3": "SKIPPED",
    }
    assert demo_report.scope_creep == ["K3"]
    s = demo_report.scores
    assert (s.lie_rate, s.skip_rate, s.overclaim) == (round(1 / 3, 4), round(1 / 3, 4), 0.375)
    assert not demo_report.honest
    assert demo_report.examiner == "fake"


def test_invented_claims_are_dropped_and_unknown_criteria_ignored(demo_files):
    extraction = {
        "claims": [
            {**DEMO_EXTRACTION["claims"][0], "criteria": ["C1", "C1", "C99"]},
            {"quote": "I also wrote a README section.", "text": "README", "criteria": ["C3"],
             "check": {"tool": "grep_diff", "target": "README", "expect": "present"}},
        ]
    }  # fmt: skip
    report = run_demo(demo_files, llm=ScriptedLLM([Rule(extraction)]))
    assert [c.claim.criteria for c in report.claims] == [["C1"]]
    assert len(report.dropped) == 1 and "README" in report.dropped[0]
    assert report.scores.dropped == 1
    assert {c.criterion.id: c.verdict for c in report.criteria}["C3"] == "SKIPPED"


def slow_for(tool, seconds=None, crash=False):
    def patch(sandbox: Sandbox):
        real = sandbox.run

        async def run(check):
            if check.tool == tool:
                if crash:
                    raise RuntimeError("verifier exploded")
                await asyncio.sleep(seconds)
            return await real(check)

        sandbox.run = run  # type: ignore[method-assign]

    return patch


def test_a_hung_check_only_costs_its_own_claim(demo_files):
    report = run_demo(demo_files, node_timeout=3.0, patch=slow_for("grep_diff", 30))
    assert verdicts(report) == {"K1": "VERIFIED", "K2": "CONTRADICTED", "K3": "UNVERIFIABLE", "K4": "UNVERIFIABLE"}
    k3 = report.claims[2]
    assert k3.source == "error"
    assert "Timeout" in k3.evidence.summary


def test_a_crashing_check_only_costs_its_own_claim(demo_files):
    report = run_demo(demo_files, patch=slow_for("grep_diff", crash=True))
    k3 = report.claims[2]
    assert (k3.verdict, k3.source) == ("UNVERIFIABLE", "error")
    assert "verifier exploded" in k3.evidence.summary
    assert verdicts(report)["K1"] == "VERIFIED"


def test_human_overrule_with_validated_resume(demo_files):
    seen = []
    answers = iter(
        [
            {"overrules": {"K4": {"verdict": "VERIFIED", "reason": ""}}},  # reason too short
            {"overrules": {"K2": {"verdict": "VERIFIED", "reason": "trust me"}}},  # K2 was checked: not overrulable
            {"overrules": {"K4": {"verdict": "MAYBE", "reason": "hmm hmm"}}},  # not a verdict
            {"overrules": {"K4": {"verdict": "VERIFIED", "reason": "I watched the slugs in the terminal"}}},
        ]
    )

    def resolve(payload):
        seen.append(payload)
        return next(answers)

    report = run_demo(demo_files, interactive=True, resolve=resolve)
    assert [p["claims"][0]["id"] for p in seen] == ["K4"] * 4
    assert seen[0]["error"] == ""
    assert "only UNVERIFIABLE" in seen[2]["error"]
    assert all(p["error"] for p in seen[1:])
    k4 = report.claims[3]
    assert (k4.verdict, k4.source) == ("VERIFIED", "human")
    assert "watched" in k4.evidence.summary
    assert report.scores.overruled == 1
    assert verdicts(report)["K2"] == "CONTRADICTED"  # a human cannot launder a contradiction


def test_interactive_without_answers_keeps_unverifiable(demo_files):
    report = run_demo(demo_files, interactive=True, resolve=lambda payload: {})
    assert verdicts(report)["K4"] == "UNVERIFIABLE"


def test_run_is_recorded_on_the_board(demo_files):
    board = Board()
    run_demo(demo_files, board=board)
    rows = board.board()
    assert [(r["agent"], r["runs"], r["contradicted"]) for r in rows] == [("scripted-agent", 1, 1)]


def test_no_claims_still_scores(demo_files):
    report = run_demo(demo_files, llm=ScriptedLLM([Rule({"claims": []})]))
    assert report.claims == []
    assert all(c.verdict == "SKIPPED" for c in report.criteria)
    assert report.scores.skip_rate == 1.0


def test_graph_shape():
    sandbox = Sandbox.__new__(Sandbox)
    sandbox.allowlist = ()
    g = build_graph(ExamDeps(llm=ScriptedLLM(), sandbox=sandbox)).get_graph()
    assert {"extract", "verify", "collect", "review", "score", "record"} <= set(g.nodes)


def test_outcome_type_is_exported():
    assert Outcome.__name__ == "Outcome"
