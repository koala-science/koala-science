import uuid
from typing import List
from httpx import AsyncClient
from pydantic import TypeAdapter

from app.schemas.platform import PaperResponse, ReviewResponse, CommentResponse
from app.api.v1.mock_data import UserProfileResponse


async def test_get_papers_mock(client: AsyncClient):
    response = await client.get("/api/v1/papers/")
    assert response.status_code == 200

    data = response.json()
    adapter = TypeAdapter(List[PaperResponse])
    adapter.validate_python(data)


async def test_get_reviews_mock(client: AsyncClient):
    test_id = uuid.uuid4()
    response = await client.get(f"/api/v1/reviews/paper/{test_id}")
    assert response.status_code == 200

    data = response.json()
    adapter = TypeAdapter(List[ReviewResponse])
    adapter.validate_python(data)


async def test_get_comments_mock(client: AsyncClient):
    test_id = uuid.uuid4()
    response = await client.get(f"/api/v1/comments/paper/{test_id}")
    assert response.status_code == 200

    data = response.json()
    adapter = TypeAdapter(List[CommentResponse])
    adapter.validate_python(data)


async def test_get_users_me_mock(client: AsyncClient):
    response = await client.get("/api/v1/users/me")
    assert response.status_code == 200

    data = response.json()
    UserProfileResponse.model_validate(data)


async def test_get_domains_mock(client: AsyncClient):
    response = await client.get("/api/v1/domains/")
    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_get_domain_by_name_mock(client: AsyncClient):
    response = await client.get("/api/v1/domains/d/MachineLearning")
    assert response.status_code == 200
    assert response.json()["name"] == "d/MachineLearning"


async def test_subscribe_domain_mock(client: AsyncClient):
    test_id = uuid.uuid4()
    response = await client.post(f"/api/v1/domains/{test_id}/subscribe")
    assert response.status_code == 200
    assert "domain_id" in response.json()


async def test_unsubscribe_domain_mock(client: AsyncClient):
    test_id = uuid.uuid4()
    response = await client.delete(f"/api/v1/domains/{test_id}/subscribe")
    assert response.status_code == 200
    assert response.json()["success"] is True
