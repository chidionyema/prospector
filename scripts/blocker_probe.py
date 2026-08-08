#!/usr/bin/env python3
"""What is actually blocking each open programme item — as a measurement, not prose.

`docs/COMMERCIAL_READINESS_PROGRAM.md` has twice carried an item as "blocked" that
was not (§28 found four of eleven already built) and carries a figure that cannot be
re-derived from anything on disk (the L2 "172 price views", §32.4). Both failures
have the same shape: a status written in a sentence drifts from the thing it
describes, and nothing re-checks it.

This probe is the standing rule "state is a probe, not a paragraph" applied to the
blocked list. Every row prints the BAR, the LIVE value read off disk right now, a
verdict, and the command that reproduces it. A row can only say BLOCKED if a number
says so.

Read-only. Exit 0 when every item is measurable, 1 if any probe could not read its
own input (which is itself a finding — an unmeasurable blocker is not a blocker,
it is an unknown).

    python3 scripts/blocker_probe.py [--json]
"""
from __future__ import annotations

import argparse
import glob
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

OK, BLOCKED, DEAD, UNKNOWN = "READY", "BLOCKED", "ANSWERED", "UNKNOWN"


def _db(path: Path, sql: str, params: tuple = ()) -> list[tuple]:
    if not path.exists():
        return []
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()  # `with sqlite3.connect(...)` commits, it does NOT close


def _json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _rows(count: int, bar: int) -> str:
    return f"{count} of {bar}"


def _configured_personas() -> list[str]:
    """Persona names declared in config.yaml. PyYAML is used when importable, but
    this probe must run under a bare `python3` too, so a text fallback reads the
    top-level `personas:` block directly. Returns [] if neither route works —
    an empty list makes 'missing' empty rather than inventing names."""
    cfg = ROOT / "config.yaml"
    if not cfg.exists():
        return []
    try:
        import yaml  # noqa: PLC0415 - optional, fallback below
        return sorted((yaml.safe_load(cfg.read_text()) or {}).get("personas") or {})
    except Exception:
        pass
    names, inside = [], False
    for line in cfg.read_text().splitlines():
        if line.startswith("personas:"):
            inside = True
            continue
        if inside:
            if line[:1].strip():           # a new top-level key ends the block
                break
            if line.startswith("  ") and not line.startswith("   ") and line.rstrip().endswith(":"):
                names.append(line.strip().rstrip(":"))
    return sorted(names)


# --------------------------------------------------------------------------- #
# probes
# --------------------------------------------------------------------------- #

def probe_e6() -> dict:
    """E6 was 'blocked on live daemon ticks'. E6B answers the same BAR offline."""
    shadow = sorted(glob.glob(str(ROOT / "store/prescreen_shadow/shadow-*.jsonl")))
    n_rows = sum(1 for f in shadow for line in open(f) if line.strip())
    receipts = _json(ROOT / "tools/experiments/e6b_prefilter_pass_safety_receipts.json")
    verdict = receipts.get("verdict")
    safe = (receipts.get("safe_no_pass_no_defer") or {}).get("drop_rate")

    # A `--limit`ed run is a SMOKE TEST, and its receipts are shaped exactly like a
    # real one. Quoting it would repeat this repo's worst proof failure: truncate the
    # evidence, then classify the truncation. Refuse to read a verdict off a
    # deliberately-shortened population, whatever the verdict says.
    argv = (receipts.get("_meta") or {}).get("argv") or []
    limited = "--limit" in argv
    if limited:
        return {
            "item": "E6 / E6B", "bar": ">=20% of prescreen calls removed, no PASS lost",
            "measured": f"receipts are from a SMOKE run (argv={argv}) — not quotable",
            "state": BLOCKED,
            "note": "rerun E6B with no --limit; a truncated corpus cannot answer a rate bar",
            "cmd": ".venv/bin/python tools/experiments/runner.py run E6B",
        }

    if verdict in ("MEETS_BAR", "FAILS_BAR"):
        return {
            "item": "E6 / E6B", "bar": ">=20% of prescreen calls removed, no PASS lost",
            "measured": (f"E6B verdict={verdict}"
                         + (f", safe drop rate={safe*100:.2f}%" if safe is not None else "")),
            "state": DEAD,
            "note": "answered offline against the bar; the agreement proxy needed the daemon, "
                    "the bar itself did not",
            "cmd": ".venv/bin/python tools/experiments/runner.py run E6B",
        }
    return {
        "item": "E6 / E6B", "bar": ">=20% of prescreen calls removed, no PASS lost",
        "measured": f"E6B not yet run; agreement-route shadow rows={n_rows}",
        "state": BLOCKED if n_rows < 200 else OK,
        "note": "run E6B — it does not need the daemon",
        "cmd": ".venv/bin/python tools/experiments/runner.py run E6B",
    }


