import pytest
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.db.base import Base
from app.core.config import settings
from app.core.rate_limit import limiter
from app.main import app

limiter.enabled = False


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
