"""
ArxivIngestionWorkflow: Multi-step workflow for ingesting papers from arXiv.

Steps: fetch metadata → download PDF → extract text → create DB record → generate embedding
Each step is a discrete Temporal activity with automatic retry on failure.
"""
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from temporalio import activity, workflow

with workflow.unsafe.imports_passed_through():
    import httpx
    import fitz  # pymupdf


# arXiv category → Coalescence domain mapping
ARXIV_DOMAIN_MAP = {
    "cs.CL": "d/NLP",
    "cs.AI": "d/LLM-Alignment",
    "cs.LG": "d/LLM-Alignment",
    "cs.CV": "d/LLM-Alignment",
    "cond-mat": "d/MaterialScience",
    "q-bio": "d/Bioinformatics",
    "quant-ph": "d/QuantumComputing",
}


@dataclass
class ArxivIngestionInput:
    arxiv_url: str
    domain: str | None = None
    submitted_by_actor_id: str | None = None


@dataclass
class ArxivIngestionResult:
    paper_id: str
    title: str
    domain: str
    has_embedding: bool


def _extract_arxiv_id(url_or_id: str) -> str:
    """Extract arXiv ID from URL or raw ID."""
    # Match patterns like: 2301.07041, arxiv.org/abs/2301.07041, arxiv.org/pdf/2301.07041
    match = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", url_or_id)
    if match:
        return match.group(1)
    raise ValueError(f"Could not extract arXiv ID from: {url_or_id}")


def _map_categories_to_domain(categories: list[str]) -> str:
    """Map arXiv categories to Coalescence domain."""
    for cat in categories:
        for prefix, domain in ARXIV_DOMAIN_MAP.items():
            if cat.startswith(prefix):
                return domain
    return "d/LLM-Alignment"  # Default


class ArxivIngestionActivities:

    @activity.defn
    async def fetch_arxiv_metadata(self, arxiv_url: str) -> dict:
        """Fetch paper metadata from the arXiv API."""
        arxiv_id = _extract_arxiv_id(arxiv_url)
        activity.logger.info(f"Fetching metadata for arXiv ID: {arxiv_id}")

        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(
                f"https://export.arxiv.org/api/query?id_list={arxiv_id}"
            )
            resp.raise_for_status()

        # Parse Atom XML
        root = ET.fromstring(resp.text)
        ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

        entry = root.find("atom:entry", ns)
        if entry is None:
            raise ValueError(f"Paper not found on arXiv: {arxiv_id}")

        title = entry.findtext("atom:title", "", ns).strip().replace("\n", " ")
        abstract = entry.findtext("atom:summary", "", ns).strip()
        authors = [a.findtext("atom:name", "", ns) for a in entry.findall("atom:author", ns)]
        categories = [c.get("term", "") for c in entry.findall("atom:category", ns)]
        published = entry.findtext("atom:published", "", ns)

        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

        return {
            "arxiv_id": arxiv_id,
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "categories": categories,
            "pdf_url": pdf_url,
            "published_date": published,
        }

    @activity.defn
    async def download_pdf(self, pdf_url: str) -> str:
        """Download PDF to a temp file for processing, persist to storage backend."""
        import tempfile
        activity.logger.info(f"Downloading PDF: {pdf_url}")

        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(pdf_url)
            resp.raise_for_status()

        # Write to temp file for downstream processing (text extraction, preview)
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp.write(resp.content)
        tmp.close()

        # Also persist to storage backend
        filename = pdf_url.split("/")[-1]
        if not filename.endswith(".pdf"):
            filename += ".pdf"
        from app.core.storage import storage
        await storage.save(f"pdfs/{filename}", resp.content, content_type="application/pdf")

        return tmp.name

    @activity.defn
    async def extract_text_from_pdf(self, pdf_path: str) -> str:
        """Extract text content from PDF using PyMuPDF."""
        activity.logger.info(f"Extracting text from: {pdf_path}")

        doc = fitz.open(pdf_path)
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()

        full_text = "\n".join(text_parts)
        # Strip null bytes (PostgreSQL rejects them) and limit size
        full_text = full_text.replace("\x00", "")
        return full_text[:100_000]

    @activity.defn
    async def extract_preview_image(self, pdf_path: str) -> str | None:
        """Extract the best preview image from the PDF and store it."""
        activity.logger.info(f"Extracting preview from: {pdf_path}")
        from app.core.pdf_preview import extract_and_store_preview
        return await extract_and_store_preview(pdf_path)

    @activity.defn
    async def create_paper_record(self, metadata: dict, extracted_text: str, pdf_path: str, preview_image_url: str | None = None) -> str:
        """Create Paper record in database, return paper_id."""
        activity.logger.info(f"Creating paper record: {metadata.get('title', 'unknown')}")

        from app.db.session import AsyncSessionLocal
        from app.models.platform import Paper

        domain = _map_categories_to_domain(metadata.get("categories", []))

        async with AsyncSessionLocal() as session:
            paper = Paper(
                title=metadata["title"],
                abstract=metadata["abstract"],
                domain=domain,
                pdf_url=metadata["pdf_url"],
                arxiv_id=metadata["arxiv_id"],
                authors=metadata.get("authors"),
                full_text=extracted_text,
                preview_image_url=preview_image_url,
            )

            # For arXiv ingestion, we need a system actor — skip submitter for now
            # This will be set by the caller via workflow input
            if metadata.get("submitted_by_actor_id"):
                import uuid
                paper.submitter_id = uuid.UUID(metadata["submitted_by_actor_id"])

            session.add(paper)
            await session.flush()
            await session.refresh(paper)
            paper_id = str(paper.id)
            await session.commit()

        return paper_id


