"""HTTP-level tests for the eval dashboard endpoints.

Requires FastAPI + httpx; skipped when either is unavailable. Covers:

- `/api/metrics` returns the combined payload shape.
- ETag/Cache-Control headers are set and drive a 304 on replay.
- The derived-result cache is invalidated when the dataset refreshes.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from tests.conftest import (  # noqa: E402
    ACTORS,
    COMMENTS,
    DOMAINS,
    EVENTS,
    PAPERS,
    VOTES,
)


def _write_dump(dest: Path) -> None:
    for name, data in [
        ("papers", PAPERS),
        ("comments", COMMENTS),
        ("votes", VOTES),
        ("actors", ACTORS),
        ("events", EVENTS),
        ("domains", DOMAINS),
    ]:
        (dest / f"{name}.jsonl").write_text(
            "\n".join(json.dumps(r) for r in data) + "\n"
        )


@pytest.fixture
def client(tmp_path, monkeypatch):
    _write_dump(tmp_path)
    monkeypatch.setenv("DUMP_DIR", str(tmp_path))

    import dashboard as dashboard_module

    importlib.reload(dashboard_module)
    app = dashboard_module.create_app("x@y", "pw")
    with TestClient(app) as c:
        yield c, dashboard_module


def test_combined_metrics_returns_all_sections(client):
    c, _ = client
    r = c.get("/api/metrics")
    assert r.status_code == 200
    assert set(r.json().keys()) == {"summary", "papers", "reviewers", "rankings"}


def test_metrics_sets_etag_and_cache_control(client):
    c, _ = client
    r = c.get("/api/metrics")
    assert r.headers.get("etag", "").startswith('W/"')
    assert "max-age" in r.headers.get("cache-control", "")


def test_conditional_get_returns_304(client):
    c, _ = client
    r1 = c.get("/api/metrics")
    r2 = c.get("/api/metrics", headers={"if-none-match": r1.headers["etag"]})
    assert r2.status_code == 304


def test_individual_endpoints_still_work(client):
    c, _ = client
    for path in [
        "/api/summary",
        "/api/papers",
        "/api/reviewers",
        "/api/rankings",
        "/api/merged",
    ]:
        r = c.get(path)
        assert r.status_code == 200, path
        assert r.headers.get("etag"), path


def test_dataset_refresh_invalidates_derived_cache(client, monkeypatch):
    c, dashboard_module = client
    from coalescence.dashboard import cache as derived_cache

    # Prime the cache.
    c.get("/api/metrics")

    # Force get_dataset to refresh on next call, then verify the cache is
    # empty *before* the first new derivation runs.
    dashboard_module._cache["ts"] = 0
    observed: list[int] = []
    real_invalidate = derived_cache.invalidate

    def spy_invalidate():
        observed.append(1)
        real_invalidate()

    monkeypatch.setattr(derived_cache, "invalidate", spy_invalidate)
    c.get("/api/metrics")
    assert observed, "derived_cache.invalidate was not called on ds refresh"
