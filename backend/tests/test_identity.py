from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.identity import Actor, ActorType, HumanAccount, DelegatedAgent, SovereignAgent


async def test_human_account_reputation(db_session: AsyncSession):
    user = HumanAccount(
        name="Test Rep",
        email="test_rep_async@example.com",
        hashed_password="hashed_password",
        reputation_score=100,
        oauth_provider="github",
        oauth_id="rep_test_async_1",
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)

    assert user.reputation_score == 100
    assert user.actor_type == ActorType.HUMAN


async def test_delegated_agent_relationship(db_session: AsyncSession):
    user = HumanAccount(
        name="Owner Rel",
        email="owner_rel_async@example.com",
        hashed_password="hashed_password",
        oauth_provider="github",
        oauth_id="owner_rel_async_1",
    )
    db_session.add(user)
    await db_session.flush()

    agent1 = DelegatedAgent(name="Agent 1", owner_id=user.id, api_key_hash="hash1_actor", api_key_lookup="lookup1_actor")
    agent2 = DelegatedAgent(name="Agent 2", owner_id=user.id, api_key_hash="hash2_actor", api_key_lookup="lookup2_actor")
    db_session.add_all([agent1, agent2])
    await db_session.flush()

    result = await db_session.execute(
        select(DelegatedAgent).where(DelegatedAgent.owner_id == user.id)
    )
    agents = result.scalars().all()
    assert len(agents) == 2
    assert agents[0].actor_type == ActorType.DELEGATED_AGENT


async def test_sovereign_agent_fields(db_session: AsyncSession):
    agent = SovereignAgent(
        name="Agent S",
        api_key_hash="hash_api_actor",
        public_key_hash="hash_pub_actor",
        public_key="public_key_text",
    )
    db_session.add(agent)
    await db_session.flush()
    await db_session.refresh(agent)

    assert agent.public_key_hash == "hash_pub_actor"
    assert agent.actor_type == ActorType.SOVEREIGN_AGENT


async def test_actor_polymorphic_query(db_session: AsyncSession):
    """Querying Actor table returns all actor types."""
    human = HumanAccount(
        name="Poly Human",
        email="poly_human@example.com",
        oauth_provider="github",
        oauth_id="poly_1",
    )
    agent = SovereignAgent(
        name="Poly Agent",
        public_key_hash="poly_pub_hash",
    )
    db_session.add_all([human, agent])
    await db_session.flush()

    result = await db_session.execute(select(Actor))
    actors = result.scalars().all()
    types = {a.actor_type for a in actors}
    assert ActorType.HUMAN in types
    assert ActorType.SOVEREIGN_AGENT in types
