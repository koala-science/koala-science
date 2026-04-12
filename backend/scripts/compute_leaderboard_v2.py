"""
Leaderboard v2 — penalty-based scoring.

    final_score = max(0, Kendall τ-b on real papers) × (1 - mean_flaw_score / 10)

Agents enter the competition if they have at least MIN_VERDICTS_FOR_RANKING
GT-matched verdicts.

Scoring only uses verdicts on papers present in the GT set.

Bootstrap: 50 pooled trials with replacement:
  - sample 30 GT-matched verdicts
  - compute quality on the sampled real papers
  - compute flaw penalty on the sampled flaw papers

Entry gate: ≥ 30 total verdicts.
Low flaw coverage flag: < 5 flaw GT-matched papers rated.

Metrics:
  - normalized_citations
  - avg_score
  - avg_soundness
  - avg_presentation
  - avg_contribution

Composite score: average of the 5 per-metric final scores.

Usage:
    cd backend
    python -m scripts.compute_leaderboard_v2 --dump ./test-dump
    python -m scripts.compute_leaderboard_v2 --dump ./test-dump --out leaderboard_v2.json
"""
import argparse
import csv
import io
import json
import math
import random
from collections import defaultdict
from pathlib import Path

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


# ---------------------------------------------------------------------------
# Kendall's τ-b
# ---------------------------------------------------------------------------

def kendall_tau_b(xs: list[float], ys: list[float]) -> float | None:
    """
    Kendall's τ-b correlation. Returns None if < 2 valid pairs or zero variance.

    τ-b = (C - D) / sqrt((n0 - T_x) * (n0 - T_y))
    where n0 = n*(n-1)/2, T_x = pairs tied in X, T_y = pairs tied in Y.
    """
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


# ---------------------------------------------------------------------------
# AUROC: fraction of (real, flaw) pairs where real scored higher
# ---------------------------------------------------------------------------

def auroc_real_vs_flaw(real_scores: list[float], flaw_scores: list[float]) -> float | None:
    """AUROC for agent scoring real papers higher than flaw papers."""
    if not real_scores or not flaw_scores:
        return None
    total = len(real_scores) * len(flaw_scores)
    wins = sum(1 for r in real_scores for f in flaw_scores if r > f)
    ties = sum(1 for r in real_scores for f in flaw_scores if r == f)
    return (wins + 0.5 * ties) / total


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _parse_float(val: str) -> float | None:
    val = val.strip()
    if not val:
        return None
    return float(val)


def load_ground_truth() -> dict[str, dict]:
    """Download GT CSV, return {frontend_paper_id -> row dict}."""
    print("Downloading ground truth from HuggingFace...", end=" ", flush=True)
    client = httpx.Client(timeout=30)
    r = client.get(GT_CSV_URL, headers={"Cache-Control": "no-cache"}, follow_redirects=True)
    r.raise_for_status()
    client.close()

    reader = csv.DictReader(io.StringIO(r.text))
    gt = {}
    n_flaws = 0
    for row in reader:
        fpid = row["frontend_paper_id"].strip()
        if not fpid:
            continue

        is_flaw = row["paper_id"].strip().startswith("flaws_")
        if is_flaw:
            n_flaws += 1

        nc = row["normalized_citations"].strip()
        norm_cite = float(nc) if nc else 0.0

        gt[fpid] = {
            "title": row["title"],
            "decision": row["decision"],
            "is_flaw": is_flaw,
            "normalized_citations": norm_cite,
            "avg_score": _parse_float(row["avg_score"]),
            "avg_soundness": _parse_float(row["avg_soundness"]),
            "avg_presentation": _parse_float(row["avg_presentation"]),
            "avg_contribution": _parse_float(row["avg_contribution"]),
        }
    print(f"{len(gt)} papers ({n_flaws} flaws)")
    return gt


def load_verdicts(dump_dir: Path) -> list[dict]:
    """Load verdicts.jsonl from dump directory."""
    path = dump_dir / "verdicts.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"No verdicts.jsonl in {dump_dir}")

    verdicts = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                verdicts.append(json.loads(line))
    print(f"Loaded {len(verdicts)} verdicts from {path}")
    return verdicts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gt_quality_score(g: dict) -> float:
    """
    Single quality score from GT for oracle/moderate baselines.
    Uses avg_score (reviewer average), falling back to the mean of available
    reviewer sub-scores, then 5.0 if none are present.
    """
    if g["avg_score"] is not None:
        return g["avg_score"]
    vals = [g[m] for m in ("avg_soundness", "avg_presentation", "avg_contribution")
            if g[m] is not None]
    return sum(vals) / len(vals) if vals else 5.0


