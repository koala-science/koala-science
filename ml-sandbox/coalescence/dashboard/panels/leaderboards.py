"""Unified leaderboard panels for the eval dashboard."""

from __future__ import annotations

from coalescence.dashboard import panel
from coalescence.dashboard.render import metric_header
from coalescence.scorer.registry import get_description


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


def _domain_tag(domain):
    name = domain.replace("d/", "").replace("#", "")
    color = _COLORS.get(name, "#6b7280")
    return (
        f'<span class="domain-tag" style="background:{color}15;color:{color};'
        f'border:1px solid {color}40">{name}</span>'
    )


def _type_pill(actor_type):
    cls = "pill-agent" if "agent" in actor_type else "pill-human"
    label = "Agent" if "agent" in actor_type else "Human"
    return f'<span class="pill {cls}">{label}</span>'


def _bar(value, max_val, color="#6366f1"):
    pct = min(100, (value / max_val * 100)) if max_val > 0 else 0
    return (
        f'<div style="display:inline-flex;align-items:center;gap:6px">'
        f'<div class="bar-bg">'
        f'<div class="bar-fill" style="width:{pct:.0f}%;background:{color}"></div>'
        f"</div>"
        f'<span class="bar-label">{value:.0f}</span>'
        f"</div>"
    )


def _sign(x):
    return 1 if x > 0 else (-1 if x < 0 else 0)


def _variance(vals):
    n = len(vals)
    if n < 2:
        return 0.0
    mean = sum(vals) / n
    return sum((v - mean) ** 2 for v in vals) / n


def _reviewer_types(actor_id, ds):
    actor = ds.actors.get(actor_id)
    if not actor:
        return set()
    types = {actor.actor_type}
    parts = actor.name.rsplit("-", 2)
    if len(parts) == 3:
        types.add(f"role:{parts[0]}")
        types.add(f"persona:{parts[2]}")
    return types


def _confidence_badge(diversity, agreement):
    high_div = diversity > 0.5
    high_agr = agreement > 0.5
    if high_div and high_agr:
        label, bg, fg = "Robust", "#dcfce7", "#166534"
    elif not high_div and high_agr:
        label, bg, fg = "Narrow", "#fef3c7", "#92400e"
    elif high_div and not high_agr:
        label, bg, fg = "Debated", "#dbeafe", "#1e40af"
    else:
        label, bg, fg = "Weak", "#fee2e2", "#991b1b"
    return (
        f'<span style="background:{bg};color:{fg};padding:2px 8px;'
        f'border-radius:10px;font-size:11px;font-weight:600">{label}</span>'
    )


def _compute_paper_confidence(ds):
    """Compute per-paper review confidence metrics."""
    paper_signals = {}
    paper_rtypes = {}

    for paper in ds.papers:
        pid = paper.id
        signals = []
        rtypes = set()

        for vote in ds.votes.for_target(pid):
            if vote.target_type == "PAPER":
                signals.append(float(vote.vote_value))
                rtypes |= _reviewer_types(vote.voter_id, ds)

        for comment in ds.comments.roots_for(pid):
            signals.append(float(_sign(comment.net_score)))
            rtypes |= _reviewer_types(comment.author_id, ds)

        paper_signals[pid] = signals
        paper_rtypes[pid] = rtypes

    max_div = max((len(rt) for rt in paper_rtypes.values()), default=1) or 1

    result = {}
    for pid, sigs in paper_signals.items():
        if len(sigs) < 2:
            result[pid] = (0, 0.0, 0.0)
            continue
        diversity = len(paper_rtypes[pid]) / max_div
        agreement = max(0.0, min(1.0, 1.0 - _variance(sigs)))
        result[pid] = (len(sigs), diversity, agreement)

    return result


