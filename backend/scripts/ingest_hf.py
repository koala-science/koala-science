"""
Ingest papers from the McGill-NLP/koala-science-icml-2026-competition HF dataset.

Uses the anonymized PDFs shipped inside the dataset repo rather than fetching
from arxiv.org. Each paper ends up with:
  - PDF bytes saved to the storage backend at pdfs/<arxiv_id>.pdf
  - pdf_url set to the local storage path (same convention the arXiv workflow uses)
  - full_text extracted via PyMuPDF (100KB cap, null bytes stripped)
  - preview_image_url extracted via app.core.pdf_preview
  - A Temporal EmbeddingGenerationWorkflow kicked off (best-effort)

Usage (inside the backend container):
    python -m scripts.ingest_hf                         # first 10 rows
    python -m scripts.ingest_hf --limit 100
    python -m scripts.ingest_hf --limit -1              # entire dataset
    python -m scripts.ingest_hf --submitter-email me@x  # pick the owning human
    python -m scripts.ingest_hf --skip-embeddings       # don't touch Temporal
    python -m scripts.ingest_hf --no-arxiv-id           # omit arxiv_id metadata
"""
from __future__ import annotations

import argparse
import asyncio
import re
import tempfile
import uuid as _uuid
from pathlib import Path

from sqlalchemy import select

from app.core.pdf_preview import extract_best_preview_bytes
from app.core.storage import storage
from app.db.session import AsyncSessionLocal
from app.models.identity import HumanAccount
from app.models.platform import Domain, Paper

DATASET = "McGill-NLP/koala-science-icml-2026-competition"


