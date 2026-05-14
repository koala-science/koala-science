import hashlib
import uuid
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from tests.conftest import promote_to_superuser


def _unique_email(prefix: str = "test") -> str:
    """Generate a unique email to avoid conflicts across test runs."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


def _unique_openreview_id(prefix: str = "User") -> str:
    """Generate a unique well-formed OpenReview ID for test signups."""
    suffix = uuid.uuid4().hex[:8]
    return f"~{prefix}_{suffix}1"


async def _mark_verified(email: str) -> str:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            res = await conn.execute(
                text(
                    "UPDATE human_account SET email_verified = TRUE "
                    "WHERE email = :email RETURNING id"
                ),
                {"email": email},
            )
            row = res.one()
            return str(row[0])
    finally:
        await engine.dispose()


async def _signup(client: AsyncClient, prefix: str = "user") -> tuple[str, str]:
    """Sign up + verify + login a human account; return (access_token, actor_id)."""
    email = _unique_email(prefix)
    password = "secure_password_123"
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Test User",
            "email": email,
            "password": password,
            "openreview_ids": [_unique_openreview_id(prefix.capitalize() or "User")],
        },
    )
    assert resp.status_code == 201, resp.text
    actor_id = await _mark_verified(email)
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    return login.json()["access_token"], actor_id


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
    """Signup returns verification_required; login works after verification."""
    email = _unique_email("signup")

    signup_resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Auth Test User",
            "email": email,
            "password": "secure_password_123",
            "openreview_ids": [_unique_openreview_id("Signup")],
        },
    )
    assert signup_resp.status_code == 201
    body = signup_resp.json()
    assert body == {"verification_required": True, "email": email}
    assert "access_token" not in body

    await _mark_verified(email)

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
            "openreview_ids": [_unique_openreview_id("Super")],
        },
    )
    assert signup.status_code == 201

    actor_id = await _mark_verified(email)

    login_pre = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login_pre.status_code == 200
    assert login_pre.json()["is_superuser"] is False

    await promote_to_superuser(actor_id)

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
            "openreview_ids": [_unique_openreview_id("WrongPass")],
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
    """Missing openreview_ids → 422."""
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "No OR",
            "email": _unique_email("no_or"),
            "password": "secure_password_123",
        },
    )
    assert resp.status_code == 422


async def test_signup_rejects_empty_openreview_ids(client: AsyncClient):
    """Empty openreview_ids list → 422."""
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Empty OR",
            "email": _unique_email("empty_or"),
            "password": "secure_password_123",
            "openreview_ids": [],
        },
    )
    assert resp.status_code == 422


async def test_signup_rejects_more_than_three_openreview_ids(client: AsyncClient):
    """More than 3 openreview_ids → 422."""
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Too Many OR",
            "email": _unique_email("toomany_or"),
            "password": "secure_password_123",
            "openreview_ids": [_unique_openreview_id(f"TM{i}") for i in range(4)],
        },
    )
    assert resp.status_code == 422


async def test_signup_rejects_duplicate_ids_in_list(client: AsyncClient):
    """Same ID repeated within the list → 422."""
    openreview_id = _unique_openreview_id("DupList")
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Dup List",
            "email": _unique_email("duplist"),
            "password": "secure_password_123",
            "openreview_ids": [openreview_id, openreview_id],
        },
    )
    assert resp.status_code == 422


async def test_signup_rejects_malformed_openreview_id(client: AsyncClient):
    """Malformed openreview_ids entries → 422."""
    bad_ids = ["alice", "~alice", "~Alice_Chen", "~1Alice1", "", "Alice_Chen1"]
    for bad_id in bad_ids:
        resp = await client.post(
            "/api/v1/auth/signup",
            json={
                "name": "Bad OR",
                "email": _unique_email("bad_or"),
                "password": "secure_password_123",
                "openreview_ids": [bad_id],
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
            "openreview_ids": [f"~Eugenio_Herrera-Berg_{uuid.uuid4().hex[:6]}1"],
        },
    )
    assert resp.status_code == 201, resp.text


async def test_signup_accepts_multiple_openreview_ids(client: AsyncClient):
    """Up to 3 openreview_ids can be supplied on signup."""
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Three IDs",
            "email": _unique_email("three_or"),
            "password": "secure_password_123",
            "openreview_ids": [
                _unique_openreview_id("TriA"),
                _unique_openreview_id("TriB"),
                _unique_openreview_id("TriC"),
            ],
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
            "openreview_ids": [f"~Ghost_User_{uuid.uuid4().hex[:6]}1"],
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
            "openreview_ids": [openreview_id],
        },
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Second User",
            "email": _unique_email("dup_second"),
            "password": "secure_password_123",
            "openreview_ids": [openreview_id],
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
            "openreview_ids": [_unique_openreview_id("Down")],
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
            "name": "TooLate",
            "email": _unique_email("too_late"),
            "password": "secure_password_123",
            "openreview_ids": [_unique_openreview_id("TooLate")],
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


# --- Email verification ---


def _install_email_recorder(monkeypatch):
    """Replace send_email with a recorder; return the list of (to, subject, html)."""
    sent: list[tuple[str, str, str]] = []

    async def _record(to: str, subject: str, html: str) -> None:
        sent.append((to, subject, html))

    import app.api.v1.endpoints.auth as auth_module

    monkeypatch.setattr(auth_module, "send_email", _record)
    return sent


async def _select_one(sql: str, params: dict | None = None):
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params or {})).one_or_none()
    finally:
        await engine.dispose()


async def _select_all(sql: str, params: dict | None = None):
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params or {})).all()
    finally:
        await engine.dispose()


def _extract_token_from_email(html: str) -> str:
    marker = "/auth/verify?token="
    idx = html.find(marker)
    assert idx >= 0, html
    start = idx + len(marker)
    end = start
    while end < len(html) and html[end] not in ('"', " ", "<", "&"):
        end += 1
    return html[start:end]


async def test_signup_sends_verification_email_and_returns_shape(
    client: AsyncClient, monkeypatch
):
    sent = _install_email_recorder(monkeypatch)
    email = _unique_email("verify_signup")

    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Verify Me",
            "email": email,
            "password": "secure_password_123",
            "openreview_ids": [_unique_openreview_id("VerifySignup")],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body == {"verification_required": True, "email": email}
    assert "access_token" not in body
    assert "refresh_token" not in resp.cookies

    assert len(sent) == 1
    to_addr, subject, html = sent[0]
    assert to_addr == email
    assert subject == "Verify your email"
    raw_token = _extract_token_from_email(html)
    expected_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    user_row = await _select_one(
        "SELECT id, email_verified FROM human_account WHERE email = :e",
        {"e": email},
    )
    assert user_row is not None
    assert user_row[1] is False

    token_row = await _select_one(
        "SELECT token_hash FROM email_verification_token "
        "WHERE human_account_id = :id",
        {"id": user_row[0]},
    )
    assert token_row is not None
    assert token_row[0] == expected_hash


async def test_verify_with_valid_token_flips_verified(
    client: AsyncClient, monkeypatch
):
    sent = _install_email_recorder(monkeypatch)
    email = _unique_email("verify_valid")
    await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Valid Token",
            "email": email,
            "password": "secure_password_123",
            "openreview_ids": [_unique_openreview_id("VerifyValid")],
        },
    )
    raw_token = _extract_token_from_email(sent[0][2])

    resp = await client.post("/api/v1/auth/verify", json={"token": raw_token})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True}

    row = await _select_one(
        "SELECT email_verified FROM human_account WHERE email = :e",
        {"e": email},
    )
    assert row[0] is True

    token_row = await _select_one(
        "SELECT used_at FROM email_verification_token "
        "WHERE token_hash = :h",
        {"h": hashlib.sha256(raw_token.encode()).hexdigest()},
    )
    assert token_row[0] is not None


async def test_verify_with_already_used_token_returns_400(
    client: AsyncClient, monkeypatch
):
    sent = _install_email_recorder(monkeypatch)
    email = _unique_email("verify_used")
    await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Used",
            "email": email,
            "password": "secure_password_123",
            "openreview_ids": [_unique_openreview_id("VerifyUsed")],
        },
    )
    raw_token = _extract_token_from_email(sent[0][2])

    first = await client.post("/api/v1/auth/verify", json={"token": raw_token})
    assert first.status_code == 200

    second = await client.post("/api/v1/auth/verify", json={"token": raw_token})
    assert second.status_code == 400
    detail = second.json()["detail"]
    assert detail["code"] == "INVALID_OR_EXPIRED_TOKEN"


async def test_verify_with_expired_token_returns_400(
    client: AsyncClient, monkeypatch
):
    sent = _install_email_recorder(monkeypatch)
    email = _unique_email("verify_expired")
    await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Expired",
            "email": email,
            "password": "secure_password_123",
            "openreview_ids": [_unique_openreview_id("VerifyExpired")],
        },
    )
    raw_token = _extract_token_from_email(sent[0][2])

    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE email_verification_token "
                    "SET expires_at = now() - interval '1 hour' "
                    "WHERE token_hash = :h"
                ),
                {"h": hashlib.sha256(raw_token.encode()).hexdigest()},
            )
    finally:
        await engine.dispose()

    resp = await client.post("/api/v1/auth/verify", json={"token": raw_token})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "INVALID_OR_EXPIRED_TOKEN"


async def test_verify_with_unknown_token_returns_400(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/verify", json={"token": "definitely-not-a-real-token"}
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "INVALID_OR_EXPIRED_TOKEN"


async def test_login_blocked_when_unverified(client: AsyncClient, monkeypatch):
    _install_email_recorder(monkeypatch)
    email = _unique_email("login_unverified")
    password = "secure_password_123"
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Unverified",
            "email": email,
            "password": password,
            "openreview_ids": [_unique_openreview_id("LoginUnverified")],
        },
    )
    assert resp.status_code == 201

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 403
    assert login.json()["detail"]["code"] == "EMAIL_NOT_VERIFIED"


async def test_login_succeeds_after_verification(client: AsyncClient, monkeypatch):
    sent = _install_email_recorder(monkeypatch)
    email = _unique_email("login_verified")
    password = "secure_password_123"
    await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Verified",
            "email": email,
            "password": password,
            "openreview_ids": [_unique_openreview_id("LoginVerified")],
        },
    )
    raw_token = _extract_token_from_email(sent[0][2])
    verify = await client.post("/api/v1/auth/verify", json={"token": raw_token})
    assert verify.status_code == 200

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200
    assert "access_token" in login.json()


async def test_resend_verification_for_unverified_user(
    client: AsyncClient, monkeypatch
):
    sent = _install_email_recorder(monkeypatch)
    email = _unique_email("resend_unv")
    password = "secure_password_123"
    await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Resend",
            "email": email,
            "password": password,
            "openreview_ids": [_unique_openreview_id("ResendUnv")],
        },
    )
    assert len(sent) == 1
    first_token = _extract_token_from_email(sent[0][2])

    resp = await client.post(
        "/api/v1/auth/resend-verification", json={"email": email}
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert len(sent) == 2
    new_token = _extract_token_from_email(sent[1][2])
    assert new_token != first_token

    rows = await _select_all(
        "SELECT token_hash, used_at FROM email_verification_token evt "
        "JOIN human_account ha ON ha.id = evt.human_account_id "
        "WHERE ha.email = :e ORDER BY evt.created_at",
        {"e": email},
    )
    assert len(rows) == 2
    first_hash = hashlib.sha256(first_token.encode()).hexdigest()
    new_hash = hashlib.sha256(new_token.encode()).hexdigest()
    by_hash = {row[0]: row[1] for row in rows}
    assert by_hash[first_hash] is not None
    assert by_hash[new_hash] is None


async def test_resend_verification_for_unknown_email_returns_200(
    client: AsyncClient, monkeypatch
):
    sent = _install_email_recorder(monkeypatch)
    resp = await client.post(
        "/api/v1/auth/resend-verification",
        json={"email": _unique_email("resend_unknown")},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert sent == []


async def test_resend_verification_for_verified_user_returns_200_no_email(
    client: AsyncClient, monkeypatch
):
    sent = _install_email_recorder(monkeypatch)
    email = _unique_email("resend_verified")
    password = "secure_password_123"
    await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "AlreadyVerified",
            "email": email,
            "password": password,
            "openreview_ids": [_unique_openreview_id("ResendVerified")],
        },
    )
    assert len(sent) == 1
    await _mark_verified(email)
    sent.clear()

    resp = await client.post(
        "/api/v1/auth/resend-verification", json={"email": email}
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert sent == []
