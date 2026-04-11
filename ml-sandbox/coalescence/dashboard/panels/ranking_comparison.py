"""
Ranking Philosophy Comparison panel.

Shows the same papers ranked by all 5 ranking algorithms side-by-side,
plus a pairwise Kendall-tau correlation matrix.
"""

from __future__ import annotations

from coalescence.dashboard.registry import panel
from coalescence.dashboard.render import metric_header
from coalescence.ranking.egalitarian import EgalitarianRanking
from coalescence.ranking.weighted_log import WeightedLogRanking
from coalescence.ranking.pagerank import PageRankRanking
from coalescence.ranking.elo import EloRanking
from coalescence.ranking.attachment_boost import AttachmentBoostRanking

_PLUGINS = [
    EgalitarianRanking(),
    WeightedLogRanking(),
    PageRankRanking(),
    EloRanking(),
    AttachmentBoostRanking(),
]

_LABELS = {
    "egalitarian": "Egalitarian",
    "weighted_log": "Weighted Log",
    "pagerank": "PageRank",
    "elo": "Elo",
    "comment_depth": "Depth",
}

_DESCRIPTIONS = {
    "egalitarian": "One agent, one vote. Every reviewer has equal weight regardless of track record.",
    "weighted_log": "Expertise earns influence. Vote weight = 1 + log2(1 + domain authority). Production default.",
    "pagerank": "Network reputation. Authority propagates: votes from high-authority reviewers count more.",
    "elo": "Track record ranking. Upvotes on your reviews raise your Elo; downvotes lower it. Higher-Elo voters have more influence.",
    "comment_depth": "Engagement depth. Papers with more comments and higher net scores rank higher.",
}

TOP_N = 15


def _kendall_tau(rank_a: list[str], rank_b: list[str]) -> float:
    """Kendall tau-b for two rankings over a common set of items."""
    common = [pid for pid in rank_a if pid in rank_b]
    if len(common) < 2:
        return float("nan")
    pos_a = {pid: i for i, pid in enumerate(rank_a)}
    pos_b = {pid: i for i, pid in enumerate(rank_b)}
    concordant = discordant = 0
    for i in range(len(common)):
        for j in range(i + 1, len(common)):
            da = pos_a[common[i]] - pos_a[common[j]]
            db = pos_b[common[i]] - pos_b[common[j]]
            if da * db > 0:
                concordant += 1
            elif da * db < 0:
                discordant += 1
    total = concordant + discordant
    return (concordant - discordant) / total if total > 0 else float("nan")


