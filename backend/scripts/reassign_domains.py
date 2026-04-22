"""
Reassign papers from d/NLP to appropriate domains using LLM classification.

Usage:
    cd backend

    # Dry run — classify papers and write reassignments.json (no changes applied):
    ANTHROPIC_API_KEY=sk-... python -m scripts.reassign_domains

    # Apply reassignments from the JSON file:
    ANTHROPIC_API_KEY=sk-... python -m scripts.reassign_domains --apply

    # Target production:
    API_URL=https://koala.science/api/v1 API_KEY=... ANTHROPIC_API_KEY=sk-... python -m scripts.reassign_domains
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

API_URL = os.environ.get("API_URL", "http://localhost:8000/api/v1")
API_KEY = os.environ.get("API_KEY", "cs_pRBMOvof5APP8q4jhVodEJfSdLs4sgl40T1p02gWHEg")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

OUTPUT_PATH = Path(__file__).resolve().parent / "reassignments.json"

BATCH_SIZE = 20

DOMAINS = {
    "d/NLP": "Natural language processing, text understanding, generation, multilingual models, and large language models (LLMs)",
    "d/LLM-Alignment": "Aligning LLMs with human values: safety, interpretability, explainability, adversarial robustness, privacy, fairness, and federated learning",
    "d/Reinforcement-Learning": "Reinforcement learning, multi-agent RL, offline RL, policy optimization, reward modeling, and sequential decision making",
    "d/Computer-Vision": "Computer vision, image recognition, object detection, segmentation, visual transformers, vision-language models, and autonomous driving",
    "d/Generative-Models": "Generative modeling: diffusion models, GANs, VAEs, flow matching, score matching, and image/video generation",
    "d/Graph-Learning": "Graph neural networks, knowledge graphs, graph representation learning, node/link/graph classification, and topological deep learning",
    "d/Bioinformatics": "Computational biology, genomics, protein structure prediction, neuroscience, and biological data analysis",
    "d/MaterialScience": "Computational and experimental materials science, crystal structure prediction, and materials informatics",
    "d/QuantumComputing": "Quantum algorithms, error correction, quantum machine learning, and quantum hardware",
}

NEW_DOMAINS = {
    "d/Reinforcement-Learning": "Reinforcement learning, multi-agent RL, offline RL, policy optimization, reward modeling, and sequential decision making",
    "d/Computer-Vision": "Computer vision, image recognition, object detection, segmentation, visual transformers, vision-language models, and autonomous driving",
    "d/Generative-Models": "Generative modeling: diffusion models, GANs, VAEs, flow matching, score matching, and image/video generation",
    "d/Graph-Learning": "Graph neural networks, knowledge graphs, graph representation learning, node/link/graph classification, and topological deep learning",
}

CLASSIFICATION_PROMPT = """You are classifying machine learning research papers into domains.

Available domains:
{domains}

For each paper below, pick the SINGLE most appropriate domain. If a paper is genuinely about NLP or large language models, keep it in d/NLP. Only reassign papers that clearly belong in another domain.

Papers:
{papers}

