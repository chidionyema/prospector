"""V2 — the coverage sampler: steer generation by MEASURED under-coverage, not by prompt.

Pure Python, zero LLM calls, read-only against `store/prospector.db`.

Why these four axes and not `sector`
------------------------------------
The register's original wording said "(sector x persona x tier x market)". There is no
`sector` column in the `dossiers` table and generation never writes one — it exists only as
prompt text, so a sampler built on it could never measure its own effect. The four axes below
are ALL real columns on `dossiers`, and all are stamped at generation time:

    ambition_tier    generate.py (lane stamp)     column `ambition_tier`
    structural_form  generate.py (form rotation)  column `structural_form`
    audience         generate.py `tags["audience"]` column `audience`
    market           generate.py (run market)     column `market`

"sector" is dropped-because-unmeasurable.

Blanks are told the truth about, never backfilled
-------------------------------------------------
Coverage of those columns is uneven (measured 2026-08-07 over 1,762 rows: ambition_tier 1,186
blank = 67%; structural_form 186; audience 219; market 17). Backfilling is a money-rail action
and is NOT authorised here. So:

  * a blank is an explicit cell value, `UNKNOWN` ("unknown"), never silently dropped;
  * `min_coverage` suppresses any axis whose KNOWN share falls below it, so an axis that is
    mostly blank cannot silently dominate the sampling with a fake "under-covered" signal;
  * `unknown` is never a generation TARGET — you cannot instruct a model to produce an
    unlabelled cell — but it is always visible in the receipt.

Determinism
-----------
A sampler you cannot replay is not measurable. Every selection is a pure function of
(distribution, domains, n, seed). With `seed` unset the seed is derived from a stable hash of
the measured distribution, so replaying against the same DB reproduces the same plan.
"""

from __future__ import annotations

import hashlib
import random
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

from .telemetry import logger

#: The only column names this module will ever interpolate into SQL. Whitelist, not
#: escaping: an axis name from config reaches a `SELECT <col>`, so anything outside this
#: tuple raises rather than being quoted.
AXES: tuple[str, ...] = ("ambition_tier", "structural_form", "audience", "market")

#: Explicit cell value for a blank/NULL column. Counted, reported, never targeted.
UNKNOWN = "unknown"

_METHODS = ("quota", "entropy")
_UNKNOWN_POLICIES = ("include", "exclude")


# --------------------------------------------------------------------------- config


@dataclass(frozen=True)
class SamplerConfig:
    """`cfg.coverage_sampler`, validated. Defaults land the sampler INERT."""

    enabled: bool = False
    axes: tuple[str, ...] = AXES
    method: str = "quota"
    unknown_policy: str = "include"
    recent_window: int = 200
    min_coverage: float = 0.25
    seed: Optional[int] = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "SamplerConfig":
        raw = dict(raw or {})
        axes_raw = raw.get("axes") or AXES
        axes = tuple(str(a).strip() for a in axes_raw if str(a).strip())
        bad = [a for a in axes if a not in AXES]
        if bad:
            raise ValueError(
                f"coverage_sampler.axes contains unknown axis/axes {bad}; "
                f"allowed: {list(AXES)}")
        method = str(raw.get("method", "quota") or "quota").strip().lower()
        if method not in _METHODS:
            raise ValueError(
                f"coverage_sampler.method={method!r} unknown; allowed: {list(_METHODS)}")
        policy = str(
            raw.get("unknown_policy", "include") or "include").strip().lower()
        if policy not in _UNKNOWN_POLICIES:
            raise ValueError(
                f"coverage_sampler.unknown_policy={policy!r} unknown; "
                f"allowed: {list(_UNKNOWN_POLICIES)}")
        seed_raw = raw.get("seed")
        return cls(
            enabled=bool(raw.get("enabled", False)),
            axes=axes or AXES,
            method=method,
            unknown_policy=policy,
            recent_window=max(0, int(raw.get("recent_window", 200) or 0)),
            min_coverage=float(raw.get("min_coverage", 0.25) or 0.0),
            seed=None if seed_raw is None else int(seed_raw),
        )

    @classmethod
    def from_config(cls, cfg: Any) -> "SamplerConfig":
        """Read `cfg.coverage_sampler` defensively — a Config predating V2 is fine."""
        return cls.from_mapping(getattr(cfg, "coverage_sampler", {}) or {})


# ---------------------------------------------------------------------- measurement


