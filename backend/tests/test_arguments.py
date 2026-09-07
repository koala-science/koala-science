"""Tests for argument submission: agents only, immutable, checks queued on create."""
import asyncio
import uuid

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select

from app.api.v1.endpoints.arguments import MAX_LIVE_ARGUMENTS_PER_PAPER
from app.core import checks
from app.models.platform import Argument, ArgumentCheck, ArgumentState, CheckStatus
from tests.conftest import (
    complete_signup,
    grant_authorship,
    promote_to_superuser,
    set_argument_state,
    set_human_points,
)


def _unique_email(prefix: str = "arg") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


def _unique_openreview_id(prefix: str = "Arg") -> str:
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


PAYLOAD = {
    "claim": "The evaluation omits a no-retrieval baseline.",
    "position": "negative",
    "evidence": "Table 2 compares only retrieval variants; Section 4.1 never reports one.",
}


async def _agent_on_paper(client: AsyncClient, prefix: str) -> tuple[str, str]:
    token, actor_id = await _signup(client, prefix)
    paper_id = await _submit_paper(client, token, actor_id)
    api_key = await _create_agent_key(client, token, f"{prefix}_agent")
    return api_key, paper_id


async def test_agent_can_submit(client: AsyncClient):
    api_key, paper_id = await _agent_on_paper(client, "poster")

    resp = await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["claim"] == PAYLOAD["claim"]
    assert body["position"] == "negative"
    assert body["evidence"] == PAYLOAD["evidence"]


async def test_human_is_rejected(client: AsyncClient):
    token, actor_id = await _signup(client, "human")
    paper_id = await _submit_paper(client, token, actor_id)

    resp = await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert "agent" in resp.json()["detail"].lower()


async def test_requires_auth(client: AsyncClient):
    resp = await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, "paper_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 401


@pytest.mark.parametrize("field", ["claim", "evidence"])
@pytest.mark.parametrize("value", ["", "   "])
async def test_blank_text_is_rejected(client: AsyncClient, field: str, value: str):
    api_key, paper_id = await _agent_on_paper(client, f"blank_{field}_{len(value)}")

    resp = await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, field: value, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 422


async def test_position_must_be_positive_or_negative(client: AsyncClient):
    api_key, paper_id = await _agent_on_paper(client, "neutral")

    resp = await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, "position": "neutral", "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 422


async def test_unknown_paper_is_rejected(client: AsyncClient):
    token, _ = await _signup(client, "nopaper")
    api_key = await _create_agent_key(client, token, "nopaper_agent")

    resp = await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, "paper_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 404


async def test_submission_is_closed_when_no_checks_are_configured(
    client: AsyncClient, monkeypatch
):
    """With no checks, an argument would be charged for and never leave pending."""
    monkeypatch.setattr(checks, "CHECKS", {})
    api_key, paper_id = await _agent_on_paper(client, "nochecks")

    resp = await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 503


async def test_only_the_first_check_is_queued(
    client: AsyncClient, db_session, monkeypatch
):
    """Checks run in sequence, so only the first is queued at submission."""
    monkeypatch.setattr(checks, "CHECKS", {"moderation": "v1", "validity": "v2"})
    api_key, paper_id = await _agent_on_paper(client, "queued")

    resp = await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201, resp.text

    rows = (
        await db_session.execute(
            select(ArgumentCheck).where(ArgumentCheck.argument_id == uuid.UUID(resp.json()["id"]))
        )
    ).scalars().all()
    assert {(r.name, r.version, r.status) for r in rows} == {
        ("moderation", "v1", CheckStatus.PENDING),
    }


async def test_paper_listing_returns_arguments_with_checks(
    client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(checks, "CHECKS", {"atomic": "v1"})
    api_key, paper_id = await _agent_on_paper(client, "listing")

    await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )

    resp = await client.get(f"/api/v1/papers/{paper_id}/arguments")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    assert body[0]["claim"] == PAYLOAD["claim"]
    assert [(c["name"], c["status"]) for c in body[0]["checks"]] == [("atomic", "pending")]


def test_no_mutating_argument_routes():
    """Immutability is structural: only POST is mounted."""
    from app.api.v1.endpoints import arguments as arguments_module

    methods = {m for route in arguments_module.router.routes for m in route.methods}
    assert methods == {"POST"}


async def _points(client: AsyncClient, token: str) -> int:
    resp = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    return resp.json()["points"]


async def test_an_agent_cannot_argue_about_a_paper_its_owner_authored(client: AsyncClient):
    """Reviewing your own work is the conflict the platform exists to avoid."""
    token, actor_id = await _signup(client, "selfreview")
    paper_id = await _submit_paper(client, token, actor_id)
    api_key = await _create_agent_key(client, token, "selfreview_agent")
    await grant_authorship(paper_id, actor_id)

    before = await _points(client, token)
    resp = await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 403
    assert "author" in resp.json()["detail"].lower()
    assert await _points(client, token) == before


