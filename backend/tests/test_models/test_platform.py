import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.platform import Paper, Comment, Vote, TargetType, DomainAuthority, Domain
from app.models.identity import HumanAccount


async def test_paper_persistence(db_session: AsyncSession):
    submitter = HumanAccount(
        name="Paper Submitter",
        email="paper_submitter@example.com",
        oauth_provider="github",
        oauth_id="paper_sub_1",
    )
    db_session.add(submitter)
    await db_session.flush()

    paper = Paper(
        title="Decentralized Peer Review",
        abstract="A novel approach to scientific consensus.",
        domains=["d/Computer Science"],
        pdf_url="https://example.com/paper.pdf",
        submitter_id=submitter.id,
    )
    db_session.add(paper)
    await db_session.flush()

    result = await db_session.execute(
        select(Paper).where(Paper.title == "Decentralized Peer Review")
    )
    retrieved_paper = result.scalar_one()
    assert retrieved_paper is not None
    assert retrieved_paper.submitter_id == submitter.id


async def test_comment_thread_persistence(db_session: AsyncSession):
    submitter = HumanAccount(
        name="Comment Sub",
        email="comment_sub@example.com",
        oauth_provider="github",
        oauth_id="comment_sub_1",
    )
    db_session.add(submitter)
    await db_session.flush()

    paper = Paper(
        title="Comment Test Paper Actor",
        abstract="Abstract",
        domains=["d/Physics"],
        submitter_id=submitter.id,
    )
    db_session.add(paper)
    await db_session.flush()

    parent_comment = Comment(
        paper_id=paper.id,
        author_id=submitter.id,
        content_markdown="I have a question about equation 3.",
    )
    db_session.add(parent_comment)
    await db_session.flush()

    reply_comment = Comment(
        paper_id=paper.id,
        parent_id=parent_comment.id,
        author_id=submitter.id,
        content_markdown="Equation 3 is derived from...",
    )
    db_session.add(reply_comment)
    await db_session.flush()

    result = await db_session.execute(
        select(Comment).where(Comment.parent_id == parent_comment.id)
    )
    replies = result.scalars().all()
    assert len(replies) == 1
    assert replies[0].id == reply_comment.id


async def test_vote_persistence(db_session: AsyncSession):
    voter = HumanAccount(
        name="Voter",
        email="voter@example.com",
        oauth_provider="github",
        oauth_id="voter_1",
    )
    db_session.add(voter)
    await db_session.flush()

    target_id = uuid.uuid4()

    vote = Vote(
        target_type=TargetType.PAPER,
        target_id=target_id,
        voter_id=voter.id,
        vote_value=1,
    )
    db_session.add(vote)
    await db_session.flush()

    result = await db_session.execute(
        select(Vote).where(Vote.voter_id == voter.id)
    )
    retrieved_vote = result.scalar_one()
    assert retrieved_vote is not None
    assert retrieved_vote.target_type == TargetType.PAPER
    assert retrieved_vote.vote_value == 1
    assert retrieved_vote.vote_weight == 1.0


async def test_domain_authority_persistence(db_session: AsyncSession):
    actor = HumanAccount(
        name="Authority Test",
        email="authority@example.com",
        oauth_provider="github",
        oauth_id="authority_1",
    )
    domain = Domain(name="d/TestDomain", description="Test domain")
    db_session.add_all([actor, domain])
    await db_session.flush()

    da = DomainAuthority(
        actor_id=actor.id,
        domain_id=domain.id,
        authority_score=12.5,
        total_comments=10,
    )
    db_session.add(da)
    await db_session.flush()

    result = await db_session.execute(
        select(DomainAuthority).where(DomainAuthority.actor_id == actor.id)
    )
    retrieved = result.scalar_one()
    assert retrieved.authority_score == 12.5
    assert retrieved.total_comments == 10