def _slug_domain(label: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", label).strip("-")
    return f"d/{cleaned}" if cleaned else "d/LLM-Alignment"


async def _ensure_domains(session, raw_to_slug: dict[str, str]) -> None:
    """Upsert Domain rows so the ingested labels exist as first-class domains."""
    if not raw_to_slug:
        return
    slugs = set(raw_to_slug.values())
    result = await session.execute(select(Domain.name).where(Domain.name.in_(slugs)))
    existing = set(result.scalars().all())
    created = 0
    for raw, slug in raw_to_slug.items():
        if slug in existing:
            continue
        session.add(Domain(name=slug, description=f"ICML 2026 competition: {raw}"))
        existing.add(slug)
        created += 1
    if created:
        await session.commit()
        print(f"Created {created} new Domain row(s)")


def _extract_full_text(pdf_path: str) -> str:
    import fitz  # pymupdf

    doc = fitz.open(pdf_path)
    try:
        text = "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()
    return text.replace("\x00", "")[:100_000]


async def _save_preview(pdf_bytes: bytes) -> str | None:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name
    try:
        png = extract_best_preview_bytes(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    if not png:
        return None
    return await storage.save(f"previews/{_uuid.uuid4().hex}.png", png, content_type="image/png")


async def _trigger_embedding(paper_id: str, text: str) -> bool:
    from app.core.config import settings

    try:
        from temporalio.client import Client

        client = await Client.connect(settings.TEMPORAL_HOST)
        await client.start_workflow(
            "EmbeddingGenerationWorkflow",
            args=[paper_id, text],
            id=f"embedding-{paper_id}",
            task_queue="coalescence-workflows",
        )
        return True
    except Exception as exc:
        print(f"    embedding trigger failed for {paper_id}: {exc}")
        return False


async def _resolve_submitter(session, email: str | None) -> HumanAccount:
    if email:
        result = await session.execute(
            select(HumanAccount).where(HumanAccount.email == email)
        )
        human = result.scalar_one_or_none()
        if not human:
            raise SystemExit(f"No human account with email={email!r}")
        return human

    # Prefer a superuser, fall back to any human.
    result = await session.execute(
        select(HumanAccount).where(HumanAccount.is_superuser.is_(True)).limit(1)
    )
    human = result.scalar_one_or_none()
    if human:
        return human

    result = await session.execute(select(HumanAccount).limit(1))
    human = result.scalar_one_or_none()
    if not human:
        raise SystemExit("No HumanAccount rows found; create one before ingesting.")
    print(f"  [warn] no superuser found; using {human.email} as submitter")
    return human


def _hf_token() -> str | None:
    """Resolve the HF access token for gated datasets.

    Reads from settings (env `HF_TOKEN`) first, falls back to `HF_TOKEN` /
    `HUGGING_FACE_HUB_TOKEN` / `HUGGINGFACEHUB_API_TOKEN` directly so ad-hoc
    runs outside the container still work. Empty string → None so the hub
    client treats it as anonymous.
    """
    import os

    from app.core.config import settings

    candidates = [
        settings.HF_TOKEN,
        os.environ.get("HF_TOKEN"),
        os.environ.get("HUGGING_FACE_HUB_TOKEN"),
        os.environ.get("HUGGINGFACEHUB_API_TOKEN"),
    ]
    for t in candidates:
        if t:
            return t
    return None


def _load_rows(limit: int):
    """Download only the parquet metadata; PDFs are fetched per-row on demand."""
    from huggingface_hub import hf_hub_download, list_repo_files
    import pyarrow.parquet as pq

    token = _hf_token()
    if not token:
        print("  [warn] no HF_TOKEN found; attempting anonymous access (will 401 on gated datasets)")

    print(f"Listing parquet files for {DATASET}...")
    repo_files = list_repo_files(repo_id=DATASET, repo_type="dataset", token=token)
    parquet_paths = sorted(f for f in repo_files if f.endswith(".parquet"))
    if not parquet_paths:
        raise SystemExit(f"No parquet files found in {DATASET}")

    local_parquets = [
        Path(hf_hub_download(repo_id=DATASET, filename=p, repo_type="dataset", token=token))
        for p in parquet_paths
    ]
    table = (
        pq.read_table(local_parquets[0])
        if len(local_parquets) == 1
        else pq.concat_tables([pq.read_table(p) for p in local_parquets])
    )
    rows = table.to_pylist()
    if limit > 0:
        rows = rows[:limit]
    print(f"Loaded {len(rows)} rows from {len(local_parquets)} parquet file(s)")
    return rows


def _fetch_pdf_bytes(pdf_rel: str) -> bytes | None:
    """Download a single PDF by its dataset-relative path (e.g. 'pdfs/2601.00242.pdf')."""
    from huggingface_hub import hf_hub_download
    from huggingface_hub.errors import EntryNotFoundError

    try:
        local = hf_hub_download(
            repo_id=DATASET,
            filename=pdf_rel,
            repo_type="dataset",
            token=_hf_token(),
        )
    except EntryNotFoundError:
        return None
    return Path(local).read_bytes()


async def ingest(
    limit: int,
    submitter_email: str | None,
    skip_embeddings: bool,
    keep_arxiv_id: bool,
) -> None:
    rows = _load_rows(limit)

    async with AsyncSessionLocal() as session:
        submitter = await _resolve_submitter(session, submitter_email)
        print(f"Submitter: {submitter.name} <{submitter.email}>  id={submitter.id}")

        raw_to_slug = {
            d: _slug_domain(d)
            for row in rows
            for d in (row.get("domains") or [])
        }
        await _ensure_domains(session, raw_to_slug)

        created: list[tuple[str, str, str]] = []  # (paper_id, arxiv_id, abstract)
        skipped_existing = 0
        skipped_missing_pdf = 0

        for row in rows:
            arxiv_id = row["arxiv_id"]

            if keep_arxiv_id:
                existing = await session.execute(
                    select(Paper).where(Paper.arxiv_id == arxiv_id)
                )
                if existing.scalar_one_or_none():
                    print(f"  [skip] {arxiv_id} already exists")
                    skipped_existing += 1
                    continue

            pdf_rel = row.get("pdf_path") or f"pdfs/{arxiv_id}.pdf"
            pdf_bytes = _fetch_pdf_bytes(pdf_rel)
            if pdf_bytes is None:
                print(f"  [miss] {arxiv_id}: {pdf_rel} not found in dataset")
                skipped_missing_pdf += 1
                continue
            if not pdf_bytes.startswith(b"%PDF"):
                print(f"  [miss] {arxiv_id}: not a valid PDF")
                skipped_missing_pdf += 1
                continue

            storage_url = await storage.save(
                f"pdfs/{arxiv_id}.pdf", pdf_bytes, content_type="application/pdf"
            )

            tarball_url: str | None = None
            tar_rel = row.get("tarball_path")
            if tar_rel:
                tar_bytes = _fetch_pdf_bytes(tar_rel)
                if tar_bytes:
                    tarball_url = await storage.save(
                        f"tarballs/{arxiv_id}.tar.gz",
                        tar_bytes,
                        content_type="application/gzip",
                    )
                else:
                    print(f"  [warn] {arxiv_id}: {tar_rel} not found in dataset")

            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(pdf_bytes)
                tmp_path = tmp.name
            try:
                full_text = _extract_full_text(tmp_path)
            finally:
                Path(tmp_path).unlink(missing_ok=True)

            preview_url = await _save_preview(pdf_bytes)

            raw_domains = row.get("domains") or []
            domains = [_slug_domain(d) for d in raw_domains] or ["d/LLM-Alignment"]

            authors = row.get("authors") or []
            github_urls = row.get("github_urls") or []

            paper = Paper(
                title=row["title"],
                abstract=row.get("abstract") or "",
                domains=list(domains),
                pdf_url=storage_url,
                tarball_url=tarball_url,
                arxiv_id=arxiv_id if keep_arxiv_id else None,
                authors=list(authors),
                submitter_id=submitter.id,
                full_text=full_text,
                preview_image_url=preview_url,
                github_repo_url=github_urls[0] if github_urls else None,
                github_urls=list(github_urls),
            )
            session.add(paper)
            await session.flush()
            await session.refresh(paper)
            await session.commit()

            created.append((str(paper.id), arxiv_id, paper.abstract))
            print(
                f"  [ok]   {arxiv_id}  id={paper.id}  "
                f"text={len(full_text)}c  preview={'yes' if preview_url else 'no'}"
            )

    if not skip_embeddings and created:
        print(f"Triggering embeddings for {len(created)} papers...")
        for pid, aid, abstract in created:
            ok = await _trigger_embedding(pid, abstract)
            print(f"  [{'emb' if ok else 'err'}] {aid}")

    print(
        f"\nDone. created={len(created)}  "
        f"skipped_existing={skipped_existing}  "
        f"skipped_missing_pdf={skipped_missing_pdf}"
    )


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--limit", type=int, default=10, help="Rows to ingest; -1 for all")
    p.add_argument("--submitter-email", default=None, help="Email of human owner (defaults to first superuser)")
    p.add_argument("--skip-embeddings", action="store_true")
    p.add_argument("--no-arxiv-id", action="store_true", help="Omit arxiv_id (fully anonymous)")
    args = p.parse_args()

    asyncio.run(
        ingest(
            limit=args.limit,
            submitter_email=args.submitter_email,
            skip_embeddings=args.skip_embeddings,
            keep_arxiv_id=not args.no_arxiv_id,
        )
    )


if __name__ == "__main__":
    main()
