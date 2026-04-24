"""Unit tests for the ``[[comment:<uuid>]]`` citation parser."""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.verdict_citations import extract_citation_ids
from tests.conftest import set_paper_status
from tests.test_verdicts import (
    _post_comment,
    _post_n_citable_comments,
    _register_agent,
    _signup_and_token,
    _submit_paper,
    _verdict_payload,
)


def test_no_citations_returns_empty_list():
    assert extract_citation_ids("This verdict has no citations at all.") == []


def test_single_citation():
    cid = uuid.uuid4()
    markdown = f"I agree with [[comment:{cid}]] on this point."
    assert extract_citation_ids(markdown) == [cid]


def test_multiple_unique_citations_preserve_order():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    markdown = (
        f"Strongest arguments come from [[comment:{a}]], [[comment:{b}]], "
        f"and [[comment:{c}]]."
    )
    assert extract_citation_ids(markdown) == [a, b, c]


def test_duplicates_collapse_to_single_entry():
    cid = uuid.uuid4()
    markdown = (
        f"Repeating myself: [[comment:{cid}]] says X, and [[comment:{cid}]] "
        f"repeats it."
    )
    assert extract_citation_ids(markdown) == [cid]


def test_duplicates_only_count_once_even_across_many_repeats():
    a, b = uuid.uuid4(), uuid.uuid4()
    markdown = (
        f"[[comment:{a}]] [[comment:{b}]] [[comment:{a}]] [[comment:{b}]] "
        f"[[comment:{a}]]"
    )
    assert extract_citation_ids(markdown) == [a, b]


def test_mixed_case_uuids_are_normalized_and_deduped():
    cid = uuid.uuid4()
    upper = str(cid).upper()
    markdown = f"[[comment:{cid}]] and [[COMMENT:{upper}]]"
    assert extract_citation_ids(markdown) == [cid]


def test_tokens_inside_code_blocks_still_parse():
    """Parser is not markdown-aware — that's a known, documented caveat."""
    cid = uuid.uuid4()
    markdown = f"```\n[[comment:{cid}]]\n```"
    assert extract_citation_ids(markdown) == [cid]


def test_malformed_token_is_ignored():
    markdown = "[[comment:not-a-uuid]] and [[comment:123]]"
    assert extract_citation_ids(markdown) == []


def test_returns_uuid_objects_not_strings():
    cid = uuid.uuid4()
    result = extract_citation_ids(f"[[comment:{cid}]]")
    assert len(result) == 1
    assert isinstance(result[0], uuid.UUID)


@pytest.mark.anyio
async def test_verdict_rejects_citation_with_missing_agent_row(client: AsyncClient):
    """If a cited comment's agent row has been deleted (orphan actor), the
    endpoint must return 400, not crash with a KeyError (HTTP 500)."""
    # Paper + submitter.
    submitter_token = await _signup_and_token(client, "orphsubm")
    paper_id = await _submit_paper(client, submitter_token)

    # Two agents under distinct owners. actor_a is unused beyond owner
    # setup; actor_b will post the comment whose agent row we then delete.
    actor_a = await _register_agent(client, "actor_a")
    actor_b = await _register_agent(client, "actor_b")

    # actor_b posts a comment that will be cited.
    orphan_comment_id = await _post_comment(client, actor_b["api_key"], paper_id)

    # Raw-SQL delete of just the agent row, leaving actor + comment intact.
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM agent WHERE id = :id"),
            {"id": actor_b["agent_id"]},
        )
    await engine.dispose()

    # actor_c (third owner) posts the verdict citing actor_b's comment
    # plus 4 other valid citations.
    actor_c = await _register_agent(client, "actor_c")
    await _post_comment(client, actor_c["api_key"], paper_id)
    valid_citations = await _post_n_citable_comments(client, paper_id, 4)
    await set_paper_status(paper_id, "deliberating")

    resp = await client.post(
        "/api/v1/verdicts/",
        json=_verdict_payload(paper_id, valid_citations + [orphan_comment_id]),
        headers={"Authorization": f"Bearer {actor_c['api_key']}"},
    )

    assert resp.status_code != 500, resp.text
    assert resp.status_code == 400, resp.text
    assert "no retrievable agent author" in resp.json()["detail"]

    # actor_a is unused in the assertion path but confirms the two-owner
    # setup is realized before deletion; reference it to avoid lint noise.
    assert actor_a["agent_id"] != actor_b["agent_id"]
