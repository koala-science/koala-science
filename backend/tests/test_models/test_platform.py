from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.platform import Paper, Comment
from app.models.identity import HumanAccount, OpenReviewId


async def test_paper_persistence(db_session: AsyncSession):
    submitter = HumanAccount(
        name="Paper Submitter",
        email="paper_submitter@example.com",
        oauth_provider="github",
        oauth_id="paper_sub_1",
        openreview_ids=[OpenReviewId(value="~X_paper_sub_11")]
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


async def test_paper_authors_round_trips_as_list(db_session: AsyncSession):
    """Paper.authors is JSONB and every write site (seed, seed_benchmarks,
    ingest_hf) passes a list — confirm the list shape round-trips cleanly."""
    submitter = HumanAccount(
        name="Authors RT",
        email="authors_rt@example.com",
        oauth_provider="github",
        oauth_id="authors_rt_1",
        openreview_ids=[OpenReviewId(value="~X_authors_rt_11")],
    )
    db_session.add(submitter)
    await db_session.flush()

    paper = Paper(
        title="Authors Round-Trip",
        abstract="Abstract",
        domains=["d/NLP"],
        submitter_id=submitter.id,
        authors=[{"name": "A"}, {"name": "B"}],
    )
    db_session.add(paper)
    await db_session.flush()

    result = await db_session.execute(
        select(Paper).where(Paper.title == "Authors Round-Trip")
    )
    retrieved = result.scalar_one()
    assert retrieved.authors == [{"name": "A"}, {"name": "B"}]


async def test_comment_thread_persistence(db_session: AsyncSession):
    submitter = HumanAccount(
        name="Comment Sub",
        email="comment_sub@example.com",
        oauth_provider="github",
        oauth_id="comment_sub_1",
        openreview_ids=[OpenReviewId(value="~X_comment_sub_11")]
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
        github_file_url="https://github.com/test/agent/blob/main/logs/p.md",
    )
    db_session.add(parent_comment)
    await db_session.flush()

    reply_comment = Comment(
        paper_id=paper.id,
        parent_id=parent_comment.id,
        author_id=submitter.id,
        content_markdown="Equation 3 is derived from...",
        github_file_url="https://github.com/test/agent/blob/main/logs/r.md",
    )
    db_session.add(reply_comment)
    await db_session.flush()

    result = await db_session.execute(
        select(Comment).where(Comment.parent_id == parent_comment.id)
    )
    replies = result.scalars().all()
    assert len(replies) == 1
    assert replies[0].id == reply_comment.id
