"""ReviewerToo per-persona avg score, split by ICML 2026 acceptance.

For each koala-science reviewed paper with ≥3 verdicts that also has
a ReviewerToo pipeline (~349 of them), parse the 1-5 numeric score
from each persona's ``monolithic_review.json``, average across
personas, and plot the distribution split by ICML 2026 acceptance.

Run from the analysis/ directory:
    .venv/bin/python plots/reviewertoo_score_by_acceptance.py
"""
import json
import os
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg
from scipy import stats

DB = "postgresql:///coalescence_snapshot"
RT_BASE = Path("/Users/tom/personal/reviewertoo-koala/agents/ReviewerToo")
ICML_FILE = Path(__file__).parent.parent / "data" / "icml_2026_accepted.jsonl"
OUT = Path(__file__).parent.parent / "output" / "reviewertoo_score_by_acceptance.png"

SCORE_RE = re.compile(r"^\s*(\d+)")


def norm(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# 1. Reviewed papers with ≥3 verdicts
with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT p.id::text, p.title
        FROM paper p WHERE p.status = 'reviewed'
          AND (SELECT COUNT(*) FROM verdict v WHERE v.paper_id = p.id) >= 3
    """)
    papers = {pid: title for pid, title in cur.fetchall()}
print(f"reviewed papers with ≥3 verdicts: {len(papers)}")

# 2. ICML 2026 accepted-title set
accepted_titles = set()
with ICML_FILE.open() as f:
    for line in f:
        accepted_titles.add(norm(json.loads(line)["title"]))

# 3. Per-paper avg ReviewerToo score across personas
records = []
for pid, title in papers.items():
    revs_dir = RT_BASE / pid / "pipeline" / "reviews"
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
        except Exception:
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
        "accepted": norm(title) in accepted_titles,
    })

df = pd.DataFrame(records)
print(f"papers with ReviewerToo reviews: {len(df)}")

acc = df.loc[df.accepted, "avg_score"]
rej = df.loc[~df.accepted, "avg_score"]
print(f"  accepted: n={len(acc)}, mean={acc.mean():.3f}, median={acc.median():.3f}, std={acc.std():.3f}")
print(f"  rejected: n={len(rej)}, mean={rej.mean():.3f}, median={rej.median():.3f}, std={rej.std():.3f}")

t_stat, t_p = stats.ttest_ind(acc, rej, equal_var=False)
ks_stat, ks_p = stats.ks_2samp(acc, rej)
print(f"\nWelch t: t={t_stat:+.3f}, p={t_p:.2e}")
print(f"KS:      D={ks_stat:.3f}, p={ks_p:.2e}")

# 4. Plot
fig, ax = plt.subplots(figsize=(11, 6))
bins = np.linspace(df.avg_score.min() - 0.05, df.avg_score.max() + 0.05, 31)
ax.hist(rej, bins=bins, alpha=0.5, label=f"not in ICML 2026 (n={len(rej)})",
        color="steelblue", edgecolor="white", density=True)
ax.hist(acc, bins=bins, alpha=0.5, label=f"accepted at ICML 2026 (n={len(acc)})",
        color="crimson", edgecolor="white", density=True)
ax.axvline(rej.mean(), color="steelblue", linestyle="--", linewidth=1.2,
           label=f"reject mean = {rej.mean():.2f}")
ax.axvline(acc.mean(), color="crimson", linestyle="--", linewidth=1.2,
           label=f"accept mean = {acc.mean():.2f}")

stats_text = (
    f"Welch t: t={t_stat:+.2f}, p={t_p:.2e}\n"
    f"KS D = {ks_stat:.3f}, p={ks_p:.2e}"
)
ax.text(0.02, 0.97, stats_text, transform=ax.transAxes, va="top", ha="left",
        fontsize=10, family="monospace",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor="0.6", alpha=0.9))

ax.set_xlabel("ReviewerToo avg per-persona score (1–5)")
ax.set_ylabel("Density")
ax.set_title(f"ReviewerToo persona-avg score: ICML 2026 accepted vs not "
             f"(≥3 verdicts/paper, n={len(df)})")
ax.grid(alpha=0.3, axis="y")
ax.legend(loc="upper left")

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"\nsaved: {OUT}")
