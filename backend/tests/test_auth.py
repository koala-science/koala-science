import uuid
from httpx import AsyncClient


def _unique_email(prefix: str = "test") -> str:
    """Generate a unique email to avoid conflicts across test runs."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def test_health(client: AsyncClient):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "coalescence"}


async def test_public_agent_register(client: AsyncClient):
    """Public registration: creates human owner + delegated agent in one call."""
    response = await client.post(
        "/api/v1/auth/agents/register",
        json={
            "name": "test_agent_public",
            "owner_email": _unique_email("pubreg"),
            "owner_name": "Test Owner",
            "owner_password": "test_password_123",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert "api_key" in data
    assert data["api_key"].startswith("cs_")
    assert "id" in data


async def test_public_agent_register_duplicate_email(client: AsyncClient):
    """Public registration rejects duplicate emails."""
    email = _unique_email("dupreg")
    payload = {
        "name": "dup_agent",
        "owner_email": email,
        "owner_name": "Dup Owner",
        "owner_password": "test_password_123",
    }
    # First registration succeeds
    response = await client.post("/api/v1/auth/agents/register", json=payload)
    assert response.status_code == 201

    # Second with same email fails
    payload["name"] = "dup_agent_2"
    response = await client.post("/api/v1/auth/agents/register", json=payload)
    assert response.status_code == 409


async def test_delegated_register_requires_auth(client: AsyncClient):
    """Authenticated delegated agent registration requires a valid token."""
    response = await client.post(
        "/api/v1/auth/agents/delegated/register",
        json={"name": "test_agent_noauth"},
    )
    assert response.status_code == 401


async def test_signup_and_login(client: AsyncClient):
    """Signup creates a human account, login returns JWT."""
    email = _unique_email("signup")

    # Signup
    signup_resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Auth Test User",
            "email": email,
            "password": "secure_password_123",
        },
    )
    assert signup_resp.status_code == 201
    assert "access_token" in signup_resp.json()

    # Login
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": "secure_password_123",
        },
    )
    assert login_resp.status_code == 200
    data = login_resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


async def test_login_wrong_password(client: AsyncClient):
    """Login with wrong password returns 401."""
    email = _unique_email("wrongpass")

    # Create account first
    await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Wrong Pass User",
            "email": email,
            "password": "correct_password",
        },
    )

    response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": "wrong_password",
        },
    )
    assert response.status_code == 401


async def test_agent_key_auth(client: AsyncClient):
    """Agent API key can be used to access authenticated endpoints."""
    email = _unique_email("keyauth")

    # Register agent
    reg_resp = await client.post(
        "/api/v1/auth/agents/register",
        json={
            "name": "key_auth_agent",
            "owner_email": email,
            "owner_name": "Key Owner",
            "owner_password": "test_password_123",
        },
    )
    assert reg_resp.status_code == 201
    api_key = reg_resp.json()["api_key"]

    # Use the key to access /users/me
    me_resp = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["name"] == "key_auth_agent"
