"""Server-side filters on the paper feed, for agents choosing what to argue about.

Agents used to download the whole feed and filter it themselves. `after`,
`max_arguments`, `sort=least_argued` and `eligible` move that onto the server.

`eligible=true` is the one that can quietly lie: a feed that hides papers an
agent could argue on, or offers ones it will be refused on, wastes the agent's
budget and attention either way. So besides asserting what it returns, the
parity test posts to the real argument endpoint for every paper in the fixture
and requires the feed and the submission guard to agree.
"""
import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.argument_eligibility import MAX_LIVE_ARGUMENTS_PER_PAPER
from app.core.config import settings
from tests.conftest import complete_signup, grant_authorship, promote_to_superuser

FEED = "/api/v1/papers/"


async def _exec(sql: str, params: dict | None = None) -> None:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(sql), params or {})
    finally:
        await engine.dispose()


def _domain() -> str:
    return f"d/FilterTest{uuid.uuid4().hex[:8]}"


async def _signup(client: AsyncClient, prefix: str) -> tuple[str, str]:
    return await complete_signup(client, {
        "name": "Filter User",
        "email": f"{prefix}_{uuid.uuid4().hex[:8]}@example.com",
        "password": "secure_password_123",
        "openreview_id": f"~{prefix}_{uuid.uuid4().hex[:8]}1",
    })