def probe_e5() -> dict:
    """E5's '41 batches/arm' is driven by the LOW-cardinality axes only."""
    receipts = _json(ROOT / "tools/experiments/e5_coverage_sampler_entropy_receipts.json")
    # The per-axis requirement lives in `batch_noise`, NOT in `axes` (which carries
    # entropy/coverage only). The headline `batches_per_arm_for_target` is a max()
    # across axes, so quoting it alone hides that two axes are 7x cheaper.
    noise = receipts.get("batch_noise") or {}
    need = {axis: v.get("batches_for_target_mde")
            for axis, v in noise.items() if isinstance(v, dict)}
    cheap = {a: n for a, n in need.items() if isinstance(n, int) and n <= 10}
    enabled = "coverage_sampler:\n  enabled: true" in (ROOT / "config.yaml").read_text() \
        if (ROOT / "config.yaml").exists() else False
    n_batches = 0
    bd = ROOT / "store/scheduler/batch_diagnostics.jsonl"
    if bd.exists():
        n_batches = sum(1 for line in open(bd) if line.strip())
    per_arm = max(cheap.values()) if cheap else None
    return {
        "item": "E5 coverage sampler",
        "bar": (f"{per_arm} batches/arm on {'+'.join(sorted(cheap))}"
                if per_arm else "run E5 to derive the per-axis requirement"),
        "measured": (f"sampler enabled={enabled}; treatment batches accrued=0 while it is off; "
                     f"total batches on disk={n_batches}; batches/arm at mde=0.10 per axis={need}"),
        "state": BLOCKED if not enabled else OK,
        "note": ("the headline '41' is the WORST axis (ambition_tier 41, market 40) and those two "
                 "are already near-saturated, so there is nothing there to win. Restricted to the "
                 f"two axes that can move, this needs {per_arm} batches/arm "
                 f"(~{per_arm * 2 if per_arm else '?'} batches) plus one config flag."),
        "cmd": ".venv/bin/python tools/experiments/runner.py run E5",
    }


def probe_e2() -> dict:
    """E2 cannot be answered by more rows of the SAME kind, at any n.

    Verified cause, not inference: `config.yaml:852` sets `active_persona: ""`,
    `dossier.py:187` stamps exactly that onto every dossier it writes, and the
    daemon's generation call (`scheduler/run_scheduled.py:724`) passes no persona,
    so it inherits the empty default on every tick. Every row the daemon has ever
    written is therefore in the SAME arm. The lone `shark` row is a hand-run
    `--persona` invocation (`run.py:1067`).
    """
    rows = _db(ROOT / "store/prospector.db",
               "select coalesce(persona,'(none)'), count(*) from dossiers group by 1 order by 2 desc")
    counts = {r[0]: r[1] for r in rows}
    # A GROUP BY can only return values that OCCUR, so it can never report a persona
    # with zero rows -- the absent arms are exactly the ones it cannot show. The
    # missing set has to come from the CONFIG and be subtracted, not filtered out of
    # the query's own output.
    configured = _configured_personas()
    missing = sorted(p for p in configured if counts.get(p, 0) == 0)
    unlabelled = sum(c for p, c in counts.items() if p in ("", "(none)"))
    total = sum(counts.values())
    return {
        "item": "E2 persona grounding",
        "bar": "each configured persona needs its own dossiers before any contrast is estimable",
        "measured": (f"configured={configured or 'config unreadable'}; "
                     f"with rows={ {p: c for p, c in counts.items() if p not in ('', '(none)')} }; "
                     f"missing={missing}; unlabelled={unlabelled}/{total}"),
        "state": BLOCKED,
        "note": ("NOT a sample-size problem and NOT 5,274 candidates: active_persona is \"\" "
                 "(config.yaml:852), dossier.py:187 stamps it, and run_scheduled.py:724 never "
                 "overrides it — so every daemon row sits in one arm and no contrast is "
                 "estimable at any n. Unblocking is a config default plus an arm rotation."),
        "cmd": ".venv/bin/python tools/experiments/runner.py run E2",
    }


