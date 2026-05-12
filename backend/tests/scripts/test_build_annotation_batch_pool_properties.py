"""Property-style tests for the greedy pool builder.

Direct tests of the pure ``_greedy_pool`` helper — no DB required.
"""
import random
import uuid

from scripts.build_annotation_batch import _greedy_pool


def _ids(n: int) -> list[uuid.UUID]:
    return [uuid.uuid4() for _ in range(n)]


def test_pool_size_in_bounds():
    """Pool size is in [K, N_agents * K] for any seed."""
    K = 5
    n_agents = 6
    all_papers = _ids(50)

    agent_papers: dict[uuid.UUID, list[uuid.UUID]] = {}
    rng = random.Random(0)
    agent_order: list[uuid.UUID] = []
    for _ in range(n_agents):
        aid = uuid.uuid4()
        agent_order.append(aid)
        agent_papers[aid] = rng.sample(all_papers, 20)

    pool, samples = _greedy_pool(agent_order, agent_papers, K, random.Random(1))

    assert K <= len(pool) <= n_agents * K
    for aid in agent_order:
        assert len(samples[aid]) == K


def test_every_agent_has_at_least_k_papers_in_pool():
    """The greedy invariant: after build, |papers(A) ∩ pool| >= K for
    every A."""
    K = 4
    n_agents = 8
    all_papers = _ids(30)

    agent_papers: dict[uuid.UUID, list[uuid.UUID]] = {}
    rng = random.Random(2)
    agent_order: list[uuid.UUID] = []
    for _ in range(n_agents):
        aid = uuid.uuid4()
        agent_order.append(aid)
        agent_papers[aid] = rng.sample(all_papers, 15)

    pool, samples = _greedy_pool(agent_order, agent_papers, K, random.Random(3))
    pool_set = set(pool)

    for aid in agent_order:
        have = len([p for p in agent_papers[aid] if p in pool_set])
        assert have >= K
        assert len(samples[aid]) == K
        for p in samples[aid]:
            assert p in pool_set


def test_pool_compression_when_papers_are_shared():
    """If two agents fully overlap, the pool should be exactly K."""
    K = 3
    shared = _ids(10)

    agent_a = uuid.uuid4()
    agent_b = uuid.uuid4()
    agent_papers = {agent_a: list(shared), agent_b: list(shared)}
    pool, samples = _greedy_pool(
        [agent_a, agent_b], agent_papers, K, random.Random(42)
    )

    assert len(pool) == K
    assert set(samples[agent_a]) <= set(pool)
    assert set(samples[agent_b]) <= set(pool)


def test_pool_no_compression_when_disjoint():
    """Two agents with disjoint papers => pool = 2K."""
    K = 3
    a_papers = _ids(10)
    b_papers = _ids(10)

    agent_a = uuid.uuid4()
    agent_b = uuid.uuid4()
    agent_papers = {agent_a: a_papers, agent_b: b_papers}
    pool, _ = _greedy_pool(
        [agent_a, agent_b], agent_papers, K, random.Random(7)
    )

    assert len(pool) == 2 * K


def test_pool_deterministic_for_same_seed():
    K = 3
    all_papers = _ids(20)
    rng_init = random.Random(99)
    n_agents = 5
    agent_papers: dict[uuid.UUID, list[uuid.UUID]] = {}
    agent_order: list[uuid.UUID] = []
    for _ in range(n_agents):
        aid = uuid.uuid4()
        agent_order.append(aid)
        agent_papers[aid] = rng_init.sample(all_papers, 10)

    pool_a, samples_a = _greedy_pool(
        agent_order, agent_papers, K, random.Random(123)
    )
    pool_b, samples_b = _greedy_pool(
        agent_order, agent_papers, K, random.Random(123)
    )
    assert pool_a == pool_b
    assert samples_a == samples_b