async def _agent(client: AsyncClient, token: str, prefix: str) -> tuple[str, str]:
    """Returns (api_key, agent_id)."""
    name = f"{prefix}_{uuid.uuid4().hex[:6]}"
    resp = await client.post(
        "/api/v1/auth/agents",
        json={"name": name, "github_repo": f"https://github.com/example/{name}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["api_key"], body["id"]


async def _paper(
    submitter_id: str, domain: str, *, created_at: datetime | None = None
) -> str:
    """A released paper. `created_at` is naive UTC, as the column stores it."""
    pid = str(uuid.uuid4())
    created = created_at or datetime.now(UTC).replace(tzinfo=None)
    await _exec(
        "INSERT INTO paper (id, title, abstract, domains, submitter_id, "
        "released_at, created_at, updated_at) "
        "VALUES (:id, :t, 'a', ARRAY[:domain], :sub, now(), :created, now())",
        {
            "id": pid,
            "t": f"filter-paper-{pid[:8]}",
            "domain": domain,
            "sub": submitter_id,
            "created": created,
        },
    )
    return pid


async def _arguments(
    paper_id: str, author_id: str, count: int, state: str = "pending"
) -> list[str]:
    ids = []
    for _ in range(count):
        aid = str(uuid.uuid4())
        await _exec(
            "INSERT INTO argument (id, paper_id, author_id, claim, position, evidence, "
            "state, created_at, updated_at) "
            "VALUES (:id, :p, :a, :c, 'negative', 'evidence', :s, now(), now())",
            {"id": aid, "p": paper_id, "a": author_id, "c": f"claim {aid}", "s": state},
        )
        ids.append(aid)
    return ids


async def _fail_moderation(argument_id: str) -> None:
    await _exec(
        "INSERT INTO argument_check (id, argument_id, name, version, status, "
        "detail, created_at, updated_at) "
        "VALUES (:id, :a, 'moderation', 'v1', 'failed', 'spam', now(), now())",
        {"id": str(uuid.uuid4()), "a": argument_id},
    )


async def _feed_ids(
    client: AsyncClient, params: dict, api_key: str | None = None
) -> list[str]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    resp = await client.get(FEED, params={"limit": 100, **params}, headers=headers)
    assert resp.status_code == 200, resp.text
    return [p["id"] for p in resp.json()]


# --- after -----------------------------------------------------------------


async def test_after_keeps_only_papers_created_after_the_cutoff(client: AsyncClient):
    domain = _domain()
    _, human = await _signup(client, "after")
    now = datetime.now(UTC).replace(tzinfo=None)
    old = await _paper(human, domain, created_at=now - timedelta(days=3))
    new = await _paper(human, domain, created_at=now - timedelta(days=1))
    cutoff = now - timedelta(days=2)

    assert await _feed_ids(client, {"domain": domain, "after": cutoff.isoformat()}) == [new]
    assert old in await _feed_ids(client, {"domain": domain})


async def test_after_accepts_epoch_seconds_and_dates_alike(client: AsyncClient):
    domain = _domain()
    _, human = await _signup(client, "afterfmt")
    now = datetime.now(UTC).replace(tzinfo=None)
    await _paper(human, domain, created_at=now - timedelta(days=10))
    new = await _paper(human, domain, created_at=now - timedelta(hours=1))
    cutoff = now - timedelta(days=2)

    as_iso = await _feed_ids(client, {"domain": domain, "after": cutoff.isoformat()})
    as_epoch = await _feed_ids(
        client, {"domain": domain, "after": int(cutoff.replace(tzinfo=UTC).timestamp())}
    )
    as_date = await _feed_ids(client, {"domain": domain, "after": cutoff.date().isoformat()})
    assert as_iso == as_epoch == as_date == [new]


async def test_after_is_strict(client: AsyncClient):
    domain = _domain()
    _, human = await _signup(client, "afterstrict")
    at = datetime(2026, 1, 1, 12, 0, 0)
    await _paper(human, domain, created_at=at)

    assert await _feed_ids(client, {"domain": domain, "after": at.isoformat()}) == []


# --- max_arguments ---------------------------------------------------------


async def test_max_arguments_skips_papers_that_already_have_many(client: AsyncClient):
    domain = _domain()
    token, human = await _signup(client, "maxargs")
    _, agent = await _agent(client, token, "maxargs")
    none = await _paper(human, domain)
    two = await _paper(human, domain)
    three = await _paper(human, domain)
    await _arguments(two, agent, 2)
    await _arguments(three, agent, 3)

    kept = await _feed_ids(client, {"domain": domain, "max_arguments": 2})
    assert set(kept) == {none, two}
    assert three in await _feed_ids(client, {"domain": domain})


async def test_max_arguments_counts_what_the_feed_reports(client: AsyncClient):
    """A withheld argument is not in `argument_count`, so it must not count here."""
    domain = _domain()
    token, human = await _signup(client, "maxvis")
    _, agent = await _agent(client, token, "maxvis")
    paper = await _paper(human, domain)
    visible, withheld = await _arguments(paper, agent, 2)
    await _fail_moderation(withheld)

    resp = await client.get(FEED, params={"domain": domain, "max_arguments": 1})
    assert resp.status_code == 200, resp.text
    assert [(p["id"], p["argument_count"]) for p in resp.json()] == [(paper, 1)]


async def test_max_arguments_zero_keeps_unargued_papers(client: AsyncClient):
    domain = _domain()
    token, human = await _signup(client, "maxzero")
    _, agent = await _agent(client, token, "maxzero")
    untouched = await _paper(human, domain)
    argued = await _paper(human, domain)
    await _arguments(argued, agent, 1)

    assert await _feed_ids(client, {"domain": domain, "max_arguments": 0}) == [untouched]


async def test_negative_max_arguments_is_rejected(client: AsyncClient):
    resp = await client.get(FEED, params={"max_arguments": -1})
    assert resp.status_code == 422


# --- sort=least_argued -----------------------------------------------------


async def test_least_argued_orders_by_count_then_newest(client: AsyncClient):
    domain = _domain()
    token, human = await _signup(client, "least")
    _, agent = await _agent(client, token, "least")
    now = datetime.now(UTC).replace(tzinfo=None)
    busy = await _paper(human, domain, created_at=now - timedelta(days=5))
    quiet_old = await _paper(human, domain, created_at=now - timedelta(days=4))
    quiet_new = await _paper(human, domain, created_at=now - timedelta(days=1))
    one = await _paper(human, domain, created_at=now - timedelta(days=3))
    await _arguments(busy, agent, 3)
    await _arguments(one, agent, 1)
    withheld = await _arguments(quiet_old, agent, 1)
    await _fail_moderation(withheld[0])

    ordered = await _feed_ids(client, {"domain": domain, "sort": "least_argued"})
    assert ordered == [quiet_new, quiet_old, one, busy]


async def test_least_argued_pages_visit_each_paper_once(client: AsyncClient):
    domain = _domain()
    _, human = await _signup(client, "leastpage")
    at = datetime(2026, 3, 1, 9, 0, 0)
    papers = {await _paper(human, domain, created_at=at) for _ in range(4)}

    seen = []
    for skip in range(5):
        seen += await _feed_ids(
            client, {"domain": domain, "sort": "least_argued", "skip": skip, "limit": 1}
        )
    assert sorted(seen) == sorted(papers)


async def test_unknown_sort_is_rejected(client: AsyncClient):
    resp = await client.get(FEED, params={"sort": "most_argued"})
    assert resp.status_code == 422


# --- eligible --------------------------------------------------------------


async def test_eligible_needs_credentials(client: AsyncClient):
    resp = await client.get(FEED, params={"eligible": "true"})
    assert resp.status_code == 401


async def test_eligible_rejects_an_invalid_key(client: AsyncClient):
    resp = await client.get(
        FEED, params={"eligible": "true"}, headers={"Authorization": "Bearer cs_nonsense"}
    )
    assert resp.status_code == 401


async def test_eligible_is_for_agents(client: AsyncClient):
    token, _ = await _signup(client, "eligiblehuman")
    resp = await client.get(
        FEED, params={"eligible": "true"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403


async def test_eligible_works_for_an_agent_logged_in_with_a_jwt(client: AsyncClient):
    """`/auth/agents/login` gives agents a JWT, which resolves to a base-columns Actor."""
    domain = _domain()
    token, owner = await _signup(client, "eligjwt")
    key, _ = await _agent(client, token, "eligjwt")
    authored = await _paper(owner, domain)
    await grant_authorship(authored, owner)
    clean = await _paper(owner, domain)

    login = await client.post("/api/v1/auth/agents/login", json={"api_key": key})
    assert login.status_code == 200, login.text
    jwt = login.json()["access_token"]

    assert await _feed_ids(client, {"domain": domain, "eligible": "true"}, jwt) == [clean]


async def test_eligible_false_needs_no_credentials(client: AsyncClient):
    resp = await client.get(FEED, params={"eligible": "false"})
    assert resp.status_code == 200, resp.text


async def test_eligible_paginates_after_filtering(client: AsyncClient):
    """`limit` counts eligible papers, not papers that survive a filter applied later."""
    domain = _domain()
    token, owner = await _signup(client, "eligpage")
    key, _ = await _agent(client, token, "eligpage")
    now = datetime.now(UTC).replace(tzinfo=None)
    authored = await _paper(owner, domain, created_at=now)
    await grant_authorship(authored, owner)
    older = await _paper(owner, domain, created_at=now - timedelta(days=1))

    assert await _feed_ids(client, {"domain": domain, "eligible": "true", "limit": 1}, key) == [older]


async def _parity_fixture(client: AsyncClient):
    """Papers covering every reason an agent may or may not argue on one.

    Returns (domain, owner_token, owner_id, first_agent_key, expected_eligible).
    """
    domain = _domain()
    token, owner = await _signup(client, "parity")
    first_key, first = await _agent(client, token, "parity_first")
    _, sibling = await _agent(client, token, "parity_sibling")
    other_token, _ = await _signup(client, "parityother")
    _, stranger = await _agent(client, other_token, "parity_stranger")

    authored = await _paper(owner, domain)
    await grant_authorship(authored, owner)

    full_by_sibling = await _paper(owner, domain)
    await _arguments(full_by_sibling, sibling, MAX_LIVE_ARGUMENTS_PER_PAPER)

    full_with_accepted = await _paper(owner, domain)
    await _arguments(full_with_accepted, first, MAX_LIVE_ARGUMENTS_PER_PAPER - 1, "accepted")
    await _arguments(full_with_accepted, first, 1, "pending")

    one_slot_left = await _paper(owner, domain)
    await _arguments(one_slot_left, first, MAX_LIVE_ARGUMENTS_PER_PAPER - 1)

    rejected_only = await _paper(owner, domain)
    await _arguments(rejected_only, first, MAX_LIVE_ARGUMENTS_PER_PAPER, "rejected")

    full_by_stranger = await _paper(owner, domain)
    await _arguments(full_by_stranger, stranger, MAX_LIVE_ARGUMENTS_PER_PAPER)

    submitted_not_authored = await _paper(owner, domain)

    expected = {one_slot_left, rejected_only, full_by_stranger, submitted_not_authored}
    return domain, token, owner, first_key, expected


async def _post_argument(client: AsyncClient, api_key: str, paper_id: str) -> int:
    resp = await client.post(
        "/api/v1/arguments/",
        json={
            "paper_id": paper_id,
            "claim": f"Parity claim {uuid.uuid4().hex[:8]}.",
            "position": "negative",
            "evidence": "Section 3 does not report variance across seeds.",
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code in (201, 403, 409), resp.text
    return resp.status_code


async def test_eligible_omits_authored_and_full_papers(client: AsyncClient):
    domain, _, _, key, expected = await _parity_fixture(client)

    eligible = await _feed_ids(client, {"domain": domain, "eligible": "true"}, key)
    assert set(eligible) == expected
    assert len(eligible) == len(expected)


async def test_eligible_agrees_with_the_argument_endpoint(client: AsyncClient):
    """Every paper the feed offers is accepted; every paper it hides is refused."""
    domain, _, _, key, _ = await _parity_fixture(client)
    everything = await _feed_ids(client, {"domain": domain})
    eligible = set(await _feed_ids(client, {"domain": domain, "eligible": "true"}, key))

    outcomes = {pid: await _post_argument(client, key, pid) for pid in everything}
    disagreements = {
        pid: status
        for pid, status in outcomes.items()
        if (status == 201) != (pid in eligible)
    }
    assert not disagreements, (
        f"feed and POST /arguments disagree: {disagreements} "
        f"(eligible={sorted(eligible)})"
    )
    assert any(s == 201 for s in outcomes.values())
    assert any(s != 201 for s in outcomes.values())


async def test_a_superusers_agent_is_offered_everything(client: AsyncClient):
    domain, _, owner, key, _ = await _parity_fixture(client)
    await promote_to_superuser(owner)

    everything = await _feed_ids(client, {"domain": domain})
    assert set(await _feed_ids(client, {"domain": domain, "eligible": "true"}, key)) == set(everything)


async def test_filters_compose(client: AsyncClient):
    domain = _domain()
    token, owner = await _signup(client, "compose")
    key, agent = await _agent(client, token, "compose")
    other_token, _ = await _signup(client, "composeother")
    _, stranger = await _agent(client, other_token, "composeother")
    now = datetime.now(UTC).replace(tzinfo=None)

    too_old = await _paper(owner, domain, created_at=now - timedelta(days=10))
    too_busy = await _paper(owner, domain, created_at=now - timedelta(hours=2))
    await _arguments(too_busy, stranger, 3)
    authored = await _paper(owner, domain, created_at=now - timedelta(hours=3))
    await grant_authorship(authored, owner)
    keep_busier = await _paper(owner, domain, created_at=now - timedelta(hours=4))
    await _arguments(keep_busier, stranger, 1)
    keep_quiet = await _paper(owner, domain, created_at=now - timedelta(hours=5))
    await _paper(owner, _domain(), created_at=now)

    params = {
        "domain": domain,
        "after": (now - timedelta(days=1)).isoformat(),
        "max_arguments": 2,
        "eligible": "true",
        "sort": "least_argued",
    }
    assert await _feed_ids(client, params, key) == [keep_quiet, keep_busier]
    assert too_old not in await _feed_ids(client, params, key)
