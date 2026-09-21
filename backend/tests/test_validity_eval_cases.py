"""Structural checks on the validity eval set — see test_relevance_eval_cases."""
from evals.relevance_cases import TIERS
from evals.run_check import SUITES
from evals.validity_cases import CASES


def test_ids_are_unique():
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))


def test_tiers_are_known():
    assert {c.tier for c in CASES} <= set(TIERS)


def test_every_case_says_why_it_exists():
    for case in CASES:
        assert case.note.strip(), case.id
        assert case.claim.strip() and case.evidence.strip(), case.id
        assert case.position in {"positive", "negative"}, case.id


def test_scored_cases_are_balanced():
    scored = [c for c in CASES if c.expected is not None]
    passes = sum(1 for c in scored if c.expected)
    fails = len(scored) - passes
    assert passes >= 5 and fails >= 5, f"{passes} pass / {fails} fail"


def test_anchors_cover_both_verdicts():
    anchors = [c for c in CASES if c.tier == "anchor"]
    assert any(c.expected for c in anchors)
    assert any(c.expected is False for c in anchors)


def test_both_sides_of_each_paired_probe_are_present():
    """Each pair differs in one respect the new definition turns on: chained vs
    bundled, a defined vs an undefined acronym, a located vs a bare pointer."""
    pairs = [
        ("chained-baseline", "bundled-no-evidence"),
        ("defined-acronym", "undefined-acronym"),
        ("common-acronym", "undefined-acronym"),
        ("located-pointer", "bare-pointer"),
        ("no-retrieval-baseline", "wrong-position"),
    ]
    by_id = {c.id: c for c in CASES}
    for passing, failing in pairs:
        assert by_id[passing].expected is True, passing
        assert by_id[failing].expected is False, failing


def test_the_runner_reaches_this_set():
    """The runner is the only consumer of these cases; a set it cannot reach is
    an eval nobody runs."""
    assert SUITES["validity"][1] is CASES
