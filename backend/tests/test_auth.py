from httpx import AsyncClient


async def test_health(client: AsyncClient):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "coalescence"}


async def test_register_delegated_agent(client: AsyncClient):
    response = await client.post(
        "/api/v1/auth/agents/delegated/register",
        json={"name": "test_agent", "description": "test description"},
    )
    assert response.status_code == 201
    assert "api_key" in response.json()
    assert "id" in response.json()


async def test_register_sovereign_agent(client: AsyncClient):
    response = await client.post(
        "/api/v1/auth/agents/sovereign/register",
        json={"public_key": "test_public_key", "name": "test_sovereign"},
    )
    assert response.status_code == 201
    assert "message" in response.json()
    assert "agent_id" in response.json()


async def test_get_sovereign_challenge(client: AsyncClient):
    response = await client.post(
        "/api/v1/auth/agents/sovereign/challenge",
        json={"public_key": "test_public_key"},
    )
    assert response.status_code == 200
    assert "challenge" in response.json()


async def test_login_sovereign_agent(client: AsyncClient):
    response = await client.post(
        "/api/v1/auth/agents/sovereign/login",
        json={
            "public_key": "test_public_key",
            "signature": "test_signature",
            "challenge": "test_challenge",
        },
    )
    assert response.status_code == 200
    assert "access_token" in response.json()
    assert response.json()["token_type"] == "bearer"
