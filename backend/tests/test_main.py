from httpx import AsyncClient
from app.core.config import settings


async def test_health_check(client: AsyncClient):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "coalescence"}


async def test_api_v1_prefix_exists(client: AsyncClient):
    response = await client.get(f"{settings.API_V1_STR}/")
    assert response.status_code == 404
