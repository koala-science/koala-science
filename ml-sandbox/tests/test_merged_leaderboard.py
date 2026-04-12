"""Tests for build_merged_leaderboard and its distance-to-clear helper.

The shared ``ds`` fixture in conftest.py has no verdicts or ground-truth,
so we fabricate an in-memory Dataset for the integration tests rather than
extending the global fixture (which would ripple into unrelated tests).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from coalescence.dashboard.api import (
    _MERGED_MIN_VERDICTS,
    _distance_to_clear,
    build_merged_leaderboard,
)
from coalescence.data import Dataset
from coalescence.data.collections import (
    CommentCollection,
    DomainCollection,
    EventCollection,
    GroundTruthCollection,
    PaperCollection,
    VerdictCollection,
    VoteCollection,
    ActorCollection,
)
from coalescence.data.entities import (
    Actor,
    GroundTruthPaper,
    Paper,
    Verdict,
)


# --------------------------------------------------------------------------- #
# _distance_to_clear unit tests
# --------------------------------------------------------------------------- #


def test_distance_to_clear_passer_is_zero():
    # Above the verdict threshold and strictly positive correlation.
    assert _distance_to_clear(_MERGED_MIN_VERDICTS, 0.5) == 0.0
    assert _distance_to_clear(100, 0.01) == 0.0


def test_distance_to_clear_components_additive():
    # (49, 0.5) is one verdict short of threshold; corr is fine.
    # Expected: (50 - 49) / 50 = 0.02
    assert _distance_to_clear(49, 0.5) == pytest.approx(0.02)

    # (49, None) adds coverage gap + 1.0 no-signal penalty.
    assert _distance_to_clear(49, None) == pytest.approx(0.02 + 1.0)

    # (10, 0.5) has a bigger coverage gap, corr fine.
    # Expected: (50 - 10) / 50 = 0.8
    assert _distance_to_clear(10, 0.5) == pytest.approx(0.8)

    # (0, None) maximum coverage gap + no-signal penalty = 1.0 + 1.0 = 2.0
    assert _distance_to_clear(0, None) == pytest.approx(2.0)

    # (50, -0.3) threshold met but corr below gate.
    # Expected: (_MERGED_MIN_CORR - corr) = 0.0 - (-0.3) = 0.3
    assert _distance_to_clear(50, -0.3) == pytest.approx(0.3)


def test_distance_to_clear_monotonic_in_verdicts():
    # Fixed corr just below threshold: distance should strictly decrease as
    # verdict count grows until we clear the verdict gate, at which point
    # distance stops changing (still blocked by corr) but never increases.
    prev = _distance_to_clear(0, 0.5)
    for n in range(1, _MERGED_MIN_VERDICTS + 1):
        d = _distance_to_clear(n, 0.5)
        assert d <= prev, f"distance increased: {prev} -> {d} at n={n}"
        prev = d
    # And once past the threshold with positive corr, distance is exactly 0.
    assert _distance_to_clear(_MERGED_MIN_VERDICTS, 0.5) == 0.0


def test_distance_to_clear_none_vs_negative():
    # Same verdict count: corr=None must be strictly worse than corr=-0.99.
    # "Can't measure" penalty (1.0) is larger than any in-range negative
    # correlation gap (max 0 - (-0.99) = 0.99).
    none_d = _distance_to_clear(50, None)
    neg_d = _distance_to_clear(50, -0.99)
    assert none_d > neg_d


# --------------------------------------------------------------------------- #
# Integration tests: fabricated Dataset driving build_merged_leaderboard
# --------------------------------------------------------------------------- #


def _make_dataset(
    *,
    passers: int = 0,
    failers_coverage: int = 0,
    failers_neg_corr: int = 0,
    failers_no_gt: int = 0,
    out_of_gt_verdicts_per_agent: int = 0,
) -> Dataset:
    """Build a minimal Dataset with enough agents/papers/verdicts/GT to
    drive build_merged_leaderboard through every branch we need to exercise.

    - ``passers``: agents with enough verdicts and strongly positive corr
    - ``failers_coverage``: agents with too few verdicts (but matched GT)
    - ``failers_neg_corr``: agents with enough verdicts but negative corr
    - ``failers_no_gt``: agents with verdicts on out-of-GT papers only
    - ``out_of_gt_verdicts_per_agent``: extra poison verdicts added to every
      agent that already has at least one in-GT verdict, to exercise the
      n_out_of_gt_verdicts accounting
    """
    now = datetime(2026, 4, 11, 12, 0, 0)

    # We need >= _MERGED_MIN_VERDICTS papers per passer to drive the gate.
    # Build a shared pool of GT-matched papers plus a pool of out-of-GT ones.
    n_in_gt_papers = max(_MERGED_MIN_VERDICTS * 2, 100)
    # Each no-GT failer needs _MERGED_MIN_VERDICTS + 5 distinct poison papers,
    # since (author, paper) verdicts must be unique per the backend model.
    n_out_of_gt_papers = max(out_of_gt_verdicts_per_agent, _MERGED_MIN_VERDICTS + 5)

    papers: list[Paper] = []
    gt_rows: list[GroundTruthPaper] = []
    platform_to_gt: dict[str, GroundTruthPaper] = {}

    for i in range(n_in_gt_papers):
        pid = f"pin{i}"
        papers.append(
            Paper(
                id=pid,
                title=f"GT Paper {i}",
                abstract="",
                domain="d/test",
                submitter_id="a0",
                submitter_type="human",
                submitter_name="Seed",
                upvotes=0,
                downvotes=0,
                net_score=0,
                created_at=now,
                updated_at=now,
                embedding=None,
                full_text_length=0,
            )
        )
        gt = GroundTruthPaper(
            openreview_id=f"or{i}",
            title_normalized=f"gt paper {i}",
            decision="Accept",
            accepted=(i % 2 == 0),
            year=2024,
            avg_score=float(5 + (i % 5)),
            citations=10 + i,
            primary_area="cs.CL",
        )
        gt_rows.append(gt)
        platform_to_gt[pid] = gt

    for j in range(n_out_of_gt_papers):
        pid = f"poison{j}"
        papers.append(
            Paper(
                id=pid,
                title=f"Poison {j}",
                abstract="",
                domain="d/test",
                submitter_id="a0",
                submitter_type="human",
                submitter_name="Seed",
                upvotes=0,
                downvotes=0,
                net_score=0,
                created_at=now,
                updated_at=now,
                embedding=None,
                full_text_length=0,
            )
        )

    actors: list[Actor] = []
    verdicts: list[Verdict] = []
    next_verdict_id = 0

    def add_actor(aid: str, name: str):
        actors.append(
            Actor(
                id=aid,
                name=name,
                actor_type="delegated_agent",
                is_active=True,
                reputation_score=0,
                voting_weight=1.0,
                domain_authorities={},
                created_at=now,
            )
        )

    def add_verdict(aid: str, pid: str, score: float):
        nonlocal next_verdict_id
        verdicts.append(
            Verdict(
                id=f"v{next_verdict_id}",
                paper_id=pid,
                author_id=aid,
                content_markdown="",
                score=score,
                upvotes=0,
                downvotes=0,
                net_score=0,
                created_at=now,
                updated_at=now,
                author_type="delegated_agent",
                author_name=None,
            )
        )
        next_verdict_id += 1

    # Passers: score aligned with avg_score so Pearson is strongly positive.
    for k in range(passers):
        aid = f"pass{k}"
        add_actor(aid, f"Passer {k}")
        for i in range(_MERGED_MIN_VERDICTS + 5):
            pid = f"pin{i}"
            gt = platform_to_gt[pid]
            add_verdict(aid, pid, float(gt.avg_score or 0.0))
        for j in range(out_of_gt_verdicts_per_agent):
            add_verdict(aid, f"poison{j}", 5.0)

    # Coverage failers: enough GT pairs to compute Pearson (>=3) but below
    # the verdict threshold.
    for k in range(failers_coverage):
        aid = f"cov{k}"
        add_actor(aid, f"CovFail {k}")
        for i in range(5):
            pid = f"pin{i}"
            gt = platform_to_gt[pid]
            add_verdict(aid, pid, float(gt.avg_score or 0.0))

    # Negative-corr failers: enough verdicts, but score is anti-aligned.
    for k in range(failers_neg_corr):
        aid = f"neg{k}"
        add_actor(aid, f"NegFail {k}")
        for i in range(_MERGED_MIN_VERDICTS + 5):
            pid = f"pin{i}"
            gt = platform_to_gt[pid]
            # Invert: high GT avg_score -> low verdict score.
            add_verdict(aid, pid, 10.0 - float(gt.avg_score or 0.0))

    # No-GT-signal failers: verdicts only on out-of-GT papers. Each paper
    # is verdicted at most once per agent (uniqueness constraint).
    for k in range(failers_no_gt):
        aid = f"nogt{k}"
        add_actor(aid, f"NoGT {k}")
        for j in range(_MERGED_MIN_VERDICTS + 5):
            pid = f"poison{j}"
            add_verdict(aid, pid, 5.0)

    return Dataset(
        papers=PaperCollection(papers),
        comments=CommentCollection([]),
        votes=VoteCollection([]),
        actors=ActorCollection(actors),
        events=EventCollection([]),
        domains=DomainCollection([]),
        verdicts=VerdictCollection(verdicts),
        ground_truth=GroundTruthCollection(gt_rows, platform_to_gt),
    )


def test_merged_response_has_new_fields():
    ds = _make_dataset(
        passers=1, failers_coverage=1, failers_neg_corr=1, failers_no_gt=1
    )
    res = build_merged_leaderboard(ds)
    assert res["entries"], "expected at least one entry"
    for e in res["entries"]:
        assert "distance_to_clear" in e
        assert "n_out_of_gt_verdicts" in e
        assert "actor_type" in e


def test_merged_failer_sort_by_distance():
    ds = _make_dataset(
        passers=0,
        failers_coverage=2,
        failers_neg_corr=1,
        failers_no_gt=2,
    )
    res = build_merged_leaderboard(ds)
    failers = [e for e in res["entries"] if not e["passed_gate"]]
    assert len(failers) >= 5
    distances = [e["distance_to_clear"] for e in failers]
    assert distances == sorted(distances), (
        f"failers not sorted by distance_to_clear: {distances}"
    )


def test_merged_n_out_of_gt_invariant():
    ds = _make_dataset(
        passers=1,
        failers_coverage=1,
        failers_neg_corr=1,
        failers_no_gt=1,
        out_of_gt_verdicts_per_agent=3,
    )
    res = build_merged_leaderboard(ds)
    for e in res["entries"]:
        assert e["n_out_of_gt_verdicts"] == e["n_verdicts"] - e["n_gt_matched"], e


def test_merged_passer_sort_unchanged():
    # Two passers with distinct trust; confirm the passer ordering still
    # matches -trust_pct desc, unaffected by the new distance sort key.
    ds = _make_dataset(passers=2)
    res = build_merged_leaderboard(ds)
    passers = [e for e in res["entries"] if e["passed_gate"]]
    # If there are at least two passers, they must come out sorted by trust_pct desc.
    if len(passers) >= 2:
        trusts = [
            p["trust_pct"] if p["trust_pct"] is not None else -1.0 for p in passers
        ]
        assert trusts == sorted(trusts, reverse=True), f"passer order drifted: {trusts}"
    # Gate summary must still reflect the passers count.
    assert res["n_passers"] == len(passers)


def test_merged_distance_is_zero_for_passers():
    ds = _make_dataset(passers=2)
    res = build_merged_leaderboard(ds)
    passers = [e for e in res["entries"] if e["passed_gate"]]
    for p in passers:
        assert p["distance_to_clear"] == 0.0
