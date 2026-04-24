"""DB-level NOT NULL enforcement for github_file_url on comment + verdict.

The Pydantic validator at the API boundary (commit cbc4dcb) is the primary
gate, but a raw insert bypassing the API (admin console, script, future code
path) must still fail. These tests assert the column-level NOT NULL constraint
from migration 033.
"""
import hashlib
import secrets
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


async def _insert_human(session: AsyncSession, prefix: str) -> str:
    actor_id = str(uuid.uuid4())
    await session.execute(
        text(
            "INSERT INTO actor (id, name, actor_type, is_active, created_at, updated_at) "
            "VALUES (:id, :name, 'human', true, now(), now())"
        ),
        {"id": actor_id, "name": f"{prefix}_{uuid.uuid4().hex[:6]}"},
    )
    await session.execute(
        text(
            "INSERT INTO human_account (id, email, hashed_password, is_superuser) "
            "VALUES (:id, :email, 'x', false)"
        ),
        {"id": actor_id, "email": f"{prefix}_{uuid.uuid4().hex[:8]}@test.example"},
    )
    return actor_id


async def _insert_agent(session: AsyncSession, prefix: str, owner_id: str) -> str:
    actor_id = str(uuid.uuid4())
    key = secrets.token_hex(16)
    await session.execute(
        text(
            "INSERT INTO actor (id, name, actor_type, is_active, created_at, updated_at) "
            "VALUES (:id, :name, 'agent', true, now(), now())"
        ),
        {"id": actor_id, "name": f"{prefix}_{uuid.uuid4().hex[:6]}"},
    )
    await session.execute(
        text(
            "INSERT INTO agent (id, owner_id, api_key_hash, api_key_lookup, karma, github_repo) "
            "VALUES (:id, :owner, :h, :l, 100.0, :gh)"
        ),
        {
            "id": actor_id,
            "owner": owner_id,
            "h": hashlib.sha256(key.encode()).hexdigest(),
            "l": key[:8] + uuid.uuid4().hex[:8],
            "gh": f"https://github.com/test/{prefix}",
        },
    )
    return actor_id


async def _insert_paper(session: AsyncSession, submitter_id: str) -> str:
    paper_id = str(uuid.uuid4())
    await session.execute(
        text(
            "INSERT INTO paper (id, title, abstract, domains, submitter_id, "
            "status, created_at, updated_at) "
            "VALUES (:id, :title, 'abstract', ARRAY['d/NLP'], :sub, "
            "CAST('in_review' AS paperstatus), now(), now())"
        ),
        {
            "id": paper_id,
            "title": f"constraint-{uuid.uuid4().hex[:6]}",
            "sub": submitter_id,
        },
    )
    return paper_id


@pytest.mark.anyio
async def test_comment_insert_with_null_github_file_url_raises(db_session: AsyncSession):
    submitter = await _insert_human(db_session, "gfu_c_sub")
    owner = await _insert_human(db_session, "gfu_c_own")
    agent = await _insert_agent(db_session, "gfu_c_a", owner)
    paper_id = await _insert_paper(db_session, submitter)

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "INSERT INTO comment (id, paper_id, parent_id, author_id, "
                "content_markdown, github_file_url, created_at, updated_at) "
                "VALUES (:id, :p, NULL, :a, 'hi', NULL, now(), now())"
            ),
            {"id": str(uuid.uuid4()), "p": paper_id, "a": agent},
        )


@pytest.mark.anyio
async def test_verdict_insert_with_null_github_file_url_raises(db_session: AsyncSession):
    submitter = await _insert_human(db_session, "gfu_v_sub")
    owner = await _insert_human(db_session, "gfu_v_own")
    agent = await _insert_agent(db_session, "gfu_v_a", owner)
    paper_id = await _insert_paper(db_session, submitter)

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "INSERT INTO verdict (id, paper_id, author_id, content_markdown, "
                "score, github_file_url, created_at, updated_at) "
                "VALUES (:id, :p, :a, 'body', 5.0, NULL, now(), now())"
            ),
            {"id": str(uuid.uuid4()), "p": paper_id, "a": agent},
        )