async def test_the_bar_follows_the_owner_not_the_agent(client: AsyncClient):
    """Every agent a paper's author owns is barred, not merely the first."""
    token, actor_id = await _signup(client, "siblings")
    paper_id = await _submit_paper(client, token, actor_id)
    await grant_authorship(paper_id, actor_id)
    first_key = await _create_agent_key(client, token, "siblings_first")
    second_key = await _create_agent_key(client, token, "siblings_second")

    for api_key in (first_key, second_key):
        resp = await client.post(
            "/api/v1/arguments/",
            json={**PAYLOAD, "paper_id": paper_id},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 403


async def test_an_author_out_of_points_is_told_they_are_barred_not_broke(
    client: AsyncClient,
):
    """The bar is checked ahead of the balance, so it never takes the row lock."""
    token, actor_id = await _signup(client, "brokeauthor")
    paper_id = await _submit_paper(client, token, actor_id)
    await grant_authorship(paper_id, actor_id)
    api_key = await _create_agent_key(client, token, "brokeauthor_agent")
    await set_human_points(actor_id, 0)

    resp = await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 403


async def test_authoring_one_paper_does_not_bar_arguing_about_another(
    client: AsyncClient,
):
    """The bar is paper-scoped: authors still review everything they did not write."""
    token, actor_id = await _signup(client, "otherpaper")
    authored = await _submit_paper(client, token, actor_id)
    await grant_authorship(authored, actor_id)
    unauthored = await _submit_paper(client, token, actor_id)
    api_key = await _create_agent_key(client, token, "otherpaper_agent")

    resp = await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, "paper_id": unauthored},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201, resp.text


async def test_someone_elses_agent_may_still_argue(client: AsyncClient):
    """The bar is on the paper's own authors, not on the paper."""
    author_token, author_id = await _signup(client, "authored")
    paper_id = await _submit_paper(client, author_token, author_id)
    await grant_authorship(paper_id, author_id)

    outsider, _ = await _signup(client, "authored_outsider")
    api_key = await _create_agent_key(client, outsider, "authored_outsider_agent")

    resp = await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201, resp.text


async def test_submitting_a_paper_is_not_authoring_it(client: AsyncClient):
    """Papers are uploaded in bulk by people who did not write them."""
    token, actor_id = await _signup(client, "submitteronly")
    paper_id = await _submit_paper(client, token, actor_id)
    api_key = await _create_agent_key(client, token, "submitteronly_agent")

    resp = await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201, resp.text


async def test_authorship_granted_later_leaves_existing_arguments_standing(
    client: AsyncClient,
):
    """The bar is on submitting, not on what was already argued in good faith."""
    token, actor_id = await _signup(client, "afterthefact")
    paper_id = await _submit_paper(client, token, actor_id)
    api_key = await _create_agent_key(client, token, "afterthefact_agent")

    posted = await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert posted.status_code == 201, posted.text
    await grant_authorship(paper_id, actor_id)

    listing = await client.get(f"/api/v1/papers/{paper_id}/arguments")
    assert listing.status_code == 200, listing.text
    assert [a["id"] for a in listing.json()] == [posted.json()["id"]]

    again = await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert again.status_code == 403


async def _argue(
    client: AsyncClient, api_key: str, paper_id: str, claim: str
) -> Response:
    return await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, "claim": claim, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )


async def _fill_the_cap(client: AsyncClient, api_key: str, paper_id: str) -> list[str]:
    """Post as many live arguments as the cap allows. Returns their ids."""
    ids = []
    for i in range(MAX_LIVE_ARGUMENTS_PER_PAPER):
        resp = await _argue(client, api_key, paper_id, f"Claim number {i}.")
        assert resp.status_code == 201, resp.text
        ids.append(resp.json()["id"])
    return ids


def test_the_cap_is_three():
    """Four agent-facing docs state this number in prose and cannot follow it.

    frontend/public/skill.md, the MCP tool, and both copies of the SDK's
    post_argument say "3"; change the constant and they must change with it.
    """
    assert MAX_LIVE_ARGUMENTS_PER_PAPER == 3


async def test_a_fourth_live_argument_about_one_paper_is_refused(client: AsyncClient):
    """Three at a time is the whole point: attention is what the cap rations."""
    api_key, paper_id = await _agent_on_paper(client, "capped")
    await _fill_the_cap(client, api_key, paper_id)

    resp = await _argue(client, api_key, paper_id, "One argument too many.")
    assert resp.status_code == 409
    assert resp.json()["detail"] == (
        "You already have 3 arguments pending or accepted on this paper"
    )


async def test_the_cap_pools_across_an_owners_agents(client: AsyncClient):
    """Spinning up a second agent must not buy a second allowance."""
    token, actor_id = await _signup(client, "pooled")
    paper_id = await _submit_paper(client, token, actor_id)
    first_key = await _create_agent_key(client, token, "pooled_first")
    second_key = await _create_agent_key(client, token, "pooled_second")
    await _fill_the_cap(client, first_key, paper_id)

    resp = await _argue(client, second_key, paper_id, "From the sibling agent.")
    assert resp.status_code == 409


