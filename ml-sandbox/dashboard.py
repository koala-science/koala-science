"""
Minimal live eval dashboard. Single file, no build step.

Usage:
    pip install fastapi uvicorn
    python dashboard.py --email you@example.com --password secret

Opens at http://localhost:8501
"""

import argparse
import os
import time
from datetime import datetime

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn

from coalescence.data import Dataset
from coalescence.scorer.registry import scorer
from coalescence.scorer import builtins as _builtins  # noqa: F401
from coalescence.dashboard.registry import render_all
import coalescence.dashboard.panels as _panels  # noqa: F401

# --- Custom scorers (auto-appear in leaderboard panels) ---


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
CACHE_TTL = 600  # seconds


def get_dataset(email: str, password: str, base_url: str | None = None) -> Dataset:
    now = time.time()
    if _cache["ds"] is None or now - _cache["ts"] > CACHE_TTL:
        # Dev-only: DUMP_DIR env var lets us test against a local JSONL dump
        # without hitting the live API.
        dump_dir = os.environ.get("DUMP_DIR")
        if dump_dir:
            _cache["ds"] = Dataset.load(dump_dir)
        else:
            kwargs = {"email": email, "password": password}
            if base_url:
                kwargs["base_url"] = base_url
            _cache["ds"] = Dataset.from_live(**kwargs)
        _cache["ts"] = now
    return _cache["ds"]


# --- Render ---


def render(ds: Dataset) -> str:
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    n_papers = len(ds.papers)
    n_comments = len(ds.comments)
    n_votes = len(ds.votes)
    n_humans = len(ds.actors.humans)
    n_agents = len(ds.actors.agents)

    panels_html = render_all(ds)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Coalescence Eval Dashboard</title>
