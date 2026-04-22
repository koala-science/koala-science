import uuid
from httpx import AsyncClient

from tests.conftest import promote_to_superuser


def _unique_email(prefix: str = "test") -> str:
    """Generate a unique email to avoid conflicts across test runs."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


def _unique_openreview_id(prefix: str = "User") -> str:
    """Generate a unique well-formed OpenReview ID for test signups."""
    suffix = uuid.uuid4().hex[:8]
    return f"~{prefix}_{suffix}1"


async def _signup(client: AsyncClient, prefix: str = "user") -> tuple[str, str]:
    """Sign up a human account, return (access_token, actor_id)."""
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Test User",
            "email": _unique_email(prefix),
            "password": "secure_password_123",
            "openreview_id": _unique_openreview_id(prefix.capitalize() or "User"),
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["access_token"], body["actor_id"]


async def test_health(client: AsyncClient):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "coalescence"}


async def test_public_agent_register_endpoint_removed(client: AsyncClient):
    """The old public self-register endpoint is gone. Either 404 (no such
    path) or 405 (path collides with DELETE /auth/agents/{id}) means the
    POST endpoint is unavailable — both count as 'removed'."""
    response = await client.post(
        "/api/v1/auth/agents/register",
        json={
            "name": "ghost_agent",
            "owner_email": _unique_email("gone"),
            "owner_name": "Ghost",
            "owner_password": "test_password_123",
            "github_repo": "https://github.com/example/gone",
        },
    )
    assert response.status_code in (404, 405)


async def test_sovereign_register_endpoint_removed(client: AsyncClient):
    """Sovereign-agent register endpoint is gone."""
    response = await client.post(
        "/api/v1/auth/agents/sovereign/register",
        json={"name": "sov", "public_key": "ed25519:x"},
    )
    assert response.status_code in (404, 405)


async def test_create_agent_rejects_invalid_github_repo(client: AsyncClient):
    """Agents cannot be created without a valid GitHub repo URL."""
    token, _ = await _signup(client, "bad_github")
    response = await client.post(
        "/api/v1/auth/agents",
        json={"name": "bad_github_agent", "github_repo": "not a url"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422


async def test_create_agent_requires_github_repo(client: AsyncClient):
    """github_repo is a required field."""
    token, _ = await _signup(client, "missing_github")
    response = await client.post(
        "/api/v1/auth/agents",
        json={"name": "missing_github_agent"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422


async def test_create_agent_requires_auth(client: AsyncClient):
    """POST /auth/agents rejects unauthenticated requests."""
    response = await client.post(
        "/api/v1/auth/agents",
        json={
            "name": "test_agent_noauth",
            "github_repo": "https://github.com/example/noauth",
        },
    )
    assert response.status_code == 401


async def test_create_agent_rejects_agent_auth(client: AsyncClient):
    """Agents cannot create other agents — human-only endpoint."""
    token, _ = await _signup(client, "owner")
    # Create first agent as the human
    first = await client.post(
        "/api/v1/auth/agents",
        json={
            "name": "first_agent",
            "github_repo": "https://github.com/example/first",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 201, first.text
    agent_api_key = first.json()["api_key"]
    assert agent_api_key.startswith("cs_")

    # Try to create a second agent using the first agent's API key → 403
    second = await client.post(
        "/api/v1/auth/agents",
        json={
            "name": "second_agent",
            "github_repo": "https://github.com/example/second",
        },
        headers={"Authorization": f"Bearer {agent_api_key}"},
    )
    assert second.status_code == 403


async def test_create_agent_succeeds_for_human(client: AsyncClient):
    """Humans can create agents and get a cs_ API key back."""
    token, _ = await _signup(client, "creator")
    resp = await client.post(
        "/api/v1/auth/agents",
        json={
            "name": "my_agent",
            "description": "Test agent",
            "github_repo": "https://github.com/example/my-agent",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert "id" in data
    assert "api_key" in data
    assert data["api_key"].startswith("cs_")


async def test_created_agent_can_authenticate(client: AsyncClient):
    """The API key returned by POST /auth/agents works as a bearer."""
    token, _ = await _signup(client, "auther")
    reg_resp = await client.post(
        "/api/v1/auth/agents",
        json={
            "name": "key_auth_agent",
            "github_repo": "https://github.com/example/key-auth-agent",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert reg_resp.status_code == 201
    api_key = reg_resp.json()["api_key"]

    me_resp = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["name"] == "key_auth_agent"


async def test_list_agents_exposes_default_karma(client: AsyncClient):
    """GET /auth/agents returns karma on each agent, defaulting to 100.0."""
    token, _ = await _signup(client, "karma_user")
    create = await client.post(
        "/api/v1/auth/agents",
        json={
            "name": "karma_agent",
            "github_repo": "https://github.com/example/karma-agent",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create.status_code == 201

    listing = await client.get(
        "/api/v1/auth/agents",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert listing.status_code == 200
    entries = listing.json()
    assert entries, "expected at least one agent in the listing"
    for entry in entries:
        assert "karma" in entry
        assert entry["karma"] == 100.0


async def test_list_agents_scoped_to_owner(client: AsyncClient):
    """GET /auth/agents returns only the authenticated human's agents."""
    token_a, _ = await _signup(client, "lister_a")
    token_b, _ = await _signup(client, "lister_b")

    # User A creates two agents, user B creates one
    for name in ("a_agent_1", "a_agent_2"):
        resp = await client.post(
            "/api/v1/auth/agents",
            json={"name": name, "github_repo": f"https://github.com/example/{name}"},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 201
    resp_b = await client.post(
        "/api/v1/auth/agents",
        json={"name": "b_agent_1", "github_repo": "https://github.com/example/b_agent_1"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp_b.status_code == 201

    list_a = await client.get(
        "/api/v1/auth/agents", headers={"Authorization": f"Bearer {token_a}"}
    )
    assert list_a.status_code == 200
    names_a = {a["name"] for a in list_a.json()}
    assert {"a_agent_1", "a_agent_2"}.issubset(names_a)
    assert "b_agent_1" not in names_a


async def test_list_agents_no_plaintext_key(client: AsyncClient):
    """GET /auth/agents response must not include the plaintext API key."""
    token, _ = await _signup(client, "noplain")
    await client.post(
        "/api/v1/auth/agents",
        json={"name": "noplain_agent", "github_repo": "https://github.com/example/noplain"},
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = await client.get(
        "/api/v1/auth/agents", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    for entry in resp.json():
        assert "api_key" not in entry
        assert "api_key_plain" not in entry
        assert "api_key_preview" not in entry


async def test_delete_agent_endpoint_removed(client: AsyncClient):
    """Agents cannot be deleted — DELETE /auth/agents/{id} is not routed."""
    token, _ = await _signup(client, "del_gone")
    resp = await client.post(
        "/api/v1/auth/agents",
        json={"name": "del_gone_agent", "github_repo": "https://github.com/example/del"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    agent_id = resp.json()["id"]

    gone = await client.delete(
        f"/api/v1/auth/agents/{agent_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert gone.status_code in (404, 405)


async def test_agent_limit_rejects_fourth(client: AsyncClient):
    """A human can create at most 3 agents; the 4th returns 409."""
    token, _ = await _signup(client, "cap")
    for i in range(3):
        resp = await client.post(
            "/api/v1/auth/agents",
            json={
                "name": f"cap_agent_{i}",
                "github_repo": f"https://github.com/example/cap_{i}",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201, resp.text

    over = await client.post(
        "/api/v1/auth/agents",
        json={"name": "cap_agent_4", "github_repo": "https://github.com/example/cap_4"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert over.status_code == 409
    assert "limit" in over.json()["detail"].lower() or "3" in over.json()["detail"]


async def test_agent_limit_is_per_user(client: AsyncClient):
    """Hitting the cap for user A does not affect user B."""
    token_a, _ = await _signup(client, "cap_a")
    token_b, _ = await _signup(client, "cap_b")
    for i in range(3):
        resp = await client.post(
            "/api/v1/auth/agents",
            json={
                "name": f"cap_a_{i}",
                "github_repo": f"https://github.com/example/cap_a_{i}",
            },
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 201

    # B is unaffected
    resp = await client.post(
        "/api/v1/auth/agents",
        json={"name": "cap_b_0", "github_repo": "https://github.com/example/cap_b_0"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp.status_code == 201


async def test_signup_and_login(client: AsyncClient):
    """Signup creates a human account, login returns JWT."""
    email = _unique_email("signup")

    signup_resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Auth Test User",
            "email": email,
            "password": "secure_password_123",
            "openreview_id": _unique_openreview_id("Signup"),
        },
    )
    assert signup_resp.status_code == 201
    assert "access_token" in signup_resp.json()

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


async def test_token_response_exposes_is_superuser(client: AsyncClient):
    """TokenResponse includes is_superuser: false by default, true after promotion."""
    email = _unique_email("super")
    password = "secure_password_123"

    signup = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Super Test",
            "email": email,
            "password": password,
            "openreview_id": _unique_openreview_id("Super"),
        },
    )
    assert signup.status_code == 201
    assert signup.json()["is_superuser"] is False

    await promote_to_superuser(signup.json()["actor_id"])

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200
    assert login.json()["is_superuser"] is True


async def test_login_wrong_password(client: AsyncClient):
    """Login with wrong password returns 401."""
    email = _unique_email("wrongpass")

    await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Wrong Pass User",
            "email": email,
            "password": "correct_password",
            "openreview_id": _unique_openreview_id("WrongPass"),
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


async def test_signup_requires_openreview_id(client: AsyncClient):
    """Missing openreview_id → 422."""
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "No OR",
            "email": _unique_email("no_or"),
            "password": "secure_password_123",
        },
    )
    assert resp.status_code == 422


async def test_signup_rejects_malformed_openreview_id(client: AsyncClient):
    """Malformed openreview_id values → 422."""
    bad_ids = ["alice", "~alice", "~Alice_Chen", "~1Alice1", "", "Alice_Chen1"]
    for bad_id in bad_ids:
        resp = await client.post(
            "/api/v1/auth/signup",
            json={
                "name": "Bad OR",
                "email": _unique_email("bad_or"),
                "password": "secure_password_123",
                "openreview_id": bad_id,
            },
        )
        assert resp.status_code == 422, f"expected 422 for {bad_id!r}, got {resp.status_code}"


async def test_signup_accepts_hyphenated_surname(client: AsyncClient):
    """Hyphenated surnames like ~Eugenio_Herrera-Berg1 are accepted."""
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Eugenio Herrera-Berg",
            "email": _unique_email("hyphen"),
            "password": "secure_password_123",
            "openreview_id": f"~Eugenio_Herrera-Berg_{uuid.uuid4().hex[:6]}1",
        },
    )
    assert resp.status_code == 201, resp.text


async def test_signup_rejects_nonexistent_openreview_id(client: AsyncClient, monkeypatch):
    """A well-formed openreview_id that OpenReview doesn't know about → 422."""
    import app.api.v1.endpoints.auth as auth_module

    async def _returns_false(openreview_id: str) -> bool:
        return False

    monkeypatch.setattr(auth_module, "profile_exists", _returns_false)

    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Ghost",
            "email": _unique_email("ghost"),
            "password": "secure_password_123",
            "openreview_id": f"~Ghost_User_{uuid.uuid4().hex[:6]}1",
        },
    )
    assert resp.status_code == 422
    assert "OpenReview" in resp.json()["detail"]


async def test_signup_rejects_duplicate_openreview_id(client: AsyncClient):
    """Two signups with the same openreview_id → second returns 409."""
    openreview_id = _unique_openreview_id("Dup")

    first = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "First User",
            "email": _unique_email("dup_first"),
            "password": "secure_password_123",
            "openreview_id": openreview_id,
        },
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Second User",
            "email": _unique_email("dup_second"),
            "password": "secure_password_123",
            "openreview_id": openreview_id,
        },
    )
    assert second.status_code == 409


async def test_signup_returns_503_when_openreview_down(client: AsyncClient, monkeypatch):
    """Network error talking to OpenReview → signup returns 503."""
    import app.api.v1.endpoints.auth as auth_module
    from app.core.openreview import OpenReviewUnavailableError

    async def _boom(openreview_id: str) -> bool:
        raise OpenReviewUnavailableError("boom")

    monkeypatch.setattr(auth_module, "profile_exists", _boom)

    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Unlucky",
            "email": _unique_email("down"),
            "password": "secure_password_123",
            "openreview_id": _unique_openreview_id("Down"),
        },
    )
    assert resp.status_code == 503
