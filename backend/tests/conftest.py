from pathlib import Path
from dotenv import load_dotenv

# Load .env.test before app.core.config is imported.
_ENV_TEST = Path(__file__).resolve().parent.parent / ".env.test"
if _ENV_TEST.exists():
    load_dotenv(_ENV_TEST, override=True)

import json

import pytest
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine, async_sessionmaker

from app.db.base import Base
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import pwd_context
from app.main import app

_SAFE_DB_NAME = "coalescence_test"
if settings.POSTGRES_DB != _SAFE_DB_NAME:
    raise RuntimeError(
        f"Refusing to run pytest against POSTGRES_DB={settings.POSTGRES_DB!r}. "
        f"Tests must run against {_SAFE_DB_NAME!r}. "
        f"Create backend/.env.test with POSTGRES_DB={_SAFE_DB_NAME}, "
        f"and bootstrap the DB with: "
        f"createdb -h localhost -U worknomic {_SAFE_DB_NAME} && "
        f"POSTGRES_DB={_SAFE_DB_NAME} alembic upgrade head"
    )

limiter.enabled = False

# bcrypt defaults to 12 rounds (~250 ms/hash) — fine for prod, a tax in tests
# where _register_agent hashes password + api_key on every signup. Drop to the
# minimum permitted rounds so verdict tests (many agents each) aren't
# bcrypt-bound.
pwd_context.update(bcrypt__rounds=4)


@pytest.fixture(autouse=True)
def _mock_openreview_profile_exists(request, monkeypatch):
    """Every signup in the test suite uses a fabricated OpenReview ID.
    Short-circuit the HTTP lookup in the signup endpoint so tests never
    hit the network. ``test_openreview.py`` exercises the real client
    directly, so we skip the override there."""
    if request.node.nodeid.startswith("tests/test_openreview.py"):
        return

    async def _always_true(openreview_id: str) -> bool:
        return True

    import app.api.v1.endpoints.auth as auth_module

    monkeypatch.setattr(auth_module, "profile_exists", _always_true)


@pytest.fixture(autouse=True)
def _mock_moderation_pass(request, monkeypatch):
    """Comment moderation calls out to Gemini. Bypass it in the test suite
    so unit/integration tests don't hit the network or require an API key.
    ``test_moderation.py`` exercises the real client directly, so we skip
    the override there. Individual tests that need to simulate a VIOLATE
    or an upstream outage monkeypatch the symbol directly themselves."""
    if request.node.nodeid.startswith("tests/test_moderation.py"):
        return

    from app.core.moderation import (
        ModerationCategory,
        ModerationResult,
        ModerationVerdict,
    )

    async def _always_pass(content, *, paper_title=None):
        return ModerationResult(
            verdict=ModerationVerdict.PASS,
            category=ModerationCategory.OK,
            reason="ok",
        )

    import app.api.v1.endpoints.comments as comments_module

    monkeypatch.setattr(comments_module, "moderate_comment", _always_pass)


async def promote_to_superuser(actor_id: str) -> None:
    # Per-call engine: asyncpg connections bind to the event loop they were
    # created on, so a cached engine breaks across tests. Matches the pattern
    # used by the client/db_session fixtures below.
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE human_account SET is_superuser = true WHERE id = :id"),
            {"id": actor_id},
        )
    await engine.dispose()


async def set_agent_karma(agent_name: str, karma: float) -> None:
    # See promote_to_superuser above for the per-call-engine rationale.
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE agent SET karma = :k WHERE id IN "
                "(SELECT id FROM actor WHERE name = :n)"
            ),
            {"k": karma, "n": agent_name},
        )
    await engine.dispose()


async def set_paper_status(
    paper_id: str,
    status: str,
    created_at=None,
    deliberating_at=None,
) -> None:
    """Force a paper into a given lifecycle phase for tests.

    Writes ``status``/``created_at``/``deliberating_at`` directly so tests
    don't need to wait for the cron script or 48h to elapse.
    """
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    assignments = ["status = :status"]
    params: dict = {"status": status, "id": paper_id}
    if created_at is not None:
        assignments.append("created_at = :created_at")
        params["created_at"] = created_at
    if deliberating_at is not None:
        assignments.append("deliberating_at = :deliberating_at")
        params["deliberating_at"] = deliberating_at
    sql = f"UPDATE paper SET {', '.join(assignments)} WHERE id = :id"
    async with engine.begin() as conn:
        await conn.execute(text(sql), params)
    await engine.dispose()


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session", autouse=True)
async def create_test_db():
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    yield


class _AutoVerifyAsyncClient(AsyncClient):
    """AsyncClient that backfills the pre-verification signup contract.

    Most legacy tests rely on ``POST /auth/signup`` returning a TokenResponse
    (access_token + actor_id + ...). The new contract returns
    ``{verification_required, email}`` and a separate verify step is needed.
    To avoid rewriting every callsite, this client intercepts a 201
    signup response, marks the new human as verified directly in the DB,
    logs in to mint a real access token, and returns a TokenResponse-shaped
    response body so legacy ``access_token``/``actor_id`` reads keep working.

    Tests that explicitly exercise the verification flow use the
    ``raw_client`` fixture instead.
    """

    def __init__(self, *args, engine: AsyncEngine, **kwargs):
        super().__init__(*args, **kwargs)
        self._engine = engine

    async def post(self, url, *args, **kwargs):
        resp = await super().post(url, *args, **kwargs)
        if not url.endswith("/auth/signup") or resp.status_code != 201:
            return resp
        body = resp.json()
        if "verification_required" not in body:
            return resp

        email = body["email"]
        password = kwargs["json"]["password"]

        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    text(
                        "UPDATE human_account SET email_verified = TRUE "
                        "WHERE email = :email RETURNING id"
                    ),
                    {"email": email},
                )
            ).one()
            actor_id = str(row[0])

        login = await super().post(
            url.replace("/auth/signup", "/auth/login"),
            json={"email": email, "password": password},
        )
        assert login.status_code == 200, login.text
        new_body = {**login.json(), "actor_id": actor_id}
        resp._content = json.dumps(new_body).encode()
        resp.headers["content-length"] = str(len(resp._content))
        return resp


@pytest.fixture
async def client(request) -> AsyncGenerator[AsyncClient, None]:
    from app.db.session import get_db

    # Override the app's DB dependency with a fresh engine for this test,
    # avoiding asyncpg "Future attached to different loop" errors.
    test_engine_client = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    test_session_factory = async_sessionmaker(test_engine_client, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    raw_optout = (
        "tests/test_auth.py",
        "tests/core/",
    )
    use_raw = any(request.node.nodeid.startswith(p) for p in raw_optout)

    transport = ASGITransport(app=app)
    if use_raw:
        ctx = AsyncClient(transport=transport, base_url="http://test")
    else:
        ctx = _AutoVerifyAsyncClient(
            transport=transport, base_url="http://test", engine=test_engine_client
        )
    async with ctx as c:
        yield c

    app.dependency_overrides.clear()
    await test_engine_client.dispose()


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = session_factory(bind=connection)

        yield session

        await session.close()
        await transaction.rollback()

    await engine.dispose()
