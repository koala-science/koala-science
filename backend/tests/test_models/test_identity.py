import uuid
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.models.identity import Actor, ActorType, HumanAccount, Agent, OpenReviewId


async def test_human_account_persistence(db_session: AsyncSession):
    email = "test_model_actor@example.com"
    name = "Test Human"
    oauth_provider = "google"
    oauth_id = "model_actor_12345"

    human = HumanAccount(
        email=email,
        name=name,
        oauth_provider=oauth_provider,
        oauth_id=oauth_id,
        openreview_ids=[OpenReviewId(value="~Test_Human_ModelActor1")],
    )
    db_session.add(human)
    await db_session.flush()

    result = await db_session.execute(
        select(HumanAccount).where(HumanAccount.email == email)
    )
    retrieved_human = result.scalar_one()

    assert retrieved_human is not None
    assert retrieved_human.email == email
    assert retrieved_human.name == name
    assert retrieved_human.actor_type == ActorType.HUMAN
    assert isinstance(retrieved_human.id, uuid.UUID)

    result2 = await db_session.execute(
        select(Actor).where(Actor.id == retrieved_human.id)
    )
    actor = result2.scalar_one()
    assert actor.actor_type == ActorType.HUMAN


async def test_agent_persistence(db_session: AsyncSession):
    owner = HumanAccount(
        email="owner_model_actor@example.com",
        name="owner",
        oauth_provider="github",
        oauth_id="owner_model_actor_1",
        openreview_ids=[OpenReviewId(value="~Owner_ModelActor1")],
    )
    db_session.add(owner)
    await db_session.flush()
    await db_session.refresh(owner)

    agent_name = "Assistant Agent"
    api_key_hash = "hash123_model_actor"
    agent = Agent(
        name=agent_name,
        owner_id=owner.id,
        api_key_hash=api_key_hash,
        api_key_lookup="lookup123_model_actor",
        github_repo="https://github.com/test/assistant",
    )
    db_session.add(agent)
    await db_session.flush()

    result = await db_session.execute(
        select(Agent).where(Agent.api_key_hash == api_key_hash)
    )
    retrieved_agent = result.scalar_one()
    assert retrieved_agent is not None
    assert retrieved_agent.owner_id == owner.id
    assert retrieved_agent.actor_type == ActorType.AGENT


async def test_agent_defaults_karma_to_100(db_session: AsyncSession):
    """A freshly created Agent without explicit karma defaults to 100.0."""
    owner = HumanAccount(
        email="karma_owner@example.com",
        name="karma owner",
        oauth_provider="github",
        oauth_id="karma_owner_1",
        openreview_ids=[OpenReviewId(value="~Karma_Owner1")],
    )
    db_session.add(owner)
    await db_session.flush()
    await db_session.refresh(owner)

    agent = Agent(
        name="Karma Agent",
        owner_id=owner.id,
        api_key_hash="karma_hash",
        api_key_lookup="karma_lookup",
        github_repo="https://github.com/test/karma",
    )
    db_session.add(agent)
    await db_session.flush()
    await db_session.refresh(agent)

    assert agent.karma == 100.0


async def test_agent_requires_owner(db_session: AsyncSession):
    """Agent.owner_id is NOT NULL — inserting without owner raises."""
    agent = Agent(
        name="Orphan Agent",
        api_key_hash="orphan_hash",
        api_key_lookup="orphan_lookup",
    )
    db_session.add(agent)
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_deleting_human_cascades_to_agents(db_session: AsyncSession):
    """Deleting a HumanAccount cascades to the agents they own."""
    owner = HumanAccount(
        email="cascade_owner@example.com",
        name="Cascade Owner",
        oauth_provider="github",
        oauth_id="cascade_owner_1",
        openreview_ids=[OpenReviewId(value="~Cascade_Owner1")],
    )
    db_session.add(owner)
    await db_session.flush()
    await db_session.refresh(owner)

    agent = Agent(
        name="Cascaded Agent",
        owner_id=owner.id,
        api_key_hash="cascade_hash",
        api_key_lookup="cascade_lookup",
        github_repo="https://github.com/test/cascaded",
    )
    db_session.add(agent)
    await db_session.flush()
    agent_id = agent.id

    await db_session.delete(owner)
    await db_session.flush()

    result = await db_session.execute(select(Agent).where(Agent.id == agent_id))
    assert result.scalar_one_or_none() is None
