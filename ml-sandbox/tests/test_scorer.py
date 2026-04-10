"""Tests for the scorer framework."""
import pytest
from coalescence.scorer.registry import scorer, clear_registry, list_scorers, run_all


@pytest.fixture(autouse=True)
def clean_registry():
    """Clear the scorer registry before each test."""
    clear_registry()
    yield
    clear_registry()


class TestScorerDecorator:

    def test_register_scorer(self):
        @scorer(entity="actor")
        def my_score(actor, ds):
            return 1.0

        assert ("actor", "my_score") in list_scorers()

    def test_dimension_from_name(self):
        @scorer(entity="paper")
        def engagement(paper, ds):
            return 0.0

        assert ("paper", "engagement") in list_scorers()

    def test_explicit_dimension(self):
        @scorer(entity="actor", dimension="custom_name")
        def some_function(actor, ds):
            return 0.0

        assert ("actor", "custom_name") in list_scorers()

    def test_clear_registry(self):
        @scorer(entity="actor")
        def temp(actor, ds):
            return 0.0

        assert len(list_scorers()) == 1
        clear_registry()
        assert len(list_scorers()) == 0


class TestRunScorers:

    def test_run_empty_registry(self, ds):
        results = run_all(ds)
        assert results.actor_scores.empty
        assert results.paper_scores.empty

    def test_run_actor_scorer(self, ds):
        @scorer(entity="actor")
        def comment_count(actor, ds):
            return len(ds.comments.by_author(actor.id))

        results = run_all(ds)
        assert len(results.actor_scores) == 3
        assert "comment_count" in results.actor_scores.columns

        # Bot1 (a2) has 1 comment
        assert results.actor_scores.loc["a2", "comment_count"] == 1

    def test_run_paper_scorer(self, ds):
        @scorer(entity="paper")
        def vote_count(paper, ds):
            return len(ds.votes.for_target(paper.id))

        results = run_all(ds)
        assert len(results.paper_scores) == 3
        assert "vote_count" in results.paper_scores.columns

        # p1 has 3 votes
        assert results.paper_scores.loc["p1", "vote_count"] == 3

    def test_multiple_scorers(self, ds):
        @scorer(entity="actor")
        def score_a(actor, ds):
            return 1.0

        @scorer(entity="actor")
        def score_b(actor, ds):
            return 2.0

        results = run_all(ds)
        assert "score_a" in results.actor_scores.columns
        assert "score_b" in results.actor_scores.columns
        assert results.actor_scores["score_a"].iloc[0] == 1.0
        assert results.actor_scores["score_b"].iloc[0] == 2.0

    def test_results_include_metadata(self, ds):
        @scorer(entity="actor")
        def dummy(actor, ds):
            return 0

        results = run_all(ds)
        assert "name" in results.actor_scores.columns
        assert "actor_type" in results.actor_scores.columns

    def test_results_repr(self, ds):
        @scorer(entity="actor")
        def x(actor, ds):
            return 0

        results = run_all(ds)
        assert "ScorerResults" in repr(results)


class TestBuiltinScorers:
    """These tests need the builtins re-registered after clean_registry clears them."""

    def _register_builtins(self):
        """Re-register builtins since the autouse fixture clears them."""
        import importlib
        import coalescence.scorer.builtins as mod
        importlib.reload(mod)

    def test_builtins_register(self, ds):
        self._register_builtins()
        scorers = list_scorers()
        assert ("actor", "comment_depth") in scorers
        assert ("actor", "community_trust") in scorers
        assert ("actor", "domain_breadth") in scorers
        assert ("paper", "engagement") in scorers
        assert ("paper", "controversy") in scorers

    def test_builtins_produce_values(self, ds):
        self._register_builtins()
        results = run_all(ds)

        # comment_depth for Bot1 (1 comment, 47 chars)
        assert results.actor_scores.loc["a2", "comment_depth"] == 47.0

        # controversy for p1 (1 downvote / 6 total)
        assert results.paper_scores.loc["p1", "controversy"] == pytest.approx(1 / 6)

        # engagement for p1 (1 root thread * 2 + 3 votes)
        assert results.paper_scores.loc["p1", "engagement"] == 5

    def test_to_jsonl(self, ds, tmp_path):
        self._register_builtins()
        results = run_all(ds)
        results.to_jsonl(str(tmp_path / "scores"))
        assert (tmp_path / "scores" / "actor_scores.jsonl").exists()
        assert (tmp_path / "scores" / "paper_scores.jsonl").exists()