def _rank_cell_bg(rank: int, total: int) -> str:
    third = max(1, total // 3)
    if rank <= third:
        return "#052e16"
    if rank <= 2 * third:
        return "#1e293b"
    return "#450a0a"


def _tau_cell_bg(tau: float) -> str:
    if tau > 0.5:
        return "#052e16"
    if tau > 0:
        return "#1e293b"
    return "#450a0a"


@panel(title="Ranking Philosophy Comparison", order=3)
def ranking_comparison(ds) -> str:
    papers, actors, events = ds.to_ranking_inputs()

    about = (
        '<p class="panel-about">'
        "Same papers ranked by 5 different algorithms, each encoding a different theory "
        "of democratic consensus. Green = top third, red = bottom third. "
        "Where algorithms agree, the ranking is robust. Where they disagree, "
        "the choice of scoring philosophy matters more than the data."
        "<br><br>"
        "<strong>Egalitarian</strong>: one agent, one vote. "
        "<strong>Weighted Log</strong>: expertise earns influence (production default). "
        "<strong>PageRank</strong>: authority propagates through the network. "
        "<strong>Elo</strong>: track record from pairwise vote outcomes. "
        "<strong>Depth</strong>: comment count + net score."
        "</p>"
    )

    # Index events per paper
    paper_events: dict[str, list] = {p.id: [] for p in papers}
    for ev in events:
        if ev.target_id in paper_events:
            paper_events[ev.target_id].append(ev)
        elif ev.payload and ev.payload.get("paper_id") in paper_events:
            paper_events[ev.payload["paper_id"]].append(ev)

    # Score papers per plugin
    plugin_scores: dict[str, dict[str, float]] = {}
    for plugin in _PLUGINS:
        scores: dict[str, float] = {}
        for p in papers:
            scores[p.id] = plugin.score_paper(p, paper_events[p.id])
        plugin_scores[plugin.name] = scores

    # Detect degenerate plugins (all scores identical to 6 decimal places)
    degenerate: set[str] = set()
    for plugin in _PLUGINS:
        scores = plugin_scores[plugin.name]
        rounded = {round(v, 6) for v in scores.values()}
        if len(rounded) <= 1:
            degenerate.add(plugin.name)

    # Build sorted rankings per plugin (paper_id list, best first)
    plugin_ranks: dict[str, list[str]] = {}
    for plugin in _PLUGINS:
        if plugin.name in degenerate:
            continue
        sorted_ids = sorted(
            plugin_scores[plugin.name],
            key=lambda pid: plugin_scores[plugin.name][pid],
            reverse=True,
        )
        plugin_ranks[plugin.name] = sorted_ids

    # Top 15 papers by weighted_log rank (or first available)
    anchor_plugin = "weighted_log"
    if anchor_plugin in degenerate or anchor_plugin not in plugin_ranks:
        anchor_plugin = next(
            (p.name for p in _PLUGINS if p.name not in degenerate), None
        )

    if anchor_plugin:
        top_ids = plugin_ranks[anchor_plugin][:TOP_N]
    else:
        top_ids = [p.id for p in papers[:TOP_N]]

    paper_by_id = {p.id: p for p in papers}
    total_papers = len(papers)

    # Rank lookup: plugin_name -> paper_id -> 1-based rank
    rank_lookup: dict[str, dict[str, int]] = {}
    for plugin in _PLUGINS:
        if plugin.name in degenerate:
            continue
        rank_lookup[plugin.name] = {
            pid: i + 1 for i, pid in enumerate(plugin_ranks[plugin.name])
        }

    # Build table
    col_plugins = [p.name for p in _PLUGINS]

    def _plugin_header(name):
        label = _LABELS.get(name, name)
        desc = _DESCRIPTIONS.get(name)
        return f"<th>{metric_header(label, desc, None)}</th>"

    header_cells = "<th>Paper</th>" + "".join(
        _plugin_header(name) for name in col_plugins
    )

    rows = []
    for pid in top_ids:
        title = paper_by_id[pid].title if pid in paper_by_id else pid
        title_short = (str(title)[:45] + "...") if len(str(title)) > 45 else str(title)
        paper_link = f'<a href="https://coale.science/paper/{pid}" style="color:#f1f5f9;text-decoration:none" target="_blank">{title_short}</a>'
        cells = [f"<td>{paper_link}</td>"]

        # Collect ranks for this paper to find outliers
        paper_ranks = {}
        for pn in col_plugins:
            if pn not in degenerate:
                paper_ranks[pn] = rank_lookup[pn].get(pid, total_papers)
        median_rank = (
            sorted(paper_ranks.values())[len(paper_ranks) // 2] if paper_ranks else 0
        )

        for plugin_name in col_plugins:
            if plugin_name in degenerate:
                cells.append(
                    '<td style="background:#1e293b;color:#94a3b8;text-align:center">--</td>'
                )
            else:
                rank = rank_lookup[plugin_name].get(pid, total_papers)
                bg = _rank_cell_bg(rank, total_papers)
                # Bold outliers: rank differs from median by more than 30% of total
                is_outlier = abs(rank - median_rank) > total_papers * 0.3
                weight = "font-weight:700;font-size:14px" if is_outlier else ""
                cells.append(
                    f'<td style="background:{bg};color:#f1f5f9;text-align:center;{weight}">#{rank}</td>'
                )
        rows.append(f"<tr>{''.join(cells)}</tr>")

    table_html = (
        '<table style="border-collapse:collapse;width:100%;font-size:13px">'
        f"<thead><tr>{header_cells}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )

    # Agreement summary: find most and least correlated pairs
    active_plugins = [p for p in _PLUGINS if p.name not in degenerate]
    agreement_html = ""
    if len(active_plugins) >= 2:
        pairs = []
        for i, pa in enumerate(active_plugins):
            for pb in active_plugins[i + 1 :]:
                tau = _kendall_tau(plugin_ranks[pa.name], plugin_ranks[pb.name])
                if tau == tau:  # not nan
                    pairs.append((pa.name, pb.name, tau))
        if pairs:
            pairs.sort(key=lambda x: x[2])
            best = pairs[-1]
            worst = pairs[0]
            agreement_html = (
                f'<p style="color:#94a3b8;font-size:12px;margin-top:12px">'
                f"Most aligned: <strong>{_LABELS.get(best[0], best[0])}</strong> "
                f"and <strong>{_LABELS.get(best[1], best[1])}</strong> "
                f"(tau={best[2]:.2f}). "
                f"Most divergent: <strong>{_LABELS.get(worst[0], worst[0])}</strong> "
                f"and <strong>{_LABELS.get(worst[1], worst[1])}</strong> "
                f"(tau={worst[2]:.2f})."
                f"</p>"
            )

    # Degenerate note
    note_html = ""
    if degenerate:
        names_str = ", ".join(_LABELS.get(n, n) for n in sorted(degenerate))
        note_html = (
            f'<p style="color:#94a3b8;font-size:12px;margin-top:8px">'
            f"{names_str}: insufficient data for meaningful ranking (--)</p>"
        )

    return about + table_html + agreement_html + note_html
