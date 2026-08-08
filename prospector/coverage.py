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

V2.1 — illumination: a cell is covered to the degree its ideas are good (G7)
-----------------------------------------------------------------------------
V2 counts rows. MAP-Elites/QDAIF (arXiv:2310.13032) count QUALITY: a grid square holds the
best solution found there, and the search keeps pushing on squares whose occupant is weak.
Row count alone cannot tell those apart — a cell with 100 rows whose ideas all score 1.0
reads as thoroughly covered when what it actually is, is thoroughly *failed*.

`quality_weight` (0.0 by default, which is byte-identical to V2 including the seed) discounts
a value's occupancy credit by how good its ideas are:

    credit(v) = count(v) * ((1 - qw) + qw * illum(v)),  illum(v) = stat(v) / best stat

so at qw=1 a cell scoring zero gets zero credit for its rows and is targeted hardest.

`quality_stat` picks the statistic, and the default is `mean`, NOT the QD-canonical `elite`.
The elite was measured on the live index and found to have almost no discriminating power
(1.16x-1.20x spread against 1.71x-2.56x for the mean) — `_illumination` carries the numbers
and the reason. Shipping the canonical choice would have been a lever with no authority.

**Note the polarity, because it is the opposite of G9's and that is deliberate.** This steers
generation TOWARD the cells that have produced the worst ideas, not away from them. It is not
a pass-rate lever and cannot be used as one: it moves no gate, and the direction it pushes is
the direction that costs pass rate in the short run. The justification is that a barren cell
and a badly-attempted cell look identical in a row count, and the only way to tell them apart
is to attempt the cell again with better generation behind it. If a cell is genuinely barren,
that is a finding — and it is one this repo has been wrong about before (chunk C's `smb` cell
looked like weak generation and its modal kill gate was `moat_ungrounded`, a RETRIEVAL
outcome).

Both statistics are computed over rows that were actually RULED and not provisional: a
provisional composite comes from a brain that may not rule (`operator.py:892`), and a DEFER
has no composite to speak for the cell.
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
_QUALITY_STATS = ("mean", "elite")


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
    #: G7. 0.0 = V2 exactly (elites are still MEASURED and reported, they just do not steer).
    #: Clamped to [0,1] rather than validated-and-raised: an out-of-range weight is a typo in
    #: a steering knob, and refusing to generate over a typo is a worse failure than clamping
    #: it and saying so in the receipt.
    quality_weight: float = 0.0
    #: Which per-cell statistic the weight acts on. See `_illumination` for the measurement
    #: that made `mean` the default instead of the QD-canonical `elite`.
    quality_stat: str = "mean"

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
        stat = str(raw.get("quality_stat", "mean") or "mean").strip().lower()
        if stat not in _QUALITY_STATS:
            raise ValueError(
                f"coverage_sampler.quality_stat={stat!r} unknown; "
                f"allowed: {list(_QUALITY_STATS)}")
        seed_raw = raw.get("seed")
        return cls(
            enabled=bool(raw.get("enabled", False)),
            axes=axes or AXES,
            method=method,
            unknown_policy=policy,
            recent_window=max(0, int(raw.get("recent_window", 200) or 0)),
            min_coverage=float(raw.get("min_coverage", 0.25) or 0.0),
            seed=None if seed_raw is None else int(seed_raw),
            quality_weight=min(1.0, max(0.0, float(raw.get("quality_weight", 0.0) or 0.0))),
            quality_stat=stat,
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
    #: G7. Best composite ever RULED in this cell (non-provisional, composite not null).
    #: A value absent here has never produced a ruled row — which is not the same as having
    #: produced a bad one, so `_illumination` treats the two differently.
    elite: dict[str, float] = field(default_factory=dict)
    #: Ruled, non-provisional rows per value — the denominator that says whether an absent
    #: elite means "never tried" or "tried and every attempt is still unfinished".
    ruled: dict[str, int] = field(default_factory=dict)
    #: G7. MEAN composite over the same ruled rows. Measured because the elite turned out
    #: not to discriminate (see `_illumination`); reported always, steers only when
    #: `quality_stat: mean`.
    mean_composite: dict[str, float] = field(default_factory=dict)

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
                    "elite": {k: round(v, 4) for k, v in c.elite.items()},
                    "mean_composite": {k: round(v, 4) for k, v in c.mean_composite.items()},
                    "ruled": dict(c.ruled),
                }
                for a, c in self.axes.items()
            },
        }

    def fingerprint(self) -> str:
        """Stable hash of the distribution — the default seed source.

        Counts only, deliberately: the elites are NOT hashed in. The seed decides tie-breaks
        and rotation offsets, so folding a new signal into it would change the plan on a DB
        where nothing about the distribution moved, and `quality_weight: 0.0` would stop
        being byte-identical to V2 the moment a single verdict landed.
        """
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


