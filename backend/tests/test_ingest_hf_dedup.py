"""Regression test: `--no-arxiv-id` must dedup on re-ingest.

Before the fix, dedup only fired when `keep_arxiv_id=True`. Re-running the
script with `--no-arxiv-id` re-ingested every row. The fix adds an
`openreview_id` fallback (the HF dataset ships that field per row).
"""
import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession

from app.core.config import settings
from app.db import session as session_module
from app.models.identity import HumanAccount, OpenReviewId
from app.models.platform import Paper
from scripts import ingest_hf


_MINIMAL_PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<<>>\n%%EOF\n"


def _rows(run_id: str) -> list[dict]:
    # Arxiv/openreview IDs are suffixed with a per-test run_id so re-running
    # the test in a dirty DB doesn't clash with prior-run Paper rows.
    return [
        {
            "arxiv_id": f"2601.{run_id}.{i:05d}",
            "openreview_id": f"orid_{run_id}_{i}",
            "title": f"Paper {i}",
            "abstract": f"Abstract {i}.",
            "domains": ["Test Domain"],
            "authors": [],
            "github_urls": [],
            "pdf_path": f"pdfs/2601.{run_id}.{i:05d}.pdf",
        }
        for i in range(3)
    ]


def _run(coro_factory):
    """Run a coroutine under a fresh engine + event loop.

    asyncpg connections bind to the loop that created them, so sharing the
    module-level ``AsyncSessionLocal`` across multiple ``asyncio.run()``
    calls raises ``Task got Future attached to a different loop``. This
    helper swaps in a per-call engine and disposes it after.
    """
    async def _wrapped():
        engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        prev_engine = session_module.engine
        prev_factory = session_module.AsyncSessionLocal
        session_module.engine = engine
        session_module.AsyncSessionLocal = factory
        # The script imports ``AsyncSessionLocal`` by name, so patch it there too.
        prev_script_factory = ingest_hf.AsyncSessionLocal
        ingest_hf.AsyncSessionLocal = factory
        try:
            return await coro_factory()
        finally:
            session_module.engine = prev_engine
            session_module.AsyncSessionLocal = prev_factory
            ingest_hf.AsyncSessionLocal = prev_script_factory
            await engine.dispose()

    return asyncio.run(_wrapped())


async def _seed_submitter() -> str:
    async with ingest_hf.AsyncSessionLocal() as session:
        email = f"ingest_dedup_{uuid.uuid4().hex[:8]}@example.com"
        human = HumanAccount(
            name="Ingest Dedup Owner",
            email=email,
            hashed_password="x",
            is_superuser=True,
            openreview_ids=[OpenReviewId(value=f"~Ingest_Dedup_{uuid.uuid4().hex[:8]}1")],
        )
        session.add(human)
        await session.commit()
        return email


async def _count_papers_for(email: str) -> int:
    async with ingest_hf.AsyncSessionLocal() as session:
        result = await session.execute(
            select(Paper)
            .join(HumanAccount, Paper.submitter_id == HumanAccount.id)
            .where(HumanAccount.email == email)
        )
        return len(result.scalars().all())


def test_no_arxiv_id_run_dedups_on_rerun(monkeypatch):
    run_id = uuid.uuid4().hex[:8]
    monkeypatch.setattr(ingest_hf, "_load_rows", lambda limit: _rows(run_id))
    monkeypatch.setattr(ingest_hf, "_fetch_pdf_bytes", lambda pdf_rel: _MINIMAL_PDF)

    async def _no_preview(_bytes: bytes) -> str | None:
        return None

    async def _no_embed(_pid: str, _text: str) -> bool:
        return True

    monkeypatch.setattr(ingest_hf, "_save_preview", _no_preview)
    monkeypatch.setattr(ingest_hf, "_trigger_embedding", _no_embed)
    monkeypatch.setattr(ingest_hf, "_extract_full_text", lambda _p: "full text")

    class _NoopStorage:
        async def save(self, path, data, content_type=None):
            return f"local://{path}"

    monkeypatch.setattr(ingest_hf, "storage", _NoopStorage())

    email = _run(_seed_submitter)

    _run(lambda: ingest_hf.ingest(
        limit=-1,
        submitter_email=email,
        skip_embeddings=True,
        keep_arxiv_id=False,
    ))
    assert _run(lambda: _count_papers_for(email)) == 3

    _run(lambda: ingest_hf.ingest(
        limit=-1,
        submitter_email=email,
        skip_embeddings=True,
        keep_arxiv_id=False,
    ))
    assert _run(lambda: _count_papers_for(email)) == 3
