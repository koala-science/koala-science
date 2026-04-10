"""
Panel decorator and registry for the eval dashboard.

Usage:
    from coalescence.dashboard import panel

    @panel(title="Overview", order=0)
    def overview(ds):
        return "<p>Summary stats here</p>"

    @panel(title="Scores", order=1)
    def scores(ds, results):
        return f"<p>{len(results.actor_scores)} actors scored</p>"

    html = render_all(ds)
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from coalescence.data.dataset import Dataset

_PANELS: dict[str, "PanelSpec"] = {}


@dataclass
class PanelSpec:
    title: str
    order: int
    fn: Callable


def panel(title: str, order: int = 0):
    """Register a panel function for the eval dashboard."""

    def decorator(fn: Callable) -> Callable:
        _PANELS[fn.__name__] = PanelSpec(title=title, order=order, fn=fn)
        return fn

    return decorator


def list_panels() -> list[PanelSpec]:
    """Return registered panels sorted by order."""
    return sorted(_PANELS.values(), key=lambda p: p.order)


def clear_panels() -> None:
    """Clear all registered panels. Useful in tests and notebooks."""
    _PANELS.clear()


def render_all(ds: "Dataset | None") -> str:
    """Run all panels and return concatenated HTML."""
    from coalescence.scorer.registry import run_all as _run_scorers

    results = _run_scorers(ds) if ds is not None else None

    parts: list[str] = []
    for spec in list_panels():
        try:
            sig = inspect.signature(spec.fn)
            if len(sig.parameters) >= 2:
                body = spec.fn(ds, results)
            else:
                body = spec.fn(ds)
        except Exception as exc:
            body = f'<div class="error">Panel error: {exc}</div>'
        parts.append(f'<div class="section"><h2>{spec.title}</h2>{body}</div>')
    return "".join(parts)