Return ONLY a JSON array. Each element must have "id" (the paper id) and "domain" (one of the domain names above). No explanation, no markdown fences — just the JSON array."""


def format_domains() -> str:
    return "\n".join(f"- {name}: {desc}" for name, desc in DOMAINS.items())


def format_papers(batch: list[dict]) -> str:
    lines = []
    for p in batch:
        abstract = (p.get("abstract") or "")[:400]
        lines.append(f'- id: {p["id"]}\n  title: {p["title"]}\n  abstract: {abstract}')
    return "\n".join(lines)


async def classify_batch(client: httpx.AsyncClient, batch: list[dict]) -> list[dict]:
    """Send a batch of papers to Claude for classification."""
    prompt = CLASSIFICATION_PROMPT.format(
        domains=format_domains(),
        papers=format_papers(batch),
    )

    resp = await client.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )

    if resp.status_code != 200:
        print(f"  Anthropic API error [{resp.status_code}]: {resp.text[:200]}")
        return []

    body = resp.json()
    text = body["content"][0]["text"].strip()

    # Strip markdown fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[: text.rfind("```")]
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        print(f"  Failed to parse classification response: {text[:200]}")
        return []


async def fetch_all_papers(client: httpx.AsyncClient) -> list[dict]:
    """Fetch all papers from the API, paginating."""
    papers = []
    skip = 0
    limit = 100
    while True:
        resp = await client.get(
            f"{API_URL}/papers/",
            params={"skip": skip, "limit": limit},
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"  Fetch error [{resp.status_code}]: {resp.text[:200]}")
            break
        batch = resp.json()
        if not batch:
            break
        papers.extend(batch)
        skip += len(batch)
        print(f"  Fetched {len(papers)} papers...")
    return papers


async def create_new_domains(client: httpx.AsyncClient):
    """Create the new domains, skipping any that already exist."""
    headers = {"Authorization": API_KEY, "Content-Type": "application/json"}
    for name, description in NEW_DOMAINS.items():
        resp = await client.post(
            f"{API_URL}/domains/",
            headers=headers,
            json={"name": name, "description": description},
            timeout=15,
        )
        if resp.status_code == 201:
            print(f"  Created domain: {name}")
        elif resp.status_code == 409:
            print(f"  Domain already exists: {name}")
        else:
            print(f"  Failed to create {name} [{resp.status_code}]: {resp.text[:100]}")


async def apply_reassignments(client: httpx.AsyncClient, reassignments: list[dict]):
    """PATCH papers with their new domain assignments."""
    headers = {"Authorization": API_KEY, "Content-Type": "application/json"}
    success = 0
    errors = 0
    for r in reassignments:
        if r["new_domain"] == "d/NLP":
            continue  # No change needed
        resp = await client.patch(
            f"{API_URL}/papers/{r['id']}",
            headers=headers,
            json={"domain": r["new_domain"]},
            timeout=15,
        )
        if resp.status_code == 200:
            success += 1
        else:
            errors += 1
            if errors <= 5:
                print(f"  PATCH error [{resp.status_code}] {r['id']}: {resp.text[:100]}")
        if (success + errors) % 50 == 0:
            print(f"  Progress: {success + errors}/{len(reassignments)} ({success} ok, {errors} err)")
    print(f"  Applied: {success} updated, {errors} errors")


async def run_classify():
    """Classify all d/NLP-only papers and write reassignments.json."""
    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY environment variable is required")
        sys.exit(1)

    async with httpx.AsyncClient() as client:
        # Step 1: Create new domains
        print("Creating new domains...")
        await create_new_domains(client)

        # Step 2: Fetch all papers
        print("\nFetching all papers...")
        all_papers = await fetch_all_papers(client)
        print(f"Total papers: {len(all_papers)}")

        # Step 3: Filter to papers only in d/NLP
        nlp_only = [p for p in all_papers if p.get("domains") == ["d/NLP"]]
        print(f"Papers in d/NLP only: {len(nlp_only)}")

        if not nlp_only:
            print("No papers to reassign.")
            return

        # Step 4: Classify in batches
        print(f"\nClassifying {len(nlp_only)} papers in batches of {BATCH_SIZE}...")
        reassignments = []

        for i in range(0, len(nlp_only), BATCH_SIZE):
            batch = nlp_only[i : i + BATCH_SIZE]
            batch_num = i // BATCH_SIZE + 1
            total_batches = (len(nlp_only) + BATCH_SIZE - 1) // BATCH_SIZE
            print(f"  Batch {batch_num}/{total_batches} ({len(batch)} papers)...")

            results = await classify_batch(client, batch)

            # Build a lookup for quick matching
            result_map = {r["id"]: r["domain"] for r in results}
            for p in batch:
                new_domain = result_map.get(p["id"], "d/NLP")
                # Validate domain
                if new_domain not in DOMAINS:
                    new_domain = "d/NLP"
                reassignments.append({
                    "id": p["id"],
                    "title": p["title"],
                    "old_domain": "d/NLP",
                    "new_domain": new_domain,
                })

        # Step 5: Write results
        OUTPUT_PATH.write_text(json.dumps(reassignments, indent=2))
        print(f"\nWrote {len(reassignments)} reassignments to {OUTPUT_PATH}")

        # Summary
        from collections import Counter
        counts = Counter(r["new_domain"] for r in reassignments)
        print("\nClassification summary:")
        for domain, count in sorted(counts.items(), key=lambda x: -x[1]):
            print(f"  {domain}: {count}")

        moved = sum(1 for r in reassignments if r["new_domain"] != "d/NLP")
        print(f"\nTotal to move out of d/NLP: {moved}")
        print("Run with --apply to update papers on the platform.")


async def run_apply():
    """Read reassignments.json and apply the changes."""
    if not OUTPUT_PATH.exists():
        print(f"ERROR: {OUTPUT_PATH} not found. Run without --apply first to classify.")
        sys.exit(1)

    reassignments = json.loads(OUTPUT_PATH.read_text())
    to_move = [r for r in reassignments if r["new_domain"] != "d/NLP"]
    print(f"Applying {len(to_move)} domain changes...")

    async with httpx.AsyncClient() as client:
        # Ensure domains exist
        print("Ensuring new domains exist...")
        await create_new_domains(client)

        print("\nUpdating papers...")
        await apply_reassignments(client, to_move)


if __name__ == "__main__":
    if "--apply" in sys.argv:
        asyncio.run(run_apply())
    else:
        asyncio.run(run_classify())
