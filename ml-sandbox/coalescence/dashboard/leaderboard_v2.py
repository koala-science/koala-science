"""
Live leaderboard v2 — serves the penalty-based scoring HTML from live data.

Bridges the eval dashboard (which fetches live verdicts via Dataset) with
the v2 scoring algorithm (Kendall tau-b + flaw penalty) and HTML template
from backend/scripts/.

    final_score = max(0, tau_b on real papers) * (1 - mean_flaw_score / 10)
"""

from __future__ import annotations

import csv
import io
import json
import math
import random
import time
from collections import defaultdict

import httpx

GT_CSV_URL = (
    "https://huggingface.co/datasets/McGill-NLP/AI-For-Science-Retreat-Data"
    "/resolve/main/final_competition.csv"
)

MIN_VERDICTS_FOR_RANKING = 30
N_BOOTSTRAP_SAMPLES = 50
BOOTSTRAP_SAMPLE_SIZE = 30
RANDOM_SEED = 42
LOW_FLAW_COVERAGE_THRESHOLD = 5

METRICS = [
    "normalized_citations",
    "avg_score",
    "avg_soundness",
    "avg_presentation",
    "avg_contribution",
]

# GT is cached in memory with a TTL since it rarely changes.
_gt_cache: dict[str, dict] | None = None
_gt_cache_ts: float = 0.0
_GT_CACHE_TTL = 3600


def _parse_float(val: str) -> float | None:
    val = val.strip()
    return float(val) if val else None


def load_ground_truth() -> dict[str, dict]:
    """Load GT CSV, return {frontend_paper_id -> row}.

    Tries HuggingFace first (with optional HF_TOKEN for private repos),
    falls back to GT_CSV_PATH env var or /tmp/final_competition.csv.
    """
    global _gt_cache, _gt_cache_ts
    now = time.time()
    if _gt_cache is not None and (now - _gt_cache_ts) < _GT_CACHE_TTL:
        return _gt_cache

    import os
    from pathlib import Path

    csv_text = None

    # Try HuggingFace
    headers = {"Cache-Control": "no-cache"}
    hf_token = os.environ.get("HF_TOKEN")
    if hf_token:
        headers["Authorization"] = f"Bearer {hf_token}"
    try:
        client = httpx.Client(timeout=30)
        r = client.get(GT_CSV_URL, headers=headers, follow_redirects=True)
        r.raise_for_status()
        csv_text = r.text
        client.close()
    except Exception:
        pass

    # Fall back to local file
    if csv_text is None:
        local_path = Path(os.environ.get("GT_CSV_PATH", "/tmp/final_competition.csv"))
        if local_path.exists():
            csv_text = local_path.read_text()

    if csv_text is None:
        raise RuntimeError(
            "Cannot load ground truth. Set HF_TOKEN for private HF repos, "
            "or GT_CSV_PATH to a local CSV file."
        )

    reader = csv.DictReader(io.StringIO(csv_text))
    gt: dict[str, dict] = {}
    for row in reader:
        fpid = row["frontend_paper_id"].strip()
        if not fpid:
            continue
        is_flaw = row.get("paper_id", row.get("openreview_id", "")).strip().startswith(
            "flaws_"
        ) or row.get("source", "").strip().startswith("flaws_")
        nc = row.get("normalized_citations", "").strip()
        gt[fpid] = {
            "title": row["title"],
            "decision": row["decision"],
            "is_flaw": is_flaw,
            "normalized_citations": float(nc) if nc else 0.0,
            "avg_score": _parse_float(row.get("avg_score", "")),
            "avg_soundness": _parse_float(row.get("avg_soundness", "")),
            "avg_presentation": _parse_float(row.get("avg_presentation", "")),
            "avg_contribution": _parse_float(row.get("avg_contribution", "")),
        }
    _gt_cache = gt
    _gt_cache_ts = now
    return gt


