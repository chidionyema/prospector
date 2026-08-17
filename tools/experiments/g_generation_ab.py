#!/usr/bin/env python3
"""G-programme A/B: does each generation lever actually change the BATCH?

This is the proof step for `docs/GENERATION_QUALITY_PROGRAM.md`. Every row in that
table is currently `built` and none is `proven`, because proof was defined there as a
receipt in `generation_metrics.jsonl` and no lever has one.

Three design decisions, each of which exists because getting it wrong has already cost
this repo a wrong finding:

PAIRED, NOT POOLED. Every arm sees the SAME (signal, repeat) cells, and the report is
built from per-cell deltas. Generation variance between signals dwarfs the effect we are
looking for, so pooling arm means would mostly measure which signals happened to land in
which arm. A paired design read unpaired only prints nulls
(memory: `unpaired-analysis-of-a-paired-design-generates-nulls.md`).

AN OUTAGE ENDS THE MEASUREMENT. If the generation chain is exhausted mid-run we stop,
write what completed, and stamp `complete: false`. We never let a failed call become a
zero — E1 once printed `0/0` as its own kill bar
(memory: `an-outage-is-the-end-of-the-measurement-not-a-datum.md`).

That rule was written here and then broken here, because an outage does not always
RAISE. The 2026-08-08 live run hit the Claude usage wall, `generate()` swallowed it and
returned `[]`, and `batch_report([])` scored a perfectly well-formed `distinct_k=0/0`.
Five such cells entered the paired deltas as real -6.00 observations and the run still
printed `COMPLETE`. So an empty batch is now an `EmptyBatch` abort, not a data point:
"the generator produced nothing" and "the generator produced nothing DIVERSE" are
opposite findings and must never reach the arithmetic as the same number.

DISTINCT_K SATURATES. It is capped at k, so once every cell scores k/k its deltas are
zero by construction and a lever that helps is indistinguishable from one that does
nothing. That is not a null result, it is a broken ruler, and the summary says so
outright rather than printing `+0.00` and letting it read as evidence of no effect.

FIXTURE FIRST. `--fixture` runs the whole harness against a MockOperator, so the
arithmetic, the pairing, the call accounting and the receipt shape are all exercised
before a single paid call
(memory: `paid-ab-harness-must-be-fixture-tested-first.md`).

`--fixture` also forces `incumbent_seed.providers: []`, and that is not tidiness. G2's
landscape fetch goes through the RETRIEVAL chain, not through the operator, so a
MockOperator does not stop it: the first fixture run wrote two live-fetched briefs into
`store/incumbent_cache.json` while the docstring claimed zero network. A fixture mode
that quietly reaches the network is worse than no fixture mode, because the whole point
is a safe rehearsal. Pass `--fixture-live-retrieval` to exercise G2's real fetch path;
without it the G2 arm is INERT and the fixture is a mechanics test only.

Note the trap that cost a second attempt here: setting `incumbent_seed.providers: []`
does NOT disable the fetch. `landscape.py:92` reads `icfg.get("providers") or
_DEFAULT_PROVIDERS`, and an empty list is falsy, so an operator who empties the list to
turn retrieval off silently gets the default chain instead. The block has to be disabled
by `enabled: False`.

Call accounting is MEASURED, not estimated: the operator is wrapped in a counter, so the
receipt reports the calls that actually happened per arm. `--max-calls` is a hard ceiling
that aborts the run rather than a budget that is hoped for.

Usage:
    # free, proves the harness itself
    python tools/experiments/g_generation_ab.py --fixture

    # what a paid run would cost, without paying it
    python tools/experiments/g_generation_ab.py --dry-run

    # the real thing
    python tools/experiments/g_generation_ab.py --signals 3 --repeats 2 --k 8
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prospector.diversity import batch_report  # noqa: E402
from prospector.errors import ProviderExhaustedError  # noqa: E402

# The levers, as overrides ON TOP of an all-off baseline. `shipped` is deliberately last
# and is NOT a lever: it is the configuration a daemon tick actually runs today, so the
# report can say whether the combination behaves like the parts.
_ALL_OFF = {
    "incumbent_seed": {"enabled": False},
    "denylist": {"enabled": False},
    "verbalized_sampling": {"enabled": False},
    "critique_revise": {"enabled": False},
}

ARMS: list[tuple[str, dict[str, Any]]] = [
    ("baseline", {}),
    ("g2_incumbent", {"incumbent_seed": {"enabled": True}}),
    ("g3_denylist", {"denylist": {"enabled": True}}),
    ("g4_verbalized_sampling", {"verbalized_sampling": {"enabled": True}}),
    ("g8_critique_revise", {"critique_revise": {"enabled": True}}),
    ("shipped", None),  # sentinel: the unmodified config
]

# The metrics a lever is allowed to be judged on. All come straight from
# `diversity.batch_report` — the harness computes no metric of its own, so it cannot
# quietly define a metric that flatters a lever.
_METRICS = ("distinct_k", "distinct_ratio", "mean_pairwise_overlap", "max_pairwise_overlap")
_AXES = ("structural_form", "audience", "market", "ambition_tier")


# Marker -> label, checked in order. Each marker is a phrase that appears in exactly one
# prompt body; the shared `OUTPUT CONTRACT` preamble is deliberately not used as a key.
_CALL_MARKERS: list[tuple[str, str]] = [
    ("write one specific", "critique"),
    ("act on the critique", "revise"),
    ("critique and repair", "refine"),
    ("execute the generation", "generate"),
]


class _CountingOperator:
    """Wraps an Operator and counts calls. Delegates everything else untouched.

    The count is the receipt for cost: G8 claims "one extra generation call per wave",
    and that claim is only checkable if something counts the calls that happened rather
    than the calls the design intended.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls = 0
        self.kinds: dict[str, int] = {}
        self.name = getattr(inner, "name", "unknown")

    def __getattr__(self, item: str) -> Any:
        return getattr(self._inner, item)

    def _tally(self, a: tuple, kw: dict) -> None:
        """Bucket the call by a distinctive marker in its system prompt.

        A bare total answers "how much did this cost" and nothing else. The first
        fixture run cost 8 calls per wave when the design said 1-2, and a bare counter
        could not say which 8. The first attempt at classifying them keyed on the first
        LINE of the system prompt and put every call in one bucket, because every prompt
        here shares an `OUTPUT CONTRACT — READ FIRST` preamble. So the key is a marker
        unique to each prompt body instead, and anything unmatched is reported as
        `other:<first line>` rather than silently folded into a known bucket.
        """
        self.calls += 1
        system = str(kw.get("system") or (a[0] if a else ""))
        low = system.lower()
        for marker, label in _CALL_MARKERS:
            if marker in low:
                self.kinds[label] = self.kinds.get(label, 0) + 1
                return
        head = system.strip().splitlines()[0][:40] if system.strip() else "(no system)"
        self.kinds[f"other:{head}"] = self.kinds.get(f"other:{head}", 0) + 1

    def complete_json(self, *a: Any, **kw: Any) -> Any:
        self._tally(a, kw)
        return self._inner.complete_json(*a, **kw)

    def complete(self, *a: Any, **kw: Any) -> Any:
        self._tally(a, kw)
        return self._inner.complete(*a, **kw)