@workflow.defn
class ArxivIngestionWorkflow:
    """
    Durable multi-step workflow for arXiv paper ingestion.
    If any step fails, Temporal retries from that step, not from the beginning.
    """

    @workflow.run
    async def run(self, input: ArxivIngestionInput) -> ArxivIngestionResult:
        # Step 1: Fetch metadata
        metadata = await workflow.execute_activity_method(
            ArxivIngestionActivities.fetch_arxiv_metadata,
            input.arxiv_url,
            start_to_close_timeout=timedelta(seconds=30),
        )

        if input.submitted_by_actor_id:
            metadata["submitted_by_actor_id"] = input.submitted_by_actor_id

        # Step 2: Download PDF
        pdf_path = await workflow.execute_activity_method(
            ArxivIngestionActivities.download_pdf,
            metadata["pdf_url"],
            start_to_close_timeout=timedelta(seconds=120),
        )

        # Step 3: Extract text
        extracted_text = await workflow.execute_activity_method(
            ArxivIngestionActivities.extract_text_from_pdf,
            pdf_path,
            start_to_close_timeout=timedelta(seconds=60),
        )

        # Step 4: Extract preview image
        preview_image_url = await workflow.execute_activity_method(
            ArxivIngestionActivities.extract_preview_image,
            pdf_path,
            start_to_close_timeout=timedelta(seconds=30),
        )

        # Step 5: Create DB record
        paper_id = await workflow.execute_activity_method(
            ArxivIngestionActivities.create_paper_record,
            args=[metadata, extracted_text, pdf_path, preview_image_url],
            start_to_close_timeout=timedelta(seconds=15),
        )

        # Step 5: Generate embedding (child workflow)
        try:
            await workflow.execute_child_workflow(
                "EmbeddingGenerationWorkflow",
                args=[paper_id, metadata.get("abstract", "")],
                task_queue="coalescence-workflows",
            )
            has_embedding = True
        except Exception:
            # Embedding generation is non-critical — paper still created
            has_embedding = False

        domain = input.domain or _map_categories_to_domain(metadata.get("categories", []))

        return ArxivIngestionResult(
            paper_id=paper_id,
            title=metadata.get("title", ""),
            domain=domain,
            has_embedding=has_embedding,
        )
