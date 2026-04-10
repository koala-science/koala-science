"""
Scorer decorator and registry.

Usage:
    from coalescence.scorer import scorer

    @scorer(entity="actor")
    def comment_depth(actor, ds):
        comments = ds.comments.by_author(actor.id)
        if not comments: return 0.0
        return sum(c.content_length for c in comments) / len(comments)

    results = ds.run_scorers()
    results.actor_scores  # DataFrame: actor_id × dimensions
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from coalescence.data.dataset import Dataset

# Global registry: (entity_type, dimension_name) → scorer function
_REGISTRY: dict[tuple[str, str], Callable] = {}


def scorer(entity: str, dimension: str | None = None):
    """
    Register a scoring function.

    Args:
        entity: "actor" or "paper"
        dimension: Dimension name. Defaults to the function name.
    """
    def decorator(fn: Callable):
        dim = dimension or fn.__name__
        _REGISTRY[(entity, dim)] = fn
        return fn
    return decorator


def clear_registry():
    """Clear all registered scorers. Useful in notebooks."""
    _REGISTRY.clear()


def list_scorers() -> list[tuple[str, str]]:
    """List all registered (entity, dimension) pairs."""
    return list(_REGISTRY.keys())


@dataclass
class ScorerResults:
    """Results from running all registered scorers."""
    actor_scores: pd.DataFrame
    paper_scores: pd.DataFrame

    def to_jsonl(self, path: str) -> None:
        """Save scores to JSONL files in the given directory."""
        out = Path(path)
        out.mkdir(parents=True, exist_ok=True)

        if not self.actor_scores.empty:
            self.actor_scores.to_json(out / "actor_scores.jsonl", orient="records", lines=True)

        if not self.paper_scores.empty:
            self.paper_scores.to_json(out / "paper_scores.jsonl", orient="records", lines=True)

    def __repr__(self) -> str:
        a_dims = list(self.actor_scores.columns) if not self.actor_scores.empty else []
        p_dims = list(self.paper_scores.columns) if not self.paper_scores.empty else []
        return (
            f"ScorerResults(\n"
            f"  actor_scores: {self.actor_scores.shape[0]} actors × {len(a_dims)} dims {a_dims}\n"
            f"  paper_scores: {self.paper_scores.shape[0]} papers × {len(p_dims)} dims {p_dims}\n"
            f")"
        )


def run_all(ds: Dataset) -> ScorerResults:
    """Run all registered scorers against a Dataset."""
    actor_rows: dict[str, dict[str, float]] = {}
    paper_rows: dict[str, dict[str, float]] = {}

    for (entity, dim), fn in _REGISTRY.items():
        if entity == "actor":
            for actor in ds.actors:
                score = fn(actor, ds)
                actor_rows.setdefault(actor.id, {"name": actor.name, "actor_type": actor.actor_type})[dim] = score
        elif entity == "paper":
            for paper in ds.papers:
                score = fn(paper, ds)
                paper_rows.setdefault(paper.id, {"title": paper.title, "domain": paper.domain})[dim] = score

    actor_df = pd.DataFrame.from_dict(actor_rows, orient="index")
    actor_df.index.name = "actor_id"

    paper_df = pd.DataFrame.from_dict(paper_rows, orient="index")
    paper_df.index.name = "paper_id"

    return ScorerResults(actor_scores=actor_df, paper_scores=paper_df)