def _arm_config(base_cfg: Any, overrides: dict[str, Any] | None) -> Any:
    """Baseline-plus-one-lever, or the shipped config when `overrides is None`.

    Deep-merges one level: a lever's block replaces the baseline block wholesale, which
    is what we want (`{"enabled": True}` must not drop the block's other tuned keys), so
    the baseline block is merged UNDER the shipped block first.
    """
    if overrides is None:
        return base_cfg
    gen = dict(base_cfg.generation)
    for key, off in _ALL_OFF.items():
        gen[key] = {**(gen.get(key) or {}), **off}
    for key, on in overrides.items():
        gen[key] = {**(gen.get(key) or {}), **on}
    return replace(base_cfg, generation=gen)


def _load_signals(limit: int) -> list[tuple[str, str]]:
    """(name, text) for the first `limit` signals, sorted for determinism."""
    sig_dir = ROOT / "signals"
    out: list[tuple[str, str]] = []
    for p in sorted(sig_dir.glob("*.txt")):
        text = p.read_text(encoding="utf-8", errors="replace").strip()
        if len(text) < 40:
            continue  # a stub signal generates a stub batch; it is not a measurement
        out.append((p.stem, text))
        if len(out) >= limit:
            break
    return out


def _fixture_operator(k: int) -> Any:
    """A MockOperator that returns a DIFFERENT batch per distinct prompt.

    It must vary, or every arm scores an identical distinct_k and the harness would
    report "no lever does anything" whatever the levers do — a fixture that cannot fail
    proves nothing. Variation is derived from the prompt text so it stays deterministic.
    """
    from prospector.operator import MockOperator

    forms = ["saas", "marketplace", "service", "data_product"]
    auds = ["smb", "enterprise", "prosumer", "public_sector"]

    def router(system: str, user: str) -> Any:
        low = (system or "").lower()
        # G8's two calls must both be exercised, or the fixture reports G8 as free.
        # The first fixture run did exactly that: the critic was handed the generic idea
        # shape, produced no `critique` field, and `critique_revise` correctly bailed
        # before the revision call — so the arm cost the same as baseline and the harness
        # looked like it had proved G8 costs nothing.
        if "write one specific" in low:  # critique_system.md
            n = min(k, 24)
            return [{"idx": i, "weakest_axis": "value_durability",
                     "critique": f"Anchor {i} to a buyer who already pays."}
                    for i in range(n)]
        if "act on the critique" in low:  # revise_system.md
            h2 = abs(hash(user)) % 997
            return [{"idx": i,
                     "title": f"Revised {h2}-{i}",
                     "one_liner": f"A {forms[(h2 + i * 2) % len(forms)]} priced per seat",
                     "hypothesis": f"Named buyer {h2 + i} renews on outcome {i}"}
                    for i in range(min(k, 24))]
        h = abs(hash(user)) % 997
        # `spread` is what makes arms differ: a prompt carrying more directives (a
        # landscape block, a denylist, a typicality demand) is longer, and a longer
        # prompt yields a wider batch here. Crude, but it gives the metrics something
        # real to separate, which is the only job of a fixture.
        spread = 1 + (len(user) // 900)
        return [
            {
                "title": f"Idea {h}-{i}-{'x' * (i % spread)}",
                "one_liner": f"A {forms[(h + i) % len(forms)]} for {auds[(h + i * spread) % len(auds)]}",
                "hypothesis": f"Buyers at tier {(h + i) % 3} pay for outcome {h * (i + 1) % 41}",
                "structural_form": forms[(h + i) % len(forms)],
                "audience": auds[(h + i * spread) % len(auds)],
                "market": ["uk", "us", "eu"][(h + i) % 3],
                "ambition_tier": ["incremental", "ambitious", "moonshot"][(h + i) % 3],
                "typicality": round(((h + i * 7) % 100) / 100.0, 2),
            }
            for i in range(k)
        ]

    return MockOperator(router=router)


def _serving_provider(op: Any) -> str:
    """Which brain actually served this cell.

    A FallbackOperator can change tier mid-run, and arms run in the OUTER loop, so a flip
    lands BETWEEN arms rather than inside one: baseline entirely on claude_cli, the next
    arm entirely on minimax. Every delta would then measure the BRAIN and be reported as
    an effect of the lever. Recorded per cell so `_paired_deltas` can refuse those
    comparisons instead of averaging across them.
    """
    served = getattr(op, "last_served", None)
    if callable(served):
        name = served()
        if name:
            return str(name)
    return str(getattr(op, "name", "") or "unknown")


class EmptyBatch(RuntimeError):
    """Generation returned nothing. An outage, never a diversity score of zero.

    Carries the calls already made so the receipt still reports what the aborted cell
    cost — the run stops being a measurement, but it does not stop having been paid for.
    """

    def __init__(self, msg: str, calls: int = 0) -> None:
        super().__init__(msg)
        self.calls = calls


def _run_cell(op: Any, cfg: Any, signal_text: str, k: int) -> tuple[dict[str, Any], int]:
    """One (arm, signal, repeat) cell. Returns (batch_report, calls_made).

    Raises `EmptyBatch` on an empty batch rather than returning a `0/0` report. The
    caller cannot tell the difference downstream: by the time it is a dict of numbers,
    an outage looks exactly like a generator that produced six identical ideas.
    """
    from prospector.generate import generate

    counted = _CountingOperator(op)
    cands = generate(counted, cfg, signal_text=signal_text, k=k, gen_op=counted)
    if not cands:
        raise EmptyBatch(
            f"generation returned 0 of {k} candidates after {counted.calls} call(s) "
            "— a usage wall, an exhausted chain or a refused batch, not a measurement",
            calls=counted.calls,
        )
    rep = batch_report(cands)
    rep["_calls"] = counted.calls
    rep["_call_kinds"] = dict(counted.kinds)
    rep["_provider"] = _serving_provider(counted)
    return rep, counted.calls


def _paired_deltas(cells: dict[str, dict[str, dict[str, Any]]],
                   arm: str, metric: str) -> dict[str, Any] | None:
    """Per-cell `arm - baseline` for one metric. None when no cell has both.

    Returning None rather than 0.0 for "no paired observation" is the whole point: a
    zero delta and an absent delta are opposite findings and must never render the same.
    """
    diffs = []
    mixed = 0
    for cell_id, by_arm in cells.items():
        base = by_arm.get("baseline")
        got = by_arm.get(arm)
        if base is None or got is None:
            continue
        # A pair served by two different brains compares the brains, not the lever.
        bp, gp = base.get("_provider"), got.get("_provider")
        if bp and gp and bp != gp:
            mixed += 1
            continue
        b, g = base.get(metric), got.get(metric)
        if b is None or g is None:
            continue
        diffs.append(float(g) - float(b))
    if not diffs:
        return None if not mixed else {"n_pairs": 0, "mixed_provider_pairs": mixed,
                                       "mean_delta": None, "median_delta": None,
                                       "won": 0, "lost": 0, "tied": 0}
    return {
        "mixed_provider_pairs": mixed,
        "n_pairs": len(diffs),
        "mean_delta": round(statistics.fmean(diffs), 4),
        "median_delta": round(statistics.median(diffs), 4),
        "won": sum(1 for d in diffs if d > 0),
        "lost": sum(1 for d in diffs if d < 0),
        "tied": sum(1 for d in diffs if d == 0),
    }


def _axis_entropy(rep: dict[str, Any], axis: str) -> float | None:
    ax = (rep.get("axes") or {}).get(axis) or {}
    val = ax.get("entropy")
    return None if val is None else float(val)


def _distinct_k_saturated(cells: dict[str, dict[str, dict[str, Any]]]) -> bool:
    """True when every recorded cell scored distinct_k == n, i.e. a full house.

    distinct_k cannot exceed k, so at a small k every arm hits the ceiling and every
    paired delta is 0.00 whatever the levers did. The danger is that this reads exactly
    like a confident "no lever has any effect". It is the opposite: the ruler ran out of
    headroom before the levers ran out of effect. The 2026-08-08 live run scored 6/6 in
    all 19 of its non-empty cells.
    """
    seen = [r for by in cells.values() for r in by.values()]
    if not seen:
        return False
    return all(r.get("distinct_k") == r.get("n") for r in seen)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--signals", type=int, default=3, help="how many signal files to use")
    ap.add_argument("--repeats", type=int, default=2, help="waves per (arm, signal)")
    ap.add_argument("--k", type=int, default=8, help="candidates requested per wave")
    ap.add_argument("--arms", default="", help="comma-separated arm names; default all")
    ap.add_argument("--fixture", action="store_true",
                    help="MockOperator + no live retrieval: zero network, zero spend")
    ap.add_argument("--fixture-live-retrieval", action="store_true",
                    help="in fixture mode, still let G2 fetch its landscape for real")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan and the cell count, call nothing")
    ap.add_argument("--max-calls", type=int, default=400,
                    help="hard ceiling; the run ABORTS at it rather than overspending")
    ap.add_argument("--out", default="", help="receipts path; default beside this script")
    args = ap.parse_args(argv)

    from prospector.config import load_config

    base_cfg = load_config(str(ROOT / "config.yaml"))

    wanted = [a.strip() for a in args.arms.split(",") if a.strip()]
    arms = [(n, o) for n, o in ARMS if not wanted or n in wanted]
    if not any(n == "baseline" for n, _ in arms):
        print("refusing to run: every delta in this report is against `baseline`, so "
              "dropping it would leave the arms uncomparable", file=sys.stderr)
        return 2

    signals = _load_signals(args.signals)
    if not signals:
        print(f"no usable signals under {ROOT / 'signals'}", file=sys.stderr)
        return 2

    n_cells = len(arms) * len(signals) * args.repeats
    print(f"arms={len(arms)} signals={len(signals)} repeats={args.repeats} "
          f"k={args.k} -> {n_cells} generation waves")
    for name, _ in arms:
        print(f"  arm: {name}")
    if args.dry_run:
        print("\ndry run: nothing was called. A wave is >=1 operator call (2 under "
              "g8_critique_revise), so expect roughly "
              f"{n_cells}-{n_cells + len(signals) * args.repeats} calls.")
        return 0

    if args.fixture:
        op: Any = _fixture_operator(args.k)
        print("fixture mode: MockOperator; live retrieval "
              f"{'ON' if args.fixture_live_retrieval else 'OFF'}")
    else:
        # Build the SAME tiered chain production generation uses (`run.py:303`,
        # `_NONCRITICAL_ORDER = ("claude_cli", "minimax")`), not a bare claude_cli. A
        # harness that measures a path the daemon does not run is measuring the wrong
        # thing, and a single operator also has no fallback: the 2026-08-08 k=12 run died
        # on its first cell against the monthly spend limit while the daemon beside it
        # still had a live tier to fall through to.
        from prospector.operator import FallbackOperator, _build_operator
        from prospector.run import _NONCRITICAL_ORDER

        tiers = []
        for kind in _NONCRITICAL_ORDER:
            try:
                tiers.append((kind, _build_operator(kind, base_cfg, fast=True)))
            except RuntimeError as e:      # tier not configured / no API key
                print(f"  tier {kind} unavailable: {e}")
        if not tiers:
            print(f"refusing to run: no tier in {_NONCRITICAL_ORDER} is available",
                  file=sys.stderr)
            return 2
        if len(tiers) == 1:
            op = tiers[0][1]
        else:
            # Same health store production uses (`run.py:616,635`). Without it the
            # harness re-probes a tier already marked dead on disk and pays a guaranteed
            # failure before every call until its in-run breaker trips.
            from prospector.health import get_noncritical_health

            r = base_cfg.retrieval
            op = FallbackOperator(tiers,
                                  failure_threshold=r.breaker_failure_threshold,
                                  cooldown_s=r.breaker_cooldown_s,
                                  health=get_noncritical_health())
        print(f"live mode: chain={' -> '.join(n for n, _ in tiers)} — this run SPENDS")

    cells: dict[str, dict[str, dict[str, Any]]] = {}
    calls_by_arm: dict[str, int] = {}
    total_calls = 0
    complete = True
    stopped_because = ""
    t0 = time.time()

    offline = args.fixture and not args.fixture_live_retrieval
    for name, overrides in arms:
        cfg = _arm_config(base_cfg, overrides)
        if offline:
            # See the module docstring: the operator is mocked, the retrieval chain is
            # not, and `providers: []` does not turn it off. Applied AFTER `_arm_config`
            # so it also covers the `shipped` arm, which returns the config untouched.
            seed = {**(cfg.generation.get("incumbent_seed") or {}), "enabled": False}
            cfg = replace(cfg, generation={**cfg.generation, "incumbent_seed": seed})
        for sig_name, sig_text in signals:
            for r in range(args.repeats):
                cell_id = f"{sig_name}#{r}"
                if total_calls >= args.max_calls:
                    complete, stopped_because = False, (
                        f"hit --max-calls={args.max_calls} before finishing")
                    break
                try:
                    rep, made = _run_cell(op, cfg, sig_text, args.k)
                except EmptyBatch as e:
                    # Bank the spend, discard the "observation". Recording this cell is
                    # the exact defect that produced the 2026-08-08 junk numbers.
                    total_calls += e.calls
                    calls_by_arm[name] = calls_by_arm.get(name, 0) + e.calls
                    complete, stopped_because = False, f"{name} {cell_id}: {e}"
                    break
                except ProviderExhaustedError as e:
                    complete, stopped_because = False, f"generation chain exhausted: {e}"
                    break
                except Exception as e:  # noqa: BLE001 - any failure ends the measurement
                    complete, stopped_because = False, f"{type(e).__name__}: {e}"
                    break
                total_calls += made
                calls_by_arm[name] = calls_by_arm.get(name, 0) + made
                cells.setdefault(cell_id, {})[name] = rep
                print(f"  {name:24} {cell_id:34} distinct_k={rep.get('distinct_k')}/"
                      f"{rep.get('n')} overlap={rep.get('mean_pairwise_overlap')} "
                      f"calls={made}")
            if not complete:
                break
        if not complete:
            break

    if not complete:
        print(f"\nMEASUREMENT ENDED EARLY: {stopped_because}", file=sys.stderr)

    report: dict[str, Any] = {}
    for name, _ in arms:
        if name == "baseline":
            continue
        per_metric = {m: _paired_deltas(cells, name, m) for m in _METRICS}
        for axis in _AXES:
            key = f"entropy_{axis}"
            # `_provider` must survive the flattening, or the entropy metrics would
            # silently keep comparing across brains after the guard rejected the rest.
            flat = {c: {a: {key: _axis_entropy(r, axis),
                            "_provider": r.get("_provider")}
                        for a, r in by.items()}
                    for c, by in cells.items()}
            per_metric[key] = _paired_deltas(flat, name, key)
        report[name] = per_metric

    saturated = _distinct_k_saturated(cells)
    providers = sorted({r.get("_provider") or "unknown"
                        for by in cells.values() for r in by.values()})

    receipts = {
        "harness": "g_generation_ab",
        "mode": "fixture" if args.fixture else "live",
        "complete": complete,
        "stopped_because": stopped_because,
        # A reader of the JSON must be able to tell "distinct_k said +0.00" from
        # "distinct_k could not say anything" without re-deriving it from `raw`.
        "distinct_k_saturated": saturated,
        "primary_metric": "mean_pairwise_overlap" if saturated else "distinct_k",
        # Which brain(s) served the run. A result measured on the fallback tier is a
        # result ABOUT that tier, and must never be read as a property of the shipped
        # claude_cli-headed path.
        "providers": providers,
        "elapsed_s": round(time.time() - t0, 1),
        "config": {"signals": [s for s, _ in signals], "repeats": args.repeats,
                   "k": args.k, "arms": [n for n, _ in arms]},
        "calls": {"total": total_calls, "by_arm": calls_by_arm},
        "cells_completed": {n: sum(1 for by in cells.values() if n in by)
                            for n, _ in arms},
        "paired_deltas_vs_baseline": report,
        "raw": cells,
    }
    out = Path(args.out) if args.out else Path(__file__).with_name(
        "g_generation_ab_receipts.json")
    out.write_text(json.dumps(receipts, indent=2), encoding="utf-8")

    print(f"\n--- paired deltas vs baseline ({'COMPLETE' if complete else 'PARTIAL'}) ---")
    print(f"brain(s): {', '.join(providers) if providers else 'none'}")
    if len(providers) > 1:
        print("!! MIXED BRAINS: the chain changed tier mid-run. Arms run in the outer "
              "loop, so a flip lands BETWEEN arms and any delta across it measures the "
              "brain, not the lever. Those pairs are DROPPED, not averaged.")
    elif providers and not any("claude" in p for p in providers):
        print(f"!! served entirely by {providers[0]}, the FALLBACK tier. This measures "
              "that brain's response to the levers, not the shipped claude_cli-headed "
              "path. Valid as a paired result; label it with the brain.")
    if saturated:
        print("!! distinct_k is SATURATED: every cell scored k/k, so its deltas below "
              f"are 0.00 by construction and discriminate nothing at --k {args.k}. "
              "Re-run with a larger --k. Ranking is on overlap (lower = more diverse).")

    def _fmt(d: dict | None, label: str, prec: int, note: str = "") -> str:
        if d is None:
            return f"{label} no paired observation"
        if d.get("mean_delta") is None:
            return (f"{label} UNCOMPARABLE — all "
                    f"{d.get('mixed_provider_pairs', 0)} pair(s) crossed brains")
        mixed = d.get("mixed_provider_pairs") or 0
        drop = f", {mixed} dropped (mixed brains)" if mixed else ""
        return (f"{label} {d['mean_delta']:+.{prec}f} "
                f"(won {d['won']} / lost {d['lost']} / tied {d['tied']}, "
                f"n={d['n_pairs']}{drop}){note}")

    for name, per_metric in report.items():
        ov = per_metric.get("mean_pairwise_overlap")
        dk = per_metric.get("distinct_k")
        if ov is None and dk is None:
            print(f"{name:24} no paired observation")
            continue
        # Overlap first: lower is more diverse, so its win/loss reads inverted.
        print(f"{name:24} {_fmt(ov, 'overlap', 4)}")
        print(f"{'':24}   {_fmt(dk, 'distinct_k', 2,
                                '  [saturated - not evidence]' if saturated else '')}")
    print(f"\ncalls: {total_calls} total, by arm: {calls_by_arm}")
    print(f"receipts: {out}")
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
