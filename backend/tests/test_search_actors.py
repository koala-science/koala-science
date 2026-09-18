"""An agent in search results carries what a reader needs to place it.

A paper result says who submitted it and when; an agent result says who owns
it, when it joined and how much it has argued, so the two read alike.
"""
import uuid

from tests.conftest import complete_signup


async def test_an_agent_result_names_its_owner_and_activity(client):
    prefix = uuid.uuid4().hex[:8]
    token, owner_id = await complete_signup(client, {
        "name": f"Owner {prefix}",
        "email": f"search_{prefix}@example.com",
        "password": "secure_password_123",
        "openreview_id": f"~Search_Owner_{prefix}1",
    })
    agent = await client.post(
        "/api/v1/auth/agents",
        json={"name": f"finder_{prefix}", "github_repo": f"https://github.com/e/{prefix}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert agent.status_code == 201, agent.text

    resp = await client.get("/api/v1/search/", params={"q": f"finder_{prefix}", "type": "actor"})
    assert resp.status_code == 200, resp.text
    [hit] = [r for r in resp.json() if r["name"] == f"finder_{prefix}"]

    assert hit["actor_type"] == "agent"
    assert hit["owner_id"] == owner_id
    assert hit["owner_name"] == f"Owner {prefix}"
    assert hit["argument_count"] == 0
    assert hit["created_at"]


async def test_a_human_result_has_no_owner(client):
    prefix = uuid.uuid4().hex[:8]
    await complete_signup(client, {
        "name": f"Seeker {prefix}",
        "email": f"seeker_{prefix}@example.com",
        "password": "secure_password_123",
        "openreview_id": f"~Seeker_{prefix}1",
    })

    resp = await client.get("/api/v1/search/", params={"q": f"Seeker {prefix}", "type": "actor"})
    assert resp.status_code == 200, resp.text
    [hit] = [r for r in resp.json() if r["name"] == f"Seeker {prefix}"]

    assert hit["actor_type"] == "human"
    assert hit["owner_id"] is None
    assert hit["owner_name"] is None


async def test_a_paper_result_counts_its_arguments(client):
    """Search counts a paper's arguments as the feed does; it used to send 0."""
    from tests.conftest import set_argument_state
    from tests.test_argument_visibility import _argument_on_paper

    submitted = await _argument_on_paper(client, "The ablation omits the baseline.")
    await set_argument_state(submitted.argument_id, "accepted")
    paper = (await client.get(f"/api/v1/papers/{submitted.paper_id}")).json()

    resp = await client.get("/api/v1/search/", params={"q": paper["title"], "type": "paper"})
    assert resp.status_code == 200, resp.text
    [hit] = [r for r in resp.json() if r["paper"]["id"] == submitted.paper_id]

    assert hit["paper"]["argument_count"] == 1
