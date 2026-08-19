"""Slide version: top 5 agents on the final leaderboard (karma + AUROC points
+ human-correlation points) next to top 5 agents by verified+relevant
argument rate. Two independent rankings side by side, big fonts, for a
presentation rather than a paper figure.

Run from the analysis/ directory:
    .venv/bin/python plots/top5_leaderboards_slides.py
"""
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg

plt.rcParams["text.parse_math"] = False  # agent names like "$_$" are literal

DB = "postgresql:///coalescence_snapshot"
AUROC_LABELS = Path(__file__).parent.parent / "output" / "loo_auroc_paper_labels.csv"
HUMAN_LABELS = Path(__file__).parent.parent / "output" / "loo_correlation_human_labels.csv"
OUT = Path(__file__).parent.parent / "output" / "top5_leaderboards_slides.png"
POINTS = 5.0
SENT = "41eac833-6a6a-417e-9847-7834e887f34c"
VERIF = "05678219-d68a-46f3-88aa-35d5211306cf"
RELEV = "4fb20402-f264-4fae-815a-a9461564ee57"
REL = {"very_relevant", "somewhat_relevant"}
N_TOP = 5

# --- final leaderboard -------------------------------------------------
with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute("SELECT v.paper_id::text, v.author_id::text FROM verdict v")
    verdicts = cur.fetchall()
    cur.execute("SELECT ag.id::text, ag.karma, ac.name FROM agent ag JOIN actor ac ON ac.id = ag.id")
    agent_rows = cur.fetchall()

karma = {aid: k for aid, k, _ in agent_rows}
name_of = {aid: n for aid, _, n in agent_rows}
participants = defaultdict(set)
for pid, aid in verdicts:
    participants[pid].add(aid)


def points_from(csv):
    good = set(pd.read_csv(csv).query("label == 'good'").paper_id)
    pts = defaultdict(float)
    for pid in good:
        share = POINTS / len(participants[pid])
        for aid in participants[pid]:
            pts[aid] += share
    return pts


pa = points_from(AUROC_LABELS)
pb = points_from(HUMAN_LABELS)

agents = {aid for pids in participants.values() for aid in pids} & set(karma)
lb_rows = []
for aid in agents:
    base, ap, hp = karma[aid], pa.get(aid, 0.0), pb.get(aid, 0.0)
    lb_rows.append((name_of[aid], aid, base, ap, hp, base + ap + hp))
lb_rows.sort(key=lambda r: r[5], reverse=True)
lb_top = lb_rows[:N_TOP]

lb_name_counts = pd.Series([r[0] for r in lb_top]).value_counts()
lb_names = [r[0] if lb_name_counts[r[0]] == 1 else f"{r[0]} [{r[1][:4]}]" for r in lb_top]

# --- verified + relevant rate -------------------------------------------
with psycopg.connect(DB) as conn, conn.cursor() as cur:
    def load(q):
        cur.execute("""
            SELECT fact_id::text, annotator_id::text, response_value_json->>'value'
            FROM annotation_response
            WHERE question_id = %s AND submitted_at IS NOT NULL AND fact_id IS NOT NULL
        """, (q,))
        d = defaultdict(dict)
        for f, a, v in cur.fetchall():
            d[f][a] = v
        return d
    sent, verif, relev = load(SENT), load(VERIF), load(RELEV)
    vr_args = [f for f, ann in sent.items() if len(ann) == 2]
    cur.execute("""
        SELECT cf.id::text, ac.name
        FROM comment_fact cf JOIN comment c ON c.id = cf.comment_id
        JOIN actor ac ON ac.id = c.author_id
        WHERE cf.id = ANY(%s::uuid[])
    """, (vr_args,))
    agent_of = dict(cur.fetchall())


def is_vr(f):
    return (len(verif.get(f, {})) == 2 and set(verif[f].values()) == {"verified"}
            and len(relev.get(f, {})) == 2 and all(v in REL for v in relev[f].values()))


per = defaultdict(lambda: [0, 0])
for f in vr_args:
    ag = agent_of[f]
    per[ag][1] += 1
    if is_vr(f):
        per[ag][0] += 1

vr_ranked = sorted(((ag, n, tot) for ag, (n, tot) in per.items()),
                    key=lambda r: r[1] / r[2], reverse=True)
vr_top = vr_ranked[:N_TOP]
vr_overall = sum(n for _, n, _ in vr_ranked) / sum(t for _, _, t in vr_ranked)

# --- plot ----------------------------------------------------------------
fig, axes = plt.subplots(1, 2, figsize=(20, 8))

ax = axes[0]
names = lb_names[::-1]
base = np.array([r[2] for r in lb_top][::-1])
ap = np.array([r[3] for r in lb_top][::-1])
hp = np.array([r[4] for r in lb_top][::-1])
total = base + ap + hp
ypos = np.arange(len(lb_top))
ax.barh(ypos, base, color="#9ecae1", edgecolor="white", label="Karma")
ax.barh(ypos, ap, left=base, color="#4c78a8", edgecolor="white",
        label="ICML acceptance correlation")
ax.barh(ypos, hp, left=base + ap, color="seagreen", edgecolor="white",
        label="Review score correlation")
ax.set_yticks(ypos)
ax.set_yticklabels(names, fontsize=26)
for i, t in enumerate(total):
    ax.text(t + max(total) * 0.02, i, f"{t:.0f}", va="center", fontsize=26)
ax.set_title("Final leaderboard", fontsize=32, pad=70)
ax.set_xlim(0, max(total) * 1.18)
ax.legend(fontsize=16, loc="lower center", bbox_to_anchor=(0.5, 1.01),
          ncol=3, frameon=False, columnspacing=1.3, handletextpad=0.5)
ax.set_xticks([])
ax.tick_params(left=False)
for spine in ax.spines.values():
    spine.set_visible(False)

ax = axes[1]
names = [ag for ag, n, tot in vr_top][::-1]
pct = np.array([n / tot for ag, n, tot in vr_top][::-1])
ypos = np.arange(len(vr_top))
ax.barh(ypos, pct, color="#4c78a8", edgecolor="white")
ax.set_yticks(ypos)
ax.set_yticklabels(names, fontsize=26)
for i, p in enumerate(pct):
    ax.text(p + 0.012, i, f"{p:.0%}", va="center", fontsize=26)
ax.axvline(vr_overall, color="crimson", linestyle="--", linewidth=1.5,
           label=f"overall ({vr_overall:.0%})")
ax.set_title("Verified + relevant arguments", fontsize=32)
ax.set_xlim(0, max(pct) * 1.2)
ax.set_xticks([])
ax.legend(fontsize=18, loc="lower right", frameon=False)
ax.tick_params(left=False)
for spine in ax.spines.values():
    spine.set_visible(False)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150, bbox_inches="tight")
print("Final leaderboard top 5:")
for name, aid, b, a, h, t in lb_top:
    print(f"  {name[:24]:24s} total={t:6.1f}")
print("Verified+relevant top 5:")
for ag, n, tot in vr_top:
    print(f"  {ag[:24]:24s} {n/tot:.0%} (n={tot})")
print(f"saved: {OUT}")
