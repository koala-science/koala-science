"""Concurrency regression for the ``openreview_id`` cap trigger.

Migration 030 installs a BEFORE INSERT trigger that caps each human at 3
OpenReview IDs via a ``COUNT(*)`` check. Under ``READ COMMITTED`` two
concurrent inserts can both see ``count < 3`` and both succeed — TOCTOU.
Migration 033 fixes this by serializing inserts for the same human with a
transactional advisory lock.

This test fires 4 concurrent inserts from independent connections and
asserts the cap holds (exactly 3 rows, at least one insert rejected).
"""
import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.identity import HumanAccount


# Mirrors the function body shipped in migration 033. The session-scoped
# ``create_test_db`` fixture only runs ``Base.metadata.create_all``, which
# does not install SQL functions or triggers, so we install them here.
_TRIGGER_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION enforce_openreview_id_cap()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtext('openreview_id_cap'),
        hashtext(NEW.human_account_id::text)
    );
    IF (
        SELECT COUNT(*) FROM openreview_id
        WHERE human_account_id = NEW.human_account_id
    ) >= 3 THEN
        RAISE EXCEPTION 'a human may have at most 3 OpenReview IDs';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


@pytest.fixture
async def cap_trigger_installed():
    """Install the fixed trigger for the duration of this test."""
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(text(_TRIGGER_FUNCTION_SQL))
        await conn.execute(
            text(
                "DROP TRIGGER IF EXISTS openreview_id_cap_trigger "
                "ON openreview_id;"
            )
        )
        await conn.execute(
            text(
                "CREATE TRIGGER openreview_id_cap_trigger "
                "BEFORE INSERT ON openreview_id "
                "FOR EACH ROW EXECUTE FUNCTION enforce_openreview_id_cap();"
            )
        )
    try:
        yield
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "DROP TRIGGER IF EXISTS openreview_id_cap_trigger "
                    "ON openreview_id;"
                )
            )
        await engine.dispose()


async def _insert_openreview_id(human_id: uuid.UUID, value: str) -> None:
    """Insert one ``openreview_id`` row on a fresh engine.

    Each call gets its own engine + transaction so the 4 tasks truly race
    inside Postgres rather than serializing on a shared connection.
    """
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO openreview_id (id, human_account_id, value, "
                    "created_at, updated_at) VALUES "
                    "(gen_random_uuid(), :hid, :val, now(), now())"
                ),
                {"hid": human_id, "val": value},
            )
    finally:
        await engine.dispose()


async def test_cap_holds_under_concurrent_inserts(cap_trigger_installed):
    """Four concurrent inserts for one human: exactly 3 land, 1+ rejected."""
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    # Create + COMMIT the HumanAccount row via ORM so the concurrent
    # workers (each on their own transaction) can see it.
    async with session_factory() as session:
        human = HumanAccount(
            name="Race Target",
            email=f"race_{uuid.uuid4().hex[:8]}@example.com",
            hashed_password="hashed",
            oauth_provider="github",
            oauth_id=f"race_{uuid.uuid4().hex[:8]}",
        )
        session.add(human)
        await session.commit()
        human_id = human.id

    try:
        # Fire 4 concurrent inserts.
        results = await asyncio.gather(
            _insert_openreview_id(human_id, f"~Race_A_{uuid.uuid4().hex[:6]}"),
            _insert_openreview_id(human_id, f"~Race_B_{uuid.uuid4().hex[:6]}"),
            _insert_openreview_id(human_id, f"~Race_C_{uuid.uuid4().hex[:6]}"),
            _insert_openreview_id(human_id, f"~Race_D_{uuid.uuid4().hex[:6]}"),
            return_exceptions=True,
        )

        succeeded = [r for r in results if not isinstance(r, BaseException)]
        raised = [r for r in results if isinstance(r, BaseException)]

        # At least one insert must be rejected with the cap error.
        assert raised, (
            f"expected at least one insert to be rejected, "
            f"got {len(succeeded)} successes and 0 rejections"
        )
        assert any(
            "at most 3 OpenReview IDs" in str(e) for e in raised
        ), f"unexpected error(s): {[repr(e) for e in raised]}"

        # Final count must be exactly the cap.
        async with session_factory() as session:
            count = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM openreview_id "
                        "WHERE human_account_id = :hid"
                    ),
                    {"hid": human_id},
                )
            ).scalar_one()
        assert count == 3, (
            f"expected final count=3, got {count} "
            f"(successes={len(succeeded)}, rejections={len(raised)})"
        )
    finally:
        # Clean up so repeat runs stay deterministic.
        async with session_factory() as session:
            await session.execute(
                text(
                    "DELETE FROM openreview_id WHERE human_account_id = :hid"
                ),
                {"hid": human_id},
            )
            await session.execute(
                text("DELETE FROM human_account WHERE id = :hid"),
                {"hid": human_id},
            )
            await session.execute(
                text("DELETE FROM actor WHERE id = :hid"), {"hid": human_id}
            )
            await session.commit()
        await engine.dispose()
