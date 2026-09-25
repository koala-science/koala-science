"""Flagging an argument's strength label as wrong.

The same rules as flagging a check result: humans only, one flag per person per
label, withdrawable, counts public and reasons not. The target is the argument,
because arguments accepted before verification existed carry a label but no
verification row to hang a flag on.
"""
import uuid

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from tests.conftest import promote_to_superuser
from tests.test_check_flags import _argument_with_check, _create_agent_key, _signup


async def _label(argument_id: str, strength: str | None) -> None:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE argument SET state = 'accepted', strength = :s WHERE id = :id"
            ),
            {"s": strength, "id": argument_id},
        )
    await engine.dispose()


async def _labelled_argument(
    client: AsyncClient, monkeypatch, prefix: str, strength: str | None = "critical"
) -> tuple[str, str]:
    """Returns (paper_id, argument_id) for an accepted argument with that label."""
    paper_id, argument_id, _ = await _argument_with_check(client, monkeypatch, prefix, "passed")
    await _label(argument_id, strength)
    return paper_id, argument_id


async def _flag_strength(
    client: AsyncClient, token: str, argument_id: str, reason: str = "It is only a detail."
):
    return await client.post(
        "/api/v1/check-flags/",
        json={"argument_id": argument_id, "reason": reason},
        headers={"Authorization": f"Bearer {token}"},
    )


async def _listed(client: AsyncClient, paper_id: str, argument_id: str) -> dict:
    resp = await client.get(f"/api/v1/papers/{paper_id}/arguments")
    assert resp.status_code == 200, resp.text
    return next(a for a in resp.json() if a["id"] == argument_id)


async def test_a_human_can_flag_a_strength_label(client: AsyncClient, monkeypatch):
    _, argument_id = await _labelled_argument(client, monkeypatch, "sflag")
    token, _ = await _signup(client, "sflagger")

    resp = await _flag_strength(client, token, argument_id)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["argument_id"] == argument_id
    assert body["check_id"] is None
    assert body["strength"] == "critical"
    assert body["reason"] == "It is only a detail."


async def test_the_count_is_public_and_the_reason_is_not(client: AsyncClient, monkeypatch):
    paper_id, argument_id = await _labelled_argument(client, monkeypatch, "scount")
    first, _ = await _signup(client, "scount_a")
    second, _ = await _signup(client, "scount_b")
    secret = "This reason must never reach the paper page."

    assert (await _flag_strength(client, first, argument_id, secret)).status_code == 201
    assert (await _flag_strength(client, second, argument_id)).status_code == 201

    listed = await _listed(client, paper_id, argument_id)
    assert listed["strength_flag_count"] == 2
    assert all(c["flag_count"] == 0 for c in listed["checks"])
    listing = await client.get(f"/api/v1/papers/{paper_id}/arguments")
    assert secret not in listing.text


async def test_an_unflagged_label_counts_zero(client: AsyncClient, monkeypatch):
    paper_id, argument_id = await _labelled_argument(client, monkeypatch, "szero")

    assert (await _listed(client, paper_id, argument_id))["strength_flag_count"] == 0


async def test_a_second_strength_flag_by_the_same_human_conflicts(client: AsyncClient, monkeypatch):
    _, argument_id = await _labelled_argument(client, monkeypatch, "sdup")
    token, _ = await _signup(client, "sdupflagger")

    assert (await _flag_strength(client, token, argument_id)).status_code == 201
    assert (await _flag_strength(client, token, argument_id, "Still wrong.")).status_code == 409


