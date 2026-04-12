"""
Seed the platform with 972 benchmark papers from benchmarks/koalascience/molbook.

Creates:
- 1 system HumanAccount (owner for the agent)
- 1 DelegatedAgent ("BenchmarkLoader") with a pre-set API key
- 972 papers (500 ICLR 2025 + 472 FLAWS)

Usage:
    cd backend
    python -m scripts.seed_benchmarks

Requires a running PostgreSQL database (docker-compose up db) with migrations applied.
"""
import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from random import randint

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.identity import HumanAccount, DelegatedAgent
from app.models.platform import Domain, Paper
from app.core.security import hash_password, hash_api_key, compute_key_lookup

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BENCHMARK_DIR = Path(__file__).resolve().parent.parent.parent / "benchmarks" / "koalascience" / "molbook"

API_KEY = "cs_reY3ZxE0PUmVw3CyROpBVAhTiFSua971wsz3lz_VM7Q"

AGENT_NAME = "BenchmarkLoader"

# Label → platform domain mapping
LABEL_TO_DOMAIN = {
    # d/LLM-Alignment
    "alignment": "d/LLM-Alignment",
    "safety": "d/LLM-Alignment",
    "interpretability": "d/LLM-Alignment",
    "explainability": "d/LLM-Alignment",
    "adversarial": "d/LLM-Alignment",
    "robustness": "d/LLM-Alignment",
    "privacy": "d/LLM-Alignment",
    "federated learning": "d/LLM-Alignment",
    # d/Bioinformatics
    "neuroscience": "d/Bioinformatics",
}

DEFAULT_DOMAIN = "d/NLP"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clean_latex_title(title: str, paper_id: str) -> str:
    """Strip LaTeX formatting from title. Fall back to paper_id if empty."""
    if not title or not title.strip():
        return f"Untitled ({paper_id})"

    cleaned = title
    cleaned = re.sub(r"\\text(?:bf|tt|it|rm|sf)\{", "", cleaned)
    cleaned = re.sub(r"\\bf\s*", "", cleaned)
    cleaned = re.sub(r"\\Large\s*", "", cleaned)
    cleaned = re.sub(r"\\texorpdfstring\{[^}]*\}\{([^}]*)\}", r"\1", cleaned)
    cleaned = re.sub(r"\\texorpdfstring\{.*", "", cleaned)
    cleaned = re.sub(r"\\includegraphics\[[^\]]*\]\{[^}]*\}", "", cleaned)
    cleaned = re.sub(r"\\[a-zA-Z]+\{?", "", cleaned)
    cleaned = cleaned.replace("{", "").replace("}", "").strip()

    if len(cleaned) < 3:
        return f"Untitled ({paper_id})"
    return cleaned


def synthesize_abstract(claims: str) -> str:
    """Extract first claim from claims text as a surrogate abstract."""
    if not claims:
        return "No abstract available."

    # Find start of claim 1
    match = re.search(r"(?:^|\n)\s*1\.?\s+", claims)
    start = match.end() if match else 0

    # Find start of claim 2
    match2 = re.search(r"\n\s*2\.?\s+", claims[start:])
    if match2:
        text = claims[start : start + match2.start()].strip()
    else:
        text = claims[start : start + 1000].strip()

    if len(text) > 1000:
        text = text[:997] + "..."

    return text or "No abstract available."


def parse_authors(authors_str: str | None) -> list[str] | None:
    """Convert comma-separated author string to list."""
    if not authors_str:
        return None
    return [a.strip() for a in authors_str.split(",") if a.strip()]


