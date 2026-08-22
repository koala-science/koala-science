from pathlib import Path
from dotenv import load_dotenv

# Load .env.test before app.core.config is imported.
_ENV_TEST = Path(__file__).resolve().parent.parent / ".env.test"
if _ENV_TEST.exists():
    load_dotenv(_ENV_TEST, override=True)

import pytest
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.db.base import Base
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import hash_password, pwd_context
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
# minimum permitted rounds so tests that register many agents aren't
# bcrypt-bound.
pwd_context.update(bcrypt__rounds=4)


# Every signup in the suite uses a fabricated OpenReview ID and an @example.com
# address. The stub profile lists those domains so the institutional-domain match
# passes; tests that exercise the rejection paths override it themselves.
TEST_PROFILE_DOMAINS = ("example.com", "test.example")


@pytest.fixture(autouse=True)
def _stub_openreview_profile(request, monkeypatch):
    """Keep signup off the network.

    ``test_openreview.py`` drives the real client, so it is skipped here.
    """
    if request.node.nodeid.startswith("tests/test_openreview.py"):
        return

    from app.core.openreview import OpenReviewProfile

    async def _stub(openreview_id: str) -> OpenReviewProfile:
        return OpenReviewProfile(
            id=openreview_id,
            name="Test Human",
            email_domains=TEST_PROFILE_DOMAINS,
        )

    import app.api.v1.endpoints.auth as auth_module

    monkeypatch.setattr(auth_module, "fetch_profile", _stub)


# Signup mails a link and the account holds no credentials until it is redeemed,
# so tests cannot shortcut verification with a flag — they have to apply the
# pending submission. Tests that need the raw link capture it themselves; a
# module-level outbox here is not safe, because pytest can import this file under
# two names and each copy would get its own list.


async def mark_email_verified(email: str, password: str) -> None:
    """Stand in for redeeming the link: attach the claim and set a password.

    Verification itself — the token, its expiry, single use, and the fact that the
    password comes from whoever holds the mailbox — is covered directly in
    test_email_verification.
    """
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE human_account h SET email_verified = true, "
                "  hashed_password = :pw, "
                "  openreview_id = t.pending_openreview_id, "
                "  openreview_name = t.pending_openreview_name "
                "FROM (SELECT DISTINCT ON (human_account_id) * FROM email_verification_token "
                "      ORDER BY human_account_id, created_at DESC) t "
                "WHERE t.human_account_id = h.id AND h.email = :e"
            ),
            {"e": email, "pw": hash_password(password)},
        )
    await engine.dispose()


async def _set_actor_name(email: str, name: str) -> None:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE actor SET name = :n WHERE id = "
                "(SELECT id FROM human_account WHERE email = :e)"
            ),
            {"n": name, "e": email},
        )
    await engine.dispose()


async def complete_signup(client, payload: dict) -> tuple[str, str]:
    """Sign up, verify, log in. Returns (access_token, actor_id).

    Signup no longer returns tokens — an account cannot act until the address it
    claims has been proven — so every test that needs an authenticated human goes
    through here.
    """
    password = payload.pop("password")
    name = payload.pop("name", None)
    resp = await client.post("/api/v1/auth/signup", json=payload)
    assert resp.status_code == 201, resp.text

    await mark_email_verified(payload["email"], password)
    if name is not None:
        await _set_actor_name(payload["email"], name)

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": password},
    )
    assert login.status_code == 200, login.text
    body = login.json()
    return body["access_token"], body["actor_id"]


async def set_owner_points(agent_name: str, points: int) -> None:
    """Force the balance of the human owning this agent, to exercise the limit.

    Points live on the owner, so a test that names an agent is really naming the
    pool that agent draws on.
    """
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE human_account SET points = :p WHERE id IN "
                 "(SELECT owner_id FROM agent WHERE id IN "
                 "(SELECT id FROM actor WHERE name = :n))"),
            {"p": points, "n": agent_name},
        )
    await engine.dispose()


async def set_human_points(actor_id: str, points: int) -> None:
    """Force a human's balance directly, to exercise the spend limit."""
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE human_account SET points = :p WHERE id = :id"),
            {"p": points, "id": actor_id},
        )
    await engine.dispose()


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



async def unrelease_paper(paper_id: str) -> None:
    """Put a paper back into the pre-release embargo the ingest scripts create."""
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE paper SET released_at = NULL WHERE id = :id"), {"id": paper_id}
        )


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


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    from app.db.session import get_db

    # Override the app's DB dependency with a fresh engine for this test,
    # avoiding asyncpg "Future attached to different loop" errors.
    test_engine_client = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    test_session_factory = async_sessionmaker(test_engine_client, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
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
