"""
Consensus Quality Map panel.

Scatter plot showing agreement vs. reviewer diversity per paper,
revealing whether democratic consensus is robust or fragile.
"""

from __future__ import annotations


from coalescence.dashboard.registry import panel

_COLORS = {
    "NLP": "#3b82f6",
    "Bioinformatics": "#10b981",
    "QuantumComputing": "#8b5cf6",
    "LLM-Alignment": "#f59e0b",
    "MaterialScience": "#ef4444",
    "AI Safety": "#ec4899",
    "Environment": "#22c55e",
    "AI for Science": "#06b6d4",
    "ML-Research": "#6366f1",
}
_DEFAULT_COLOR = "#94a3b8"


def _sign(x: float) -> int:
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


def _variance(vals: list[float]) -> float:
    n = len(vals)
    if n < 2:
        return 0.0
    mean = sum(vals) / n
    return sum((v - mean) ** 2 for v in vals) / n


def _domain_color(domain: str) -> str:
    # Strip "d/" prefix if present
    key = domain[2:] if domain.startswith("d/") else domain
    return _COLORS.get(key, _DEFAULT_COLOR)


def _reviewer_types(actor_id: str, ds) -> set[str]:
    actor = ds.actors.get(actor_id)
    if actor is None:
        return set()
    types: set[str] = {actor.actor_type}
    # Parse role-interest-persona pattern
    parts = actor.name.rsplit("-", 2)
    if len(parts) == 3:
        role, _interest, persona = parts
        types.add(f"role:{role}")
        types.add(f"persona:{persona}")
    return types


@panel(title="Consensus Quality", order=4)
def consensus_quality(ds) -> str:
    # Collect per-paper signals and reviewer types
    paper_signals: dict[str, list[float]] = {}
    paper_reviewer_types: dict[str, set[str]] = {}

    for paper in ds.papers:
        pid = paper.id
        signals: list[float] = []
        rtypes: set[str] = set()

        # Votes on the paper
        for vote in ds.votes.for_target(pid):
            if vote.target_type == "PAPER":
                signals.append(float(vote.vote_value))
                rtypes |= _reviewer_types(vote.voter_id, ds)

        # Root comments
        for comment in ds.comments.roots_for(pid):
            signals.append(float(_sign(comment.net_score)))
            rtypes |= _reviewer_types(comment.author_id, ds)

        paper_signals[pid] = signals
        paper_reviewer_types[pid] = rtypes

    # Filter papers with >= 2 signals
    valid_ids = [pid for pid, sigs in paper_signals.items() if len(sigs) >= 2]

    if not valid_ids:
        return "<p>No papers with enough reviews for consensus analysis.</p>"

    # Compute diversity and agreement per paper
    max_diversity = max(len(paper_reviewer_types[pid]) for pid in valid_ids) or 1

    scores: dict[str, tuple[float, float]] = {}  # pid -> (diversity, agreement)
    for pid in valid_ids:
        diversity = len(paper_reviewer_types[pid]) / max_diversity
        agreement = 1.0 - _variance(paper_signals[pid])
        # Clamp agreement to [0, 1]
        agreement = max(0.0, min(1.0, agreement))
        scores[pid] = (diversity, agreement)

    # Quadrant counts (diversity > 0.5 = high, agreement > 0.5 = high)
    robust = echo = debate = under = 0
    for div, agr in scores.values():
        high_div = div > 0.5
        high_agr = agr > 0.5
        if high_div and high_agr:
            robust += 1
        elif not high_div and high_agr:
            echo += 1
        elif high_div and not high_agr:
            debate += 1
        else:
            under += 1

    # Build dots
    dots = []
    paper_by_id = {p.id: p for p in ds.papers}
    for pid in valid_ids:
        paper = paper_by_id.get(pid)
        title = paper.title if paper else pid
        domain = paper.domain if paper else ""
        color = _domain_color(domain)
        div, agr = scores[pid]
        x = round(div * 90 + 5, 1)  # 5%–95% range
        y = round(agr * 90 + 5, 1)
        dots.append(
            f'<span class="scatter-dot" style="'
            f"position:absolute;left:{x}%;bottom:{y}%;width:10px;height:10px;"
            f"border-radius:50%;background:{color};transform:translate(-50%,50%);"
            f'cursor:pointer" title="{title}"></span>'
        )

    # Crosshair lines
    crosshair = (
        # vertical at 50%
        '<div style="position:absolute;left:50%;top:0;bottom:0;width:1px;background:#334155"></div>'
        # horizontal at 50%
        '<div style="position:absolute;bottom:50%;left:0;right:0;height:1px;background:#334155"></div>'
    )

    # Quadrant labels
    label_style_base = (
        "position:absolute;font-size:11px;color:#64748b;pointer-events:none"
    )
    quadrant_labels = (
        f'<span style="{label_style_base};top:6px;right:8px">Robust consensus</span>'
        f'<span style="{label_style_base};top:6px;left:8px">Echo chamber</span>'
        f'<span style="{label_style_base};bottom:6px;right:8px">Genuine debate</span>'
        f'<span style="{label_style_base};bottom:6px;left:8px">Under-reviewed</span>'
    )

    # Axis labels
    x_label = (
        '<div style="text-align:center;font-size:12px;color:#94a3b8;margin-top:6px">'
        "Reviewer Diversity →</div>"
    )
    y_label = (
        '<div style="position:absolute;left:-28px;top:50%;transform:translateY(-50%) rotate(-90deg);'
        'font-size:12px;color:#94a3b8;white-space:nowrap">Agreement →</div>'
    )

    plot_html = (
        '<div class="scatter-plot" style="'
        "position:relative;width:100%;max-width:600px;height:300px;"
        "background:#1e293b;border-radius:12px;border:1px solid #334155"
        '">'
        + crosshair
        + quadrant_labels
        + y_label
        + "".join(dots)
        + "</div>"
        + x_label
    )

    summary = (
        f'<p style="font-size:13px;color:#94a3b8;margin-top:8px">'
        f"{robust} robust · {echo} echo chamber · {debate} genuine debate · {under} under-reviewed"
        f"</p>"
    )

    return plot_html + summary
