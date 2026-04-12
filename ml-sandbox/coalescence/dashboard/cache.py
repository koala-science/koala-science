"""Derived-result memoization for the eval dashboard.

The raw Dataset is already cached for ``CACHE_TTL`` seconds in
``dashboard.py``. This module layers a second cache on top of that: derived
results (`run_all`, `_compute_paper_agreement`, `_compute_plugin_scores`) are
memoized per dataset identity so a metrics page load recomputes each exactly
once instead of once per endpoint.

Key properties:

- Single-flight: concurrent callers racing on a cache miss share the same
  ``Future``, so the compute runs once even under parallel request bursts.
- Dataset-scoped: the first access with a new ``id(ds)`` wipes older entries,
  bounding memory to one dataset's derived state at a time.
- Exception-safe: a failed compute is evicted instead of being cached, so the
  next caller retries rather than re-raising a stale exception forever.
"""

from __future__ import annotations

import threading
from concurrent.futures import Future
from typing import Any, Callable

_lock = threading.Lock()
_cache: dict[tuple[int, str], Future] = {}
_current_ds_id: int | None = None


def memoize_derived(ds: Any, key: str, compute: Callable[[], Any]) -> Any:
    """Return a cached derived value for ``ds``, computing it at most once.

    ``key`` discriminates distinct derivations on the same dataset (e.g.
    ``"scorer_results"`` vs ``"paper_agreement"``). ``compute`` is a zero-arg
    callable that produces the value on a miss.
    """
    global _current_ds_id
    ds_id = id(ds)
    cache_key = (ds_id, key)

    with _lock:
        if _current_ds_id is not None and _current_ds_id != ds_id:
            _cache.clear()
        _current_ds_id = ds_id

        future = _cache.get(cache_key)
        if future is None:
            future = Future()
            _cache[cache_key] = future
            owner = True
        else:
            owner = False

    if owner:
        try:
            future.set_result(compute())
        except BaseException as exc:
            future.set_exception(exc)
            with _lock:
                _cache.pop(cache_key, None)

    return future.result()


def invalidate() -> None:
    """Drop all cached derived results. Call when the underlying ds refreshes."""
    global _current_ds_id
    with _lock:
        _cache.clear()
        _current_ds_id = None
