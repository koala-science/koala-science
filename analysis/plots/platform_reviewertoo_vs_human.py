"""Side-by-side: KoalaScience and ReviewerToo scores vs mean human ICML score.

Left  = platform per-agent-normalized avg score vs mean human review score.
Right = ReviewerToo per-persona avg score vs mean human review score.
Human score = mean reviewer overall_recommendation per paper.

Run from the analysis/ directory:
    .venv/bin/python plots/platform_reviewertoo_vs_human.py
"""
import json
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg
from matplotlib.lines import Line2D
from scipy import stats

DB = "postgresql:///coalescence_snapshot"
RT_BASE = Path("/Users/tom/personal/reviewertoo-koala/agents/ReviewerToo")
CONV_FILE = Path(__file__).parent.parent / "data" / "icml_2026_openreview_conversations.jsonl"
OUT = Path(__file__).parent.parent / "output" / "platform_reviewertoo_vs_human.png"
MIN_VERDICTS_TO_NORMALIZE = 5
MIN_VERDICTS_PER_PAPER = 3
SCORE_RE = re.compile(r"^\s*(\d+)")

# 1. Mean human ICML review score per paper
human = {}
for line in CONV_FILE.open():
    c = json.loads(line)
    recs = [r["overall_recommendation_int"] for r in c["reviews"]
            if r["overall_recommendation_int"] is not None]
    if recs:
        human[c["paper_id"]] = sum(recs) / len(recs)

# 2. Platform per-agent-normalized avg score
with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT v.paper_id::text, v.author_id::text, v.score::float
        FROM verdict v JOIN paper p ON p.id = v.paper_id
        WHERE p.status = 'reviewed'
    """)
    df = pd.DataFrame(cur.fetchall(), columns=["pid", "agent", "score"])
df["score"] = 1.0 + df["score"] * 0.5
ag = df.groupby("agent").score.agg(["mean", "std", "count"])

def adjust(r):
    s = ag.loc[r.agent]
    if s["count"] <= MIN_VERDICTS_TO_NORMALIZE or not s["std"] or pd.isna(s["std"]):
        return r.score
    return (r.score - s["mean"]) / s["std"] + 3.0

df["adj"] = df.apply(adjust, axis=1)
plat_df = df.groupby("pid").agg(score=("adj", "mean"), n=("score", "size"))
platform = plat_df[plat_df.n >= MIN_VERDICTS_PER_PAPER]["score"].to_dict()

# 3. ReviewerToo per-persona avg score
rt = {}
for pid in human:
    revs = RT_BASE / pid / "pipeline" / "reviews"
    if not revs.is_dir():
        continue
    scores = []
    for persona in revs.iterdir():
        f = persona / "monolithic_review.json"
        if not f.exists():
            continue
        rec = json.loads(f.read_text()).get("recommendation")
        if isinstance(rec, str):
            m = SCORE_RE.match(rec)
            if m:
                scores.append(int(m.group(1)))
    if scores:
        rt[pid] = sum(scores) / len(scores)


def panel(ax, score_by_pid, color, title, show_ylabel):
    pids = sorted(set(score_by_pid) & set(human))
    x = np.array([score_by_pid[p] for p in pids], dtype=float)
    y = np.array([human[p] for p in pids], dtype=float)
    pear_r, pear_p = stats.pearsonr(x, y)
    spear_r, _ = stats.spearmanr(x, y)

    ax.scatter(x, y, s=34, alpha=0.6, color=color, edgecolor="white", linewidth=0.5)
    slope, intercept = np.polyfit(x, y, 1)
    xs = np.linspace(x.min(), x.max(), 100)
    ax.plot(xs, slope * xs + intercept, color="crimson", linewidth=1.8)

    handles = [Line2D([], [], linestyle="none")] * 3
    labels = [f"Pearson r = {pear_r:+.2f} (p={pear_p:.1e})",
              f"Spearman r = {spear_r:+.2f}",
              f"n = {len(pids)}"]
    ax.legend(handles, labels, loc="upper left", bbox_to_anchor=(0.03, 0.97),
              handlelength=0, handletextpad=0,
              prop=dict(family="monospace", size=14), fancybox=True,
              edgecolor="0.6", facecolor="white", framealpha=0.9, borderpad=0.6)
    ax.set_title(title, fontsize=18)
    ax.set_xlabel("Score", fontsize=17)
    if show_ylabel:
        ax.set_ylabel("ICML score", fontsize=17)
    ax.tick_params(labelsize=14)
    ax.grid(alpha=0.3)


fig, axes = plt.subplots(1, 2, figsize=(15, 4), sharey=True)
panel(axes[0], platform, "steelblue", "KoalaScience", show_ylabel=True)
panel(axes[1], rt, "seagreen", "ReviewerToo", show_ylabel=False)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"platform joined: {len(set(platform) & set(human))} | "
      f"reviewertoo joined: {len(set(rt) & set(human))}")
print(f"saved: {OUT}")
