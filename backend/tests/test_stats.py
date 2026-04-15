"""Tests for GET /api/v1/stats/metrics."""

from httpx import AsyncClient


async def test_metrics_endpoint_returns_200(client: AsyncClient):
    response = await client.get("/api/v1/stats/metrics")
    assert response.status_code == 200


async def test_metrics_response_has_required_keys(client: AsyncClient):
    response = await client.get("/api/v1/stats/metrics")
    data = response.json()
    assert "summary" in data
    assert "papers" in data
    assert "reviewers" in data
    assert "rankings" in data


async def test_metrics_summary_shape(client: AsyncClient):
    data = (await client.get("/api/v1/stats/metrics")).json()
    summary = data["summary"]
    for key in ("papers", "comments", "votes", "humans", "agents"):
        assert isinstance(summary[key], int)
    agreement = summary["agreement"]
    assert "n_rated" in agreement
    assert "label_counts" in agreement


async def test_metrics_rankings_shape(client: AsyncClient):
    data = (await client.get("/api/v1/stats/metrics")).json()
    rankings = data["rankings"]
    assert isinstance(rankings["algorithms"], list)
    assert isinstance(rankings["papers"], list)
    assert isinstance(rankings["total_papers"], int)


async def test_metrics_paper_entry_fields(client: AsyncClient):
    data = (await client.get("/api/v1/stats/metrics")).json()
    if data["papers"]:
        paper = data["papers"][0]
        required = [
            "rank", "id", "title", "domain", "engagement", "engagement_pct",
            "net_score", "upvotes", "downvotes", "n_reviews", "n_votes",
            "n_reviewers", "agreement", "agreement_label", "tentative", "url",
            "p_positive", "direction", "ci_low", "ci_high", "stance_source",
        ]
        for field in required:
            assert field in paper, f"Missing field: {field}"


async def test_metrics_reviewer_entry_fields(client: AsyncClient):
    data = (await client.get("/api/v1/stats/metrics")).json()
    if data["reviewers"]:
        reviewer = data["reviewers"][0]
        required = [
            "rank", "id", "name", "actor_type", "is_agent",
            "trust", "trust_pct", "activity", "domains", "avg_length", "url",
        ]
        for field in required:
            assert field in reviewer, f"Missing field: {field}"


async def test_metrics_agent_entry_fields(client: AsyncClient):
    data = (await client.get("/api/v1/stats/metrics")).json()
    if data["agents"]:
        agent = data["agents"][0]
        required = [
            "rank", "id", "name", "actor_type", "is_agent",
            "trust", "trust_pct", "activity", "domains", "avg_length",
            "trust_efficiency", "engagement_depth", "review_substance",
            "domain_breadth", "consensus_alignment",
            "quality_score", "quality_pct", "url",
        ]
        for field in required:
            assert field in agent, f"Missing field: {field}"
        assert 0.0 <= agent["quality_score"] <= 1.0
        for sig in ["trust_efficiency", "engagement_depth", "review_substance",
                     "domain_breadth", "consensus_alignment"]:
            assert 0.0 <= agent[sig] <= 1.0, f"{sig} out of range: {agent[sig]}"


async def test_metrics_agents_quality_score_range(client: AsyncClient):
    """All quality scores must be in [0, 1]."""
    data = (await client.get("/api/v1/stats/metrics")).json()
    for agent in data["agents"]:
        assert 0.0 <= agent["quality_score"] <= 1.0, f"{agent['name']}: {agent['quality_score']}"
        assert 0.0 <= agent["quality_pct"] <= 1.0, f"{agent['name']}: {agent['quality_pct']}"


async def test_metrics_agents_sorted_by_quality(client: AsyncClient):
    """Agents must be sorted by quality_score descending."""
    data = (await client.get("/api/v1/stats/metrics")).json()
    agents = data["agents"]
    if len(agents) > 1:
        scores = [a["quality_score"] for a in agents]
        assert scores == sorted(scores, reverse=True), "Agents not sorted by quality_score"


async def test_metrics_agents_includes_all_reviewers(client: AsyncClient):
    """Agents list should include ALL reviewers, not just top N."""
    data = (await client.get("/api/v1/stats/metrics")).json()
    assert len(data["agents"]) == len(data["reviewers"])


async def test_metrics_backwards_compat_reviewers_key(client: AsyncClient):
    """Response must still include 'reviewers' key for backwards compat."""
    data = (await client.get("/api/v1/stats/metrics")).json()
    assert "reviewers" in data
    assert "agents" in data
    assert data["agents"] == data["reviewers"]
