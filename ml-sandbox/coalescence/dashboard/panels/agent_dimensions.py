"""Agent Dimension Fingerprints panel.

Groups agents by role/interest/persona (parsed from name convention
``role-interest-persona``) and shows mean scorer values with deviation
indicators relative to the population.
"""

from __future__ import annotations

from coalescence.dashboard import panel

_ACTOR_META = {"name", "actor_type"}
_DIMENSIONS = ("role", "interest", "persona")

_IND_UP = '<span style="color:#22c55e">▲</span>'
_IND_DOWN = '<span style="color:#ef4444">▼</span>'
_IND_NEUTRAL = '<span style="color:#64748b">--</span>'


def _indicator(group_mean: float, pop_mean: float, pop_std: float) -> str:
    if pop_std == 0:
        return _IND_NEUTRAL
    if group_mean > pop_mean + pop_std:
        return _IND_UP
    if group_mean < pop_mean - pop_std:
        return _IND_DOWN
    return _IND_NEUTRAL


@panel(title="Agent Dimension Fingerprints", order=5)
def agent_dimensions(ds, results=None):
    if results is None:
        from coalescence.scorer.registry import run_all

        results = run_all(ds)

    df = results.actor_scores
    if df.empty:
        return "<p>No actor scores available.</p>"

    agents = df[df["actor_type"] != "human"].copy()
    if agents.empty:
        return "<p>No agent actors found.</p>"

    # Parse names into dimension columns
    parsed_rows = []
    for idx, row in agents.iterrows():
        parts = str(row["name"]).rsplit("-", 2)
        if len(parts) == 3:
            parsed_rows.append((idx, parts[0], parts[1], parts[2]))

    if not parsed_rows:
        return "<p>No agents with parseable role-interest-persona names.</p>"

    import pandas as pd

    parsed_df = pd.DataFrame(
        parsed_rows, columns=["_idx", "role", "interest", "persona"]
    ).set_index("_idx")
    agents = agents.join(parsed_df)

    score_cols = [
        c for c in agents.columns if c not in _ACTOR_META and c not in _DIMENSIONS
    ]
    if not score_cols:
        return "<p>No scorer dimensions registered.</p>"

    pop_mean = {col: agents[col].mean() for col in score_cols}
    pop_std = {col: agents[col].std(ddof=0) for col in score_cols}

    tables = []
    for dim in _DIMENSIONS:
        if dim not in agents.columns:
            continue
        groups = agents.groupby(dim)[score_cols].mean()
        if groups.empty:
            continue

        header = f"<th>{dim}</th>" + "".join(f"<th>{c}</th>" for c in score_cols)
        rows = []
        for dim_val, means in groups.iterrows():
            cells = [f"<td><strong>{dim_val}</strong></td>"]
            for col in score_cols:
                m = means[col]
                ind = _indicator(m, pop_mean[col], pop_std[col])
                cells.append(f"<td>{m:.1f} {ind}</td>")
            rows.append(f"<tr>{''.join(cells)}</tr>")

        tables.append(
            f"<h3 style='margin-top:16px;text-transform:capitalize'>{dim}</h3>"
            '<table style="border-collapse:collapse;width:100%;font-size:13px">'
            f"<thead><tr>{header}</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table>"
        )

    if not tables:
        return "<p>No parseable agent dimension groups found.</p>"

    return "".join(tables)
