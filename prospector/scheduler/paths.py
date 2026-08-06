"""Where the scheduler is allowed to write.

WHY THIS MODULE EXISTS (measured 2026-08-06)
--------------------------------------------
Three separate call sites resolved the store the same wrong way::

    prospector/scheduler/guard.py:201        Path(getattr(cfg, "store_dir", "store"))
    prospector/scheduler/run_scheduled.py:75 Path(getattr(cfg, "store_dir", "store"))
    prospector/scheduler/alerts.py:51        Path(getattr(cfg, "store_dir", "store")) / "scheduler"

The default is a RELATIVE literal. A `cfg` without a `store_dir` attribute therefore does not
fail — it silently resolves to `./store` under whatever the current working directory happens
to be, which for a pytest run is the repo root, which is the LIVE store.

That is not hypothetical. `store/scheduler/ticks.jsonl` carries 110 rows stamped 1970-01-01
through 1970-01-03 (8.8% of all 1258 rows), sitting at line indexes 687..796 between a
2026-07-30T18:43 neighbour and a 2026-07-28T00:50 one. Every one is
`{"batch_size": 5, "result": {"dossiers": 0, ...}, "reason": "ok: $0.0000 of $20.00 spent today"}`
— a fabricated shape no real tick has ever had ($0.0000 spend on a machine that spends, and an
epoch clock). Two more were written and removed on 2026-08-06 while pinning
`test_the_receipt_goes_to_the_configured_store_not_the_cwd`.

This is the same class of bug as `_AUDIT_DIR` binding at import time, which let pytest write
into the production audit log. The fix there and here is the same: make the unconfigured case
impossible rather than quiet.

The real `Config` exposes `store_dir` as a property (`prospector/config.py:302`) honouring
`PROSPECTOR_STORE_DIR`, so it is ALWAYS present in production and raising costs nothing there.
Only a hand-rolled test double can be missing it — and a test double that lands in the live
store is exactly what must fail loudly.
"""
from __future__ import annotations

from pathlib import Path


def store_dir(cfg) -> Path:
    """The store root for `cfg`. Raises rather than guessing.

    There is deliberately no fallback. A default of `"store"` is cwd-dependent (pollutes the
    live store from a test) and a default anchored to `__file__` is worse (pollutes the live
    store from anywhere at all). The only safe answer to "which store?" from a cfg that does
    not say is an exception.
    """
    d = getattr(cfg, "store_dir", None)
    if d is None:
        raise ValueError(
            f"{type(cfg).__name__} has no store_dir; refusing to guess. A cwd-relative default "
            "wrote 110 fabricated tick rows into the live store — see prospector/scheduler/"
            "paths.py. Tests must pass store_dir=tmp_path."
        )
    return Path(d)


def scheduler_dir(cfg, *, create: bool = True) -> Path:
    """`<store>/scheduler`, created on demand. The scheduler's own state lives here."""
    d = store_dir(cfg) / "scheduler"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d
