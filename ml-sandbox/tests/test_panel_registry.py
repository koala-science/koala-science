"""Tests for coalescence.dashboard panel registry."""

import pytest
from coalescence.dashboard import panel, list_panels, render_all, clear_panels


@pytest.fixture(autouse=True)
def clean_registry():
    """Isolate each test: clear panels before and after."""
    clear_panels()
    yield
    clear_panels()


# --- Registration ---


def test_register_single_panel():
    @panel(title="Overview", order=0)
    def overview(ds):
        return "<p>hello</p>"

    specs = list_panels()
    assert len(specs) == 1
    assert specs[0].title == "Overview"
    assert specs[0].order == 0
    assert specs[0].fn is overview


def test_register_multiple_panels():
    @panel(title="A", order=2)
    def a(ds):
        return ""

    @panel(title="B", order=0)
    def b(ds):
        return ""

    @panel(title="C", order=1)
    def c(ds):
        return ""

    assert len(list_panels()) == 3


# --- Order sorting ---


def test_list_panels_sorted_by_order():
    @panel(title="Third", order=10)
    def third(ds):
        return ""

    @panel(title="First", order=1)
    def first(ds):
        return ""

    @panel(title="Second", order=5)
    def second(ds):
        return ""

    titles = [p.title for p in list_panels()]
    assert titles == ["First", "Second", "Third"]


# --- Clear ---


def test_clear_panels():
    @panel(title="X", order=0)
    def x(ds):
        return ""

    assert len(list_panels()) == 1
    clear_panels()
    assert list_panels() == []


# --- render_all output ---


def test_render_all_empty(ds):
    html = render_all(ds)
    assert html == ""


def test_render_all_wraps_title_and_body(ds):
    @panel(title="My Panel", order=0)
    def my_panel(ds_arg):
        return "<p>content</p>"

    html = render_all(ds)
    assert '<div class="section">' in html
    assert "<h2>My Panel</h2>" in html
    assert "<p>content</p>" in html


def test_render_all_concatenates_in_order(ds):
    @panel(title="Beta", order=1)
    def beta(ds_arg):
        return "<p>beta</p>"

    @panel(title="Alpha", order=0)
    def alpha(ds_arg):
        return "<p>alpha</p>"

    html = render_all(ds)
    assert html.index("Alpha") < html.index("Beta")


# --- Error fallback ---


def test_render_all_error_fallback(ds):
    @panel(title="Broken", order=0)
    def broken(ds_arg):
        raise ValueError("boom")

    html = render_all(ds)
    assert '<div class="error">' in html
    assert "boom" in html
    # Section wrapper still present
    assert "<h2>Broken</h2>" in html


def test_render_all_error_does_not_stop_other_panels(ds):
    @panel(title="Broken", order=0)
    def broken(ds_arg):
        raise RuntimeError("fail")

    @panel(title="Fine", order=1)
    def fine(ds_arg):
        return "<p>ok</p>"

    html = render_all(ds)
    assert "<p>ok</p>" in html
    assert "fail" in html


# --- Two-arg panels receive scorer results ---


def test_two_arg_panel_receives_results(ds):
    received = {}

    @panel(title="Scores", order=0)
    def scores(ds_arg, results):
        received["results"] = results
        return "<p>done</p>"

    render_all(ds)
    assert "results" in received
    # results may be None if no scorers registered, but arg was passed
    # (scorer registry is separate; just verify the slot was filled)


def test_one_arg_panel_not_passed_results(ds):
    call_args = {}

    @panel(title="Simple", order=0)
    def simple(ds_arg):
        call_args["called"] = True
        return ""

    render_all(ds)
    assert call_args.get("called")


def test_render_all_none_ds():
    """render_all(None) skips scorers and still calls panels."""

    @panel(title="NoneDs", order=0)
    def none_panel(ds_arg):
        return f"<p>{ds_arg}</p>"

    html = render_all(None)
    assert "<h2>NoneDs</h2>" in html
    assert "<p>None</p>" in html
