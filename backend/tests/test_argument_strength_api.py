"""An argument's strength reaches the paper page with it."""
from httpx import AsyncClient

from tests.test_argument_visibility import _argument_on_paper, _write


async def _listed(client: AsyncClient, paper_id: str, argument_id: str) -> dict:
    resp = await client.get(f"/api/v1/papers/{paper_id}/arguments")
    assert resp.status_code == 200, resp.text
    return next(a for a in resp.json() if a["id"] == argument_id)


async def test_an_accepted_arguments_strength_and_reason_are_listed(client: AsyncClient):
    ctx = await _argument_on_paper(client, "The baseline is missing.")
    await _write(
        "UPDATE argument SET state = 'accepted', strength = 'critical', "
        "strength_reason = 'It breaks the main claim.' WHERE id = :a",
        {"a": ctx.argument_id},
    )

    listed = await _listed(client, ctx.paper_id, ctx.argument_id)

    assert listed["strength"] == "critical"
    assert listed["strength_reason"] == "It breaks the main claim."


async def test_an_unlabelled_argument_lists_no_strength(client: AsyncClient):
    ctx = await _argument_on_paper(client, "The baseline is missing.")

    listed = await _listed(client, ctx.paper_id, ctx.argument_id)

    assert listed["strength"] is None
    assert listed["strength_reason"] is None
