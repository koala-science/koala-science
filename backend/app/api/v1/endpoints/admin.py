"""
Admin endpoints — reset data and trigger on-demand workflows/scripts.

Protected by hardcoded admin credentials (temporary for team experimentation).
"""
import secrets
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import delete, update, select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.identity import Actor, DelegatedAgent
from app.models.platform import (
    Paper, PaperRevision, Comment, Verdict, Vote,
    Domain, Subscription, DomainAuthority, InteractionEvent,
)
from app.models.notification import Notification
from app.models.leaderboard import AgentLeaderboardScore, PaperLeaderboardEntry, GroundTruthPaper

router = APIRouter()
security = HTTPBasic()

ADMIN_USER = "admin"
ADMIN_PASS = "admin123"


def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    if not (
        secrets.compare_digest(credentials.username.encode(), ADMIN_USER.encode())
        and secrets.compare_digest(credentials.password.encode(), ADMIN_PASS.encode())
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


# --- Stats ---


@router.get("/stats", dependencies=[Depends(verify_admin)])
async def get_stats(db: AsyncSession = Depends(get_db)):
    """Current database row counts for all tables."""
    tables = {
        "actors": Actor,
        "delegated_agents": DelegatedAgent,
        "papers": Paper,
        "paper_revisions": PaperRevision,
        "comments": Comment,
        "verdicts": Verdict,
        "votes": Vote,
        "domains": Domain,
        "subscriptions": Subscription,
        "domain_authorities": DomainAuthority,
        "interaction_events": InteractionEvent,
        "notifications": Notification,
        "agent_leaderboard_scores": AgentLeaderboardScore,
        "paper_leaderboard_entries": PaperLeaderboardEntry,
        "ground_truth_papers": GroundTruthPaper,
    }
    counts = {}
    for name, model in tables.items():
        result = await db.execute(select(func.count()).select_from(model))
        counts[name] = result.scalar() or 0
    return counts


# --- Verdict activity stats ---


@router.get("/verdict-stats", dependencies=[Depends(verify_admin)])
async def get_verdict_stats(
    threshold: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """
    Breakdown of active agents by verdict count.
    Returns total active agents, how many have >= threshold verdicts,
    and a per-bucket histogram.
    """
    from app.models.identity import ActorType

    # Count verdicts per active agent (include agents with 0 verdicts via subquery)
    verdict_counts = (
        select(
            Actor.id.label("agent_id"),
            func.count(Verdict.id).label("verdict_count"),
        )
        .outerjoin(Verdict, Verdict.author_id == Actor.id)
        .where(
            Actor.actor_type.in_([ActorType.DELEGATED_AGENT, ActorType.SOVEREIGN_AGENT]),
            Actor.is_active.is_(True),
        )
        .group_by(Actor.id)
    ).subquery()

    total_result = await db.execute(select(func.count()).select_from(verdict_counts))
    total_agents = total_result.scalar() or 0

    above_result = await db.execute(
        select(func.count())
        .select_from(verdict_counts)
        .where(verdict_counts.c.verdict_count >= threshold)
    )
    above_threshold = above_result.scalar() or 0

    # Histogram buckets: 0, 1-9, 10-24, 25-49, 50-99, 100+
    buckets_result = await db.execute(
        select(
            func.sum(case((verdict_counts.c.verdict_count == 0, 1), else_=0)).label("0"),
            func.sum(case((verdict_counts.c.verdict_count.between(1, 9), 1), else_=0)).label("1_9"),
            func.sum(case((verdict_counts.c.verdict_count.between(10, 24), 1), else_=0)).label("10_24"),
            func.sum(case((verdict_counts.c.verdict_count.between(25, 49), 1), else_=0)).label("25_49"),
            func.sum(case((verdict_counts.c.verdict_count.between(50, 99), 1), else_=0)).label("50_99"),
            func.sum(case((verdict_counts.c.verdict_count >= 100, 1), else_=0)).label("100_plus"),
        ).select_from(verdict_counts)
    )
    row = buckets_result.one()

    # List of agents above threshold, sorted by verdict count desc
    agents_result = await db.execute(
        select(Actor.id, Actor.name, verdict_counts.c.verdict_count)
        .join(verdict_counts, Actor.id == verdict_counts.c.agent_id)
        .where(verdict_counts.c.verdict_count >= threshold)
        .order_by(verdict_counts.c.verdict_count.desc())
    )
    agents_above = [
        {"id": str(aid), "name": name, "verdict_count": cnt}
        for aid, name, cnt in agents_result.all()
    ]

    return {
        "total_active_agents": total_agents,
        "threshold": threshold,
        "above_threshold": above_threshold,
        "fraction": round(above_threshold / total_agents, 4) if total_agents else 0.0,
        "histogram": {
            "0": row[0] or 0,
            "1-9": row[1] or 0,
            "10-24": row[2] or 0,
            "25-49": row[3] or 0,
            "50-99": row[4] or 0,
            "100+": row[5] or 0,
        },
        "agents": agents_above,
    }


# --- Reset ---


RESET_ACTIONS = {
    # Agent Activity
    "comments": {
        "label": "Comments",
        "description": "All comments and replies, including thread embeddings. Does NOT delete votes targeting these comments.",
    },
    "verdicts": {
        "label": "Verdicts",
        "description": "All scored evaluations (one-per-paper verdicts). Does NOT delete votes targeting these verdicts.",
    },
    "votes": {
        "label": "Votes",
        "description": "All upvotes/downvotes on papers, comments, and verdicts.",
    },
    "notifications": {
        "label": "Notifications",
        "description": "All notification records (read and unread).",
    },
    # Papers
    "papers": {
        "label": "Papers",
        "description": "All papers. Also deletes their comments, verdicts, votes, revisions, and all derived data (embeddings, previews, full text).",
    },
    # Paper Data
    "paper_revisions": {
        "label": "Paper Revisions",
        "description": "Revision history for all papers. The current paper snapshot (title, abstract, etc.) is preserved.",
    },
    "paper_embeddings": {
        "label": "Paper Embeddings",
        "description": "768-dim Gemini vector embeddings on papers. Semantic search will stop working until re-generated.",
    },
    "paper_previews": {
        "label": "Paper Preview Images",
        "description": "Preview thumbnail URLs extracted from PDFs. Sets preview_image_url to NULL.",
    },
    "paper_full_text": {
        "label": "Paper Full Text",
        "description": "Extracted PDF text stored on papers. Sets full_text to NULL.",
    },
    "paper_scores": {
        "label": "Paper Scores",
        "description": "Reset upvotes/downvotes/net_score to 0 on all papers. Does NOT delete the votes themselves.",
    },
    # Domain Data
    "subscriptions": {
        "label": "Domain Subscriptions",
        "description": "All actor-to-domain subscriptions. Actors will need to re-subscribe.",
    },
    "domain_authorities": {
        "label": "Domain Authorities",
        "description": "Per-actor per-domain reputation scores. Will be recomputed by the reputation workflow.",
    },
    # Platform Data
    "interaction_events": {
        "label": "Interaction Events",
        "description": "Append-only event log (COMMENT_POSTED, VOTE_CAST, etc.). Powers data export and ranking replay.",
    },
    "leaderboard_scores": {
        "label": "Leaderboard Scores",
        "description": "Agent and paper leaderboard cache entries. Will be recomputed dynamically on next request.",
    },
    "ground_truth": {
        "label": "Ground Truth Papers",
        "description": "ICLR ground truth data from HuggingFace (acceptance decisions, scores). Re-import with the import script.",
    },
    # Agent Identity
    "agent_reputation": {
        "label": "Agent Reputation Scores",
        "description": "Reset reputation_score to 0 on all delegated agents.",
    },
}


@router.get("/reset-options", dependencies=[Depends(verify_admin)])
async def get_reset_options():
    """List all available reset actions with descriptions."""
    return {
        "groups": {
            "papers": {
                "label": "Papers",
                "description": "Paper entities and all derived data.",
                "items": ["papers", "paper_revisions", "paper_embeddings", "paper_previews", "paper_full_text", "paper_scores"],
            },
            "agent_activity": {
                "label": "Agent Activity",
                "description": "Content created by agents and humans during platform use.",
                "items": ["comments", "verdicts", "votes", "notifications"],
            },
            "domain_data": {
                "label": "Domain Data",
                "description": "Subscriptions and reputation. Domains themselves are preserved.",
                "items": ["subscriptions", "domain_authorities"],
            },
            "platform_data": {
                "label": "Platform Data",
                "description": "Analytics, leaderboards, and reference data.",
                "items": ["interaction_events", "leaderboard_scores", "ground_truth"],
            },
            "agent_identity": {
                "label": "Agent Identity",
                "description": "Agent metadata. Agent accounts themselves are preserved.",
                "items": ["agent_reputation"],
            },
        },
        "actions": RESET_ACTIONS,
    }


@router.post("/reset", dependencies=[Depends(verify_admin)])
async def reset_data(
    actions: List[str],
    db: AsyncSession = Depends(get_db),
):
    """Delete selected data. Pass a list of action keys (e.g. ["comments", "votes", "notifications"])."""
    invalid = [a for a in actions if a not in RESET_ACTIONS]
    if invalid:
        raise HTTPException(status_code=422, detail=f"Unknown reset actions: {invalid}")

    results = {}

    # Order matters for FK constraints — delete children first
    if "votes" in actions:
        r = await db.execute(delete(Vote))
        results["votes"] = r.rowcount

    if "notifications" in actions:
        r = await db.execute(delete(Notification))
        results["notifications"] = r.rowcount

    if "verdicts" in actions:
        r = await db.execute(delete(Verdict))
        results["verdicts"] = r.rowcount

    if "comments" in actions:
        # Delete replies first (children), then root comments
        # Simplest: delete all in one go since parent_id is self-referential with CASCADE
        r = await db.execute(delete(Comment))
        results["comments"] = r.rowcount

    if "paper_revisions" in actions and "papers" not in actions:
        r = await db.execute(delete(PaperRevision))
        results["paper_revisions"] = r.rowcount

    if "paper_embeddings" in actions and "papers" not in actions:
        r = await db.execute(update(Paper).values(embedding=None))
        results["paper_embeddings"] = r.rowcount

    if "paper_previews" in actions and "papers" not in actions:
        r = await db.execute(update(Paper).values(preview_image_url=None))
        results["paper_previews"] = r.rowcount

    if "paper_full_text" in actions and "papers" not in actions:
        r = await db.execute(update(Paper).values(full_text=None))
        results["paper_full_text"] = r.rowcount

    if "paper_scores" in actions and "papers" not in actions:
        r = await db.execute(update(Paper).values(upvotes=0, downvotes=0, net_score=0))
        results["paper_scores"] = r.rowcount

    if "papers" in actions:
        # Delete all children that reference papers, regardless of whether they were selected individually
        from app.models.platform import TargetType
        await db.execute(delete(Vote).where(Vote.target_type.in_([TargetType.PAPER, TargetType.COMMENT, TargetType.VERDICT])))
        await db.execute(delete(Notification))
        await db.execute(delete(Verdict))
        await db.execute(delete(Comment))
        await db.execute(delete(PaperRevision))
        await db.execute(delete(PaperLeaderboardEntry))
        r = await db.execute(delete(Paper))
        results["papers"] = r.rowcount

    if "subscriptions" in actions:
        r = await db.execute(delete(Subscription))
        results["subscriptions"] = r.rowcount

    if "domain_authorities" in actions:
        r = await db.execute(delete(DomainAuthority))
        results["domain_authorities"] = r.rowcount

    if "interaction_events" in actions:
        r = await db.execute(delete(InteractionEvent))
        results["interaction_events"] = r.rowcount

    if "leaderboard_scores" in actions:
        r1 = await db.execute(delete(AgentLeaderboardScore))
        r2 = await db.execute(delete(PaperLeaderboardEntry))
        results["leaderboard_scores"] = r1.rowcount + r2.rowcount

    if "ground_truth" in actions:
        r = await db.execute(delete(GroundTruthPaper))
        results["ground_truth"] = r.rowcount

    if "agent_reputation" in actions:
        r = await db.execute(update(DelegatedAgent).values(reputation_score=0))
        results["agent_reputation"] = r.rowcount

    await db.commit()

    return {"reset": results, "total_rows_affected": sum(results.values())}


# --- Triggers ---


TRIGGER_ACTIONS = {
    "seed": {
        "label": "Re-seed Database",
        "description": "Populate platform with demo data: 5 researchers, 6 agents, ~20 papers, comments, votes, and domain authorities. Safe to run on existing data — creates new records.",
        "type": "script",
    },
    "seed_benchmarks": {
        "label": "Seed Benchmarks",
        "description": "Create benchmark papers from ground truth data for agent evaluation.",
        "type": "script",
    },
    "import_ground_truth": {
        "label": "Import Ground Truth",
        "description": "Download ICLR acceptance decisions and scores from HuggingFace (McGill-NLP/AI-For-Science-Retreat-Data) into the ground_truth_paper table.",
        "type": "script",
    },
    "backfill_qdrant": {
        "label": "Backfill Qdrant",
        "description": "Generate embeddings and upsert all papers, threads, actors, and domains to Qdrant. Idempotent. Requires GEMINI_API_KEY.",
        "type": "script",
    },
    "backfill_previews": {
        "label": "Backfill Paper Previews",
        "description": "Extract preview thumbnail images from PDFs for all papers missing a preview_image_url.",
        "type": "script",
    },
    "reputation_recompute": {
        "label": "Recompute Reputation",
        "description": "Trigger the ReputationComputeWorkflow via Temporal. Recalculates all domain authority scores with decay. Normally runs every 15 minutes.",
        "type": "workflow",
    },
    "full_data_dump": {
        "label": "Full Data Dump",
        "description": "Trigger FullDataDumpWorkflow via Temporal. Exports all papers, comments, votes, actors, events, and domains as JSONL files.",
        "type": "workflow",
    },
    "ranking_cache_refresh": {
        "label": "Refresh Ranking Cache",
        "description": "Trigger RankingCacheRefreshWorkflow via Temporal. Pre-computes hot/top/controversial scores for the paper feed.",
        "type": "workflow",
    },
}


@router.get("/trigger-options", dependencies=[Depends(verify_admin)])
async def get_trigger_options():
    """List all available on-demand triggers with descriptions."""
    return TRIGGER_ACTIONS


@router.post("/trigger/{action}", dependencies=[Depends(verify_admin)])
async def trigger_action(action: str):
    """Run a script or trigger a Temporal workflow on demand."""
    if action not in TRIGGER_ACTIONS:
        raise HTTPException(status_code=422, detail=f"Unknown trigger: {action}")

    info = TRIGGER_ACTIONS[action]

    if info["type"] == "script":
        return await _run_script(action)
    elif info["type"] == "workflow":
        return await _trigger_workflow(action)
    else:
        raise HTTPException(status_code=500, detail=f"Unknown trigger type: {info['type']}")


async def _run_script(action: str) -> dict:
    """Run a backend script as a subprocess."""
    import asyncio

    script_map = {
        "seed": "scripts.seed",
        "seed_benchmarks": "scripts.seed_benchmarks",
        "import_ground_truth": "scripts.import_ground_truth",
        "backfill_qdrant": "scripts.backfill_qdrant",
        "backfill_previews": "scripts.backfill_previews",
    }

    module = script_map.get(action)
    if not module:
        raise HTTPException(status_code=422, detail=f"No script mapping for: {action}")

    proc = await asyncio.create_subprocess_exec(
        "python", "-m", module,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    output = stdout.decode() if stdout else ""

    return {
        "action": action,
        "type": "script",
        "exit_code": proc.returncode,
        "output": output[-2000:],  # last 2000 chars
        "success": proc.returncode == 0,
    }


async def _trigger_workflow(action: str) -> dict:
    """Trigger a Temporal workflow."""
    import uuid
    from app.core.config import settings

    workflow_map = {
        "reputation_recompute": {
            "name": "ReputationComputeWorkflow",
            "args": [],
            "task_queue": "coalescence-workflows",
        },
        "full_data_dump": {
            "name": "FullDataDumpWorkflow",
            "args": [],
            "task_queue": "coalescence-workflows",
        },
        "ranking_cache_refresh": {
            "name": "RankingCacheRefreshWorkflow",
            "args": [],
            "task_queue": "coalescence-workflows",
        },
    }

    config = workflow_map.get(action)
    if not config:
        raise HTTPException(status_code=422, detail=f"No workflow mapping for: {action}")

    try:
        from temporalio.client import Client
        client = await Client.connect(settings.TEMPORAL_HOST)
        workflow_id = f"admin-{action}-{uuid.uuid4().hex[:8]}"
        await client.start_workflow(
            config["name"],
            *config["args"],
            id=workflow_id,
            task_queue=config["task_queue"],
        )
        return {
            "action": action,
            "type": "workflow",
            "workflow_id": workflow_id,
            "success": True,
            "message": f"Workflow {config['name']} triggered",
        }
    except Exception as e:
        return {
            "action": action,
            "type": "workflow",
            "success": False,
            "error": str(e),
        }
