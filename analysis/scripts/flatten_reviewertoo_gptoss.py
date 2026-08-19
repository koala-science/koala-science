"""Flatten ReviewerToo-gptoss's per-paper/per-persona monolithic_review.json
files into one JSONL, matching the shape of data/reviewertoo_monolithic_reviews.jsonl
(one row per (paper_id, persona), same field names) so
scripts/reviewertoo_decompose.py can consume either source unchanged.

Pure local file I/O, no API calls, no cost. Re-running just overwrites the
output file -- nothing here needs resumability.

Run from the analysis/ directory:
    .venv/bin/python scripts/flatten_reviewertoo_gptoss.py
"""
import json
from pathlib import Path

from tqdm import tqdm

RT_BASE = Path("/Users/tom/personal/reviewertoo-koala/agents/ReviewerToo-gptoss")
OUT = Path(__file__).parent.parent / "data" / "reviewertoo_gptoss_monolithic_reviews.jsonl"

FIELDS = ("summary_of_contributions", "claims_and_evidence", "relation_to_prior_work",
          "strengths", "weaknesses", "questions_for_authors", "broader_impact_concerns")

paper_dirs = sorted(p for p in RT_BASE.iterdir() if p.is_dir())
rows = []
skipped = 0
for paper_dir in tqdm(paper_dirs, desc="papers", unit="paper"):
    revs_dir = paper_dir / "reviews"
    if not revs_dir.is_dir():
        skipped += 1
        continue
    for persona_dir in revs_dir.iterdir():
        f = persona_dir / "monolithic_review.json"
        if not f.exists():
            continue
        try:
            d = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        row = {"paper_id": paper_dir.name, "persona": persona_dir.name}
        row.update({k: d.get(k) for k in FIELDS})
        rows.append(row)

with OUT.open("w") as f:
    for row in rows:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

print(f"papers scanned: {len(paper_dirs)}  (missing reviews/ dir: {skipped})")
print(f"rows written: {len(rows)}")
print(f"saved: {OUT}")
