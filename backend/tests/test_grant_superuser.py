"""
Tests for backend/scripts/grant_superuser.py confirmation hardening.

The script is driven via subprocess + stdin so we exercise the real ``input()``
call and the real ``SUPERUSER_AUTO_CONFIRM`` env-var short-circuit. A dedicated
DB (koala_wt_grant_su) is used to keep worktrees isolated.
"""
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.security import hash_password
from app.db.base import Base
from app.models.identity import HumanAccount, OpenReviewId


REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"


@pytest.fixture
async def fresh_db():
    """Drop+recreate all tables and seed a single HumanAccount row.

    The conftest-level ``create_test_db`` fixture runs once per session; this
    fixture gives each test a clean slate plus a known starting row.
    """
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        user = HumanAccount(
            name="Alice Smith",
            email="alice@example.com",
            hashed_password=hash_password("not-the-password-1234"),
            is_superuser=False,
            openreview_ids=[OpenReviewId(value="~Alice_Smith1")],
        )
        db.add(user)
        await db.commit()
        seeded_id = str(user.id)

    yield {"engine": engine, "seeded_id": seeded_id}

    await engine.dispose()


async def _is_superuser(engine, email: str) -> bool | None:
    async with engine.begin() as conn:
        row = (await conn.execute(
            text("SELECT is_superuser FROM human_account WHERE email = :e"),
            {"e": email},
        )).first()
    return None if row is None else bool(row[0])


def _run(args, stdin_text: str = "", extra_env: dict | None = None):
    env = {**os.environ, **(extra_env or {})}
    return subprocess.run(
        [sys.executable, "-m", "scripts.grant_superuser", *args],
        input=stdin_text,
        capture_output=True,
        text=True,
        cwd=str(BACKEND),
        env=env,
        timeout=30,
    )


async def test_confirm_yes_promotes(fresh_db):
    result = _run(["--email", "alice@example.com"], stdin_text="y\n")
    assert result.returncode == 0, result.stderr
    assert "Matched account:" in result.stdout
    assert "Alice Smith" in result.stdout
    assert "Existing agents:  0" in result.stdout
    assert "~Alice_Smith1" in result.stdout
    assert "Promoted alice@example.com to superuser." in result.stdout
    assert await _is_superuser(fresh_db["engine"], "alice@example.com") is True


async def test_confirm_no_aborts(fresh_db):
    result = _run(["--email", "alice@example.com"], stdin_text="n\n")
    assert result.returncode == 2
    assert "Aborted" in result.stderr
    assert await _is_superuser(fresh_db["engine"], "alice@example.com") is False


async def test_empty_answer_aborts(fresh_db):
    result = _run(["--email", "alice@example.com"], stdin_text="\n")
    assert result.returncode == 2
    assert "Aborted" in result.stderr
    assert await _is_superuser(fresh_db["engine"], "alice@example.com") is False


async def test_auto_confirm_env_promotes_without_prompt(fresh_db):
    result = _run(
        ["--email", "alice@example.com"],
        stdin_text="",  # nothing on stdin — prompt must be skipped
        extra_env={"SUPERUSER_AUTO_CONFIRM": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert "Promote this account to superuser?" not in result.stdout
    assert "Promoted alice@example.com to superuser." in result.stdout
    assert await _is_superuser(fresh_db["engine"], "alice@example.com") is True


async def test_already_superuser_is_noop(fresh_db):
    # Flip the seeded row to superuser first.
    async with fresh_db["engine"].begin() as conn:
        await conn.execute(
            text("UPDATE human_account SET is_superuser = true WHERE email = :e"),
            {"e": "alice@example.com"},
        )

    result = _run(["--email", "alice@example.com"], stdin_text="")
    assert result.returncode == 0, result.stderr
    assert "already a superuser" in result.stdout
    assert "Matched account:" not in result.stdout


async def test_nonexistent_email_without_create_exits_1(fresh_db):
    result = _run(["--email", "ghost@example.com"], stdin_text="")
    assert result.returncode == 1
    assert "No account found" in result.stderr
    assert await _is_superuser(fresh_db["engine"], "ghost@example.com") is None


async def test_create_branch_with_confirmation(fresh_db):
    result = _run(
        ["--email", "bob@example.com", "--create"],
        stdin_text="y\n",
        extra_env={
            "SUPERUSER_NAME": "Bob Jones",
            "SUPERUSER_OPENREVIEW_ID": "~Bob_Jones1",
            "SUPERUSER_PASSWORD": "correcthorsebatterystaple",
        },
    )
    assert result.returncode == 0, result.stderr
    assert "Create new superuser with:" in result.stdout
    assert "Bob Jones" in result.stdout
    assert "~Bob_Jones1" in result.stdout
    assert "Created superuser bob@example.com" in result.stdout
    assert await _is_superuser(fresh_db["engine"], "bob@example.com") is True


async def test_create_branch_abort_on_no(fresh_db):
    result = _run(
        ["--email", "carol@example.com", "--create"],
        stdin_text="n\n",
        extra_env={
            "SUPERUSER_NAME": "Carol",
            "SUPERUSER_OPENREVIEW_ID": "~Carol1",
            "SUPERUSER_PASSWORD": "correcthorsebatterystaple",
        },
    )
    assert result.returncode == 2
    assert "Aborted" in result.stderr
    assert await _is_superuser(fresh_db["engine"], "carol@example.com") is None
