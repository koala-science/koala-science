"""Tests for derived-result memoization on the eval dashboard.

The metrics page fires 4 parallel API calls against the same cached dataset.
Without memoization, `run_all(ds)` and `_compute_paper_agreement(ds)` are
recomputed on every endpoint hit, tripling the work of a single page load.

These tests pin the expected call counts for those hot paths so the caching
layer can't silently regress.
"""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from coalescence.dashboard import api as dashboard_api
from coalescence.dashboard import cache as dashboard_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    dashboard_cache.invalidate()
    yield
    dashboard_cache.invalidate()


def test_scorer_results_memoized_across_builders(ds):
    """`run_all` is invoked exactly once across all builders for one ds."""
    real_run_all = dashboard_api.run_all
    call_count = 0

    def counting_run_all(d):
        nonlocal call_count
        call_count += 1
        return real_run_all(d)

    with patch.object(dashboard_api, "run_all", counting_run_all):
        dashboard_api.build_paper_leaderboard(ds)
        dashboard_api.build_reviewer_leaderboard(ds)
        dashboard_api.build_merged_leaderboard(ds)

    assert call_count == 1, f"expected 1 run_all call, got {call_count}"


def test_paper_agreement_memoized_across_builders(ds):
    """`_compute_paper_agreement` is invoked once across summary + papers."""
    real_fn = dashboard_api._compute_paper_agreement
    call_count = 0

    def counting(d):
        nonlocal call_count
        call_count += 1
        return real_fn(d)

    with patch.object(dashboard_api, "_compute_paper_agreement", counting):
        dashboard_api.build_summary(ds)
        dashboard_api.build_paper_leaderboard(ds)

    assert call_count == 1, f"expected 1 agreement call, got {call_count}"


def test_plugin_scores_memoized_across_calls(ds):
    """`_compute_plugin_scores` is invoked once across repeated ranking calls."""
    real_fn = dashboard_api._compute_plugin_scores
    call_count = 0

    def counting(d):
        nonlocal call_count
        call_count += 1
        return real_fn(d)

    with patch.object(dashboard_api, "_compute_plugin_scores", counting):
        dashboard_api.build_ranking_comparison(ds)
        dashboard_api.build_ranking_comparison(ds)

    assert call_count == 1, f"expected 1 plugin_scores call, got {call_count}"


def test_cache_invalidates_when_dataset_changes(dump_dir):
    """New Dataset instance triggers a fresh compute."""
    from coalescence.data import Dataset

    ds1 = Dataset.load(str(dump_dir))
    ds2 = Dataset.load(str(dump_dir))
    real_run_all = dashboard_api.run_all
    call_count = 0

    def counting(d):
        nonlocal call_count
        call_count += 1
        return real_run_all(d)

    with patch.object(dashboard_api, "run_all", counting):
        dashboard_api.build_reviewer_leaderboard(ds1)
        dashboard_api.build_reviewer_leaderboard(ds2)

    assert call_count == 2, (
        f"expected 2 run_all calls across datasets, got {call_count}"
    )


def test_explicit_invalidate_drops_cache(ds):
    real_run_all = dashboard_api.run_all
    call_count = 0

    def counting(d):
        nonlocal call_count
        call_count += 1
        return real_run_all(d)

    with patch.object(dashboard_api, "run_all", counting):
        dashboard_api.build_reviewer_leaderboard(ds)
        dashboard_cache.invalidate()
        dashboard_api.build_reviewer_leaderboard(ds)

    assert call_count == 2


def test_concurrent_builders_single_flight(ds):
    """Concurrent callers on a cache miss share one computation."""
    import time

    real_run_all = dashboard_api.run_all
    call_count = 0
    lock = threading.Lock()

    def counting(d):
        nonlocal call_count
        with lock:
            call_count += 1
        # Force overlap: hold the computation long enough that a second
        # thread racing on the same key is guaranteed to observe a pending
        # Future rather than a completed cache entry.
        time.sleep(0.05)
        return real_run_all(d)

    with patch.object(dashboard_api, "run_all", counting):
        threads = [
            threading.Thread(
                target=dashboard_api.build_reviewer_leaderboard, args=(ds,)
            )
            for _ in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert call_count == 1, f"expected 1 call under concurrent miss, got {call_count}"


def test_compute_exception_does_not_poison_cache(ds):
    """A failed compute must not leave a broken Future in the cache."""
    attempts = 0

    def boom():
        nonlocal attempts
        attempts += 1
        raise RuntimeError("first call fails")

    with pytest.raises(RuntimeError):
        dashboard_cache.memoize_derived(ds, "boom", boom)

    def ok():
        return 42

    assert dashboard_cache.memoize_derived(ds, "boom", ok) == 42
    assert attempts == 1
