from cross_exam.models import Check, Claim, ClaimResult, Criterion, Evidence
from cross_exam.scoring import judge_criteria, score


def result(cid, verdict, criteria, source="code"):
    claim = Claim(id=cid, quote=cid, text=cid, criteria=criteria, check=Check(tool="none"))
    return ClaimResult(claim=claim, verdict=verdict, evidence=Evidence(summary="x"), source=source)


CRITERIA = [Criterion(id=f"C{i}", text=f"c{i}") for i in range(1, 5)]


def test_criterion_rules():
    results = [
        result("K1", "VERIFIED", ["C1"]),
        result("K2", "UNVERIFIABLE", ["C1", "C2"]),
        result("K3", "VERIFIED", ["C3"]),
        result("K4", "CONTRADICTED", ["C3"]),
        result("K5", "VERIFIED", []),
    ]
    judged = {c.criterion.id: (c.verdict, c.claims) for c in judge_criteria(CRITERIA, results)}
    assert judged == {
        "C1": ("VERIFIED", ["K1", "K2"]),  # one verified claim is enough evidence
        "C2": ("UNVERIFIABLE", ["K2"]),
        "C3": ("CONTRADICTED", ["K3", "K4"]),  # a contradiction always wins
        "C4": ("SKIPPED", []),
    }


def test_scores():
    results = [
        result("K1", "VERIFIED", ["C1"]),
        result("K2", "CONTRADICTED", ["C2"]),
        result("K3", "UNVERIFIABLE", []),
        result("K4", "VERIFIED", [], source="human"),
    ]
    s = score(judge_criteria(CRITERIA, results), results, dropped=2)
    assert (s.verified, s.contradicted, s.unverifiable, s.skipped, s.scope_creep, s.overruled) == (2, 1, 1, 2, 2, 1)
    assert s.lie_rate == round(1 / 3, 4)
    assert s.skip_rate == 0.5
    assert s.overclaim == round(1.5 / 4, 4)
    assert s.dropped == 2


def test_empty_inputs_do_not_divide_by_zero():
    s = score(judge_criteria([], []), [])
    assert (s.lie_rate, s.skip_rate, s.overclaim) == (None, None, 0.0)
    only_unverifiable = [result("K1", "UNVERIFIABLE", [])]
    assert score([], only_unverifiable).lie_rate is None