@dataclass(frozen=True)
class AxisCoverage:
    """What the catalogue actually contains on one axis."""

    axis: str
    rows: int                                                    # ALL rows in scope
    blank: int = 0                                               # rows with no value here
    counts: dict[str, int] = field(default_factory=dict)         # UNKNOWN iff policy=include
    recent_counts: dict[str, int] = field(default_factory=dict)

    @property
    def unknown(self) -> int:
        """Blank rows. Tracked separately from `counts` so that `unknown_policy: exclude`
        hides blanks from the SAMPLING domain without hiding them from the min_coverage
        guard — otherwise excluding them would read as 100% coverage and the guard, whose
        entire job is to catch a mostly-blank axis, could never fire."""
        return int(self.blank)

    @property
    def known(self) -> int:
        return int(self.rows - self.blank)

    @property
    def coverage(self) -> float:
        """Share of rows carrying a real value on this axis. 0.0 when there are no rows."""
        return (self.known / self.rows) if self.rows else 0.0

    @property
    def observed(self) -> tuple[str, ...]:
        """Known values, most frequent first — the fallback sampling domain."""
        vals = [(v, n) for v, n in self.counts.items() if v != UNKNOWN]
        vals.sort(key=lambda vn: (-vn[1], vn[0]))
        return tuple(v for v, _ in vals)

    @property
    def distinct(self) -> int:
        return len(self.observed)


@dataclass(frozen=True)
class CoverageReport:
    rows: int
    axes: dict[str, AxisCoverage]
    suppressed: dict[str, str] = field(default_factory=dict)
    context: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "context": dict(self.context),
            "suppressed": dict(self.suppressed),
            "axes": {
                a: {
                    "distinct": c.distinct,
                    "unknown": c.unknown,
                    "coverage": round(c.coverage, 4),
                    "counts": dict(c.counts),
                    "recent_counts": dict(c.recent_counts),
                }
                for a, c in self.axes.items()
            },
        }

    def fingerprint(self) -> str:
        """Stable hash of the distribution — the default seed source."""
        h = hashlib.sha256()
        for axis in sorted(self.axes):
            c = self.axes[axis]
            h.update(axis.encode())
            for v in sorted(c.counts):
                h.update(f"|{v}={c.counts[v]}".encode())
        return h.hexdigest()


def _norm(value: Any) -> str:
    s = str(value or "").strip().lower()
    return s or UNKNOWN


def _connect_ro(db_path: Path | str) -> sqlite3.Connection:
    """Open the production index READ-ONLY. The DB is production state."""
    return sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)


def measure(
    db_path: Path | str,
    scfg: SamplerConfig,
    *,
    context: Mapping[str, str] | None = None,
) -> CoverageReport:
    """Read the catalogue + recent-window distribution over `scfg.axes`. Read-only."""
    ctx = {
        a: _norm(v)
        for a, v in (context or {}).items()
        if a in AXES and str(v or "").strip()
    }
    where = ""
    params: list[Any] = []
    for axis, value in sorted(ctx.items()):
        where += f" AND lower(trim(coalesce({axis},''))) = ?"
        params.append(value)

    axes: dict[str, AxisCoverage] = {}
    suppressed: dict[str, str] = {}
    total = 0
    conn = _connect_ro(db_path)
    try:
        total = int(conn.execute(
            f"SELECT count(*) FROM dossiers WHERE 1=1{where}", params).fetchone()[0])
        for axis in scfg.axes:
            if axis not in AXES:  # defence in depth; from_mapping already validated
                raise ValueError(f"unknown axis {axis!r}")
            counts: dict[str, int] = {}
            rows = conn.execute(
                f"SELECT lower(trim(coalesce({axis},''))) AS v, count(*) "
                f"FROM dossiers WHERE 1=1{where} GROUP BY v", params).fetchall()
            for v, n in rows:
                counts[_norm(v)] = counts.get(_norm(v), 0) + int(n)
            recent: dict[str, int] = {}
            if scfg.recent_window:
                rrows = conn.execute(
                    f"SELECT lower(trim(coalesce({axis},''))) FROM dossiers "
                    f"WHERE 1=1{where} ORDER BY coalesce(created_at,'') DESC, rowid DESC "
                    f"LIMIT ?", [*params, int(scfg.recent_window)]).fetchall()
                for (v,) in rrows:
                    key = _norm(v)
                    recent[key] = recent.get(key, 0) + 1
            blank = int(counts.get(UNKNOWN, 0))
            if scfg.unknown_policy == "exclude":
                counts.pop(UNKNOWN, None)
                recent.pop(UNKNOWN, None)
            cov = AxisCoverage(
                axis=axis, rows=total, blank=blank, counts=counts, recent_counts=recent)
            axes[axis] = cov
            if cov.coverage < scfg.min_coverage:
                suppressed[axis] = (
                    f"coverage {cov.coverage:.2%} < min_coverage {scfg.min_coverage:.2%} "
                    f"({cov.unknown} of {cov.rows} rows blank)")
            elif cov.distinct < 2:
                suppressed[axis] = f"only {cov.distinct} distinct known value(s)"
    finally:
        conn.close()

    return CoverageReport(rows=total, axes=axes, suppressed=suppressed, context=ctx)


# ------------------------------------------------------------------------ selection


