"""Test whether paper avg-score distributions are Gaussian.

Compares the raw paper-avg-score distribution with the per-agent
z-normalized version. Runs Shapiro-Wilk and D'Agostino-Pearson
tests, prints skew/kurtosis, and saves a side-by-side Q-Q plot.

Run from the analysis/ directory:
    .venv/bin/python plots/normality_test_paper_scores.py
"""
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg
from scipy import stats

DB = "postgresql:///coalescence_snapshot"
OUT = Path(__file__).parent.parent / "output" / "normality_test_paper_scores.png"
MIN_VERDICTS_TO_NORMALIZE = 5

QUERY = """
SELECT v.paper_id::text, v.author_id::text, v.score::float
FROM verdict v JOIN paper p ON p.id = v.paper_id
WHERE p.status = 'reviewed'
"""

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute(QUERY)
    df = pd.DataFrame(cur.fetchall(), columns=["paper_id", "agent_id", "score"])

raw_avg = df.groupby("paper_id").score.mean()
target_mean, target_std = raw_avg.mean(), raw_avg.std()

agent_stats = df.groupby("agent_id").score.agg(["mean", "std", "count"])

def adjust(row):
    s = agent_stats.loc[row.agent_id]
    if s["count"] <= MIN_VERDICTS_TO_NORMALIZE or not s["std"] or pd.isna(s["std"]):
        return row.score
    return (row.score - s["mean"]) / s["std"] * target_std + target_mean

df["adjusted"] = df.apply(adjust, axis=1)
adj_avg = df.groupby("paper_id").adjusted.mean()


def report(name: str, x: pd.Series) -> None:
    sw_stat, sw_p = stats.shapiro(x)
    da_stat, da_p = stats.normaltest(x)
    skew = stats.skew(x)
    kurt = stats.kurtosis(x)  # excess kurtosis (normal = 0)
    print(f"\n=== {name} ===")
    print(f"  n = {len(x)}, mean = {x.mean():.3f}, std = {x.std():.3f}")
    print(f"  skewness = {skew:+.3f}   (normal: 0)")
    print(f"  excess kurtosis = {kurt:+.3f}   (normal: 0)")
    print(f"  Shapiro-Wilk:    W = {sw_stat:.4f}, p = {sw_p:.2e}")
    print(f"  D'Agostino-K^2:  stat = {da_stat:.2f}, p = {da_p:.2e}")
    if sw_p < 0.05:
        print(f"  → reject normality at α=0.05 (Shapiro-Wilk p < 0.05)")
    else:
        print(f"  → cannot reject normality (Shapiro-Wilk p ≥ 0.05)")


report("RAW paper-avg distribution", raw_avg)
report("PER-AGENT NORMALIZED paper-avg distribution", adj_avg)

# Q-Q plots side by side
fig, axes = plt.subplots(1, 2, figsize=(13, 6))
for ax, data, title in [
    (axes[0], raw_avg, "Raw paper avg scores"),
    (axes[1], adj_avg, "Per-agent normalized paper avg scores"),
]:
    stats.probplot(data, dist="norm", plot=ax)
    sw_stat, sw_p = stats.shapiro(data)
    ax.set_title(f"{title}\nShapiro-Wilk W={sw_stat:.4f}, p={sw_p:.2e}")
    ax.grid(alpha=0.3)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"\nsaved: {OUT}")
