import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.identity import Actor, ActorType, HumanAccount, DelegatedAgent, SovereignAgent


async def test_human_account_persistence(db_session: AsyncSession):
    email = "test_model_actor@example.com"
    name = "Test Human"
    oauth_provider = "google"
    oauth_id = "model_actor_12345"
    reputation_score = 100

    human = HumanAccount(
        email=email,
        name=name,
        oauth_provider=oauth_provider,
        oauth_id=oauth_id,
        reputation_score=reputation_score,
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

    # Also retrievable as Actor
    result2 = await db_session.execute(
        select(Actor).where(Actor.id == retrieved_human.id)
    )
    actor = result2.scalar_one()
    assert actor.actor_type == ActorType.HUMAN


async def test_delegated_agent_persistence(db_session: AsyncSession):
    owner = HumanAccount(
        email="owner_model_actor@example.com",
        name="owner",
        oauth_provider="github",
        oauth_id="owner_model_actor_1",
    )
    db_session.add(owner)
    await db_session.flush()
    await db_session.refresh(owner)

    agent_name = "Assistant Agent"
    api_key_hash = "hash123_model_actor"
    agent = DelegatedAgent(
        name=agent_name,
        owner_id=owner.id,
        api_key_hash=api_key_hash,
    )
    db_session.add(agent)
    await db_session.flush()

    result = await db_session.execute(
        select(DelegatedAgent).where(DelegatedAgent.api_key_hash == api_key_hash)
    )
    retrieved_agent = result.scalar_one()
    assert retrieved_agent is not None
    assert retrieved_agent.owner_id == owner.id
    assert retrieved_agent.actor_type == ActorType.DELEGATED_AGENT


async def test_sovereign_agent_persistence(db_session: AsyncSession):
    name = "Sovereign AI"
    public_key = "ed25519:6f8f8b8a8c8d8e8f..."
    public_key_hash = "pubhash789_model_actor"
    api_key_hash = "hash456_model_actor"

    agent = SovereignAgent(
        name=name,
        public_key=public_key,
        public_key_hash=public_key_hash,
        api_key_hash=api_key_hash,
    )
    db_session.add(agent)
    await db_session.flush()

    result = await db_session.execute(
        select(SovereignAgent).where(SovereignAgent.public_key_hash == public_key_hash)
    )
    retrieved_agent = result.scalar_one()
    assert retrieved_agent is not None
    assert retrieved_agent.name == name
    assert retrieved_agent.reputation_score == 0
    assert retrieved_agent.actor_type == ActorType.SOVEREIGN_AGENT
