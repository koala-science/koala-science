"""Flagging a check result as wrong.

Humans only, one flag per person per check row, withdrawable. Counts are public
and reasons are not: the paper page must never carry the text, and only the
person who wrote it or a superuser can read it back.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core import checks
from app.core.config import settings
from tests.conftest import complete_signup, promote_to_superuser


PAYLOAD = {
    "claim": "The evaluation omits a no-retrieval baseline.",
    "position": "negative",
    "evidence": "Table 2 compares only retrieval variants; Section 4.1 never reports one.",
}


def _unique_email(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


def _unique_openreview_id(prefix: str) -> str:
    return f"~{prefix}_{uuid.uuid4().hex[:8]}1"


async def _signup(client: AsyncClient, prefix: str) -> tuple[str, str]:
    return await complete_signup(client, {
        "name": "Test User",
        "email": _unique_email(prefix),
        "password": "secure_password_123",
        "openreview_id": _unique_openreview_id(prefix),
    })


async def _create_agent_key(client: AsyncClient, token: str, name: str) -> str:
    resp = await client.post(
        "/api/v1/auth/agents",
        json={"name": name, "github_repo": f"https://github.com/example/{name}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["api_key"]


async def _submit_paper(client: AsyncClient, token: str, actor_id: str) -> str:
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


async def set_check_status(check_id: str, status: str) -> None:
    """Force a check's result.

    Checks are advanced by a worker, so nothing in the request path produces a
    `passed` or `failed` row — a test that needs one writes it.
    """
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE argument_check SET status = :s WHERE id = :id"),
            {"s": status, "id": check_id},
        )
    await engine.dispose()


async def _argument_with_check(
    client: AsyncClient,
    monkeypatch,
    prefix: str,
    status: str = "failed",
    check_name: str = "validity",
) -> tuple[str, str, str]:
    """Returns (paper_id, argument_id, check_id) with the check in `status`.

    The pipeline is narrowed to a single check so the test controls which name
    the row carries: a failed `moderation` row withholds the whole argument,
    which is a different behaviour and has its own test.
    """
    monkeypatch.setattr(checks, "CHECKS", {check_name: "v1"})
    token, actor_id = await _signup(client, prefix)
    paper_id = await _submit_paper(client, token, actor_id)
    api_key = await _create_agent_key(client, token, f"{prefix}_agent")

    resp = await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201, resp.text
    argument = resp.json()
    check_id = argument["checks"][0]["id"]
    if status != "pending":
        await set_check_status(check_id, status)
    return paper_id, argument["id"], check_id


async def _flag(client: AsyncClient, token: str, check_id: str, reason: str = "The claim is atomic."):
    return await client.post(
        "/api/v1/check-flags/",
        json={"check_id": check_id, "reason": reason},
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest.mark.parametrize("status", ["passed", "failed"])
async def test_human_can_flag_a_resolved_check(client: AsyncClient, status: str, monkeypatch):
    _, _, check_id = await _argument_with_check(client, monkeypatch, f"flag_{status}", status)
    token, _ = await _signup(client, f"flagger_{status}")

    resp = await _flag(client, token, check_id)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["check_id"] == check_id
    assert body["reason"] == "The claim is atomic."


async def test_agents_cannot_flag(client: AsyncClient, monkeypatch):
    token, actor_id = await _signup(client, "agentflag")
    _, _, check_id = await _argument_with_check(client, monkeypatch, "agentflag_target")
    api_key = await _create_agent_key(client, token, "agentflag_agent")

    resp = await _flag(client, api_key, check_id)
    assert resp.status_code == 403
    assert "human" in resp.json()["detail"].lower()


async def test_flagging_requires_auth(client: AsyncClient, monkeypatch):
    _, _, check_id = await _argument_with_check(client, monkeypatch, "anonflag")

    resp = await client.post(
        "/api/v1/check-flags/",
        json={"check_id": check_id, "reason": "No."},
    )
    assert resp.status_code == 401


async def test_pending_check_cannot_be_flagged(client: AsyncClient, monkeypatch):
    _, _, check_id = await _argument_with_check(client, monkeypatch, "pendingflag", "pending")
    token, _ = await _signup(client, "pendingflagger")

    resp = await _flag(client, token, check_id)
    assert resp.status_code == 400
    assert "result" in resp.json()["detail"].lower()


async def test_unknown_check_is_not_found(client: AsyncClient):
    token, _ = await _signup(client, "unknownflag")

    resp = await _flag(client, token, str(uuid.uuid4()))
    assert resp.status_code == 404


async def test_withheld_argument_cannot_be_flagged(client: AsyncClient, monkeypatch):
    """An argument that failed moderation is withheld, so its checks are unreachable."""
    _, _, check_id = await _argument_with_check(
        client, monkeypatch, "withheld", "failed", check_name="moderation"
    )
    token, _ = await _signup(client, "withheld_flagger")

    resp = await _flag(client, token, check_id)
    assert resp.status_code == 404, resp.text


async def test_second_flag_by_the_same_human_conflicts(client: AsyncClient, monkeypatch):
    _, _, check_id = await _argument_with_check(client, monkeypatch, "dupflag")
    token, _ = await _signup(client, "dupflagger")

    assert (await _flag(client, token, check_id)).status_code == 201
    resp = await _flag(client, token, check_id, "Still wrong.")
    assert resp.status_code == 409


async def test_two_humans_both_count(client: AsyncClient, monkeypatch):
    paper_id, _, check_id = await _argument_with_check(client, monkeypatch, "twoflag")
    first, _ = await _signup(client, "twoflag_a")
    second, _ = await _signup(client, "twoflag_b")

    assert (await _flag(client, first, check_id)).status_code == 201
    assert (await _flag(client, second, check_id)).status_code == 201

    listing = await client.get(f"/api/v1/papers/{paper_id}/arguments")
    assert listing.status_code == 200
    check = listing.json()[0]["checks"][0]
    assert check["flag_count"] == 2


async def test_paper_listing_never_carries_reasons(client: AsyncClient, monkeypatch):
    paper_id, _, check_id = await _argument_with_check(client, monkeypatch, "leakflag")
    token, _ = await _signup(client, "leakflagger")
    secret = "This reason must never reach the paper page."
    assert (await _flag(client, token, check_id, secret)).status_code == 201

    anonymous = await client.get(f"/api/v1/papers/{paper_id}/arguments")
    authenticated = await client.get(
        f"/api/v1/papers/{paper_id}/arguments",
        headers={"Authorization": f"Bearer {token}"},
    )
    for resp in (anonymous, authenticated):
        assert resp.status_code == 200
        assert secret not in resp.text
        assert resp.json()[0]["checks"][0]["flag_count"] == 1


async def test_withdrawing_removes_only_your_own(client: AsyncClient, monkeypatch):
    paper_id, _, check_id = await _argument_with_check(client, monkeypatch, "withdrawflag")
    mine, _ = await _signup(client, "withdraw_mine")
    theirs, _ = await _signup(client, "withdraw_theirs")
    assert (await _flag(client, mine, check_id)).status_code == 201
    assert (await _flag(client, theirs, check_id)).status_code == 201

    resp = await client.delete(
        f"/api/v1/check-flags/{check_id}",
        headers={"Authorization": f"Bearer {mine}"},
    )
    assert resp.status_code == 204

    listing = await client.get(f"/api/v1/papers/{paper_id}/arguments")
    assert listing.json()[0]["checks"][0]["flag_count"] == 1


async def test_withdrawing_a_flag_never_posted_is_not_found(client: AsyncClient, monkeypatch):
    _, _, check_id = await _argument_with_check(client, monkeypatch, "nowithdraw")
    token, _ = await _signup(client, "nowithdrawer")

    resp = await client.delete(
        f"/api/v1/check-flags/{check_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_mine_returns_only_my_flags_on_that_paper(client: AsyncClient, monkeypatch):
    paper_id, _, check_id = await _argument_with_check(client, monkeypatch, "mineflag")
    other_paper_id, _, other_check_id = await _argument_with_check(client, monkeypatch, "mineflag_other")
    mine, _ = await _signup(client, "mineflagger")
    theirs, _ = await _signup(client, "mineflagger_other")

    assert (await _flag(client, mine, check_id, "Mine here.")).status_code == 201
    assert (await _flag(client, mine, other_check_id, "Mine elsewhere.")).status_code == 201
    assert (await _flag(client, theirs, check_id, "Theirs here.")).status_code == 201

    resp = await client.get(
        f"/api/v1/check-flags/mine?paper_id={paper_id}",
        headers={"Authorization": f"Bearer {mine}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [(f["check_id"], f["reason"]) for f in body] == [(check_id, "Mine here.")]

    empty = await client.get(
        f"/api/v1/check-flags/mine?paper_id={other_paper_id}",
        headers={"Authorization": f"Bearer {theirs}"},
    )
    assert empty.status_code == 200
    assert empty.json() == []


@pytest.mark.parametrize("reason", ["", "   "])
async def test_blank_reason_is_rejected(client: AsyncClient, reason: str, monkeypatch):
    _, _, check_id = await _argument_with_check(client, monkeypatch, f"blank_{len(reason)}")
    token, _ = await _signup(client, f"blankflagger_{len(reason)}")

    resp = await _flag(client, token, check_id, reason)
    assert resp.status_code == 422


async def test_admin_listing_requires_a_superuser(client: AsyncClient):
    token, _ = await _signup(client, "notadmin")

    resp = await client.get(
        "/api/v1/admin/check-flags/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_admin_listing_carries_the_reason_and_its_context(client: AsyncClient, monkeypatch):
    _, argument_id, check_id = await _argument_with_check(client, monkeypatch, "adminflag")
    token, actor_id = await _signup(client, "adminflagger")
    assert (await _flag(client, token, check_id, "Relevance misread the claim.")).status_code == 201
    await promote_to_superuser(actor_id)

    resp = await client.get(
        "/api/v1/admin/check-flags/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1
    row = next(r for r in body["items"] if r["check_id"] == check_id)
    assert row["reason"] == "Relevance misread the claim."
    assert row["argument_id"] == argument_id
    assert row["check_name"] == "validity"
    assert row["flagger_name"]
    assert row["paper_title"]
    assert row["argument_claim"] == PAYLOAD["claim"]


async def test_the_bulk_export_carries_real_counts(client: AsyncClient, monkeypatch):
    """The export serves the same response model, so it must count too."""
    _, argument_id, check_id = await _argument_with_check(client, monkeypatch, "exportflag")
    token, _ = await _signup(client, "exportflagger")
    assert (await _flag(client, token, check_id, "Counted here as well.")).status_code == 201

    resp = await client.get(
        "/api/v1/export/arguments?limit=10000",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert "Counted here as well." not in resp.text
    argument = next(a for a in resp.json() if a["id"] == argument_id)
    assert [c["flag_count"] for c in argument["checks"] if c["id"] == check_id] == [1]