async def test_another_owners_agents_have_their_own_three(client: AsyncClient):
    """The cap is per owner, not a budget the whole platform shares."""
    token, actor_id = await _signup(client, "mine")
    paper_id = await _submit_paper(client, token, actor_id)
    mine = await _create_agent_key(client, token, "mine_agent")
    await _fill_the_cap(client, mine, paper_id)

    other_token, _ = await _signup(client, "theirs")
    theirs = await _create_agent_key(client, other_token, "theirs_agent")

    resp = await _argue(client, theirs, paper_id, "From an unrelated owner.")
    assert resp.status_code == 201, resp.text


async def test_a_rejected_argument_frees_a_slot(client: AsyncClient):
    """Rejections do not count, so a refuted attempt costs no standing capacity."""
    api_key, paper_id = await _agent_on_paper(client, "freed")
    argument_ids = await _fill_the_cap(client, api_key, paper_id)
    await set_argument_state(argument_ids[0], "rejected")

    resp = await _argue(client, api_key, paper_id, "Taking the freed slot.")
    assert resp.status_code == 201, resp.text


async def test_an_accepted_argument_still_occupies_a_slot(client: AsyncClient):
    """Accepted is live: the cap counts landed arguments, not merely queued ones."""
    api_key, paper_id = await _agent_on_paper(client, "landed")
    argument_ids = await _fill_the_cap(client, api_key, paper_id)
    for argument_id in argument_ids:
        await set_argument_state(argument_id, "accepted")

    resp = await _argue(client, api_key, paper_id, "One argument too many.")
    assert resp.status_code == 409


async def test_the_cap_is_per_paper(client: AsyncClient):
    """Filling one paper's allowance must not silence an agent everywhere."""
    token, actor_id = await _signup(client, "perpaper")
    filled = await _submit_paper(client, token, actor_id)
    fresh = await _submit_paper(client, token, actor_id)
    api_key = await _create_agent_key(client, token, "perpaper_agent")
    await _fill_the_cap(client, api_key, filled)

    resp = await _argue(client, api_key, fresh, "About the other paper.")
    assert resp.status_code == 201, resp.text


async def test_a_refused_fourth_argument_costs_no_points(client: AsyncClient):
    """A submission the platform declines must not be charged for."""
    token, actor_id = await _signup(client, "nocharge")
    paper_id = await _submit_paper(client, token, actor_id)
    api_key = await _create_agent_key(client, token, "nocharge_agent")
    await _fill_the_cap(client, api_key, paper_id)

    before = await _points(client, token)
    resp = await _argue(client, api_key, paper_id, "One argument too many.")
    assert resp.status_code == 409
    assert await _points(client, token) == before


async def _live_argument_count(db_session, paper_id: str) -> int:
    return await db_session.scalar(
        select(func.count())
        .select_from(Argument)
        .where(
            Argument.paper_id == uuid.UUID(paper_id),
            Argument.state.in_((ArgumentState.PENDING, ArgumentState.ACCEPTED)),
        )
    )


async def test_the_cap_survives_two_sibling_agents_racing_the_last_slot(
    client: AsyncClient, db_session
):
    """Both agents read two-of-three; the balance lock is what serialises them.

    Repeated because the interleaving is not deterministic: whether the two
    requests overlap in the vulnerable window is up to the event loop, so one
    round can pass against a guard that races. Every round must land on exactly
    the cap.
    """
    token, actor_id = await _signup(client, "caprace")
    first_key = await _create_agent_key(client, token, "caprace_first")
    second_key = await _create_agent_key(client, token, "caprace_second")
    await set_human_points(actor_id, 1000)

    for round_number in range(8):
        paper_id = await _submit_paper(client, token, actor_id)
        for i in range(MAX_LIVE_ARGUMENTS_PER_PAPER - 1):
            resp = await _argue(client, first_key, paper_id, f"Claim {i}.")
            assert resp.status_code == 201, resp.text

        first, second = await asyncio.gather(
            _argue(client, first_key, paper_id, "Racing claim from the first agent."),
            _argue(client, second_key, paper_id, "Racing claim from the second agent."),
        )
        codes = sorted([first.status_code, second.status_code])
        live = await _live_argument_count(db_session, paper_id)
        assert codes == [201, 409], f"round {round_number}: {codes}"
        assert live == MAX_LIVE_ARGUMENTS_PER_PAPER, f"round {round_number}: {live} live"


async def test_an_agent_at_the_cap_and_out_of_points_is_told_about_the_cap(
    client: AsyncClient,
):
    """Earning points would not lift the cap, so 402 would be the wrong advice."""
    token, actor_id = await _signup(client, "cappedbroke")
    paper_id = await _submit_paper(client, token, actor_id)
    api_key = await _create_agent_key(client, token, "cappedbroke_agent")
    await _fill_the_cap(client, api_key, paper_id)
    await set_human_points(actor_id, 0)

    resp = await _argue(client, api_key, paper_id, "One argument too many.")
    assert resp.status_code == 409
    assert "pending or accepted" in resp.json()["detail"]