async def test_flagging_the_label_and_a_check_are_independent(client: AsyncClient, monkeypatch):
    _, argument_id, check_id = await _argument_with_check(client, monkeypatch, "sboth", "passed")
    await _label(argument_id, "medium")
    token, _ = await _signup(client, "sbothflagger")

    assert (await _flag_strength(client, token, argument_id)).status_code == 201
    resp = await client.post(
        "/api/v1/check-flags/",
        json={"check_id": check_id, "reason": "The check was wrong too."},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text


async def test_agents_cannot_flag_a_label(client: AsyncClient, monkeypatch):
    _, argument_id = await _labelled_argument(client, monkeypatch, "sagent")
    token, _ = await _signup(client, "sagent_owner")
    api_key = await _create_agent_key(client, token, "sagent_flagger")

    resp = await _flag_strength(client, api_key, argument_id)
    assert resp.status_code == 403


async def test_an_argument_without_a_label_cannot_have_it_flagged(client: AsyncClient, monkeypatch):
    _, argument_id = await _labelled_argument(client, monkeypatch, "snone", strength=None)
    token, _ = await _signup(client, "snoneflagger")

    resp = await _flag_strength(client, token, argument_id)
    assert resp.status_code == 400, resp.text


async def test_an_unknown_argument_is_not_found(client: AsyncClient):
    token, _ = await _signup(client, "sunknown")

    resp = await _flag_strength(client, token, str(uuid.uuid4()))
    assert resp.status_code == 404


async def test_a_withheld_arguments_label_cannot_be_flagged(client: AsyncClient, monkeypatch):
    _, argument_id, _ = await _argument_with_check(
        client, monkeypatch, "swithheld", "failed", check_name="moderation"
    )
    await _label(argument_id, "weak")
    token, _ = await _signup(client, "swithheldflagger")

    resp = await _flag_strength(client, token, argument_id)
    assert resp.status_code == 404, resp.text


async def test_a_flag_names_exactly_one_target(client: AsyncClient, monkeypatch):
    _, argument_id, check_id = await _argument_with_check(client, monkeypatch, "starget", "passed")
    await _label(argument_id, "weak")
    token, _ = await _signup(client, "stargetflagger")

    for body in (
        {"reason": "No target."},
        {"check_id": check_id, "argument_id": argument_id, "reason": "Two targets."},
    ):
        resp = await client.post(
            "/api/v1/check-flags/", json=body, headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 422, resp.text


async def test_withdrawing_a_strength_flag_removes_only_your_own(client: AsyncClient, monkeypatch):
    paper_id, argument_id = await _labelled_argument(client, monkeypatch, "swithdraw")
    mine, _ = await _signup(client, "swithdraw_a")
    theirs, _ = await _signup(client, "swithdraw_b")
    assert (await _flag_strength(client, mine, argument_id)).status_code == 201
    assert (await _flag_strength(client, theirs, argument_id)).status_code == 201

    resp = await client.delete(
        f"/api/v1/check-flags/strength/{argument_id}",
        headers={"Authorization": f"Bearer {mine}"},
    )
    assert resp.status_code == 204, resp.text
    assert (await _listed(client, paper_id, argument_id))["strength_flag_count"] == 1

    again = await client.delete(
        f"/api/v1/check-flags/strength/{argument_id}",
        headers={"Authorization": f"Bearer {mine}"},
    )
    assert again.status_code == 404


async def test_mine_includes_my_strength_flags(client: AsyncClient, monkeypatch):
    paper_id, argument_id = await _labelled_argument(client, monkeypatch, "smine")
    token, _ = await _signup(client, "smineflagger")
    assert (await _flag_strength(client, token, argument_id, "Mine.")).status_code == 201

    resp = await client.get(
        f"/api/v1/check-flags/mine?paper_id={paper_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert [(f["argument_id"], f["check_id"], f["strength"], f["reason"]) for f in resp.json()] == [
        (argument_id, None, "critical", "Mine.")
    ]


async def test_the_admin_list_carries_strength_flags(client: AsyncClient, monkeypatch):
    _, argument_id = await _labelled_argument(client, monkeypatch, "sadmin")
    token, actor_id = await _signup(client, "sadminflagger")
    assert (await _flag_strength(client, token, argument_id, "Overrated.")).status_code == 201
    await promote_to_superuser(actor_id)

    resp = await client.get(
        "/api/v1/admin/check-flags/?limit=200",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    row = next(r for r in resp.json()["items"] if r["argument_id"] == argument_id)
    assert row["reason"] == "Overrated."
    assert row["strength"] == "critical"
    assert row["check_id"] is None
    assert row["check_name"] is None
    assert row["paper_title"]
