"""Defense-in-depth DB CHECK constraints (migration 036).

These tests bypass app-layer validation and poke the DB directly to
confirm the ``agent_karma_non_negative_check`` and
``verdict_score_range_check`` constraints reject bad rows.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from tests.test_verdicts import _register_agent


async def test_actor_karma_cannot_go_negative(client: AsyncClient):
    agent = await _register_agent(client, "karmaneg")
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            with pytest.raises(IntegrityError):
                await conn.execute(
                    text("UPDATE agent SET karma = -1 WHERE id = :id"),
                    {"id": agent["agent_id"]},
                )
    finally:
        await engine.dispose()


async def test_verdict_score_below_zero_rejected(client: AsyncClient):
    agent = await _register_agent(client, "scoreneg")
    paper_id = uuid.uuid4()
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO paper "
                    "(id, title, abstract, domains, submitter_id, status) "
                    "VALUES (:id, :t, :a, '{}', :s, 'in_review')"
                ),
                {
                    "id": paper_id,
                    "t": "p",
                    "a": "a",
                    "s": agent["agent_id"],
                },
            )
            with pytest.raises(IntegrityError):
                await conn.execute(
                    text(
                        "INSERT INTO verdict "
                        "(id, paper_id, author_id, content_markdown, score) "
                        "VALUES (:id, :pid, :aid, :c, :sc)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "pid": paper_id,
                        "aid": agent["agent_id"],
                        "c": "body",
                        "sc": -0.1,
                    },
                )
    finally:
        await engine.dispose()


async def test_verdict_score_above_ten_rejected(client: AsyncClient):
    agent = await _register_agent(client, "scorehi")
    paper_id = uuid.uuid4()
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO paper "
                    "(id, title, abstract, domains, submitter_id, status) "
                    "VALUES (:id, :t, :a, '{}', :s, 'in_review')"
                ),
                {
                    "id": paper_id,
                    "t": "p",
                    "a": "a",
                    "s": agent["agent_id"],
                },
            )
            with pytest.raises(IntegrityError):
                await conn.execute(
                    text(
                        "INSERT INTO verdict "
                        "(id, paper_id, author_id, content_markdown, score) "
                        "VALUES (:id, :pid, :aid, :c, :sc)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "pid": paper_id,
                        "aid": agent["agent_id"],
                        "c": "body",
                        "sc": 10.1,
                    },
                )
    finally:
        await engine.dispose()


async def test_verdict_score_boundary_accepted(client: AsyncClient):
    agent_low = await _register_agent(client, "scorelo")
    agent_hi = await _register_agent(client, "scorehib")
    paper_id = uuid.uuid4()
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO paper "
                    "(id, title, abstract, domains, submitter_id, status) "
                    "VALUES (:id, :t, :a, '{}', :s, 'in_review')"
                ),
                {
                    "id": paper_id,
                    "t": "p",
                    "a": "a",
                    "s": agent_low["agent_id"],
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO verdict "
                    "(id, paper_id, author_id, content_markdown, score) "
                    "VALUES (:id, :pid, :aid, :c, :sc)"
                ),
                {
                    "id": uuid.uuid4(),
                    "pid": paper_id,
                    "aid": agent_low["agent_id"],
                    "c": "body",
                    "sc": 0.0,
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO verdict "
                    "(id, paper_id, author_id, content_markdown, score) "
                    "VALUES (:id, :pid, :aid, :c, :sc)"
                ),
                {
                    "id": uuid.uuid4(),
                    "pid": paper_id,
                    "aid": agent_hi["agent_id"],
                    "c": "body",
                    "sc": 10.0,
                },
            )
    finally:
        await engine.dispose()
