"""Per-agent-normalized avg paper score, split by ICML 2026 acceptance.

Among the 376 papers reviewed on koala-science, ~107 made it into
ICML 2026 (matched by title). Plot the per-agent-normalized
avg-score distribution for the two cohorts and run a t-test +
KS-test on the difference.

Run from the analysis/ directory:
    .venv/bin/python plots/normalized_score_by_acceptance.py
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
ICML_FILE = Path(__file__).parent.parent / "data" / "icml_2026_accepted.jsonl"
OUT = Path(__file__).parent.parent / "output" / "normalized_score_by_acceptance.png"
MIN_VERDICTS_TO_NORMALIZE = 5


def norm(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# 1. Pull verdicts on reviewed papers + paper titles
with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT v.paper_id::text, p.title, v.author_id::text, v.score::float
        FROM verdict v JOIN paper p ON p.id = v.paper_id
        WHERE p.status = 'reviewed'
    """)
    df = pd.DataFrame(cur.fetchall(), columns=["paper_id", "title", "agent_id", "score"])

print(f"verdicts on reviewed papers: {len(df)}")

# 2. Build accepted-title set from ICML 2026 list
accepted_titles = set()
with ICML_FILE.open() as f:
    for line in f:
        accepted_titles.add(norm(json.loads(line)["title"]))
print(f"ICML 2026 accepted titles: {len(accepted_titles)}")

# 3. Per-agent normalization, same as the prior plot
raw_avg = df.groupby("paper_id").score.mean()
target_mean, target_std = raw_avg.mean(), raw_avg.std()
agent_stats = df.groupby("agent_id").score.agg(["mean", "std", "count"])

def adjust(row):
    s = agent_stats.loc[row.agent_id]
    if s["count"] <= MIN_VERDICTS_TO_NORMALIZE or not s["std"] or pd.isna(s["std"]):
        return row.score
    return (row.score - s["mean"]) / s["std"] * target_std + target_mean

df["adjusted"] = df.apply(adjust, axis=1)

MIN_VERDICTS_PER_PAPER = 3

# 4. Per-paper normalized avg + verdict count + accepted flag
per_paper = df.groupby(["paper_id", "title"]).agg(
    adjusted=("adjusted", "mean"),
    n_verdicts=("score", "size"),
).reset_index()
per_paper["accepted"] = per_paper.title.apply(lambda t: norm(t) in accepted_titles)

before = len(per_paper)
per_paper = per_paper[per_paper.n_verdicts >= MIN_VERDICTS_PER_PAPER]
print(f"\nfiltered to ≥{MIN_VERDICTS_PER_PAPER} verdicts: {len(per_paper)} (dropped {before - len(per_paper)})")

n_accept = int(per_paper.accepted.sum())
n_reject = int((~per_paper.accepted).sum())
print(f"\nreviewed papers: {len(per_paper)}")
print(f"  accepted at ICML 2026:      {n_accept}")
print(f"  not in our ICML 2026 list:  {n_reject}")

acc = per_paper.loc[per_paper.accepted, "adjusted"]
rej = per_paper.loc[~per_paper.accepted, "adjusted"]
print(f"\nadjusted avg-score:")
print(f"  accepted: mean={acc.mean():.3f}, median={acc.median():.3f}, std={acc.std():.3f}")
print(f"  rejected: mean={rej.mean():.3f}, median={rej.median():.3f}, std={rej.std():.3f}")

t_stat, t_p = stats.ttest_ind(acc, rej, equal_var=False)
ks_stat, ks_p = stats.ks_2samp(acc, rej)
print(f"\nWelch t-test:  t={t_stat:+.3f}, p={t_p:.2e}")
print(f"KS 2-sample:   D={ks_stat:.3f}, p={ks_p:.2e}")

# 5. Plot
fig, ax = plt.subplots(figsize=(11, 6))
bins = np.linspace(per_paper.adjusted.min() - 0.1, per_paper.adjusted.max() + 0.1, 31)
ax.hist(rej, bins=bins, alpha=0.5, label=f"not in ICML 2026 (n={n_reject})",
        color="steelblue", edgecolor="white", density=True)
ax.hist(acc, bins=bins, alpha=0.5, label=f"accepted at ICML 2026 (n={n_accept})",
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

ax.set_xlabel("Per-agent-normalized average score")
ax.set_ylabel("Density")
ax.set_title(f"Normalized koala-science score: ICML 2026 accepted vs not "
             f"(≥{MIN_VERDICTS_PER_PAPER} verdicts/paper, n={len(per_paper)})")
ax.grid(alpha=0.3, axis="y")
ax.legend(loc="upper right")

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"\nsaved: {OUT}")
