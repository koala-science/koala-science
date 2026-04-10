"""
POST 972 benchmark papers to the platform API.

Usage:
    cd backend
    python -m scripts.post_benchmarks

    # Target production:
    API_URL=https://coale.science/api/v1/papers/ python -m scripts.post_benchmarks
"""
import asyncio
import json
import os
import re
from pathlib import Path

import httpx

API_URL = os.environ.get("API_URL", "http://localhost:8000/api/v1/papers/")
API_KEY = os.environ.get("API_KEY", "cs_pRBMOvof5APP8q4jhVodEJfSdLs4sgl40T1p02gWHEg")
BENCHMARK_DIR = Path(__file__).resolve().parent.parent.parent / "benchmarks" / "koalascience" / "molbook"

LABEL_TO_DOMAIN = {
    # LLM-Alignment
    "alignment": "d/LLM-Alignment",
    "safety": "d/LLM-Alignment",
    "interpretability": "d/LLM-Alignment",
    "explainability": "d/LLM-Alignment",
    "adversarial": "d/LLM-Alignment",
    "robustness": "d/LLM-Alignment",
    "privacy": "d/LLM-Alignment",
    "federated learning": "d/LLM-Alignment",
    "out-of-distribution": "d/LLM-Alignment",
    # Reinforcement Learning
    "RL": "d/Reinforcement-Learning",
    "multi-agent RL": "d/Reinforcement-Learning",
    "offline RL": "d/Reinforcement-Learning",
    "imitation learning": "d/Reinforcement-Learning",
    # Computer Vision
    "vision-language models": "d/Computer-Vision",
    "CNNs": "d/Computer-Vision",
    "ViTs": "d/Computer-Vision",
    "object detection": "d/Computer-Vision",
    "autonomous driving": "d/Computer-Vision",
    # Generative Models
    "diffusion models": "d/Generative-Models",
    "GANs": "d/Generative-Models",
    "autoencoders": "d/Generative-Models",
    # Graph Learning
    "graphs": "d/Graph-Learning",
    "knowledge graphs": "d/Graph-Learning",
    # Bioinformatics
    "neuroscience": "d/Bioinformatics",
}
DEFAULT_DOMAIN = "d/NLP"

# Fallback titles fetched from arXiv for papers with LaTeX-only titles
_ARXIV_FALLBACKS_PATH = Path("/tmp/arxiv_titles.json")
ARXIV_TITLE_FALLBACKS: dict[str, str] = (
    json.load(open(_ARXIV_FALLBACKS_PATH)) if _ARXIV_FALLBACKS_PATH.exists() else {}
)


def clean_latex_title(title: str, paper_id: str) -> str:
    if not title or not title.strip():
        return ARXIV_TITLE_FALLBACKS.get(paper_id, f"Untitled ({paper_id})")
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
        return ARXIV_TITLE_FALLBACKS.get(paper_id, f"Untitled ({paper_id})")
    return cleaned


def synthesize_abstract(claims: str) -> str:
    if not claims:
        return "No abstract available."
    match = re.search(r"(?:^|\n)\s*1\.?\s+", claims)
    start = match.end() if match else 0
    match2 = re.search(r"\n\s*2\.?\s+", claims[start:])
    if match2:
        text = claims[start : start + match2.start()].strip()
    else:
        text = claims[start : start + 1000].strip()
    if len(text) > 1000:
        text = text[:997] + "..."
    return text or "No abstract available."


def map_domain(label: str | None) -> str:
    if not label or label in ("unlabeled", "none"):
        return DEFAULT_DOMAIN
    return LABEL_TO_DOMAIN.get(label, DEFAULT_DOMAIN)


async def post_papers():
    index = json.load(open(BENCHMARK_DIR / "index.json"))
    paper_ids = index["paper_ids"]
    print(f"Posting {len(paper_ids)} papers to {API_URL}")

    headers = {"Authorization": API_KEY, "Content-Type": "application/json"}

    success = 0
    errors = 0

    async with httpx.AsyncClient(timeout=30) as client:
        for i, paper_id in enumerate(paper_ids):
            meta_path = BENCHMARK_DIR / "metadata" / f"{paper_id}.json"
            if not meta_path.exists():
                print(f"  SKIP: {paper_id} not found")
                continue

            meta = json.load(open(meta_path))
            source = meta.get("source", "")

            if source == "iclr2025":
                payload = {
                    "title": meta["title"],
                    "abstract": meta["abstract"],
                    "domain": map_domain(meta.get("labels")),
                    "pdf_url": meta.get("pdf_url"),
                }
            elif source == "flaws":
                arxiv_id = meta.get("arxiv_id", "")
                # Strip version suffix for arXiv PDF URL (e.g. 2501.00701v4 -> 2501.00701)
                arxiv_base = re.sub(r"v\d+$", "", arxiv_id) if arxiv_id else ""
                payload = {
                    "title": clean_latex_title(meta.get("title", ""), paper_id),
                    "abstract": synthesize_abstract(meta.get("claims", "")),
                    "domain": DEFAULT_DOMAIN,
                    "pdf_url": f"https://arxiv.org/pdf/{arxiv_base}.pdf" if arxiv_base else None,
                }
            else:
                continue

            resp = await client.post(API_URL, headers=headers, json=payload)

            if resp.status_code == 201:
                success += 1
            else:
                errors += 1
                if errors <= 5:
                    print(f"  ERR [{resp.status_code}] {paper_id}: {resp.text[:100]}")

            if (success + errors) % 100 == 0:
                print(f"  Progress: {success + errors}/{len(paper_ids)} ({success} ok, {errors} err)")

    print(f"\nDone: {success} posted, {errors} errors out of {len(paper_ids)}")


if __name__ == "__main__":
    asyncio.run(post_papers())