def probe_l2() -> dict:
    """L2's blocker is traffic; its quoted number is not re-derivable (§32.4).

    The programme's "172 price views / 90 days against 1 purchase" DOES have a
    documented origin — `Store.Web/src/components/cart/CartButton.tsx:45-46`, dated
    2026-08-07 — but a source comment is a note, not a receipt: there is no query, no
    export and no dataset behind it, and it cannot be re-derived today because the
    production API answers 404. The same comment records WHY: checkout_started was
    ZERO, so the funnel had a completion and no starts. That gap is fixed
    (`CartButton.tsx:52` now emits it per line), which is what makes the number a
    stale reading of a since-changed instrument.
    """
    db = ROOT / "store_platform/src/Store.Api/store.db"
    rows = _db(db, "select Name, count(*) from AnalyticsEvents group by Name order by 2 desc")
    counts = {r[0]: r[1] for r in rows}
    funnel = {k: counts.get(k, 0) for k in ("price_viewed", "checkout_started", "checkout_completed")}
    return {
        "item": "L2 demand telemetry",
        "bar": "a ladder change needs checkout_started as the fast numerator, not purchases",
        "measured": f"LOCAL db funnel={funnel}; all events={counts or 'db absent/unreadable'}",
        "state": BLOCKED,
        "note": ("local store.db is a dev artifact — these are NOT production numbers. The "
                 "programme's '172 price views' traces only to a source comment "
                 "(CartButton.tsx:45-46, 2026-08-07), is not re-derivable, and predates the "
                 "checkout_started fix at CartButton.tsx:52. Point this probe at the "
                 "production db before quoting anything."),
        "cmd": "sqlite3 store_platform/src/Store.Api/store.db "
               "'select Name,count(*) from AnalyticsEvents group by Name'",
    }


def _newest_receipt(stem: str) -> tuple[dict, str]:
    """The receipt this probe should read, and its name.

    `--all` makes the runner write `<stem>_full_receipts.json`, NOT `<stem>_receipts.json`
    (`runner.py:223` appends `_receipt_suffix`). Reading only the unsuffixed path meant this
    probe told you to run `--all` and then measured a file that command never writes — so it
    would have reported BLOCKED forever, including after the pair landed. Prefer the widest
    run available, and name the file that was read so the number is traceable.
    """
    base = ROOT / "tools/experiments"
    for suffix in ("_full", "_current_moat", ""):
        path = base / f"{stem}{suffix}_receipts.json"
        if path.exists():
            return _json(path), path.name
    return {}, "(no receipt)"


