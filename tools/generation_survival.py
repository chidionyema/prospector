"""Survival analysis over the dossier index: which generation choices actually pay (G5).

The engine has always been able to say how many candidates died. It has never been able to
say *which generation decision* produced the ones that lived, because the three fields that
describe that decision — the seed provenance, the audience persona and the structural form —
were either absent from the index or present but never grouped on. Without that, every
proposal to change generation is an opinion.

This tool is deliberately ZERO-LLM and read-only. It opens the SQLite index, groups the rows
by whichever axes are asked for, and prints survival per cell. It never opens the operator's
model, never writes to the store, and never ranks an idea.

WHAT IT IS NOT FOR. This is a report card on the GENERATOR, not a lever on the moat. A low
survival cell means "generation keeps writing weak ideas for this cell", never "the gates are
too hard here". Nothing in this file may be wired into a gate, a threshold or a publish
decision. It exists so that a change to generation can be argued from measurement.

READING THE NUMBERS HONESTLY:

  * `defer` rows are UNDECIDED, not dead. A cell whose rows are mostly deferred has not been
    measured yet; it has been queued. They are reported in their own column and excluded
    from the pass-rate denominator, because counting an unfinished verdict as a failure is
    how an outage turns into a false verdict about generation (see the 2026-08-06 incident
    where seven `unverifiable, conf 0.0, "Verdict call failed"` checks were rendered as a
    reasoned KILL).
  * `provisional` rows were ruled by a non-MOAT_PRIMARY brain and can never publish. They
    are excluded from `pass` entirely — treating a provisional pass as a pass would credit
    generation for a result that has not survived a trusted verdict.
  * A cell with a handful of rows says nothing. `--min-n` (default 10) hides the noise;
    the hidden rows are still counted in the totals line, and the count of suppressed cells
    is printed, because a silently truncated table reads as "that is all there is".
  * Rows written before this field existed carry `seed_kind = ''` and appear as `unknown`.
    They are NOT redistributed. See `store.py`'s migration comment.

Usage:
    python -m tools.generation_survival                          # by seed_kind
    python -m tools.generation_survival --by seed_kind,audience
    python -m tools.generation_survival --by audience --min-n 20 --json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prospector.config import load_config  # noqa: E402

# Only columns that describe a GENERATION decision are groupable. `decision`, `gate_fired`
# and `composite` are outcomes and belong on the right-hand side of the table, never the
# left: grouping by an outcome and then reporting survival within it is circular.
AXES = ("seed_kind", "audience", "structural_form", "ambition_tier", "market")

_UNKNOWN = "unknown"


def _resolve_db(cfg) -> Path:
    return Path(cfg.store_dir) / "prospector.db"


def _fetch_rows(db: Path) -> list[dict]:
    """Read the whole index once. Returns [] when the DB or the table is absent.

    One SELECT rather than a query per cell: the row count is in the low thousands, and a
    per-cell query would multiply the open/close cost of `_connect` for no benefit. Missing
    columns are tolerated (an index that predates a migration) so this tool never becomes
    the reason someone cannot look at an old store.
    """
    if not db.exists():
        return []
    conn = sqlite3.connect(str(db), timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        have = {r[1] for r in conn.execute("PRAGMA table_info(dossiers)")}
        if not have:
            return []
        wanted = ["decision", "gate_fired", "composite", "provisional", "tombstone", *AXES]
        cols = [c for c in wanted if c in have]
        rows = [dict(r) for r in conn.execute(f"SELECT {', '.join(cols)} FROM dossiers")]
    finally:
        conn.close()
    return rows


def _cell_key(row: dict, axes: list[str]) -> tuple:
    """The group key. '' and NULL both collapse to `unknown` — see the module docstring."""
    return tuple(str(row.get(a) or "").strip().lower() or _UNKNOWN for a in axes)


def summarise(rows: list[dict], axes: list[str], min_n: int = 10) -> dict:
    """Group `rows` by `axes` and compute survival per cell. Pure — no I/O, so the tests
    exercise the arithmetic directly and a formatting change cannot hide a counting bug."""
    cells: dict[tuple, dict] = {}
    for row in rows:
        # A tombstoned row is one the ruling happened on but which is no longer workable.
        # It is real history and stays in the counts; it is only excluded from `pending`.
        dec = str(row.get("decision") or "").strip().lower()
        prov = bool(row.get("provisional"))
        cell = cells.setdefault(_cell_key(row, axes), {
            "n": 0, "pass": 0, "kill": 0, "defer": 0, "provisional": 0,
            "composites": [], "gates": {},
        })
        cell["n"] += 1
        if prov:
            # Counted, but never as a pass: a provisional ruling cannot publish.
            cell["provisional"] += 1
            if dec == "defer":
                cell["defer"] += 1
            continue
        if dec == "pass":
            cell["pass"] += 1
        elif dec == "kill":
            cell["kill"] += 1
            gate = str(row.get("gate_fired") or "").strip() or _UNKNOWN
            cell["gates"][gate] = cell["gates"].get(gate, 0) + 1
        elif dec == "defer":
            cell["defer"] += 1
        comp = row.get("composite")
        if isinstance(comp, (int, float)) and not isinstance(comp, bool):
            cell["composites"].append(float(comp))

    out = []
    suppressed = 0
    for key, c in cells.items():
        # Denominator is RULED rows only: pass + kill. Deferred and provisional rows are
        # undecided, and dividing by them would report an outage as a generation failure.
        ruled = c["pass"] + c["kill"]
        comps = c["composites"]
        rec = {
            "cell": dict(zip(axes, key)),
            "n": c["n"],
            "ruled": ruled,
            "pass": c["pass"],
            "kill": c["kill"],
            "defer": c["defer"],
            "provisional": c["provisional"],
            "pass_rate": (c["pass"] / ruled) if ruled else None,
            "mean_composite": (sum(comps) / len(comps)) if comps else None,
            "top_gate": max(c["gates"].items(), key=lambda kv: kv[1])[0] if c["gates"] else None,
        }
        if ruled < min_n:
            suppressed += 1
            continue
        out.append(rec)

    # Sort by pass rate, then by ruled volume — a cell with the same rate on more rows is
    # the better-evidenced one and should read first.
    out.sort(key=lambda r: (r["pass_rate"] or 0.0, r["ruled"]), reverse=True)
    totals = {
        "rows": sum(c["n"] for c in cells.values()),
        "cells": len(cells),
        "cells_shown": len(out),
        "cells_suppressed_below_min_n": suppressed,
        "min_n": min_n,
    }
    return {"axes": axes, "totals": totals, "cells": out}


def _fmt(report: dict) -> str:
    axes = report["axes"]
    t = report["totals"]
    width = max([len(" / ".join(axes))] + [len(" / ".join(c["cell"][a] for a in axes))
                                           for c in report["cells"]] or [0])
    lines = [
        f"Generation survival by {' x '.join(axes)}",
        f"  {t['rows']} indexed rows, {t['cells']} cells, "
        f"{t['cells_shown']} shown, {t['cells_suppressed_below_min_n']} suppressed "
        f"(< {t['min_n']} ruled rows)",
        "",
        f"  {'cell'.ljust(width)}  {'ruled':>6} {'pass':>5} {'rate':>7} "
        f"{'mean_c':>7} {'defer':>6} {'prov':>5}  top_kill_gate",
    ]
    for c in report["cells"]:
        rate = "-" if c["pass_rate"] is None else f"{c['pass_rate'] * 100:.1f}%"
        mean = "-" if c["mean_composite"] is None else f"{c['mean_composite']:.3f}"
        lines.append(
            f"  {' / '.join(c['cell'][a] for a in axes).ljust(width)}  "
            f"{c['ruled']:>6} {c['pass']:>5} {rate:>7} {mean:>7} "
            f"{c['defer']:>6} {c['provisional']:>5}  {c['top_gate'] or '-'}"
        )
    if not report["cells"]:
        lines.append("  (no cell has enough ruled rows to report — lower --min-n)")
    lines += [
        "",
        "  This is a report card on the GENERATOR. A low rate means generation keeps",
        "  writing weak ideas for that cell — never that the gates are too hard there.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--by", default="seed_kind",
                    help=f"comma-separated axes, any of: {', '.join(AXES)}")
    ap.add_argument("--min-n", type=int, default=10,
                    help="hide cells with fewer than this many RULED (pass+kill) rows")
    ap.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = ap.parse_args(argv)

    axes = [a.strip() for a in args.by.split(",") if a.strip()]
    bad = [a for a in axes if a not in AXES]
    if bad or not axes:
        print(f"unknown axis {bad or '(none given)'}; choose from: {', '.join(AXES)}",
              file=sys.stderr)
        return 2

    cfg = load_config()
    db = _resolve_db(cfg)
    rows = _fetch_rows(db)
    if not rows:
        print(f"no dossier index at {db} (nothing to report)", file=sys.stderr)
        return 1

    report = summarise(rows, axes, min_n=args.min_n)
    print(json.dumps(report, indent=2) if args.json else _fmt(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
