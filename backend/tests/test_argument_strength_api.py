"""An argument's strength reaches the paper page with it; the verifier's reason
for it does not.

The label is shown the way a check result is: publicly, as a level. The
reason is the verifier's working, kept in the database and served nowhere.
"""
from httpx import AsyncClient

from tests.test_argument_visibility import _argument_on_paper, _write

REASON = "The verifier's private reason for this label."


async def _listed(client: AsyncClient, paper_id: str, argument_id: str) -> dict:
    resp = await client.get(f"/api/v1/papers/{paper_id}/arguments")
    assert resp.status_code == 200, resp.text
    return next(a for a in resp.json() if a["id"] == argument_id)


async def _labelled(client: AsyncClient):
    ctx = await _argument_on_paper(client, "The baseline is missing.")
    await _write(
        "UPDATE argument SET state = 'accepted', strength = 'critical', "
        "strength_reason = :r WHERE id = :a",
        {"a": ctx.argument_id, "r": REASON},
    )
    return ctx


async def test_an_accepted_arguments_strength_is_listed(client: AsyncClient):
    ctx = await _labelled(client)

    assert (await _listed(client, ctx.paper_id, ctx.argument_id))["strength"] == "critical"


async def test_the_reason_for_a_label_is_never_served(client: AsyncClient):
    ctx = await _labelled(client)

    listing = await client.get(f"/api/v1/papers/{ctx.paper_id}/arguments")
    export = await client.get(
        "/api/v1/export/arguments?limit=10000",
        headers={"Authorization": f"Bearer {ctx.token}"},
    )
    own = await client.get(
        f"/api/v1/users/{ctx.author_id}/arguments",
        headers={"Authorization": f"Bearer {ctx.api_key}"},
    )

    for resp in (listing, export, own):
        assert resp.status_code == 200, resp.text
        assert ctx.argument_id in resp.text
        assert REASON not in resp.text
        assert "strength_reason" not in resp.text


async def test_an_unlabelled_argument_lists_no_strength(client: AsyncClient):
    ctx = await _argument_on_paper(client, "The baseline is missing.")

    assert (await _listed(client, ctx.paper_id, ctx.argument_id))["strength"] is None
