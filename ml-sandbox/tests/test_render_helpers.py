"""Tests for dashboard render helpers and scorer display param."""

from __future__ import annotations

import pandas as pd

from coalescence.dashboard.render import distribution_summary, render_cell
from coalescence.scorer import clear_registry, get_display_hint, scorer


# ---------------------------------------------------------------------------
# render_cell — explicit display modes
# ---------------------------------------------------------------------------


def test_bar_contains_fill_and_label():
    html = render_cell(5.0, 10.0, display="bar")
    assert "width:50.0%" in html
    assert "5.00" in html


def test_bar_zero_max_does_not_crash():
    html = render_cell(0.0, 0.0, display="bar")
    assert "0.00" in html


def test_badge_green_for_high_value():
    html = render_cell(8.0, 10.0, display="badge")
    assert "green" in html
    assert "8.00" in html


def test_badge_blue_for_mid_value():
    html = render_cell(5.0, 10.0, display="badge")
    assert "blue" in html


def test_badge_gray_for_zero():
    html = render_cell(0.0, 10.0, display="badge")
    assert "gray" in html


def test_badge_red_for_negative():
    html = render_cell(-1.0, 10.0, display="badge")
    assert "red" in html
    assert "-1.00" in html


def test_pct_renders_percentage():
    html = render_cell(0.75, 1.0, display="pct")
    assert "75.0%" in html


def test_pct_opacity_scaling():
    html = render_cell(0.4, 1.0, display="pct")
    assert "opacity:0.40" in html


def test_num_plain():
    html = render_cell(42.0, 100.0, display="num")
    assert html == "<span>42.00</span>"


# ---------------------------------------------------------------------------
# render_cell — auto-detection
# ---------------------------------------------------------------------------


def test_auto_negative_becomes_badge():
    html = render_cell(-3.0, 10.0)
    assert "red" in html


def test_auto_zero_to_one_becomes_pct():
    html = render_cell(0.6, 1.0)
    assert "%" in html


def test_auto_large_positive_becomes_bar():
    html = render_cell(7.0, 10.0)
    assert "width:" in html


# ---------------------------------------------------------------------------
# distribution_summary
# ---------------------------------------------------------------------------


def test_distribution_summary_stats():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    html = distribution_summary(s)
    # median=3, p90=4.6, max=5
    assert "3.00" in html
    assert "5.00" in html
    assert "|" in html


def test_distribution_summary_empty():
    assert distribution_summary(pd.Series([], dtype=float)) == ""


def test_distribution_summary_all_nan():
    assert distribution_summary(pd.Series([float("nan"), float("nan")])) == ""


# ---------------------------------------------------------------------------
# scorer display param + get_display_hint
# ---------------------------------------------------------------------------


def test_scorer_stores_display_hint():
    clear_registry()

    @scorer(entity="actor", dimension="score", display="bar")
    def score(actor, ds):
        return 1.0

    assert get_display_hint("actor", "score") == "bar"


def test_scorer_default_display_is_none():
    clear_registry()

    @scorer(entity="actor", dimension="plain")
    def plain(actor, ds):
        return 0.0

    assert get_display_hint("actor", "plain") is None


def test_get_display_hint_missing_returns_none():
    clear_registry()
    assert get_display_hint("actor", "nonexistent") is None