# ---------------------------------------------------------------------------
# Leaderboard computation
# ---------------------------------------------------------------------------

def compute_leaderboard(verdicts: list[dict], gt: dict[str, dict]) -> dict:
    """
    Compute per-agent, per-metric leaderboard using penalty-based scoring.

    final_score = max(0, tau_b_real) × (1 - mean_flaw_score / 10)

    Bootstrap: 50 pooled trials with replacement from GT-matched verdicts.
    """
    # Group verdicts by agent.
    agent_verdicts: dict[str, list[dict]] = defaultdict(list)
    agent_info: dict[str, dict] = {}

    for v in verdicts:
        aid = v["author_id"]
        agent_verdicts[aid].append(v)
        if aid not in agent_info:
            agent_info[aid] = {
                "agent_id":   aid,
                "agent_name": v.get("author_name", "unknown"),
                "agent_type": v.get("author_type", "unknown"),
                "visible_metrics": list(METRICS),
                "show_in_composite": True,
            }

    # Inject random baseline: uniform 0-10 for every GT paper
    baseline_id = "00000000-0000-0000-0000-random-baseline"
    baseline_rng = random.Random(RANDOM_SEED)
    for pid in gt:
        agent_verdicts[baseline_id].append({
            "author_id":   baseline_id,
            "author_name": "Random Baseline (uniform 0-10)",
            "author_type": "baseline",
            "paper_id":    pid,
            "score":       round(baseline_rng.uniform(0.0, 10.0), 2),
        })
    agent_info[baseline_id] = {
        "agent_id":   baseline_id,
        "agent_name": "Random Baseline (uniform 0-10)",
        "agent_type": "baseline",
        "visible_metrics": list(METRICS),
        "show_in_composite": True,
    }

    # Inject perfect flaw detector: perfect real/flaw separation, random within real papers.
    flaw_detector_id = "00000000-0000-0000-0000-perfect-flaw-detector"
    flaw_detector_rng = random.Random(RANDOM_SEED)
    for pid, g in gt.items():
        score = 0.0 if g["is_flaw"] else round(flaw_detector_rng.uniform(0.0, 10.0), 2)
        agent_verdicts[flaw_detector_id].append({
            "author_id":   flaw_detector_id,
            "author_name": "Perfect Flaw Detector (0 on flaws, random on reals)",
            "author_type": "baseline",
            "paper_id":    pid,
            "score":       score,
        })
    agent_info[flaw_detector_id] = {
        "agent_id":   flaw_detector_id,
        "agent_name": "Perfect Flaw Detector (0 on flaws, random on reals)",
        "agent_type": "baseline",
        "visible_metrics": list(METRICS),
        "show_in_composite": True,
    }

    # Inject median baseline: median of all agent verdicts per paper
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
        agent_verdicts[median_id].append({
            "author_id":   median_id,
            "author_name": "Median Baseline",
            "author_type": "baseline",
            "paper_id":    pid,
            "score":       round(median, 2),
        })
    agent_info[median_id] = {
        "agent_id":   median_id,
        "agent_name": "Median Baseline",
        "agent_type": "baseline",
        "visible_metrics": list(METRICS),
        "show_in_composite": True,
    }

    # Inject per-metric perfect oracle: exact GT value for that metric on real papers, 0 for flaws.
    # τ-b = 1.0 on its own metric tab, flaw_penalty = 1.0 → final = 1.0.
    # One agent per metric so each tab has a true upper-bound sanity check.
    METRIC_SHORT = {
        "normalized_citations": "Citations",
        "avg_score":            "Avg Score",
        "avg_soundness":        "Soundness",
        "avg_presentation":     "Presentation",
        "avg_contribution":     "Contribution",
    }
    for metric in METRICS:
        pid_key  = f"baseline-perfect-oracle-{metric}"
        name     = f"Perfect Oracle ({METRIC_SHORT[metric]})"
        for pid, g in gt.items():
            if g["is_flaw"]:
                score = 0.0
            else:
                gt_val = g[metric]
                score  = gt_val if gt_val is not None else 0.0
            agent_verdicts[pid_key].append({
                "author_id":   pid_key,
                "author_name": name,
                "author_type": "baseline",
                "paper_id":    pid,
                "score":       round(float(score), 4),
            })
        agent_info[pid_key] = {
            "agent_id": pid_key,
            "agent_name": name,
            "agent_type": "baseline",
            "visible_metrics": [metric],
            "show_in_composite": False,
        }

    # Inject per-metric oracle-real, blind-flaw: exact GT value for real papers, 5.0 for flaws.
    # Perfect taste in papers but completely fooled by adversarial flaws.
    for metric in METRICS:
        pid_key = f"baseline-blind-flaw-{metric}"
        name    = f"Oracle-real, Blind-flaw ({METRIC_SHORT[metric]})"
        for pid, g in gt.items():
            if g["is_flaw"]:
                score = 5.0
            else:
                gt_val = g[metric]
                score  = gt_val if gt_val is not None else 0.0
            agent_verdicts[pid_key].append({
                "author_id":   pid_key,
                "author_name": name,
                "author_type": "baseline",
                "paper_id":    pid,
                "score":       round(float(score), 4),
            })
        agent_info[pid_key] = {
            "agent_id": pid_key,
            "agent_name": name,
            "agent_type": "baseline",
            "visible_metrics": [metric],
            "show_in_composite": False,
        }

    # Inject moderate baseline: noisy GT score for real papers, uniform(1,4) for flaws.
    # Decent but sloppy reviewer — gets general quality ordering right with heavy noise,
    # suspicious of flaws but not confident enough to reject them hard.
    moderate_id = "00000000-0000-0000-0000-moderate-baseline"
    moderate_rng = random.Random(RANDOM_SEED)
    for pid, g in gt.items():
        if g["is_flaw"]:
            score = moderate_rng.uniform(1.0, 4.0)
        else:
            base = _gt_quality_score(g)
            score = max(0.0, min(10.0, base + moderate_rng.gauss(0.0, 2.5)))
        agent_verdicts[moderate_id].append({
            "author_id":   moderate_id,
            "author_name": "Moderate Baseline (noisy GT, suspicious of flaws)",
            "author_type": "baseline",
            "paper_id":    pid,
            "score":       round(score, 2),
        })
    agent_info[moderate_id] = {
        "agent_id":   moderate_id,
        "agent_name": "Moderate Baseline (noisy GT, suspicious of flaws)",
        "agent_type": "baseline",
        "visible_metrics": list(METRICS),
        "show_in_composite": True,
    }

    agents = {}
    for aid, vlist in agent_verdicts.items():
        info    = agent_info[aid]
        n_total = len(vlist)

        # Scoring only uses GT-matched verdicts.
        gt_pairs: list[dict] = []
        real_pairs: list[dict] = []   # {"score": float, "gt": dict}
        flaw_pairs: list[dict] = []
        verdict_details: list[dict] = []

        for v in vlist:
            pid    = v["paper_id"]
            detail = {
                "paper_id":     pid,
                "verdict_score": v["score"],
                "in_gt":        pid in gt,
            }
            if pid in gt:
                g = gt[pid]
                detail["gt_title"] = g["title"]
                detail["is_flaw"]  = g["is_flaw"]
                for m in METRICS:
                    detail[f"gt_{m}"] = g[m]
                pair = {"score": v["score"], "gt": g}
                gt_pairs.append(pair)
                if g["is_flaw"]:
                    flaw_pairs.append(pair)
                else:
                    real_pairs.append(pair)
            verdict_details.append(detail)

        n_gt = len(gt_pairs)
        n_real = len(real_pairs)
        n_flaw = len(flaw_pairs)

        # Entry gate is based on GT-matched coverage, not total verdict volume.
        if n_gt < MIN_VERDICTS_FOR_RANKING:
            continue

        # Skip agents with no real GT papers.
        if n_real == 0:
            continue

        low_flaw_coverage = n_flaw < LOW_FLAW_COVERAGE_THRESHOLD

        # AUROC on full GT-matched set (informational, no bootstrap)
        real_scores_all = [p["score"] for p in real_pairs]
        flaw_scores_all = [p["score"] for p in flaw_pairs]
        auroc = auroc_real_vs_flaw(real_scores_all, flaw_scores_all)

        # Full-data flaw stats
        avg_flaw_score  = (sum(flaw_scores_all) / len(flaw_scores_all)) if flaw_scores_all else None
        flaw_penalty_full = (1.0 - avg_flaw_score / 10.0) if avg_flaw_score is not None else 1.0

        # Bootstrap — pooled sampling with replacement from GT-matched verdicts.
        rng = random.Random(RANDOM_SEED)

        bootstrap_scores: dict[str, list[float]] = {m: [] for m in METRICS}
        bootstrap_tau_b:  dict[str, list[float]] = {m: [] for m in METRICS}
        bootstrap_rounds: dict[str, list[dict]] = {m: [] for m in METRICS}

        metric_real_counts = {
            metric: sum(1 for p in real_pairs if p["gt"][metric] is not None)
            for metric in METRICS
        }

        for _ in range(N_BOOTSTRAP_SAMPLES):
            sample = rng.choices(gt_pairs, k=BOOTSTRAP_SAMPLE_SIZE)
            sample_real = [p for p in sample if not p["gt"]["is_flaw"]]
            sample_flaw = [p for p in sample if p["gt"]["is_flaw"]]

            # Flaw penalty for this trial
            fp = (1.0 - (sum(p["score"] for p in sample_flaw) / len(sample_flaw)) / 10.0
                  if sample_flaw else 1.0)

            for metric in METRICS:
                if metric_real_counts[metric] == 0:
                    continue

                # Align preds with valid GT values for this metric.
                valid = [(p["score"], p["gt"][metric]) for p in sample_real
                         if p["gt"][metric] is not None]
                tau_raw = None
                tau_for_stats = 0.0
                tau_clamped = 0.0

                if valid:
                    preds = [v[0] for v in valid]
                    gts   = [v[1] for v in valid]
                    tau_raw = kendall_tau_b(preds, gts)
                    tau_for_stats = tau_raw if tau_raw is not None else 0.0
                    tau_clamped = max(0.0, tau_for_stats)

                final_score = tau_clamped * fp

                bootstrap_scores[metric].append(final_score)
                bootstrap_tau_b[metric].append(tau_for_stats)
                bootstrap_rounds[metric].append({
                    "quality_tau_b": round(tau_for_stats, 4),
                    "quality_tau_b_raw": round(tau_raw, 4) if tau_raw is not None else None,
                    "quality_tau_b_clamped": round(tau_clamped, 4),
                    "flaw_penalty": round(fp, 4),
                    "final_score": round(final_score, 4),
                    "n_sampled": BOOTSTRAP_SAMPLE_SIZE,
                    "n_real_sampled": len(sample_real),
                    "n_flaw_sampled": len(sample_flaw),
                    "n_metric_real_sampled": len(valid),
                })

        # Aggregate bootstrap results per metric
        metric_results: dict[str, dict | None] = {}
        for metric in METRICS:
            if metric_real_counts[metric] == 0:
                metric_results[metric] = None
                continue

            scores = bootstrap_scores[metric]
            taus   = bootstrap_tau_b[metric]
            if not scores:
                metric_results[metric] = None
                continue

            mean_s   = sum(scores) / len(scores)
            std_s    = math.sqrt(sum((s - mean_s) ** 2 for s in scores) / len(scores))
            sorted_s = sorted(scores)
            p5       = sorted_s[int(0.05 * len(sorted_s))]
            p95      = sorted_s[min(int(0.95 * len(sorted_s)), len(sorted_s) - 1)]
            mean_tau = sum(taus) / len(taus)

            metric_results[metric] = {
                "mean":       round(mean_s, 4),
                "std":        round(std_s, 4),
                "p5":         round(p5, 4),
                "p95":        round(p95, 4),
                "mean_tau_b": round(mean_tau, 4),
                "bootstrap_rounds": bootstrap_rounds[metric],
            }

        # Composite: average of all 5 per-metric mean scores
        visible_metrics = info.get("visible_metrics", METRICS)
        if info.get("show_in_composite", True):
            valid_means = [metric_results[m]["mean"] for m in visible_metrics if metric_results[m] is not None]
            composite = sum(valid_means) / len(valid_means) if valid_means else None
        else:
            composite = None

        agents[aid] = {
            **info,
            "n_verdicts":        n_total,
            "n_gt_matched":      n_gt,
            "n_real_gt":         n_real,
            "n_flaw_gt":         n_flaw,
            "low_flaw_coverage": low_flaw_coverage,
            "avg_flaw_score":    round(avg_flaw_score, 4) if avg_flaw_score is not None else None,
            "flaw_penalty":      round(flaw_penalty_full, 4),
            "auroc":             round(auroc, 4) if auroc is not None else None,
            "composite":         round(composite, 4) if composite is not None else None,
            "metrics":           metric_results,
            "verdicts":          verdict_details,
        }

    # Build per-metric rankings
    rankings: dict[str, list] = {}
    for metric in METRICS:
        scored = [
            (aid, a) for aid, a in agents.items()
            if a["metrics"].get(metric) is not None and metric in a.get("visible_metrics", METRICS)
        ]
        scored.sort(key=lambda x: x[1]["metrics"][metric]["mean"], reverse=True)

        ranking = []
        for rank, (aid, a) in enumerate(scored, 1):
            mr = a["metrics"][metric]
            ranking.append({
                "rank":              rank,
                "agent_id":          aid,
                "agent_name":        a["agent_name"],
                "agent_type":        a["agent_type"],
                "n_verdicts":        a["n_verdicts"],
                "n_real_gt":         a["n_real_gt"],
                "n_flaw_gt":         a["n_flaw_gt"],
                "low_flaw_coverage": a["low_flaw_coverage"],
                "score_mean":        mr["mean"],
                "score_std":         mr["std"],
                "score_p5":          mr["p5"],
                "score_p95":         mr["p95"],
                "tau_b_mean":        mr["mean_tau_b"],
                "flaw_penalty":      a["flaw_penalty"],
                "avg_flaw_score":    a["avg_flaw_score"],
                "auroc":             a["auroc"],
                "composite":         a["composite"],
            })

        rankings[metric] = ranking

    return {
        "min_verdicts_for_ranking": MIN_VERDICTS_FOR_RANKING,
        "n_bootstrap_samples":      N_BOOTSTRAP_SAMPLES,
        "bootstrap_sample_size":    BOOTSTRAP_SAMPLE_SIZE,
        "n_gt_papers":              len(gt),
        "n_agents":                 len(agents),
        "metrics":                  METRICS,
        "rankings":                 rankings,
        "agents":                   agents,
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_leaderboard(result: dict):
    for metric in result["metrics"]:
        ranking = result["rankings"][metric]
        print(f"\n{'='*140}")
        print(f"  {metric.upper()} — {len(ranking)} agents  "
              f"(bootstrap n={result['n_bootstrap_samples']}, "
              f"sample_k={result['bootstrap_sample_size']})")
        print(f"{'='*140}")
        print(f"{'Rank':>5}  {'Agent':<40} {'Vrdcts':>6} {'Real/Flaw':>10} "
              f"{'Score':>8} {'±Std':>7} {'[p5 , p95]':>14} "
              f"{'τ-b':>7} {'FlawPen':>8} {'AvgFlaw':>8} {'AUROC':>7}  Flag")
        print(f"{'-'*5}  {'-'*40} {'-'*6} {'-'*10} "
              f"{'-'*8} {'-'*7} {'-'*14} "
              f"{'-'*7} {'-'*8} {'-'*8} {'-'*7}  {'-'*10}")
        for e in ranking:
            name  = (e["agent_name"] or "?")[:40]
            score = f"{e['score_mean']:.4f}"
            std   = f"{e['score_std']:.4f}"
            ci    = f"[{e['score_p5']:.3f},{e['score_p95']:.3f}]"
            tau   = f"{e['tau_b_mean']:.4f}"
            fp    = f"{e['flaw_penalty']:.4f}"
            af    = f"{e['avg_flaw_score']:.2f}" if e["avg_flaw_score"] is not None else "N/A"
            auc   = f"{e['auroc']:.4f}" if e["auroc"] is not None else "N/A"
            rf    = f"{e['n_real_gt']}/{e['n_flaw_gt']}"
            flag  = "⚠ LOW FLAW" if e["low_flaw_coverage"] else ""
            print(f"{e['rank']:>5}  {name:<40} {e['n_verdicts']:>6} {rf:>10} "
                  f"{score:>8} {std:>7} {ci:>14} "
                  f"{tau:>7} {fp:>8} {af:>8} {auc:>7}  {flag}")


def main():
    parser = argparse.ArgumentParser(description="Compute leaderboard v2 from data dump")
    parser.add_argument("--dump", required=True, help="Path to dump directory")
    parser.add_argument("--out",  default=None,  help="Output JSON file")
    args = parser.parse_args()

    dump_dir = Path(args.dump)
    if not dump_dir.is_dir():
        print(f"Error: {dump_dir} is not a directory")
        return

    gt       = load_ground_truth()
    verdicts = load_verdicts(dump_dir)
    result   = compute_leaderboard(verdicts, gt)

    print_leaderboard(result)

    if args.out:
        with open(args.out, "w") as f:
            json.dump(result, f, indent=2)
        print(f"\nJSON written to {args.out}")


if __name__ == "__main__":
    main()
