"""Deleting a parent Comment must preserve descendant replies.

Policy: a reply thread posted by another agent is their work. When the
parent is deleted, the immediate children lift to top-level (parent_id
NULL) and grandchildren keep their immediate-parent links. This is
enforced at the DB layer via ``ON DELETE SET NULL`` on
``comment.parent_id`` (migration 034), combined with
``passive_deletes=True`` on the ORM relationship so the ORM does not
cascade in Python.

These tests cover both the raw-SQL and ORM delete paths, plus the
existing paper-delete cascade (which must continue to wipe the full
thread via the explicit nullify-then-delete sequence in
``papers.py``).
"""
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Agent, HumanAccount, OpenReviewId
from app.models.platform import Comment, Paper


async def _make_paper_with_thread(
    db: AsyncSession,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Build paper + root -> reply1 -> reply2 (a 2-deep thread).

    Returns ``(paper_id, root_id, reply1_id, reply2_id)``.
    """
    tag = uuid.uuid4().hex[:8]
    submitter = HumanAccount(
        name=f"Submitter {tag}",
        email=f"submitter_{tag}@example.com",
        hashed_password="hashed",
        oauth_provider="github",
        oauth_id=f"sub_{tag}",
        openreview_ids=[OpenReviewId(value=f"~Submitter_{tag}1")],
    )
    db.add(submitter)
    await db.flush()

    agent = Agent(
        name=f"Agent {tag}",
        owner_id=submitter.id,
        api_key_hash=f"hash_{tag}",
        api_key_lookup=f"lookup_{tag}",
        github_repo=f"https://github.com/test/agent_{tag}",
    )
    db.add(agent)
    await db.flush()

    paper = Paper(
        title=f"Paper {tag}",
        abstract="Abstract.",
        domains=["NLP"],
        submitter_id=submitter.id,
    )
    db.add(paper)
    await db.flush()

    url = "https://github.com/koala-science/test/blob/main/c.md"
    root = Comment(
        paper_id=paper.id,
        parent_id=None,
        author_id=agent.id,
        content_markdown="root",
        github_file_url=url,
    )
    db.add(root)
    await db.flush()

    reply1 = Comment(
        paper_id=paper.id,
        parent_id=root.id,
        author_id=agent.id,
        content_markdown="reply1",
        github_file_url=url,
    )
    db.add(reply1)
    await db.flush()

    reply2 = Comment(
        paper_id=paper.id,
        parent_id=reply1.id,
        author_id=agent.id,
        content_markdown="reply2",
        github_file_url=url,
    )
    db.add(reply2)
    await db.flush()

    return paper.id, root.id, reply1.id, reply2.id


async def test_raw_sql_delete_parent_preserves_replies(db_session: AsyncSession):
    """DB-level DELETE on the root comment: replies survive, reply1 lifts
    to top-level (parent_id NULL), reply2 still points at reply1."""
    _paper_id, root_id, reply1_id, reply2_id = await _make_paper_with_thread(
        db_session
    )

    await db_session.execute(
        text("DELETE FROM comment WHERE id = :rid"), {"rid": root_id}
    )
    await db_session.flush()

    # Root is gone.
    root_gone = await db_session.execute(
        select(Comment).where(Comment.id == root_id)
    )
    assert root_gone.scalar_one_or_none() is None

    # reply1 survived, lifted to top-level.
    r1 = (
        await db_session.execute(select(Comment).where(Comment.id == reply1_id))
    ).scalar_one()
    assert r1.parent_id is None

    # reply2 survived, still attached to reply1.
    r2 = (
        await db_session.execute(select(Comment).where(Comment.id == reply2_id))
    ).scalar_one()
    assert r2.parent_id == reply1_id


async def test_orm_delete_parent_preserves_replies(db_session: AsyncSession):
    """``session.delete(root)`` must not cascade through the subtree.
    With ``passive_deletes=True`` the ORM defers to the DB-level
    ``ON DELETE SET NULL`` action."""
    _paper_id, root_id, reply1_id, reply2_id = await _make_paper_with_thread(
        db_session
    )

    root = (
        await db_session.execute(select(Comment).where(Comment.id == root_id))
    ).scalar_one()
    await db_session.delete(root)
    await db_session.flush()

    # Root is gone.
    root_gone = await db_session.execute(
        select(Comment).where(Comment.id == root_id)
    )
    assert root_gone.scalar_one_or_none() is None

    # reply1 survived, lifted to top-level.
    r1 = (
        await db_session.execute(select(Comment).where(Comment.id == reply1_id))
    ).scalar_one()
    assert r1.parent_id is None

    # reply2 survived, still attached to reply1.
    r2 = (
        await db_session.execute(select(Comment).where(Comment.id == reply2_id))
    ).scalar_one()
    assert r2.parent_id == reply1_id


async def test_paper_delete_still_cascades_through_thread(db_session: AsyncSession):
    """The paper-delete path in ``papers.py`` nullifies parent_ids first,
    then bulk-deletes every comment on the paper. That behavior must
    not regress — a paper with a reply thread vanishes entirely."""
    paper_id, root_id, reply1_id, reply2_id = await _make_paper_with_thread(
        db_session
    )

    # Mirror the endpoint's two-step sequence (papers.py:325-328):
    # nullify parent_ids first to avoid FK violations inside the delete,
    # then remove every comment on the paper.
    await db_session.execute(
        Comment.__table__.update()
        .where(Comment.paper_id == paper_id)
        .values(parent_id=None)
    )
    await db_session.execute(
        text("DELETE FROM comment WHERE paper_id = :pid"), {"pid": paper_id}
    )

    paper = (
        await db_session.execute(select(Paper).where(Paper.id == paper_id))
    ).scalar_one()
    await db_session.delete(paper)
    await db_session.flush()

    # Everything is gone — paper, root, and both replies.
    for cid in (root_id, reply1_id, reply2_id):
        gone = await db_session.execute(
            select(Comment).where(Comment.id == cid)
        )
        assert gone.scalar_one_or_none() is None
    paper_gone = await db_session.execute(
        select(Paper).where(Paper.id == paper_id)
    )
    assert paper_gone.scalar_one_or_none() is None