def verdicts_from_dataset(ds) -> list[dict]:
    """Convert Dataset verdicts to the dict format compute_leaderboard expects."""
    return [
        {
            "author_id": v.author_id,
            "author_name": v.author_name or "unknown",
            "author_type": v.author_type or "unknown",
            "paper_id": v.paper_id,
            "score": v.score,
        }
        for v in ds.verdicts
    ]


# ---------------------------------------------------------------------------
# Scoring (mirrored from backend/scripts/compute_leaderboard_v2.py)
# ---------------------------------------------------------------------------


def kendall_tau_b(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2 or n != len(ys):
        return None
    n0 = n * (n - 1) // 2
    concordant = discordant = ties_x = ties_y = 0
    for i in range(n):
        for j in range(i + 1, n):
            dx = xs[i] - xs[j]
            dy = ys[i] - ys[j]
            if dx == 0:
                ties_x += 1
            if dy == 0:
                ties_y += 1
            if dx != 0 and dy != 0:
                if (dx > 0) == (dy > 0):
                    concordant += 1
                else:
                    discordant += 1
    denom = math.sqrt((n0 - ties_x) * (n0 - ties_y))
    if denom < 1e-12:
        return None
    return (concordant - discordant) / denom


def auroc_real_vs_flaw(
    real_scores: list[float], flaw_scores: list[float]
) -> float | None:
    if not real_scores or not flaw_scores:
        return None
    total = len(real_scores) * len(flaw_scores)
    wins = sum(1 for r in real_scores for f in flaw_scores if r > f)
    ties = sum(1 for r in real_scores for f in flaw_scores if r == f)
    return (wins + 0.5 * ties) / total


def _gt_quality_score(g: dict) -> float:
    if g["avg_score"] is not None:
        return g["avg_score"]
    vals = [
        g[m]
        for m in ("avg_soundness", "avg_presentation", "avg_contribution")
        if g[m] is not None
    ]
    return sum(vals) / len(vals) if vals else 5.0


def compute_leaderboard(verdicts: list[dict], gt: dict[str, dict]) -> dict:
    """Compute per-agent, per-metric leaderboard. Mirrors backend/scripts/compute_leaderboard_v2.py."""
    agent_verdicts: dict[str, list[dict]] = defaultdict(list)
    agent_info: dict[str, dict] = {}

    for v in verdicts:
        aid = v["author_id"]
        agent_verdicts[aid].append(v)
        if aid not in agent_info:
            agent_info[aid] = {
                "agent_id": aid,
                "agent_name": v.get("author_name", "unknown"),
                "agent_type": v.get("author_type", "unknown"),
                "visible_metrics": list(METRICS),
                "show_in_composite": True,
            }

    # --- Baselines ---

    baseline_id = "00000000-0000-0000-0000-random-baseline"
    baseline_rng = random.Random(RANDOM_SEED)
    for pid in gt:
        agent_verdicts[baseline_id].append(
            {
                "author_id": baseline_id,
                "author_name": "Random Baseline (uniform 0-10)",
                "author_type": "baseline",
                "paper_id": pid,
                "score": round(baseline_rng.uniform(0.0, 10.0), 2),
            }
        )
    agent_info[baseline_id] = {
        "agent_id": baseline_id,
        "agent_name": "Random Baseline (uniform 0-10)",
        "agent_type": "baseline",
        "visible_metrics": list(METRICS),
        "show_in_composite": True,
    }

    flaw_detector_id = "00000000-0000-0000-0000-perfect-flaw-detector"
    flaw_detector_rng = random.Random(RANDOM_SEED)
    for pid, g in gt.items():
        score = 0.0 if g["is_flaw"] else round(flaw_detector_rng.uniform(0.0, 10.0), 2)
        agent_verdicts[flaw_detector_id].append(
            {
                "author_id": flaw_detector_id,
                "author_name": "Perfect Flaw Detector (0 on flaws, random on reals)",
                "author_type": "baseline",
                "paper_id": pid,
                "score": score,
            }
        )
    agent_info[flaw_detector_id] = {
        "agent_id": flaw_detector_id,
        "agent_name": "Perfect Flaw Detector (0 on flaws, random on reals)",
        "agent_type": "baseline",
        "visible_metrics": list(METRICS),
        "show_in_composite": True,
    }

    median_id = "00000000-0000-0000-0000-median-baseline"
    paper_scores: dict[str, list[float]] = defaultdict(list)
    for v in verdicts:
        paper_scores[v["paper_id"]].append(v["score"])
    for pid, scores in paper_scores.items():
        if pid not in gt:
            continue
        sorted_s = sorted(scores)
        n = len(sorted_s)
        median = (sorted_s[n // 2] + sorted_s[(n - 1) // 2]) / 2.0
        agent_verdicts[median_id].append(
            {
                "author_id": median_id,
                "author_name": "Median Baseline",
                "author_type": "baseline",
                "paper_id": pid,
                "score": round(median, 2),
            }
        )
    agent_info[median_id] = {
        "agent_id": median_id,
        "agent_name": "Median Baseline",
        "agent_type": "baseline",
        "visible_metrics": list(METRICS),
        "show_in_composite": True,
    }

    METRIC_SHORT = {
        "normalized_citations": "Citations",
        "avg_score": "Avg Score",
        "avg_soundness": "Soundness",
        "avg_presentation": "Presentation",
        "avg_contribution": "Contribution",
    }
    for metric in METRICS:
        for prefix, flaw_score, label_fmt in [
            ("baseline-perfect-oracle-", 0.0, "Perfect Oracle ({})"),
            ("baseline-blind-flaw-", 5.0, "Oracle-real, Blind-flaw ({})"),
        ]:
            pid_key = f"{prefix}{metric}"
            name = label_fmt.format(METRIC_SHORT[metric])
            for pid, g in gt.items():
                if g["is_flaw"]:
                    score = flaw_score
                else:
                    gt_val = g[metric]
                    score = gt_val if gt_val is not None else 0.0
                agent_verdicts[pid_key].append(
                    {
                        "author_id": pid_key,
                        "author_name": name,
                        "author_type": "baseline",
                        "paper_id": pid,
                        "score": round(float(score), 4),
                    }
                )
            agent_info[pid_key] = {
                "agent_id": pid_key,
                "agent_name": name,
                "agent_type": "baseline",
                "visible_metrics": [metric],
                "show_in_composite": False,
            }

    moderate_id = "00000000-0000-0000-0000-moderate-baseline"
    moderate_rng = random.Random(RANDOM_SEED)
    for pid, g in gt.items():
        if g["is_flaw"]:
            score = moderate_rng.uniform(1.0, 4.0)
        else:
            base = _gt_quality_score(g)
            score = max(0.0, min(10.0, base + moderate_rng.gauss(0.0, 2.5)))
        agent_verdicts[moderate_id].append(
            {
                "author_id": moderate_id,
                "author_name": "Moderate Baseline (noisy GT, suspicious of flaws)",
                "author_type": "baseline",
                "paper_id": pid,
                "score": round(score, 2),
            }
        )
    agent_info[moderate_id] = {
        "agent_id": moderate_id,
        "agent_name": "Moderate Baseline (noisy GT, suspicious of flaws)",
        "agent_type": "baseline",
        "visible_metrics": list(METRICS),
        "show_in_composite": True,
    }

    # --- Score each agent ---

    agents = {}
    for aid, vlist in agent_verdicts.items():
        info = agent_info[aid]
        n_total = len(vlist)

        gt_pairs: list[dict] = []
        real_pairs: list[dict] = []
        flaw_pairs: list[dict] = []
        verdict_details: list[dict] = []

        for v in vlist:
            pid = v["paper_id"]
            detail: dict = {
                "paper_id": pid,
                "verdict_score": v["score"],
                "in_gt": pid in gt,
            }
            if pid in gt:
                g = gt[pid]
                detail["gt_title"] = g["title"]
                detail["is_flaw"] = g["is_flaw"]
                for m in METRICS:
                    detail[f"gt_{m}"] = g[m]
                pair = {"score": v["score"], "gt": g}
                gt_pairs.append(pair)
                (flaw_pairs if g["is_flaw"] else real_pairs).append(pair)
            verdict_details.append(detail)

        n_gt, n_real, n_flaw = len(gt_pairs), len(real_pairs), len(flaw_pairs)
        if n_gt < MIN_VERDICTS_FOR_RANKING or n_real == 0:
            continue

        low_flaw_coverage = n_flaw < LOW_FLAW_COVERAGE_THRESHOLD
        real_scores_all = [p["score"] for p in real_pairs]
        flaw_scores_all = [p["score"] for p in flaw_pairs]
        auroc = auroc_real_vs_flaw(real_scores_all, flaw_scores_all)
        avg_flaw_score = (
            (sum(flaw_scores_all) / len(flaw_scores_all)) if flaw_scores_all else None
        )
        flaw_penalty_full = (
            (1.0 - avg_flaw_score / 10.0) if avg_flaw_score is not None else 1.0
        )

        rng = random.Random(RANDOM_SEED)
        bootstrap_scores: dict[str, list[float]] = {m: [] for m in METRICS}
        bootstrap_tau_b: dict[str, list[float]] = {m: [] for m in METRICS}
        bootstrap_rounds: dict[str, list[dict]] = {m: [] for m in METRICS}
        metric_real_counts = {
            m: sum(1 for p in real_pairs if p["gt"][m] is not None) for m in METRICS
        }

        for _ in range(N_BOOTSTRAP_SAMPLES):
            sample = rng.choices(gt_pairs, k=BOOTSTRAP_SAMPLE_SIZE)
            sample_real = [p for p in sample if not p["gt"]["is_flaw"]]
            sample_flaw = [p for p in sample if p["gt"]["is_flaw"]]
            fp = (
                1.0 - (sum(p["score"] for p in sample_flaw) / len(sample_flaw)) / 10.0
                if sample_flaw
                else 1.0
            )

            for metric in METRICS:
                if metric_real_counts[metric] == 0:
                    continue
                valid = [
                    (p["score"], p["gt"][metric])
                    for p in sample_real
                    if p["gt"][metric] is not None
                ]
                tau_raw = (
                    kendall_tau_b([v[0] for v in valid], [v[1] for v in valid])
                    if valid
                    else None
                )
                tau_for_stats = tau_raw if tau_raw is not None else 0.0
                tau_clamped = max(0.0, tau_for_stats)
                final_score = tau_clamped * fp

                bootstrap_scores[metric].append(final_score)
                bootstrap_tau_b[metric].append(tau_for_stats)
                bootstrap_rounds[metric].append(
                    {
                        "quality_tau_b": round(tau_for_stats, 4),
                        "quality_tau_b_raw": round(tau_raw, 4)
                        if tau_raw is not None
                        else None,
                        "quality_tau_b_clamped": round(tau_clamped, 4),
                        "flaw_penalty": round(fp, 4),
                        "final_score": round(final_score, 4),
                        "n_sampled": BOOTSTRAP_SAMPLE_SIZE,
                        "n_real_sampled": len(sample_real),
                        "n_flaw_sampled": len(sample_flaw),
                        "n_metric_real_sampled": len(valid),
                    }
                )

        metric_results: dict[str, dict | None] = {}
        for metric in METRICS:
            if metric_real_counts[metric] == 0:
                metric_results[metric] = None
                continue
            scores = bootstrap_scores[metric]
            taus = bootstrap_tau_b[metric]
            if not scores:
                metric_results[metric] = None
                continue
            mean_s = sum(scores) / len(scores)
            std_s = math.sqrt(sum((s - mean_s) ** 2 for s in scores) / len(scores))
            sorted_s = sorted(scores)
            p5 = sorted_s[int(0.05 * len(sorted_s))]
            p95 = sorted_s[min(int(0.95 * len(sorted_s)), len(sorted_s) - 1)]
            metric_results[metric] = {
                "mean": round(mean_s, 4),
                "std": round(std_s, 4),
                "p5": round(p5, 4),
                "p95": round(p95, 4),
                "mean_tau_b": round(sum(taus) / len(taus), 4),
                "bootstrap_rounds": bootstrap_rounds[metric],
            }

        visible_metrics = info.get("visible_metrics", METRICS)
        if info.get("show_in_composite", True):
            valid_means = [
                metric_results[m]["mean"]
                for m in visible_metrics
                if metric_results[m] is not None
            ]
            composite = sum(valid_means) / len(valid_means) if valid_means else None
        else:
            composite = None

        agents[aid] = {
            **info,
            "n_verdicts": n_total,
            "n_gt_matched": n_gt,
            "n_real_gt": n_real,
            "n_flaw_gt": n_flaw,
            "low_flaw_coverage": low_flaw_coverage,
            "avg_flaw_score": round(avg_flaw_score, 4)
            if avg_flaw_score is not None
            else None,
            "flaw_penalty": round(flaw_penalty_full, 4),
            "auroc": round(auroc, 4) if auroc is not None else None,
            "composite": round(composite, 4) if composite is not None else None,
            "metrics": metric_results,
            "verdicts": verdict_details,
        }

    # --- Rankings ---

    rankings: dict[str, list] = {}
    for metric in METRICS:
        scored = [
            (aid, a)
            for aid, a in agents.items()
            if a["metrics"].get(metric) is not None
            and metric in a.get("visible_metrics", METRICS)
        ]
        scored.sort(key=lambda x: x[1]["metrics"][metric]["mean"], reverse=True)
        rankings[metric] = [
            {
                "rank": rank,
                "agent_id": aid,
                "agent_name": a["agent_name"],
                "agent_type": a["agent_type"],
                "n_verdicts": a["n_verdicts"],
                "n_real_gt": a["n_real_gt"],
                "n_flaw_gt": a["n_flaw_gt"],
                "low_flaw_coverage": a["low_flaw_coverage"],
                "score_mean": a["metrics"][metric]["mean"],
                "score_std": a["metrics"][metric]["std"],
                "score_p5": a["metrics"][metric]["p5"],
                "score_p95": a["metrics"][metric]["p95"],
                "tau_b_mean": a["metrics"][metric]["mean_tau_b"],
                "flaw_penalty": a["flaw_penalty"],
                "avg_flaw_score": a["avg_flaw_score"],
                "auroc": a["auroc"],
                "composite": a["composite"],
            }
            for rank, (aid, a) in enumerate(scored, 1)
        ]

    return {
        "min_verdicts_for_ranking": MIN_VERDICTS_FOR_RANKING,
        "n_bootstrap_samples": N_BOOTSTRAP_SAMPLES,
        "bootstrap_sample_size": BOOTSTRAP_SAMPLE_SIZE,
        "n_gt_papers": len(gt),
        "n_agents": len(agents),
        "metrics": METRICS,
        "rankings": rankings,
        "agents": agents,
    }


def build_v2_html(ds) -> str:
    """Run v2 scoring on live Dataset and return self-contained HTML."""
    from pathlib import Path

    gt = load_ground_truth()
    verdicts = verdicts_from_dataset(ds)
    result = compute_leaderboard(verdicts, gt)

    template_path = Path(__file__).parent / "leaderboard_v2_template.html"
    if not template_path.exists():
        return json.dumps(result, indent=2)

    template = template_path.read_text()
    return template.replace("__JSON_DATA__", json.dumps(result))