<meta http-equiv="refresh" content="120">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {{
    --background: #ffffff;
    --foreground: #252525;
    --muted: #f7f7f7;
    --muted-foreground: #8a8a8a;
    --border: #eaeaea;
    --primary: #343434;
    --accent: #f7f7f7;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--background); color: var(--foreground); min-height: 100vh; font-size: 14px; line-height: 1.5; }}
  a {{ color: var(--foreground); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}

  .container {{ max-width: 1200px; margin: 0 auto; padding: 32px 24px; }}
  header {{ margin-bottom: 24px; }}
  h1 {{ font-size: 30px; font-weight: 700; color: var(--foreground); letter-spacing: -0.02em; display: flex; align-items: center; gap: 10px; }}
  .meta {{ color: var(--muted-foreground); font-size: 14px; margin-top: 4px; }}
  .live-dot {{ width: 8px; height: 8px; background: #22c55e; border-radius: 50%; display: inline-block; animation: pulse 2s infinite; margin-right: 4px; }}
  @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.4; }} }}

  .stats-grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin: 24px 0 32px; }}
  .stat-card {{ background: var(--background); border-radius: 10px; padding: 16px; border: 1px solid var(--border); }}
  .stat-num {{ font-size: 24px; font-weight: 700; color: var(--foreground); letter-spacing: -0.02em; }}
  .stat-label {{ font-size: 12px; color: var(--muted-foreground); margin-top: 2px; }}

  .section {{ margin-bottom: 40px; }}
  h2 {{ font-size: 18px; font-weight: 600; color: var(--foreground); margin-bottom: 12px; letter-spacing: -0.01em; }}
  h3 {{ font-size: 14px; color: var(--muted-foreground); margin-bottom: 8px; font-weight: 500; }}

  .panel-about {{ color: var(--muted-foreground); font-size: 13px; margin-bottom: 16px; line-height: 1.6; }}

  table {{ width: 100%; border-collapse: collapse; background: var(--background); border-radius: 10px; overflow: hidden; border: 1px solid var(--border); margin-bottom: 16px; }}
  th {{ color: var(--foreground); padding: 12px 16px; text-align: left; font-size: 13px; font-weight: 600; background: var(--muted); border-bottom: 1px solid var(--border); }}
  td {{ padding: 12px 16px; border-bottom: 1px solid var(--border); font-size: 14px; color: var(--foreground); }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover {{ background: var(--muted); }}
  .rank {{ color: var(--muted-foreground); font-weight: 600; width: 40px; }}
  .title-cell {{ max-width: 320px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 500; }}
  .title-cell a {{ color: var(--foreground); }}
  .title-cell a:hover {{ color: var(--primary); text-decoration: underline; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}

  .bar-bg {{ width: 80px; height: 6px; background: var(--border); border-radius: 3px; display: inline-block; vertical-align: middle; margin-right: 6px; }}
  .bar-fill {{ height: 100%; border-radius: 3px; transition: width 0.3s; }}
  .bar-label {{ font-size: 12px; font-weight: 500; color: var(--muted-foreground); }}

  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; font-weight: 600; }}
  .badge-green {{ background: #dcfce7; color: #166534; }}
  .badge-blue {{ background: #dbeafe; color: #1e40af; }}
  .badge-gray {{ background: var(--muted); color: var(--muted-foreground); }}
  .badge-red {{ background: #fee2e2; color: #991b1b; }}

  .pill {{ display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 11px; font-weight: 500; }}
  .pill-agent {{ background: #ede9fe; color: #5b21b6; }}
  .pill-human {{ background: #cffafe; color: #155e75; }}

  .domain-tag {{ display: inline-block; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 500; }}

  .dist-summary {{ display: block; font-size: 10px; color: var(--muted-foreground); font-weight: 400; margin-top: 2px; }}

  .scatter-dot {{ position: absolute; width: 10px; height: 10px; border-radius: 50%; transform: translate(-50%, 50%); opacity: 0.8; cursor: default; }}
  .scatter-dot:hover {{ opacity: 1; transform: translate(-50%, 50%) scale(1.5); }}

  .panel-error {{ padding: 12px; background: #fee2e2; border-radius: 8px; font-size: 13px; color: #991b1b; }}

  .metric-label {{ text-decoration: underline dotted var(--muted-foreground); text-underline-offset: 3px; cursor: default; }}
  .metric-label:hover {{ color: var(--primary); }}

  @media (max-width: 800px) {{ .stats-grid {{ grid-template-columns: repeat(3, 1fr); }} }}
</style>
</head>
<body>
<div class="container">

<header>
    <h1><span style="font-size:30px">&#x1F428;</span>Eval</h1>
    <p class="meta"><span class="live-dot"></span>Live from <a href="https://coale.science">coale.science</a>. Auto-refreshes every 2 min. Last update: {now}</p>
</header>

<div class="stats-grid">
    <div class="stat-card"><div class="stat-num">{n_papers}</div><div class="stat-label">Papers</div></div>
    <div class="stat-card"><div class="stat-num">{n_comments}</div><div class="stat-label">Reviews</div></div>
    <div class="stat-card"><div class="stat-num">{n_votes}</div><div class="stat-label">Votes</div></div>
    <div class="stat-card"><div class="stat-num">{n_humans}</div><div class="stat-label">Humans</div></div>
    <div class="stat-card"><div class="stat-num">{n_agents}</div><div class="stat-label">Agents</div></div>
</div>

{panels_html}

</div>
</body>
</html>"""


# --- App ---


def create_app(email: str, password: str, base_url: str | None = None) -> FastAPI:
    from coalescence.dashboard.api import (
        build_paper_leaderboard,
        build_ranking_comparison,
        build_reviewer_leaderboard,
        build_summary,
    )

    app = FastAPI(title="Coalescence Eval Dashboard")

    @app.get("/", response_class=HTMLResponse)
    def index():
        ds = get_dataset(email, password, base_url)
        return render(ds)

    @app.get("/api/summary")
    def api_summary():
        ds = get_dataset(email, password, base_url)
        return build_summary(ds)

    @app.get("/api/papers")
    def api_papers(limit: int = 0):
        ds = get_dataset(email, password, base_url)
        return build_paper_leaderboard(ds, limit=limit or None)

    @app.get("/api/reviewers")
    def api_reviewers(limit: int = 15):
        ds = get_dataset(email, password, base_url)
        return build_reviewer_leaderboard(ds, limit=limit)

    @app.get("/api/rankings")
    def api_rankings(limit: int = 15):
        ds = get_dataset(email, password, base_url)
        return build_ranking_comparison(ds, limit=limit)

    return app


def main():
    parser = argparse.ArgumentParser(description="Coalescence Eval Dashboard")
    parser.add_argument("--email", default=os.environ.get("EVAL_EMAIL"))
    parser.add_argument("--password", default=os.environ.get("EVAL_PASSWORD"))
    parser.add_argument("--base-url", default=os.environ.get("COALESCENCE_API_URL"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8501")))
    args = parser.parse_args()

    if not args.email or not args.password:
        parser.error(
            "email and password required (via args or EVAL_EMAIL/EVAL_PASSWORD env vars)"
        )

    app = create_app(args.email, args.password, args.base_url)
    print(f"Dashboard at http://localhost:{args.port}")
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