def _table_columns(conn: sqlite3.Connection) -> set[str]:
    """Column names on `dossiers`, so a DB predating a column is measured, not refused.

    The elite query (G7) reads `composite`, `provisional` and `decision`. Those arrived by
    migration at different times and an older index legitimately lacks them. Coverage is the
    load-bearing measurement here and elites are an enrichment, so a missing column costs
    the enrichment and nothing else — asking sqlite is one PRAGMA, and the alternative is an
    OperationalError thrown from inside a read-only measurement.
    """
    try:
        return {str(r[1]) for r in conn.execute("PRAGMA table_info(dossiers)").fetchall()}
    except sqlite3.Error:
        return set()


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
        have_elite_cols = {"composite", "provisional", "decision"} <= _table_columns(conn)
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
            # G7 elites. Restricted to rows that were actually RULED and not provisional:
            # a provisional composite comes from a brain that may not rule
            # (`operator.py:892`) and would let a non-ruling model steer generation, and a
            # DEFER has no composite that speaks for the cell at all.
            elite: dict[str, float] = {}
            ruled: dict[str, int] = {}
            mean_c: dict[str, float] = {}
            if have_elite_cols:
                erows = conn.execute(
                    f"SELECT lower(trim(coalesce({axis},''))) AS v, max(composite), "
                    f"count(*), sum(composite) "
                    f"FROM dossiers WHERE composite IS NOT NULL "
                    f"AND coalesce(provisional,0) = 0 "
                    f"AND lower(coalesce(decision,'')) IN ('pass','kill'){where} "
                    f"GROUP BY v", params).fetchall()
                totals: dict[str, float] = {}
                for v, best, cnt, ssum in erows:
                    key = _norm(v)
                    elite[key] = max(elite.get(key, float(best or 0.0)), float(best or 0.0))
                    ruled[key] = ruled.get(key, 0) + int(cnt)
                    totals[key] = totals.get(key, 0.0) + float(ssum or 0.0)
                mean_c = {k: totals[k] / ruled[k] for k in totals if ruled.get(k)}
            blank = int(counts.get(UNKNOWN, 0))
            if scfg.unknown_policy == "exclude":
                counts.pop(UNKNOWN, None)
                recent.pop(UNKNOWN, None)
                elite.pop(UNKNOWN, None)
                ruled.pop(UNKNOWN, None)
                mean_c.pop(UNKNOWN, None)
            cov = AxisCoverage(
                axis=axis, rows=total, blank=blank, counts=counts, recent_counts=recent,
                elite=elite, ruled=ruled, mean_composite=mean_c)
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


