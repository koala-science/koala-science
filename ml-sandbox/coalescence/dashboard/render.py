"""
HTML render helpers for leaderboard dashboard cells.
"""

from __future__ import annotations

import pandas as pd


def render_cell(value: float, max_val: float, display: str | None = None) -> str:
    """
    Render a single metric value as an HTML string.

    Args:
        value: The metric value.
        max_val: The maximum value (used for bar fill calculation).
        display: Render hint — "bar", "badge", "pct", "num", or None for auto-detect.

    Returns:
        HTML string.
    """
    hint = display or _auto_detect(value, max_val)

    if hint == "bar":
        return _render_bar(value, max_val)
    if hint == "badge":
        return _render_badge(value)
    if hint == "pct":
        return _render_pct(value)
    # "num" or fallback
    return _render_num(value)


def distribution_summary(series: pd.Series) -> str:
    """
    Return an HTML summary of a metric distribution.

    Format: ``median | p90 | max`` as muted text.
    Returns empty string for an empty series.
    """
    s = series.dropna()
    if s.empty:
        return ""
    median = s.median()
    p90 = s.quantile(0.9)
    maximum = s.max()
    body = f"{median:.2f} | {p90:.2f} | {maximum:.2f}"
    return f'<span style="color:#888;font-size:0.85em">{body}</span>'


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _auto_detect(value: float, max_val: float) -> str:
    if value < 0:
        return "badge"
    if 0 <= value <= 1 and max_val <= 1:
        return "pct"
    return "bar"


def _render_bar(value: float, max_val: float) -> str:
    pct = (value / max_val * 100) if max_val else 0
    pct = max(0.0, min(100.0, pct))
    return (
        f'<div style="display:flex;align-items:center;gap:4px">'
        f'<div style="background:#4a90d9;width:{pct:.1f}%;height:10px;border-radius:2px"></div>'
        f"<span>{value:.2f}</span>"
        f"</div>"
    )


def _render_badge(value: float) -> str:
    if value >= 7:
        color = "green"
    elif value >= 3:
        color = "blue"
    elif value >= 0:
        color = "gray"
    else:
        color = "red"
    return (
        f'<span style="background:{color};color:#fff;padding:1px 6px;'
        f'border-radius:4px;font-size:0.85em">{value:.2f}</span>'
    )


def _render_pct(value: float) -> str:
    opacity = max(0.2, min(1.0, value))
    return f'<span style="opacity:{opacity:.2f}">{value * 100:.1f}%</span>'


def _render_num(value: float) -> str:
    return f"<span>{value:.2f}</span>"
