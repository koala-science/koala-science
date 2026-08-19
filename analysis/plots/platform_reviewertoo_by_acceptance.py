"""Side-by-side: platform vs ReviewerToo score distributions by ICML acceptance.

Left panel  = koala-science per-agent-normalized avg score (>=3 verdicts).
Right panel = ReviewerToo per-persona avg score (>=3 verdicts + RT pipeline).
Both split by the OpenReview venue-based acceptance label, with Welch t / KS.

Run from the analysis/ directory:
    .venv/bin/python plots/platform_reviewertoo_by_acceptance.py
"""
import json
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from scipy import stats

DB = "postgresql:///coalescence_snapshot"
RT_BASE = Path("/Users/tom/personal/reviewertoo-koala/agents/ReviewerToo")
MATCH_FILE = Path(__file__).parent.parent / "data" / "icml_2026_paper_openreview_match.jsonl"
OUT = Path(__file__).parent.parent / "output" / "platform_reviewertoo_by_acceptance.png"
MIN_VERDICTS_TO_NORMALIZE = 5
MIN_VERDICTS_PER_PAPER = 3
SCORE_RE = re.compile(r"^\s*(\d+)")

accepted_by_pid = {}
with MATCH_FILE.open() as f:
    for line in f:
        rec = json.loads(line)
        accepted_by_pid[rec["paper_id"]] = rec["accepted"]

# --- Platform: per-agent-normalized avg score -----------------------------
with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT v.paper_id::text, v.author_id::text, v.score::float
        FROM verdict v JOIN paper p ON p.id = v.paper_id
        WHERE p.status = 'reviewed'
    """)
    df = pd.DataFrame(cur.fetchall(), columns=["paper_id", "agent_id", "score"])

df["score"] = 1.0 + df["score"] * 0.5
agent_stats = df.groupby("agent_id").score.agg(["mean", "std", "count"])

def adjust(row):
    s = agent_stats.loc[row.agent_id]
    if s["count"] <= MIN_VERDICTS_TO_NORMALIZE or not s["std"] or pd.isna(s["std"]):
        return row.score
    return (row.score - s["mean"]) / s["std"] * 1.0 + 3.0

df["adjusted"] = df.apply(adjust, axis=1)
plat = df.groupby("paper_id").agg(
    score=("adjusted", "mean"), n=("score", "size")).reset_index()
plat = plat[plat.n >= MIN_VERDICTS_PER_PAPER]
plat["accepted"] = plat.paper_id.map(accepted_by_pid)

# --- ReviewerToo: per-persona avg score -----------------------------------
with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT p.id::text FROM paper p WHERE p.status = 'reviewed'
          AND (SELECT COUNT(*) FROM verdict v WHERE v.paper_id = p.id) >= %s
    """, (MIN_VERDICTS_PER_PAPER,))
    ge3 = [r[0] for r in cur.fetchall()]

rt_rows = []
for pid in ge3:
    revs_dir = RT_BASE / pid / "pipeline" / "reviews"
    if not revs_dir.is_dir():
        continue
    scores = []
    for persona in revs_dir.iterdir():
        f = persona / "monolithic_review.json"
        if not f.exists():
            continue
        rec = json.loads(f.read_text()).get("recommendation")
        if not isinstance(rec, str):
            continue
        m = SCORE_RE.match(rec)
        if m:
            scores.append(int(m.group(1)))
    if scores:
        rt_rows.append({"paper_id": pid, "score": sum(scores) / len(scores),
                        "accepted": accepted_by_pid[pid]})
rt = pd.DataFrame(rt_rows)


def panel(ax, data, title, show_ylabel):
    acc = data.loc[data.accepted, "score"]
    rej = data.loc[~data.accepted, "score"]
    t_stat, t_p = stats.ttest_ind(acc, rej, equal_var=False)
    bins = np.linspace(data.score.min() - 0.1, data.score.max() + 0.1, 17)
    ax.hist(rej, bins=bins, alpha=0.5, color="steelblue", edgecolor="white")
    ax.hist(acc, bins=bins, alpha=0.5, color="crimson", edgecolor="white")
    ax.axvline(rej.mean(), color="steelblue", linestyle="--", linewidth=1.2)
    ax.axvline(acc.mean(), color="crimson", linestyle="--", linewidth=1.2)
    ax.set_title(title, fontsize=18)
    ax.set_xlabel("Score", fontsize=17)
    if show_ylabel:
        ax.set_ylabel("Number of papers", fontsize=17)
    ax.tick_params(labelsize=14)
    ax.grid(alpha=0.3, axis="y")

    handles = [
        Patch(facecolor="steelblue", alpha=0.5, edgecolor="white"),
        Patch(facecolor="crimson", alpha=0.5, edgecolor="white"),
        Line2D([], [], linestyle="none"),
    ]
    labels = [
        f"not accepted (n={len(rej)}), mean {rej.mean():.2f}",
        f"accepted (n={len(acc)}), mean {acc.mean():.2f}",
        f"Welch p = {t_p:.1e}",
    ]
    ax.legend(handles, labels, loc="upper left", bbox_to_anchor=(0.03, 0.97),
              prop=dict(family="monospace", size=15), fancybox=True,
              edgecolor="0.6", facecolor="white", framealpha=0.9, borderpad=0.6)


fig, axes = plt.subplots(1, 2, figsize=(15, 5), sharey=True)
panel(axes[0], plat, "KoalaScience", show_ylabel=True)
panel(axes[1], rt, "ReviewerToo", show_ylabel=False)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"platform papers: {len(plat)} | reviewertoo papers: {len(rt)}")
print(f"saved: {OUT}")
