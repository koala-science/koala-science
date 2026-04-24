"""Temporal fire-and-forget triggers log at WARNING on failure.

A bad TEMPORAL_HOST or crashed worker must not be silent — these tests
pin the observability contract so triage has a stack trace when the
next outage happens.

Behavior preserved: endpoints still return 2xx when Temporal is down.
"""
import logging
import uuid
from unittest.mock import patch

from httpx import AsyncClient

from tests.conftest import promote_to_superuser


# --- helpers (mirrors tests/test_comments.py + test_papers.py patterns) -----

def _unique_email(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


def _unique_openreview_id(prefix: str) -> str:
    safe = "".join(c for c in prefix if c.isalnum()) or "T"
    return f"~{safe.capitalize()}_{uuid.uuid4().hex[:8]}1"


async def _signup(client: AsyncClient, prefix: str) -> tuple[str, str]:
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Test User",
            "email": _unique_email(prefix),
            "password": "secure_password_123",
            "openreview_ids": [_unique_openreview_id(prefix)],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["access_token"], body["actor_id"]


async def _submit_paper_as_superuser(
    client: AsyncClient, token: str, actor_id: str
) -> str:
    await promote_to_superuser(actor_id)
    resp = await client.post(
        "/api/v1/papers/",
        json={
            "title": f"Paper {uuid.uuid4().hex[:6]}",
            "abstract": "An abstract.",
            "domain": "NLP",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_agent_key(client: AsyncClient, token: str, name: str) -> str:
    resp = await client.post(
        "/api/v1/auth/agents",
        json={"name": name, "github_repo": f"https://github.com/example/{name}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["api_key"]


# --- tests ------------------------------------------------------------------

async def test_paper_submission_logs_temporal_failure(
    client: AsyncClient, caplog
):
    """Paper submit still returns 201 when Temporal is down, but logs WARNING."""
    caplog.set_level(logging.WARNING, logger="app.api.v1.endpoints.papers")

    token, actor_id = await _signup(client, "temporal_paper")
    await promote_to_superuser(actor_id)

    with patch(
        "temporalio.client.Client.connect",
        side_effect=RuntimeError("temporal down"),
    ):
        resp = await client.post(
            "/api/v1/papers/",
            json={
                "title": f"Paper {uuid.uuid4().hex[:6]}",
                "abstract": "An abstract that would normally trigger an embedding.",
                "domain": "NLP",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    # Fire-and-forget: submit succeeds even when Temporal is unreachable.
    assert resp.status_code == 201, resp.text

    matches = [
        r for r in caplog.records
        if "Failed to trigger EmbeddingGenerationWorkflow" in r.getMessage()
    ]
    assert matches, f"expected EmbeddingGenerationWorkflow warning, got: {caplog.text}"
    rec = matches[-1]
    assert rec.levelno == logging.WARNING
    assert rec.exc_info is not None


async def test_comment_creation_logs_temporal_failure(
    client: AsyncClient, caplog
):
    """Comment post still returns 201 when Temporal is down, but logs WARNING."""
    caplog.set_level(logging.WARNING, logger="app.api.v1.endpoints.comments")

    token, actor_id = await _signup(client, "temporal_comment_owner")
    paper_id = await _submit_paper_as_superuser(client, token, actor_id)
    api_key = await _create_agent_key(client, token, f"agent_{uuid.uuid4().hex[:6]}")

    with patch(
        "temporalio.client.Client.connect",
        side_effect=RuntimeError("temporal down"),
    ):
        resp = await client.post(
            "/api/v1/comments/",
            json={
                "paper_id": paper_id,
                "content_markdown": "Interesting paper.",
                "github_file_url": "https://github.com/example/agent/blob/main/c.md",
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )

    # Fire-and-forget: comment succeeds even when Temporal is unreachable.
    assert resp.status_code == 201, resp.text

    matches = [
        r for r in caplog.records
        if "Failed to trigger ThreadEmbeddingWorkflow" in r.getMessage()
    ]
    assert matches, f"expected ThreadEmbeddingWorkflow warning, got: {caplog.text}"
    rec = matches[-1]
    assert rec.levelno == logging.WARNING
    assert rec.exc_info is not None
