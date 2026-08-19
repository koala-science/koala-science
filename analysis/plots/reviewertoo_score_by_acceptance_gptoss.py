"""ReviewerToo-gptoss per-persona avg score, split by ICML 2026 acceptance.

Same recipe as reviewertoo_score_by_acceptance.py, pointed at the gpt-oss
backend re-run instead: azure/gpt-oss-120b, 13 personas (11 original +
critical + permissive), 373 papers (vs the original run's ~349) since this
pass covers every paper the platform has, not a subset.

Directory shape differs from the original: <paper_id>/reviews/<persona>/
directly, no pipeline/ subfolder in between.

Run from the analysis/ directory:
    .venv/bin/python plots/reviewertoo_score_by_acceptance_gptoss.py
"""
import json
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg
from scipy import stats

DB = "postgresql:///coalescence_snapshot"
RT_BASE = Path("/Users/tom/personal/reviewertoo-koala/agents/ReviewerToo-gptoss")
MATCH_FILE = Path(__file__).parent.parent / "data" / "icml_2026_paper_openreview_match.jsonl"
OUT = Path(__file__).parent.parent / "output" / "reviewertoo_score_by_acceptance_gptoss.png"

SCORE_RE = re.compile(r"^\s*(\d+)")


# 1. Reviewed papers with ≥3 verdicts
with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT p.id::text, p.title
        FROM paper p WHERE p.status = 'reviewed'
          AND (SELECT COUNT(*) FROM verdict v WHERE v.paper_id = p.id) >= 3
    """)
    papers = {pid: title for pid, title in cur.fetchall()}
print(f"reviewed papers with ≥3 verdicts: {len(papers)}")

# 2. Acceptance from the OpenReview venue field (paper_id -> accepted)
accepted_by_pid = {}
with MATCH_FILE.open() as f:
    for line in f:
        rec = json.loads(line)
        accepted_by_pid[rec["paper_id"]] = rec["accepted"]

# 3. Per-paper avg ReviewerToo-gptoss score across personas
records = []
for pid, title in papers.items():
    revs_dir = RT_BASE / pid / "reviews"
    if not revs_dir.is_dir():
        continue
    scores = []
    for persona in revs_dir.iterdir():
        if not persona.is_dir():
            continue
        f = persona / "monolithic_review.json"
        if not f.exists():
            continue
        try:
            d = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        rec = d.get("recommendation")
        if not isinstance(rec, str):
            continue
        m = SCORE_RE.match(rec)
        if not m:
            continue
        scores.append(int(m.group(1)))
    if not scores:
        continue
    records.append({
        "paper_id": pid,
        "title": title,
        "n_personas": len(scores),
        "avg_score": sum(scores) / len(scores),
        "accepted": accepted_by_pid[pid],
    })

df = pd.DataFrame(records)
print(f"papers with ReviewerToo-gptoss reviews: {len(df)}")

acc = df.loc[df.accepted, "avg_score"]
rej = df.loc[~df.accepted, "avg_score"]
print(f"  accepted: n={len(acc)}, mean={acc.mean():.3f}, median={acc.median():.3f}, std={acc.std():.3f}")
print(f"  rejected: n={len(rej)}, mean={rej.mean():.3f}, median={rej.median():.3f}, std={rej.std():.3f}")

t_stat, t_p = stats.ttest_ind(acc, rej, equal_var=False)
print(f"  Welch t={t_stat:.3f}  p={t_p:.3e}")

fig, ax = plt.subplots(figsize=(9, 6))
bins = np.linspace(df.avg_score.min() - 0.1, df.avg_score.max() + 0.1, 17)
ax.hist(rej, bins=bins, alpha=0.5, color="steelblue", edgecolor="white",
        label=f"not accepted (n={len(rej)}), mean {rej.mean():.2f}")
ax.hist(acc, bins=bins, alpha=0.5, color="crimson", edgecolor="white",
        label=f"accepted (n={len(acc)}), mean {acc.mean():.2f}")
ax.axvline(rej.mean(), color="steelblue", linestyle="--", linewidth=1.2)
ax.axvline(acc.mean(), color="crimson", linestyle="--", linewidth=1.2)
ax.set_xlabel("ReviewerToo (gpt-oss) avg per-persona score (1–5)")
ax.set_ylabel("Number of papers")
ax.set_title(f"ReviewerToo (gpt-oss) persona-avg score: ICML 2026 accepted vs not "
             f"(n={len(df)}, Welch p={t_p:.1e})")
ax.grid(alpha=0.3, axis="y")
ax.legend(loc="upper left")

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"saved: {OUT}")
