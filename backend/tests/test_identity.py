from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.identity import Actor, ActorType, HumanAccount, Agent


async def test_human_account_basic_fields(db_session: AsyncSession):
    user = HumanAccount(
        name="Test Rep",
        email="test_rep_async@example.com",
        hashed_password="hashed_password",
        oauth_provider="github",
        oauth_id="rep_test_async_1",
        openreview_id="~Test_Rep1",
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)

    assert user.actor_type == ActorType.HUMAN
    assert user.openreview_id == "~Test_Rep1"


async def test_agent_relationship(db_session: AsyncSession):
    user = HumanAccount(
        name="Owner Rel",
        email="owner_rel_async@example.com",
        hashed_password="hashed_password",
        oauth_provider="github",
        oauth_id="owner_rel_async_1",
        openreview_id="~Owner_Rel1",
    )
    db_session.add(user)
    await db_session.flush()

    agent1 = Agent(name="Agent 1", owner_id=user.id, api_key_hash="hash1_actor", api_key_lookup="lookup1_actor", github_repo="https://github.com/test/agent1")
    agent2 = Agent(name="Agent 2", owner_id=user.id, api_key_hash="hash2_actor", api_key_lookup="lookup2_actor", github_repo="https://github.com/test/agent2")
    db_session.add_all([agent1, agent2])
    await db_session.flush()

    result = await db_session.execute(
        select(Agent).where(Agent.owner_id == user.id)
    )
    agents = result.scalars().all()
    assert len(agents) == 2
    assert agents[0].actor_type == ActorType.AGENT


async def test_actor_polymorphic_query(db_session: AsyncSession):
    """Querying Actor table returns all actor types."""
    human = HumanAccount(
        name="Poly Human",
        email="poly_human@example.com",
        oauth_provider="github",
        oauth_id="poly_1",
        openreview_id="~Poly_Human1",
    )
    db_session.add(human)
    await db_session.flush()

    agent = Agent(
        name="Poly Agent",
        owner_id=human.id,
        api_key_hash="poly_hash",
        api_key_lookup="poly_lookup",
        github_repo="https://github.com/test/poly",
    )
    db_session.add(agent)
    await db_session.flush()

    result = await db_session.execute(select(Actor))
    actors = result.scalars().all()
    types = {a.actor_type for a in actors}
    assert ActorType.HUMAN in types
    assert ActorType.AGENT in types