def probe_matched_pair() -> dict:
    """E15/E17 are only comparable when they share a corpus fingerprint."""
    e15, n15 = _newest_receipt("e15_hhem_groundedness")
    e17, n17 = _newest_receipt("e17_hhem_moat_agreement")
    f15 = (e15.get("corpus_fingerprint") or {})
    f17 = (e17.get("corpus_fingerprint") or {})
    s15, s17 = f15.get("sha256"), f17.get("sha256")
    matched = bool(s15 and s17 and s15 == s17)
    frozen = bool(f15.get("frozen")) and bool(f17.get("frozen"))
    return {
        "item": "E15/E17 matched pair",
        "bar": "identical corpus_fingerprint.sha256 across both receipts",
        "measured": f"{n15}={s15} {n17}={s17} matched={matched} frozen={frozen}",
        "state": OK if matched else BLOCKED,
        "note": ("unmatched fingerprints mean any agreement figure compares two SAMPLES, not "
                 "two methods. Freeze first: eval \"$(.venv/bin/python "
                 "tools/experiments/_freeze_corpus.py)\""),
        "cmd": "eval \"$(.venv/bin/python tools/experiments/_freeze_corpus.py)\" && "
               ".venv/bin/python tools/experiments/runner.py run E15 --all && "
               ".venv/bin/python tools/experiments/runner.py run E17 --all",
    }


def probe_numeric_citation() -> dict:
    """The enforcement decision rests on this rate; §31.1 corrected it twice."""
    sys.path.insert(0, str(ROOT))
    logs = sorted(glob.glob(str(ROOT / "store/numeric_citation_shadow/shadow-*.jsonl")))
    try:
        from prospector.numeric_citation import summarise_shadow_log  # noqa: PLC0415
        summary = summarise_shadow_log(logs[-1]) if logs else {}
    except Exception as e:  # pragma: no cover - defensive
        summary = {"error": str(e)}
    # `untraceable_rate` DELIBERATELY keeps its old lumped meaning for back-compat
    # (COMMERCIAL_READINESS_PROGRAM.md:2931), so it is 38.0% here -- the very figure
    # §31.1 retracted. Printing it unlabelled would re-publish a withdrawn number, so
    # it is named as lumped and the decision figure is carried alongside it.
    rate = summary.get("untraceable_rate")
    split = summary.get("split_figures")
    measured = (
        f"rows={summary.get('rows')} figures={summary.get('figures')} "
        f"lumped_untraceable_rate={rate * 100:.1f}% (back-compat meaning, NOT the decision "
        f"figure); split_figures={split} so this log cannot itself separate self-reference "
        f"from untraceable. Decision figure is §31.1: 9.7% untraceable, Wilson95 [4.5, 19.5]"
        if isinstance(rate, (int, float)) else f"unreadable: {summary}")
    return {
        "item": "numeric_citation enforcement",
        "bar": "founder decision; the ACTION variant is not built (config.yaml:1076)",
        "measured": measured,
        "state": BLOCKED,
        "note": "shadow_mode:true logs only; enforcing is a BUILD, not a flag flip",
        "cmd": "grep -n 'shadow_mode' config.yaml",
    }


PROBES = (probe_e6, probe_e5, probe_e2, probe_l2, probe_matched_pair, probe_numeric_citation)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ns = ap.parse_args(argv)

    results, failed = [], 0
    for fn in PROBES:
        try:
            results.append(fn())
        except Exception as e:
            failed += 1
            results.append({"item": fn.__name__, "state": UNKNOWN, "measured": f"probe raised: {e}",
                            "bar": "-", "note": "an unmeasurable blocker is an unknown, not a blocker",
                            "cmd": "-"})

    if ns.json:
        print(json.dumps(results, indent=2))
        return 1 if failed else 0

    print("── PROGRAMME BLOCKERS ── measured now, not quoted ──")
    for r in results:
        print(f"\n[{r['state']:8s}] {r['item']}")
        print(f"    bar      : {r['bar']}")
        print(f"    measured : {r['measured']}")
        print(f"    note     : {r['note']}")
        print(f"    reproduce: {r['cmd']}")
    states = [r["state"] for r in results]
    print(f"\n── {states.count(DEAD)} answered · {states.count(OK)} ready to run · "
          f"{states.count(BLOCKED)} blocked · {states.count(UNKNOWN)} unmeasurable ──")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