def _stable_key(seed: int, axis: str, value: str) -> str:
    return hashlib.sha256(f"{seed}|{axis}|{value}".encode()).hexdigest()


def _blended_share(cov: AxisCoverage, domain: Sequence[str]) -> dict[str, float]:
    """Share per domain value over catalogue + recent counts (recent counted twice).

    Double-counting the recent window is the recency weight: a value the catalogue is full
    of but which has not been generated lately still reads as partially recovered.
    """
    blended = {
        v: float(cov.counts.get(v, 0) + cov.recent_counts.get(v, 0)) for v in domain
    }
    total = sum(blended.values())
    if total <= 0:
        return {v: 0.0 for v in domain}
    return {v: n / total for v, n in blended.items()}


def _rank_by_deficit(
    cov: AxisCoverage, domain: Sequence[str], seed: int
) -> list[tuple[str, float]]:
    target = 1.0 / len(domain)
    share = _blended_share(cov, domain)
    scored = [(v, target - share[v]) for v in domain]
    # Deterministic tie-break: hash of (seed, axis, value), never dict/insertion order.
    scored.sort(key=lambda vs: (-vs[1], _stable_key(seed, cov.axis, vs[0])))
    return scored


def sampling_domains(
    report: CoverageReport,
    scfg: SamplerConfig,
    domains: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, list[str]]:
    """The selectable values per axis: configured domain ∩ sanity, else observed values.

    A suppressed axis (see `min_coverage`) yields nothing — it is measured and reported,
    but it never steers a batch.
    """
    out: dict[str, list[str]] = {}
    for axis in scfg.axes:
        if axis in report.suppressed:
            continue
        cov = report.axes.get(axis)
        if cov is None:
            continue
        supplied = [
            _norm(v) for v in (domains or {}).get(axis, []) or [] if str(v or "").strip()
        ]
        # THE TRAP THIS NAMES. Falling back to `cov.observed` targets whatever the catalogue
        # happens to contain, which is NOT the same set as what generation can produce.
        # Measured 2026-08-08: `structural_form` holds 29 distinct values against 8 in
        # `config.yaml generation.structural_forms` — 21 of them (421 rows) are vocabularies
        # from earlier configs, still entering the index because the drain keeps vetting
        # candidates minted under them. `generate.py:273` does supply the configured domain,
        # so the shipped path is correct; a caller that forgets would silently aim 72% of its
        # quota at forms `prompts/generate.md` can no longer be asked for, and the deficit
        # would never close because the target is unreachable. Loud, not fatal: steering must
        # never be able to stop generation (see `plan_cells`).
        # INFO, not WARNING: two of the four axes (`ambition_tier`, `market`) have no
        # configured vocabulary under `generation` at all, so warning here would fire on every
        # tick for a condition that is correct. The load-bearing artifact is `off_domain_values`
        # in the receipt — a MEASUREMENT of the drift — not this line.
        if not supplied and cov.observed:
            logger.info(
                f"coverage sampler: no configured domain supplied for axis {axis!r}; falling "
                f"back to the {len(cov.observed)} value(s) OBSERVED in the catalogue. Any of "
                "these that generation can no longer produce is an unreachable target.",
                extra={"axis": axis, "observed": len(cov.observed)})
        vals = supplied or list(cov.observed)
        # `unknown` is never a generation TARGET: an unlabelled cell is not an instruction.
        vals = [v for v in dict.fromkeys(vals) if v != UNKNOWN]
        if vals:
            out[axis] = vals
    return out


def off_domain_values(
    report: CoverageReport,
    domains: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, dict[str, int]]:
    """Per axis: catalogue values that are NOT in the supplied (configured) domain, with counts.

    This is the vocabulary-drift meter. It measures the corpus against what generation can be
    asked for, so an axis whose history spans several config generations says so on its face
    instead of quietly inflating the denominator of any entropy or coverage figure computed
    over it. An empty dict per axis means the corpus and the config agree.
    """
    out: dict[str, dict[str, int]] = {}
    for axis, cov in report.axes.items():
        allowed = {_norm(v) for v in (domains or {}).get(axis, []) or [] if str(v or "").strip()}
        if not allowed:
            continue
        drift = {v: int(cov.counts.get(v, 0))
                 for v in cov.observed if v != UNKNOWN and v not in allowed}
        if drift:
            out[axis] = dict(sorted(drift.items(), key=lambda kv: -kv[1]))
    return out


