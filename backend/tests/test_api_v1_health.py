from httpx import AsyncClient
from app.core.config import settings


async def test_health_check(client: AsyncClient) -> None:
    response = await client.get(f"{settings.API_V1_STR}/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "coalescence"}


async def test_openapi_json(client: AsyncClient) -> None:
    response = await client.get(f"{settings.API_V1_STR}/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert data["info"]["title"] == settings.PROJECT_NAME
    assert f"{settings.API_V1_STR}/health" in data["paths"]
