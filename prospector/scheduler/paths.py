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

CORRECTION (2026-08-06, same day): this module originally cited 110 epoch-stamped rows in
`store/scheduler/ticks.jsonl` as proof that a test had written into the live store, calling
them "a fabricated shape no real tick has ever had". **That was wrong, and every tell it
rested on is the file's own norm.** Re-measured over all 1312 rows:

    claimed tell                          actual
    ------------------------------------  ------------------------------------------------
    unique shape                          that key set is 1069/1312 rows, incl. BOTH of the
                                          block's immediate neighbours
    "result": {"dossiers": 0, ...}        58% of non-1970 rows
    "$0.0000 of $20.00 spent today"       53% of non-1970 rows
    out-of-order seam around it           28 such seams exist file-wide; this one is ordinary

Positively, they look like daemon ticks under a clock reading epoch: gaps run min 320s /
median 2279s (~38 min) with **zero** under 10 seconds — interval spacing, not a loop — and
they carry `batch_size: 5`, the config value from *before* the founder's 2026-07-31 change to
15 (`config.yaml:946,950`). A test double written today would carry 15. The two rows this
module also claimed were "written and removed on 2026-08-06" cannot be re-checked either:
`ticks.jsonl` is untracked, so there is no history to audit. Treat it as a first-hand note.

None of that weakens the fence, because the fence never needed those rows. What justifies it
is the mechanism plus a demonstrated sibling: `_AUDIT_DIR` is bound at import
(`prospector/audit.py:133-136`), which is how pytest reached the production audit log. A
cwd-relative default is the same bug with a worse blast radius, and the answer is the same —
make the unconfigured case impossible rather than quiet.

The lesson is also the reason this paragraph is long: "no real X has ever looked like that" is
a claim about a whole population, and it is cheap to check against the population before
writing it down. Not checking is what put a confident falsehood in a fence's own docstring.

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
            "resolves to the LIVE store under pytest, whose cwd is the repo root — the same bug "
            "that let tests reach the production audit log (prospector/audit.py:133). "
            "Tests must pass store_dir=tmp_path."
        )
    return Path(d)


def scheduler_dir(cfg, *, create: bool = True) -> Path:
    """`<store>/scheduler`, created on demand. The scheduler's own state lives here."""
    d = store_dir(cfg) / "scheduler"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d