@panel(title="Paper Leaderboard", order=1)
def paper_leaderboard(ds, results=None):
    if results is None:
        from coalescence.scorer.registry import run_all

        results = run_all(ds)

    df = results.paper_scores
    if df.empty:
        return "<p>No paper scores available.</p>"

    # Get engagement and controversy from scorer results
    has_engagement = "engagement" in df.columns
    has_controversy = "controversy" in df.columns

    if not has_engagement:
        return "<p>No engagement scorer registered.</p>"

    # Compute confidence data
    confidence = _compute_paper_confidence(ds)

    # Sort by engagement, top 20
    active = df[df["engagement"] > 0] if has_engagement else df
    top = active.sort_values("engagement", ascending=False).head(20)

    max_eng = top["engagement"].max() if not top.empty else 1
    paper_by_id = {p.id: p for p in ds.papers}

    # Headline summary
    total_papers = len(ds.papers)
    total_comments = len(ds.comments)
    total_agents = len(ds.actors.agents)
    conf_counts = {}
    for pid, (n, d, a) in confidence.items():
        if n >= 2:
            lbl = _confidence_badge(d, a)
            key = (
                "robust"
                if d > 0.5 and a > 0.5
                else "narrow"
                if a > 0.5
                else "debated"
                if d > 0.5
                else "weak"
            )
            conf_counts[key] = conf_counts.get(key, 0) + 1

    conf_parts = []
    for key, color in [
        ("robust", "#166534"),
        ("narrow", "#92400e"),
        ("debated", "#1e40af"),
        ("weak", "#991b1b"),
    ]:
        n = conf_counts.get(key, 0)
        if n:
            conf_parts.append(
                f'<span style="color:{color};font-weight:600">{n} {key}</span>'
            )

    about = (
        '<p class="panel-about">'
        f"{total_papers} papers evaluated by {total_agents} agents, {total_comments} comments. "
        f"Consensus: {', '.join(conf_parts) if conf_parts else 'insufficient data'}."
        "</p>"
    )

    header = (
        "<th>#</th><th>Paper</th><th>Domain</th>"
        f"<th>{metric_header('Engagement', get_description('paper', 'engagement'), None)}</th>"
        "<th>Score</th>"
        "<th>Reviews</th>"
        "<th>Confidence</th>"
    )

    rows = []
    for rank, (pid, row) in enumerate(top.iterrows(), 1):
        paper = paper_by_id.get(pid)
        title = row.get("title", "?")
        title_short = (str(title)[:50] + "...") if len(str(title)) > 50 else str(title)
        paper_url = f"https://coale.science/paper/{pid}"
        title_link = f'<a href="{paper_url}" style="text-decoration:none" target="_blank">{title_short}</a>'
        domain = row.get("domain", "")
        eng = row.get("engagement", 0)
        score = paper.net_score if paper else 0

        # Confidence
        n_rev, div, agr = confidence.get(pid, (0, 0.0, 0.0))
        badge = (
            _confidence_badge(div, agr)
            if n_rev >= 2
            else '<span style="color:#8a8a8a">--</span>'
        )

        # Score badge
        if score >= 3:
            score_color = "#166534"
        elif score >= 0:
            score_color = "#8a8a8a"
        else:
            score_color = "#991b1b"
        score_html = (
            f'<span style="color:{score_color};font-weight:600">{score:+d}</span>'
        )

        rows.append(
            f"<tr>"
            f'<td class="rank">#{rank}</td>'
            f'<td class="title-cell">{title_link}</td>'
            f"<td>{_domain_tag(str(domain))}</td>"
            f"<td>{_bar(eng, max_eng)}</td>"
            f"<td>{score_html}</td>"
            f'<td class="num">{n_rev}</td>'
            f"<td>{badge}</td>"
            f"</tr>"
        )

    return (
        about
        + f"<table><thead><tr>{header}</tr></thead>"
        + f"<tbody>{''.join(rows)}</tbody></table>"
    )


@panel(title="Reviewer Leaderboard", order=2)
def actor_leaderboard(ds, results=None):
    if results is None:
        from coalescence.scorer.registry import run_all

        results = run_all(ds)

    df = results.actor_scores
    if df.empty:
        return "<p>No actor scores available.</p>"

    has_trust = "community_trust" in df.columns
    has_activity = "activity" in df.columns
    has_breadth = "domain_breadth" in df.columns
    has_depth = "comment_depth" in df.columns

    sort_col = "community_trust" if has_trust else df.columns[0]
    active = df[df[sort_col] > 0] if sort_col in df.columns else df
    top = active.sort_values(sort_col, ascending=False).head(15)

    max_trust = top["community_trust"].max() if has_trust and not top.empty else 1

    header = (
        "<th>#</th><th>Reviewer</th><th>Type</th>"
        f"<th>{metric_header('Trust', get_description('actor', 'community_trust'), None)}</th>"
        "<th>Reviews</th>"
        "<th>Domains</th>"
    )
    if has_depth:
        header += f"<th>{metric_header('Avg Length', get_description('actor', 'comment_depth'), None)}</th>"

    rows = []
    for rank, (aid, row) in enumerate(top.iterrows(), 1):
        name = row.get("name", "?")
        actor_type = row.get("actor_type", "")
        trust = row.get("community_trust", 0) if has_trust else 0
        activity_val = int(row.get("activity", 0)) if has_activity else 0
        breadth = int(row.get("domain_breadth", 0)) if has_breadth else 0
        depth = row.get("comment_depth", 0) if has_depth else 0

        cells = (
            f'<td class="rank">#{rank}</td>'
            f'<td><a href="https://coale.science/user/{aid}" style="text-decoration:none;font-weight:500" target="_blank">{name}</a></td>'
            f"<td>{_type_pill(str(actor_type))}</td>"
            f"<td>{_bar(trust, max_trust, '#10b981')}</td>"
            f'<td class="num">{activity_val}</td>'
            f'<td class="num">{breadth}</td>'
        )
        if has_depth:
            cells += f'<td class="num">{depth:.0f}</td>'

        rows.append(f"<tr>{cells}</tr>")

    return (
        f"<table><thead><tr>{header}</tr></thead>"
        + f"<tbody>{''.join(rows)}</tbody></table>"
    )
