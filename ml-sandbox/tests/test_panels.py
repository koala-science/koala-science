"""Tests for leaderboard dashboard panels."""

import importlib

import pytest

from coalescence.scorer.registry import scorer, clear_registry
from coalescence.dashboard.registry import clear_panels


@pytest.fixture(autouse=True)
def clean_registries():
    clear_registry()
    clear_panels()
    yield
    clear_registry()
    clear_panels()


def _register_builtins():
    import coalescence.scorer.builtins as mod

    importlib.reload(mod)


def _import_panels():
    import coalescence.dashboard.panels.leaderboards as mod

    importlib.reload(mod)
    return mod


def test_paper_leaderboard_renders(ds):
    _register_builtins()
    mod = _import_panels()
    html = mod.paper_leaderboard(ds)
    assert "<table" in html
    assert "Attention Is All You Need" in html or "AlphaFold" in html or "BERT" in html


def test_paper_leaderboard_dynamic_columns(ds):
    _register_builtins()

    @scorer(entity="paper", dimension="novelty_score")
    def novelty_score(paper, ds):
        return 0.5

    mod = _import_panels()
    html = mod.paper_leaderboard(ds)
    assert "novelty_score" in html


def test_actor_leaderboard_renders(ds):
    _register_builtins()
    mod = _import_panels()
    html = mod.actor_leaderboard(ds)
    assert "<table" in html
    assert "Alice" in html or "Bob" in html or "Bot1" in html


def test_leaderboard_has_distribution_summary(ds):
    _register_builtins()
    mod = _import_panels()
    html = mod.paper_leaderboard(ds)
    assert "dist-summary" in html


class TestRankingComparisonPanel:
    def test_renders_table(self, ds):
        _register_builtins()
        from coalescence.dashboard.panels.ranking_comparison import ranking_comparison

        html = ranking_comparison(ds)
        assert "<table" in html
        assert "Egalitarian" in html
        assert "Weighted Log" in html
        assert "Elo" in html

    def test_handles_degenerate_gracefully(self, ds):
        _register_builtins()
        from coalescence.dashboard.panels.ranking_comparison import ranking_comparison

        html = ranking_comparison(ds)
        # Should not crash even with sparse data
        assert html

    def test_correlation_matrix(self, ds):
        _register_builtins()
        from coalescence.dashboard.panels.ranking_comparison import ranking_comparison

        html = ranking_comparison(ds)
        # Kendall-tau values should appear
        assert "0." in html or "--" in html


class TestAgentDimensionsPanel:
    def test_renders(self, ds):
        _register_builtins()
        from coalescence.dashboard.panels.agent_dimensions import agent_dimensions

        html = agent_dimensions(ds)
        assert html  # non-empty, even if just placeholder

    def test_dynamic_scorer_columns(self, ds):
        _register_builtins()

        @scorer(entity="actor")
        def custom_actor_metric(actor, ds):
            return 1.0

        from coalescence.dashboard.panels.agent_dimensions import agent_dimensions

        html = agent_dimensions(ds)
        # Should include the custom scorer in output or show placeholder
        assert html


class TestConsensusPanel:
    def test_renders_scatter(self, ds):
        _register_builtins()
        from coalescence.dashboard.panels.consensus import consensus_quality

        html = consensus_quality(ds)
        assert "scatter-plot" in html or "No papers" in html

    def test_quadrant_labels(self, ds):
        _register_builtins()
        from coalescence.dashboard.panels.consensus import consensus_quality

        html = consensus_quality(ds)
        if "scatter-plot" in html:
            assert "Robust" in html
            assert "Debate" in html or "debate" in html
