from httpx import AsyncClient

from app.core.leaderboard_engine import (
    citation_ground_truth_score,
    extract_verdict_score,
    mean_absolute_accuracy,
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


def test_citation_ground_truth_score_uses_log_scale_and_cap():
    assert citation_ground_truth_score(1) == 0.0
    assert citation_ground_truth_score(16) == 4.0
    assert citation_ground_truth_score(4096) == 10.0


def test_mean_absolute_accuracy_perfect_prediction():
    assert mean_absolute_accuracy([10.0, 0.0, 5.0], [10.0, 0.0, 5.0]) == 10.0


def test_mean_absolute_accuracy_worst_case():
    assert mean_absolute_accuracy([0.0, 10.0], [10.0, 0.0]) == 0.0


def test_mean_absolute_accuracy_partial_error():
    # verdicts [8, 2], ground truths [10, 0] → errors [2, 2] → scores [8, 8] → mean 8
    assert mean_absolute_accuracy([8.0, 2.0], [10.0, 0.0]) == 8.0


def test_mean_absolute_accuracy_empty():
    assert mean_absolute_accuracy([], []) == 0.0


async def test_interaction_leaderboard_is_public(client: AsyncClient):
    response = await client.get("/api/v1/leaderboard/agents?metric=interactions")
    assert response.status_code == 200


async def test_protected_agent_leaderboard_requires_password(client: AsyncClient):
    response = await client.get("/api/v1/leaderboard/agents?metric=acceptance")
    assert response.status_code == 403
    assert response.json()["detail"] == "Enter the leaderboard password to unlock this ranking."


async def test_protected_agent_leaderboard_accepts_password(client: AsyncClient):
    response = await client.get(
        "/api/v1/leaderboard/agents?metric=acceptance&password=Mont-Saint-Hilaire"
    )
    assert response.status_code == 200


async def test_paper_leaderboard_requires_password(client: AsyncClient):
    response = await client.get("/api/v1/leaderboard/papers")
    assert response.status_code == 403
