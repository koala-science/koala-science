from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import HumanAccount
from app.models.platform import Paper, PaperRevision


async def test_paper_revision_persistence(db_session: AsyncSession):
    submitter = HumanAccount(
        name="Revision Submitter",
        email="revision_submitter@example.com",
        oauth_provider="github",
        oauth_id="revision_sub_1",
        openreview_id="~X_revision_sub_11"
    )
    db_session.add(submitter)
    await db_session.flush()

    paper = Paper(
        title="Initial Title",
        abstract="Initial abstract",
        domains=["d/NLP"],
        pdf_url="https://example.com/v1.pdf",
        submitter_id=submitter.id,
    )
    db_session.add(paper)
    await db_session.flush()

    revision = PaperRevision(
        paper_id=paper.id,
        version=1,
        created_by_id=submitter.id,
        title=paper.title,
        abstract=paper.abstract,
        pdf_url=paper.pdf_url,
        github_repo_url=None,
        preview_image_url=None,
        changelog="Initial submission",
    )
    db_session.add(revision)
    await db_session.flush()

    result = await db_session.execute(
        select(PaperRevision).where(PaperRevision.paper_id == paper.id)
    )
    retrieved_revision = result.scalar_one()

    assert retrieved_revision.version == 1
    assert retrieved_revision.created_by_id == submitter.id
    assert retrieved_revision.changelog == "Initial submission"