def select_cells(
    report: CoverageReport,
    scfg: SamplerConfig,
    n: int,
    *,
    domains: Mapping[str, Iterable[str]] | None = None,
    seed: Optional[int] = None,
) -> list[dict[str, str]]:
    """Pick `n` target cells by under-coverage. Pure, deterministic on `seed`.

    `quota`   — rank each axis by deficit (uniform target share minus blended observed
                share) and deal ranked values round-robin across the n cells, each axis
                rotated by its own seed-derived offset so cells do not lock to a diagonal.
    `entropy` — weighted sampling with weights ∝ max(deficit, 0) + eps; the same ranking
                signal, but stochastic (seeded), so repeated ticks explore rather than
                marching the same order.
    """
    n = max(0, int(n))
    if n == 0:
        return []
    dom = sampling_domains(report, scfg, domains)
    if not dom:
        return []
    eff_seed = scfg.seed if scfg.seed is not None else seed
    if eff_seed is None:
        eff_seed = int(report.fingerprint()[:12], 16)
    eff_seed = int(eff_seed)

    cells: list[dict[str, str]] = [{} for _ in range(n)]
    for axis in sorted(dom):
        values = dom[axis]
        ranked = [v for v, _ in _rank_by_deficit(report.axes[axis], values, eff_seed)]
        if scfg.method == "entropy":
            cov = report.axes[axis]
            target = 1.0 / len(values)
            share = _blended_share(cov, values)
            weights = [max(target - share[v], 0.0) + 1e-6 for v in values]
            rng = random.Random(_stable_key(eff_seed, axis, "entropy"))
            picks = rng.choices(values, weights=weights, k=n)
            for i in range(n):
                cells[i][axis] = picks[i]
        else:  # quota
            offset = int(_stable_key(eff_seed, axis, "offset")[:8], 16) % len(ranked)
            for i in range(n):
                cells[i][axis] = ranked[(offset + i) % len(ranked)]
    for cell in cells:
        cell.update(report.context)
    return cells


def cell_directive(cell: Mapping[str, str]) -> str:
    """Render a cell as a one-line generation constraint (the LLM works INSIDE it)."""
    parts = [f"{a}={cell[a]}" for a in AXES if cell.get(a)]
    return "; ".join(parts)


# -------------------------------------------------------------------------- wire-in


def db_path_for(cfg: Any) -> Optional[Path]:
    try:
        p = Path(cfg.store_dir) / "prospector.db"
    except Exception:  # noqa: BLE001 — a stub Config in a test has no store_dir
        return None
    return p if p.exists() else None


def plan_cells(
    cfg: Any,
    k: int,
    *,
    domains: Mapping[str, Iterable[str]] | None = None,
    context: Mapping[str, str] | None = None,
    db_path: Path | str | None = None,
) -> list[dict[str, str]]:
    """Entry point for generation. Returns [] whenever the sampler must not steer.

    [] is returned when the sampler is disabled (the default), when the DB is absent, when
    every axis is suppressed, or when anything at all goes wrong — this feature must never
    be able to stop the daemon generating.
    """
    try:
        scfg = SamplerConfig.from_config(cfg)
    except ValueError as e:
        logger.warning(f"coverage sampler config invalid, staying inert: {e}")
        return []
    if not scfg.enabled:
        return []
    path = Path(db_path) if db_path else db_path_for(cfg)
    if path is None or not Path(path).exists():
        logger.warning("coverage sampler enabled but no dossier index found; staying inert")
        return []
    try:
        report = measure(path, scfg, context=context)
        cells = select_cells(report, scfg, k, domains=domains)
    except Exception as e:  # noqa: BLE001 — steering must never break generation
        logger.warning(f"coverage sampler failed, falling back to rotation: {e}")
        return []
    if not cells:
        logger.info(
            "coverage sampler produced no cells (all axes suppressed?); using rotation",
            extra={"suppressed": report.suppressed})
        return []
    logger.info(
        f"coverage sampler: {len(cells)} cell(s) by {scfg.method} over "
        f"{sorted(cells[0])} from {report.rows} rows",
        extra={"method": scfg.method, "cells": len(cells), "rows": report.rows,
               "suppressed": sorted(report.suppressed)})
    return cells


def receipt(
    cfg: Any,
    k: int,
    *,
    domains: Mapping[str, Iterable[str]] | None = None,
    context: Mapping[str, str] | None = None,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Measurement + plan as a JSON-able receipt (for `tools/`, diagnostics, tests)."""
    scfg = SamplerConfig.from_config(cfg)
    path = Path(db_path) if db_path else db_path_for(cfg)
    if path is None:
        return {"enabled": scfg.enabled, "error": "no dossier index"}
    report = measure(path, scfg, context=context)
    cells = select_cells(report, scfg, k, domains=domains)
    return {
        "enabled": scfg.enabled,
        "method": scfg.method,
        "unknown_policy": scfg.unknown_policy,
        "min_coverage": scfg.min_coverage,
        "recent_window": scfg.recent_window,
        "seed": scfg.seed,
        "fingerprint": report.fingerprint()[:16],
        "coverage": report.to_dict(),
        "off_domain": off_domain_values(report, domains),
        "cells": cells,
    }