def _illumination(cov: AxisCoverage, domain: Sequence[str],
                  stat: str = "mean") -> dict[str, float]:
    """How well-illuminated each value is, in [0,1], relative to the best cell on the axis.

    Three cases, and the difference between the last two is the whole point:

      * a value with a ruled statistic  -> stat(v) / best stat on this axis
      * a value never ruled at all      -> 1.0, i.e. NO quality discount. We know nothing
                                           about it, and inventing a penalty from silence
                                           would let an axis with one lucky ruled value
                                           stampede every other value in the domain.
      * every statistic <= 0            -> 1.0 for all. There is no scale to normalise
                                           against, so the quality term is inert and the
                                           result is exactly the count-based V2 ranking.

    WHY `mean` IS THE DEFAULT AND NOT THE QD-CANONICAL `elite`. Measured on the live index
    (1,789 rows, 2026-08-08), over cells with n >= 30 ruled rows:

        ambition_tier   max: 3.050-3.550 = 1.16x spread   mean: 0.852-2.179 = 2.56x
        audience        max: 2.950-3.550 = 1.20x spread   mean: 0.842-1.437 = 1.71x

    The elite has almost no discriminating power here, and the reason is structural rather
    than incidental: the maximum is an extreme order statistic, and over 40-110 samples per
    cell it has already converged to roughly the same value everywhere. Steering on it would
    be a lever with no authority — the failure mode of memory `rsi-tuned-a-lever-with-no-
    authority.md`, where a knob was tuned for months while reaching 0.9% of what it aimed at.

    `elite` is kept selectable because it is the right statistic for the regime MAP-Elites
    assumes — an archive where only the best occupant of a cell survives. This pipeline is
    not that regime: every generated candidate is verified and scored, so what a cell is
    worth is what it produces on average, not what it produced once.
    """
    source = cov.elite if stat == "elite" else cov.mean_composite
    scored = {v: source[v] for v in domain if v in source}
    best = max(scored.values(), default=0.0)
    if best <= 0:
        return {v: 1.0 for v in domain}
    return {v: max(0.0, min(1.0, scored[v] / best)) if v in scored else 1.0 for v in domain}


def _blended_share(
    cov: AxisCoverage, domain: Sequence[str], quality_weight: float = 0.0,
    stat: str = "mean",
) -> dict[str, float]:
    """Share per domain value over catalogue + recent counts (recent counted twice).

    Double-counting the recent window is the recency weight: a value the catalogue is full
    of but which has not been generated lately still reads as partially recovered.

    G7: with `quality_weight` above 0 the rows a value owns are discounted by how good its
    elite is, so a cell that has been attempted a hundred times and never produced anything
    good stops reading as "covered". At 0.0 the expression collapses to `count` exactly —
    same floats, same ordering, same plan as V2.
    """
    illum = _illumination(cov, domain, stat) if quality_weight > 0 else {}
    blended: dict[str, float] = {}
    for v in domain:
        n = float(cov.counts.get(v, 0) + cov.recent_counts.get(v, 0))
        if quality_weight > 0:
            n *= (1.0 - quality_weight) + quality_weight * illum[v]
        blended[v] = n
    total = sum(blended.values())
    if total <= 0:
        return {v: 0.0 for v in domain}
    return {v: n / total for v, n in blended.items()}


def _rank_by_deficit(
    cov: AxisCoverage, domain: Sequence[str], seed: int, quality_weight: float = 0.0,
    stat: str = "mean",
) -> list[tuple[str, float]]:
    target = 1.0 / len(domain)
    share = _blended_share(cov, domain, quality_weight, stat)
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
        vals = supplied or list(cov.observed)
        # `unknown` is never a generation TARGET: an unlabelled cell is not an instruction.
        vals = [v for v in dict.fromkeys(vals) if v != UNKNOWN]
        if vals:
            out[axis] = vals
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
        ranked = [v for v, _ in _rank_by_deficit(
            report.axes[axis], values, eff_seed, scfg.quality_weight, scfg.quality_stat)]
        if scfg.method == "entropy":
            cov = report.axes[axis]
            target = 1.0 / len(values)
            share = _blended_share(cov, values, scfg.quality_weight, scfg.quality_stat)
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
        "quality_weight": scfg.quality_weight,
        "quality_stat": scfg.quality_stat,
        "fingerprint": report.fingerprint()[:16],
        "coverage": report.to_dict(),
        "cells": cells,
    }
