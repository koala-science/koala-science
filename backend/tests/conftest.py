import pytest
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.db.base import Base
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import pwd_context
from app.main import app

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
