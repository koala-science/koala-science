import uuid
from httpx import AsyncClient

from tests.conftest import mark_email_verified, complete_signup, promote_to_superuser


def _unique_email(prefix: str = "test") -> str:
    """Generate a unique email to avoid conflicts across test runs."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


def _unique_openreview_id(prefix: str = "User") -> str:
    """Generate a unique well-formed OpenReview ID for test signups."""
    suffix = uuid.uuid4().hex[:8]
    return f"~{prefix}_{suffix}1"


async def _signup(client: AsyncClient, prefix: str = "user") -> tuple[str, str]:
    """Sign up a human account, return (access_token, actor_id)."""
    return await complete_signup(client, {
        "name": "Test User",
        "email": _unique_email(prefix),
        "password": "secure_password_123",
        "openreview_id": _unique_openreview_id(prefix.capitalize() or "User"),
    })


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
            "email": email,
            "openreview_id": _unique_openreview_id("Signup"),
        },
    )
    assert signup_resp.status_code == 201
    body = signup_resp.json()
    assert body["verification_required"] is True
    assert body["email"] == email
    assert "access_token" not in body, "an unverified account must not be signed in"

    await mark_email_verified(email, "secure_password_123")

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
            "email": email,
            "openreview_id": _unique_openreview_id("Super"),
        },
    )
    assert signup.status_code == 201
    await mark_email_verified(email, password)

    first_login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert first_login.status_code == 200
    assert first_login.json()["is_superuser"] is False

    await promote_to_superuser(first_login.json()["actor_id"])

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
            "email": email,
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
            "email": _unique_email("no_or"),
        },
    )
    assert resp.status_code == 422


async def test_signup_rejects_the_legacy_list_field(client: AsyncClient):
    """The field was `openreview_ids`, a list of up to three. A client still
    sending that shape must be refused rather than have it silently ignored and
    the account created with no ID at all."""
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": _unique_email("legacy_or"),
            "openreview_ids": [_unique_openreview_id("L1"), _unique_openreview_id("L2")],
        },
    )
    assert resp.status_code == 422


async def test_signup_rejects_malformed_openreview_id(client: AsyncClient):
    """A malformed openreview_id → 422."""
    bad_ids = ["alice", "~alice", "~Alice_Chen", "~1Alice1", "", "Alice_Chen1"]
    for bad_id in bad_ids:
        resp = await client.post(
            "/api/v1/auth/signup",
            json={
                "email": _unique_email("bad_or"),
                "openreview_id": bad_id,
            },
        )
        assert resp.status_code == 422, f"expected 422 for {bad_id!r}, got {resp.status_code}"


async def test_signup_accepts_hyphenated_surname(client: AsyncClient):
    """Hyphenated surnames like ~Eugenio_Herrera-Berg1 are accepted."""
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": _unique_email("hyphen"),
            "openreview_id": f"~Eugenio_Herrera-Berg_{uuid.uuid4().hex[:6]}1",
        },
    )
    assert resp.status_code == 201, resp.text


async def test_signup_rejects_nonexistent_openreview_id(client: AsyncClient, monkeypatch):
    """A well-formed openreview_id that OpenReview doesn't know about → 422."""
    import app.api.v1.endpoints.auth as auth_module

    async def _no_profile(openreview_id: str):
        return None

    monkeypatch.setattr(auth_module, "fetch_profile", _no_profile)

    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": _unique_email("ghost"),
            "openreview_id": f"~Ghost_User_{uuid.uuid4().hex[:6]}1",
        },
    )
    assert resp.status_code == 422
    assert "OpenReview" in resp.json()["detail"]


async def test_signup_rejects_duplicate_openreview_id(client: AsyncClient):
    """An ID that a verified account holds → second signup returns 409.

    An *unredeemed* signup holds nothing: parking someone else's identity behind
    an unverified address would both deny it to its owner and report, through the
    409, that the address had been used.
    """
    openreview_id = _unique_openreview_id("Dup")
    first_email = _unique_email("dup_first")

    first = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": first_email,
            "openreview_id": openreview_id,
        },
    )
    assert first.status_code == 201, first.text
    await mark_email_verified(first_email, "secure_password_123")

    second = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": _unique_email("dup_second"),
            "openreview_id": openreview_id,
        },
    )
    assert second.status_code == 409


async def test_signup_returns_503_when_openreview_down(client: AsyncClient, monkeypatch):
    """Network error talking to OpenReview → signup returns 503."""
    import app.api.v1.endpoints.auth as auth_module
    from app.core.openreview import OpenReviewUnavailableError

    async def _boom(openreview_id: str):
        raise OpenReviewUnavailableError("boom")

    monkeypatch.setattr(auth_module, "fetch_profile", _boom)

    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": _unique_email("down"),
            "openreview_id": _unique_openreview_id("Down"),
        },
    )
    assert resp.status_code == 503


async def test_signup_returns_403_when_signups_disabled(client: AsyncClient, monkeypatch):
    """SIGNUPS_ENABLED=False shuts the door for new humans."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "SIGNUPS_ENABLED", False)

    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": _unique_email("too_late"),
            "openreview_id": _unique_openreview_id("TooLate"),
        },
    )
    assert resp.status_code == 403
    assert "signup" in resp.json()["detail"].lower() or "disabled" in resp.json()["detail"].lower()


async def test_create_agent_returns_403_when_signups_disabled(client: AsyncClient, monkeypatch):
    """SIGNUPS_ENABLED=False also blocks new-agent creation by existing humans."""
    from app.core.config import settings

    token, _ = await _signup(client, "freeze_owner")
    monkeypatch.setattr(settings, "SIGNUPS_ENABLED", False)

    resp = await client.post(
        "/api/v1/auth/agents",
        json={
            "name": f"frozen_{uuid.uuid4().hex[:6]}",
            "github_repo": "https://github.com/test/frozen",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
