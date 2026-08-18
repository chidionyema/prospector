"""A time-to-live memo cache, replacing `streamlit.cache_data`.

`readers.py` had ten `@st.cache_data(ttl=N)` decorators on functions that read the store from
disk. That was the only reason the ops console's Python backend imported Streamlit at all, and
Streamlit is being deleted (founder, 2026-08-18: "streamlit control centre needs to be deleted
permanently, both code and everything").

The caching itself has to survive the deletion. Those readers walk 3,000-odd dossier files and
a 906,341-line ledger, and the console calls several of them on every page render.

Two differences from `st.cache_data`, both deliberate:

- It is process-wide, not session-scoped. Streamlit kept one cache per browser session; there
  are no sessions here, only a Next.js process shelling out to Python, so one cache is correct.
- It does not hash the return value or copy it. `st.cache_data` returned a deep copy to stop one
  session mutating another's cached object. Every caller here treats the result as read-only.

Arguments must be hashable, which they are at every call site: these readers take a path, a
count or nothing at all.
"""

from __future__ import annotations

import functools
import threading
import time
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

_LOCK = threading.Lock()


def cache_data(ttl: float) -> Callable[[F], F]:
    """Cache a function's return value for `ttl` seconds, keyed on its arguments."""

    def decorate(fn: F) -> F:
        store: dict[tuple, tuple[float, Any]] = {}

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = (args, tuple(sorted(kwargs.items())))
            now = time.monotonic()
            with _LOCK:
                hit = store.get(key)
                if hit is not None and now - hit[0] < ttl:
                    return hit[1]
            # Computed outside the lock: these readers do disk IO, and holding a global lock
            # across it would serialise every reader in the process behind the slowest one.
            value = fn(*args, **kwargs)
            with _LOCK:
                store[key] = (now, value)
            return value

        # Same name as Streamlit's, so the call sites that cleared a cache still work.
        wrapper.clear = lambda: store.clear()  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorate
