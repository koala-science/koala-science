"""
Ranking Philosophy Comparison panel.

Shows the same papers ranked by all 5 ranking algorithms side-by-side,
plus a pairwise Kendall-tau correlation matrix.
"""

from __future__ import annotations

from coalescence.dashboard.registry import panel
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
    header_cells = "<th>Paper</th>" + "".join(
        f"<th>{_LABELS.get(name, name)}</th>" for name in col_plugins
    )

    rows = []
    for pid in top_ids:
        title = paper_by_id[pid].title if pid in paper_by_id else pid
        cells = [f"<td>{title}</td>"]
        for plugin_name in col_plugins:
            if plugin_name in degenerate:
                cells.append('<td style="background:#1e293b;color:#94a3b8">--</td>')
            else:
                rank = rank_lookup[plugin_name].get(pid, total_papers)
                bg = _rank_cell_bg(rank, total_papers)
                cells.append(
                    f'<td style="background:{bg};color:#f1f5f9;text-align:center">#{rank}</td>'
                )
        rows.append(f"<tr>{''.join(cells)}</tr>")

    table_html = (
        '<table style="border-collapse:collapse;width:100%;font-size:13px">'
        f"<thead><tr>{header_cells}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )

    # Pairwise Kendall-tau correlation matrix (skip degenerate)
    active_plugins = [p for p in _PLUGINS if p.name not in degenerate]
    tau_html = ""
    if len(active_plugins) >= 2:
        tau_header = "<th></th>" + "".join(
            f"<th>{_LABELS.get(p.name, p.name)}</th>" for p in active_plugins
        )
        tau_rows = []
        for pa in active_plugins:
            cells = [f"<th>{_LABELS.get(pa.name, pa.name)}</th>"]
            for pb in active_plugins:
                if pa.name == pb.name:
                    cells.append(
                        '<td style="background:#1e293b;color:#f1f5f9;text-align:center">1.00</td>'
                    )
                else:
                    tau = _kendall_tau(plugin_ranks[pa.name], plugin_ranks[pb.name])
                    if tau != tau:  # nan
                        cells.append(
                            '<td style="background:#1e293b;color:#94a3b8;text-align:center">--</td>'
                        )
                    else:
                        bg = _tau_cell_bg(tau)
                        cells.append(
                            f'<td style="background:{bg};color:#f1f5f9;text-align:center">{tau:.2f}</td>'
                        )
            tau_rows.append(f"<tr>{''.join(cells)}</tr>")

        tau_html = (
            "<h3>Kendall-tau correlation</h3>"
            '<table style="border-collapse:collapse;font-size:13px;margin-top:8px">'
            f"<thead><tr>{tau_header}</tr></thead>"
            f"<tbody>{''.join(tau_rows)}</tbody>"
            "</table>"
        )

    # Degenerate note
    note_html = ""
    if degenerate:
        names_str = ", ".join(_LABELS.get(n, n) for n in sorted(degenerate))
        note_html = (
            f'<p style="color:#94a3b8;font-size:12px;margin-top:8px">'
            f"{names_str}: insufficient data for meaningful ranking (--)</p>"
        )

    return table_html + tau_html + note_html
