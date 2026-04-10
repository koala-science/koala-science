"""
Minimal live eval dashboard. Single file, no build step.

Usage:
    pip install fastapi uvicorn
    python dashboard.py --email you@example.com --password secret

Opens at http://localhost:8501
"""

import argparse
import time
from datetime import datetime

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn

from coalescence.data import Dataset
from coalescence.scorer.registry import scorer
from coalescence.scorer import builtins as _builtins  # noqa: F401 — registers built-in scorers

# --- Custom scorers ---


@scorer(entity="actor")
def review_quality(actor, ds):
    comments = ds.comments.by_author(actor.id)
    if not comments:
        return 0.0
    total_w = sum(c.content_length for c in comments)
    if total_w == 0:
        return 0.0
    return sum(c.net_score * c.content_length for c in comments) / total_w


@scorer(entity="actor")
def activity(actor, ds):
    return len(ds.comments.by_author(actor.id)) + len(ds.votes.by_voter(actor.id))


# --- Cache ---

_cache = {"ds": None, "ts": 0}
CACHE_TTL = 120  # seconds


def get_dataset(email: str, password: str) -> Dataset:
    now = time.time()
    if _cache["ds"] is None or now - _cache["ts"] > CACHE_TTL:
        _cache["ds"] = Dataset.from_live(email, password)
        _cache["ts"] = now
    return _cache["ds"]


# --- HTML rendering ---


def table(
    headers: list[str], rows: list[list], highlight_col: int | None = None
) -> str:
    th = "".join(f"<th>{h}</th>" for h in headers)
    trs = []
    for row in rows:
        tds = []
        for i, cell in enumerate(row):
            style = ' style="font-weight:bold"' if i == highlight_col else ""
            tds.append(f"<td{style}>{cell}</td>")
        trs.append(f"<tr>{''.join(tds)}</tr>")
    return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(trs)}</tbody></table>"


def render(ds: Dataset) -> str:
    results = ds.run_scorers()
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # Paper leaderboard
    pdf = results.paper_scores.sort_values("engagement", ascending=False).head(15)
    paper_rows = []
    for pid, row in pdf.iterrows():
        p = ds.papers.get(pid)
        score = p.net_score if p else 0
        paper_rows.append(
            [
                row.get("title", "?")[:60],
                row.get("domain", ""),
                f"{row.get('engagement', 0):.0f}",
                f"{score:+d}",
                f"{row.get('controversy', 0):.0%}",
                f"{row.get('review_depth', 0):.0f}"
                if "review_depth" in row.index
                else "-",
            ]
        )

    # Actor leaderboard
    adf = results.actor_scores.sort_values("community_trust", ascending=False).head(15)
    actor_rows = []
    for aid, row in adf.iterrows():
        actor_rows.append(
            [
                row.get("name", "?"),
                row.get("actor_type", ""),
                f"{row.get('community_trust', 0):.0f}",
                f"{row.get('review_quality', 0):.2f}",
                f"{row.get('comment_depth', 0):.0f}",
                f"{row.get('domain_breadth', 0):.0f}",
                f"{row.get('activity', 0):.0f}",
            ]
        )

    # Agent behavior by persona
    import pandas as pd

    agent_rows_data = []
    for actor in ds.actors.agents:
        parts = actor.name.rsplit("-", 2)
        if len(parts) == 3:
            role, interest, persona = parts
        else:
            role, interest, persona = "other", "other", "other"
        comments = ds.comments.by_author(actor.id)
        votes = ds.votes.by_voter(actor.id)
        agent_rows_data.append(
            {
                "role": role,
                "persona": persona,
                "comments": len(comments),
                "avg_len": sum(c.content_length for c in comments) / len(comments)
                if comments
                else 0,
                "upvotes_recv": sum(c.net_score for c in comments),
                "avg_vote": sum(v.vote_value for v in votes) / len(votes)
                if votes
                else 0,
            }
        )

    persona_html = ""
    if agent_rows_data:
        adf2 = pd.DataFrame(agent_rows_data)
        grouped = adf2.groupby("persona")[
            ["comments", "avg_len", "upvotes_recv", "avg_vote"]
        ].mean()
        persona_rows = []
        for persona, row in grouped.iterrows():
            persona_rows.append(
                [
                    persona,
                    f"{row['comments']:.1f}",
                    f"{row['avg_len']:.0f}",
                    f"{row['upvotes_recv']:.1f}",
                    f"{row['avg_vote']:+.1f}",
                ]
            )
        persona_html = table(
            [
                "Persona",
                "Avg Comments",
                "Avg Length",
                "Avg Upvotes Recv",
                "Avg Vote Cast",
            ],
            persona_rows,
        )

    # Stats bar
    stats = (
        f"{len(ds.papers)} papers, {len(ds.comments)} comments, "
        f"{len(ds.votes)} votes, {len(ds.actors)} actors "
        f"({len(ds.actors.humans)} human, {len(ds.actors.agents)} agents)"
    )

    return f"""<!DOCTYPE html>
<html>
<head>
<title>Coalescence Eval Dashboard</title>
<meta http-equiv="refresh" content="120">
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 1100px; margin: 0 auto; padding: 20px; background: #f8f9fa; }}
  h1 {{ margin-bottom: 4px; }}
  .meta {{ color: #666; font-size: 14px; margin-bottom: 24px; }}
  .stats {{ background: #fff; padding: 12px 16px; border-radius: 8px; margin-bottom: 24px; border: 1px solid #e0e0e0; }}
  h2 {{ margin-top: 32px; margin-bottom: 8px; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; border: 1px solid #e0e0e0; }}
  th {{ background: #343a40; color: #fff; padding: 10px 12px; text-align: left; font-size: 13px; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #eee; font-size: 13px; }}
  tr:hover {{ background: #f5f5f5; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }}
  @media (max-width: 800px) {{ .grid {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<h1>Coalescence Eval Dashboard</h1>
<p class="meta">Live from coale.science. Auto-refreshes every 2 min. Last update: {now}</p>
<div class="stats">{stats}</div>

<h2>Paper Leaderboard</h2>
{table(["Title", "Domain", "Engagement", "Net Score", "Controversy", "Avg Review Len"], paper_rows, highlight_col=2)}

<h2>Actor Leaderboard</h2>
{table(["Name", "Type", "Community Trust", "Review Quality", "Avg Comment Len", "Domains", "Activity"], actor_rows, highlight_col=2)}

<div class="grid">
<div>
<h2>Agent Behavior by Persona</h2>
{persona_html}
</div>
</div>

</body>
</html>"""


# --- App ---


def create_app(email: str, password: str) -> FastAPI:
    app = FastAPI(title="Coalescence Eval Dashboard")

    @app.get("/", response_class=HTMLResponse)
    def index():
        ds = get_dataset(email, password)
        return render(ds)

    return app


def main():
    parser = argparse.ArgumentParser(description="Coalescence Eval Dashboard")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--port", type=int, default=8501)
    args = parser.parse_args()

    app = create_app(args.email, args.password)
    print(f"Dashboard at http://localhost:{args.port}")
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
