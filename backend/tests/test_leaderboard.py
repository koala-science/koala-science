from httpx import AsyncClient

from app.core.leaderboard_engine import mean_absolute_accuracy


def test_mean_absolute_accuracy_perfect():
    assert mean_absolute_accuracy([10.0, 0.0, 5.0], [10.0, 0.0, 5.0]) == 10.0


def test_mean_absolute_accuracy_worst():
    assert mean_absolute_accuracy([0.0, 10.0], [10.0, 0.0]) == 0.0


def test_mean_absolute_accuracy_partial():
    # errors [2, 2] -> scores [8, 8] -> mean 8
    assert mean_absolute_accuracy([8.0, 2.0], [10.0, 0.0]) == 8.0


def test_mean_absolute_accuracy_empty():
    assert mean_absolute_accuracy([], []) == 0.0


async def test_interaction_leaderboard_is_public(client: AsyncClient):
    response = await client.get("/api/v1/leaderboard/agents?metric=interactions")
    assert response.status_code == 200


async def test_protected_agent_leaderboard_requires_password(client: AsyncClient):
    response = await client.get("/api/v1/leaderboard/agents?metric=acceptance")
    assert response.status_code == 403


async def test_protected_agent_leaderboard_accepts_password(client: AsyncClient):
    response = await client.get(
        "/api/v1/leaderboard/agents?metric=acceptance&password=Mont-Saint-Hilaire"
    )
    assert response.status_code == 200


async def test_paper_leaderboard_requires_password(client: AsyncClient):
    response = await client.get("/api/v1/leaderboard/papers")
    assert response.status_code == 403
