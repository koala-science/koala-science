"""Structural checks on the relevance eval set.

The eval itself needs a live key and costs money, so CI cannot run it. What CI
can do is stop the case set from rotting: duplicate ids, a tier that no longer
exists, or a set that has quietly drifted to all-passes would each make the eval
look healthy while measuring nothing.
"""
from evals.relevance_cases import CASES, TIERS


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
    """A set that is nearly all one verdict measures one direction only, and the
    failure mode worth catching here is a check that passes everything."""
    scored = [c for c in CASES if c.expected is not None]
    passes = sum(1 for c in scored if c.expected)
    fails = len(scored) - passes
    assert passes >= 10 and fails >= 10, f"{passes} pass / {fails} fail"


def test_anchors_cover_both_verdicts():
    """Anchors are what the stability run asserts on, so they have to be able to
    catch drift in either direction."""
    anchors = [c for c in CASES if c.tier == "anchor"]
    assert len(anchors) >= 4
    assert any(c.expected for c in anchors)
    assert any(c.expected is False for c in anchors)


def test_both_sides_of_each_paired_probe_are_present():
    """These pairs differ in one respect and must land on opposite verdicts. They
    are the cases that caught the two real prompt bugs, so losing half of a pair
    silently would remove the guard."""
    pairs = [
        ("figure-blocks-eval", "font-size"),
        ("adoption-with-reason", "adoption-no-reason"),
        ("sign-error", "typo"),
    ]
    by_id = {c.id: c for c in CASES}
    for passing, failing in pairs:
        assert by_id[passing].expected is True, passing
        assert by_id[failing].expected is False, failing


def test_praise_cases_exist_on_both_sides():
    """Route 3 is the only route positive arguments can take, so praise needs
    coverage in both directions of its own."""
    praise = [c for c in CASES if c.position == "positive" and c.expected is not None]
    assert any(c.expected for c in praise)
    assert any(c.expected is False for c in praise)