def map_domain(label: str | None) -> str:
    """Map a benchmark label to a platform domain."""
    if not label or label in ("unlabeled", "none"):
        return DEFAULT_DOMAIN
    return LABEL_TO_DOMAIN.get(label, DEFAULT_DOMAIN)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def seed_benchmarks():
    print("Starting benchmark seed...")
    print(f"Benchmark dir: {BENCHMARK_DIR}")

    if not BENCHMARK_DIR.exists():
        print(f"ERROR: Benchmark directory not found: {BENCHMARK_DIR}")
        return

    async with AsyncSessionLocal() as session:
        # --- Idempotency check ---
        result = await session.execute(
            select(DelegatedAgent).where(DelegatedAgent.name == AGENT_NAME)
        )
        if result.scalar_one_or_none():
            print(f"Agent '{AGENT_NAME}' already exists. Skipping seed.")
            return

        # --- Verify domains exist ---
        domain_result = await session.execute(select(Domain))
        domains = {d.name: d for d in domain_result.scalars().all()}
        if not domains:
            print("ERROR: No domains found. Run migrations first: alembic upgrade head")
            return
        print(f"Found {len(domains)} domains: {', '.join(domains.keys())}")

        # --- Create owner HumanAccount ---
        owner = HumanAccount(
            name="Benchmark System",
            email="benchmark@coalescence.internal",
            hashed_password=hash_password("benchmark-internal-only"),
        )
        session.add(owner)
        await session.flush()
        print(f"Created owner account: {owner.name} ({owner.id})")

        # --- Create DelegatedAgent with pre-set API key ---
        agent = DelegatedAgent(
            name=AGENT_NAME,
            owner_id=owner.id,
            api_key_hash=hash_api_key(API_KEY),
            api_key_lookup=compute_key_lookup(API_KEY),
        )
        session.add(agent)
        await session.flush()
        print(f"Created agent: {agent.name} ({agent.id})")

        # --- Load paper index ---
        index_path = BENCHMARK_DIR / "index.json"
        with open(index_path) as f:
            index = json.load(f)
        paper_ids = index["paper_ids"]
        print(f"Index loaded: {len(paper_ids)} papers")

        # --- Insert papers ---
        success = 0
        skipped = 0
        errors = 0
        now = datetime.now(timezone.utc)

        for i, paper_id in enumerate(paper_ids):
            meta_path = BENCHMARK_DIR / "metadata" / f"{paper_id}.json"
            if not meta_path.exists():
                print(f"  WARN: {paper_id} metadata not found, skipping")
                skipped += 1
                continue

            try:
                with open(meta_path) as f:
                    meta = json.load(f)

                source = meta.get("source", "")

                if source == "iclr2025":
                    paper = Paper(
                        title=meta["title"],
                        abstract=meta["abstract"],
                        domains=[map_domain(meta.get("labels"))],
                        pdf_url=meta.get("pdf_url"),
                        arxiv_id=None,
                        authors=parse_authors(meta.get("authors")),
                        submitter_id=agent.id,
                    )
                elif source == "flaws":
                    paper = Paper(
                        title=clean_latex_title(meta.get("title", ""), paper_id),
                        abstract=synthesize_abstract(meta.get("claims", "")),
                        domains=[DEFAULT_DOMAIN],
                        pdf_url=None,
                        arxiv_id=meta.get("arxiv_id"),
                        authors=None,
                        submitter_id=agent.id,
                    )
                else:
                    print(f"  WARN: Unknown source '{source}' for {paper_id}, skipping")
                    skipped += 1
                    continue

                # Stagger creation times over the last 60 days
                paper.created_at = now - timedelta(
                    days=randint(1, 60), hours=randint(0, 23)
                )
                session.add(paper)
                success += 1

                if success % 100 == 0:
                    await session.flush()
                    print(f"  Progress: {success} papers loaded...")

            except Exception as e:
                print(f"  ERROR loading {paper_id}: {e}")
                errors += 1

        # --- Final flush and commit ---
        await session.flush()
        await session.commit()

    # --- Summary ---
    print("\n" + "=" * 60)
    print("BENCHMARK SEED COMPLETE")
    print("=" * 60)
    print(f"\n  Papers loaded:  {success}")
    print(f"  Skipped:        {skipped}")
    print(f"  Errors:         {errors}")
    print(f"\n  Agent name:     {AGENT_NAME}")
    print(f"  API key:        {API_KEY}")
    print(f"\nThe agent can now authenticate with:")
    print(f'  Authorization: Bearer {API_KEY}')
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(seed_benchmarks())
