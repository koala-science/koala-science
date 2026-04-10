"""
Diversity Dividend panel.

Scatter plot of reviewer diversity (Shannon entropy) vs. score stability
(bootstrap variance), testing whether diverse review produces stable assessments.
"""

from __future__ import annotations

import math
from collections import Counter
from random import Random

from coalescence.dashboard.registry import panel

_COLORS = {
    "NLP": "#3b82f6",
    "Bioinformatics": "#10b981",
    "QuantumComputing": "#8b5cf6",
    "LLM-Alignment": "#f59e0b",
    "MaterialScience": "#ef4444",
}
_DEFAULT_COLOR = "#94a3b8"

_MIN_PAPERS = 10
_MIN_REVIEWERS = 5
_BOOTSTRAP_N = 20
_BOOTSTRAP_SEED = 42


def _shannon_entropy(counts: Counter) -> float:
    total = sum(counts.values())
    if total == 0:
        return 0.0
    probs = [c / total for c in counts.values() if c > 0]
    return -sum(p * math.log2(p) for p in probs)


def _domain_color(domain: str) -> str:
    key = domain[2:] if domain.startswith("d/") else domain
    return _COLORS.get(key, _DEFAULT_COLOR)


def _reviewer_dimensions(actor_id: str, ds) -> list[str]:
    actor = ds.actors.get(actor_id)
    if actor is None:
        return []
    dims = [actor.actor_type]
    parts = actor.name.rsplit("-", 2)
    if len(parts) == 3:
        dims.append(f"role:{parts[0]}")
        dims.append(f"persona:{parts[2]}")
    return dims


def _variance(vals: list[float]) -> float:
    n = len(vals)
    if n < 2:
        return 0.0
    mean = sum(vals) / n
    return sum((v - mean) ** 2 for v in vals) / n


def _linear_regression_slope(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    den = sum((xs[i] - mx) ** 2 for i in range(n))
    return num / den if den != 0 else 0.0


@panel(title="Diversity Dividend", order=6)
def diversity_dividend(ds) -> str:
    # Collect reviewers per paper
    paper_reviewers: dict[str, set[str]] = {}

    for paper in ds.papers:
        pid = paper.id
        reviewers: set[str] = set()
        for comment in ds.comments.roots_for(pid):
            reviewers.add(comment.author_id)
        for vote in ds.votes.for_target(pid):
            reviewers.add(vote.voter_id)
        paper_reviewers[pid] = reviewers

    eligible_ids = [
        pid for pid, rv in paper_reviewers.items() if len(rv) >= _MIN_REVIEWERS
    ]

    if len(eligible_ids) < _MIN_PAPERS:
        n = len(eligible_ids)
        return (
            f'<p style="color:#94a3b8;font-size:13px">'
            f"Waiting for more review data to compute diversity analysis. "
            f"Need {_MIN_PAPERS}+ papers with {_MIN_REVIEWERS}+ reviewers each "
            f"(currently {n} eligible).</p>"
        )

    # Per-paper diversity and stability
    rng = Random(_BOOTSTRAP_SEED)
    paper_by_id = {p.id: p for p in ds.papers}

    raw_diversity: dict[str, float] = {}
    raw_stability: dict[str, float] = {}

    for pid in eligible_ids:
        reviewers = list(paper_reviewers[pid])

        # Diversity: Shannon entropy of dimension counts
        dim_counts: Counter = Counter()
        for rid in reviewers:
            for dim in _reviewer_dimensions(rid, ds):
                dim_counts[dim] += 1
        raw_diversity[pid] = _shannon_entropy(dim_counts)

        # Stability: bootstrap 20x sampling 50% of reviewers
        votes_by_voter: dict[str, float] = {}
        for vote in ds.votes.for_target(pid):
            votes_by_voter[vote.voter_id] = float(vote.vote_value)

        scores: list[float] = []
        sample_size = max(1, len(reviewers) // 2)
        for _ in range(_BOOTSTRAP_N):
            sample = rng.sample(reviewers, sample_size)
            total = sum(votes_by_voter.get(r, 0.0) for r in sample)
            scores.append(total)

        var = _variance(scores)
        raw_stability[pid] = 1.0 / (1.0 + math.sqrt(var))

    # Normalize to [0, 1]
    max_div = max(raw_diversity.values()) or 1.0
    min_stab = min(raw_stability.values())
    max_stab = max(raw_stability.values())
    stab_range = max_stab - min_stab or 1.0

    norm_div = {pid: raw_diversity[pid] / max_div for pid in eligible_ids}
    norm_stab = {
        pid: (raw_stability[pid] - min_stab) / stab_range for pid in eligible_ids
    }

    xs = [norm_div[pid] for pid in eligible_ids]
    ys = [norm_stab[pid] for pid in eligible_ids]
    slope = _linear_regression_slope(xs, ys)

    if slope > 0.1:
        trend = "positive"
        trend_color = "#22c55e"
        trend_text = (
            "More diverse reviewer pools are associated with more stable assessments."
        )
    elif slope < -0.1:
        trend = "negative"
        trend_color = "#ef4444"
        trend_text = "Higher reviewer diversity correlates with less stable scores — possible signal disagreement."
    else:
        trend = "neutral"
        trend_color = "#94a3b8"
        trend_text = "No clear relationship between reviewer diversity and score stability in current data."

    # Build dots
    dots = []
    for pid in eligible_ids:
        paper = paper_by_id.get(pid)
        title = paper.title if paper else pid
        domain = paper.domain if paper else ""
        color = _domain_color(domain)
        x = round(norm_div[pid] * 90 + 5, 1)
        y = round(norm_stab[pid] * 90 + 5, 1)
        dots.append(
            f'<span class="scatter-dot" style="'
            f"position:absolute;left:{x}%;bottom:{y}%;width:10px;height:10px;"
            f"border-radius:50%;background:{color};transform:translate(-50%,50%);"
            f'cursor:pointer" title="{title}"></span>'
        )

    # Axis labels
    x_label = (
        '<div style="text-align:center;font-size:12px;color:#94a3b8;margin-top:6px">'
        "Reviewer Diversity (entropy) \u2192</div>"
    )
    y_label = (
        '<div style="position:absolute;left:-28px;top:50%;transform:translateY(-50%) rotate(-90deg);'
        'font-size:12px;color:#94a3b8;white-space:nowrap">Score Stability \u2192</div>'
    )

    scatter = (
        '<div style="'
        "position:relative;width:100%;max-width:600px;height:300px;"
        "background:#1e293b;border-radius:12px;border:1px solid #334155;margin:0 auto"
        '">' + y_label + "".join(dots) + "</div>" + x_label
    )

    trend_label = trend.capitalize()
    summary = (
        f'<p style="font-size:13px;color:{trend_color};margin-top:8px">'
        f"Trend: {trend_label}. {trend_text}"
        f"</p>"
    )

    return scatter + summary
