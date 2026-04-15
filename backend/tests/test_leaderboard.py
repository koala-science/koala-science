from httpx import AsyncClient

from app.core.leaderboard_engine import (
    extract_verdict_score,
    kendall_tau_b,
    auroc_real_vs_flaw,
)


def test_extract_verdict_score_from_numeric_verdict_section():
    content = """
## Summary
Interesting paper.

## Verdict
Score: 6.5/10
"""
    assert extract_verdict_score(content) == 6.5


def test_extract_verdict_score_from_textual_recommendation():
    content = """
## Recommendation
Weak Reject
"""
    assert extract_verdict_score(content) == 3.0


def test_kendall_tau_b_perfect():
    tau = kendall_tau_b([1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 3.0, 4.0])
    assert tau is not None
    assert abs(tau - 1.0) < 1e-10


def test_kendall_tau_b_inverse():
    tau = kendall_tau_b([1.0, 2.0, 3.0], [3.0, 2.0, 1.0])
    assert tau is not None
    assert abs(tau - (-1.0)) < 1e-10


def test_kendall_tau_b_insufficient():
    assert kendall_tau_b([1.0], [1.0]) is None


def test_kendall_tau_b_with_ties():
    tau = kendall_tau_b([1.0, 2.0, 2.0, 4.0], [1.0, 3.0, 2.0, 4.0])
    assert tau is not None
    assert 0 < tau < 1.0


def test_auroc_perfect_separation():
    auroc = auroc_real_vs_flaw([8.0, 9.0, 10.0], [1.0, 2.0, 3.0])
    assert auroc == 1.0


def test_auroc_no_separation():
    auroc = auroc_real_vs_flaw([5.0, 5.0], [5.0, 5.0])
    assert auroc is not None
    assert abs(auroc - 0.5) < 1e-10


def test_auroc_empty():
    assert auroc_real_vs_flaw([], [1.0]) is None
    assert auroc_real_vs_flaw([1.0], []) is None


async def test_interaction_leaderboard_is_public(client: AsyncClient):
    response = await client.get("/api/v1/leaderboard/agents?metric=interactions")
    assert response.status_code == 200


async def test_all_metrics_are_public(client: AsyncClient):
    for metric in ["acceptance", "citation", "review_score", "soundness", "presentation", "contribution"]:
        response = await client.get(f"/api/v1/leaderboard/agents?metric={metric}")
        assert response.status_code == 200, f"{metric} returned {response.status_code}"


async def test_paper_leaderboard_is_public(client: AsyncClient):
    response = await client.get("/api/v1/leaderboard/papers")
    assert response.status_code == 200
