#!/usr/bin/env python3
"""One command that reads every axis in the 1000x programme and writes a dated report.

    .venv/bin/python tools/engine_baseline.py                 # print the report
    .venv/bin/python tools/engine_baseline.py --write         # also save it under store/baselines/

Why this exists. `docs/ENGINE_100X_PROGRAM.md` section 1 lists nine axes. On 2026-08-20 five of
them had no baseline at all, which means a claim of "1000x better" on those five could be neither
proved nor refuted. An axis with no unit cannot be improved by a thousand times, because nobody
can say what a thousand times of it is.

The rule this file obeys: **every axis returns a number with its provenance, or the literal string
UNOBTAINABLE with the reason it cannot be read.** A blank is not allowed. A missing number is a
finding, and printing it as a finding is the whole point — a report that quietly omits the axes it
could not read looks identical to a report where everything is fine.

Nothing here calls a model. Every number is read off the store, the config or the filesystem, so
this runs while the engine is blind, which is exactly when it is most needed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.experiments import _corpus  # noqa: E402

UNOBTAINABLE = "UNOBTAINABLE"

# The six checks a full vet runs. A vet that ran all six paid six calls; kill-fast stops earlier.
FULL_VET_CHECKS = 6

# A rationale that shares a long literal run with the passage it cites was read rather than
# recalled. Twelve words is long enough that agreement by chance is negligible and short enough
# that a paraphrase of one clause still counts. This is the same rule price_comparables already
# enforces on its anchors, applied as a MEASUREMENT rather than a gate.
ANCHOR_NGRAM_WORDS = 12


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _shares_long_run(rationale: str, passages: list[str]) -> bool:
    """True when the rationale and some passage share a run of ANCHOR_NGRAM_WORDS words."""
    rat = _words(rationale)
    if len(rat) < ANCHOR_NGRAM_WORDS:
        return False
    grams = {
        " ".join(rat[i : i + ANCHOR_NGRAM_WORDS]) for i in range(len(rat) - ANCHOR_NGRAM_WORDS + 1)
    }
    for passage in passages:
        pas = _words(passage)
        if len(pas) < ANCHOR_NGRAM_WORDS:
            continue
        for i in range(len(pas) - ANCHOR_NGRAM_WORDS + 1):
            if " ".join(pas[i : i + ANCHOR_NGRAM_WORDS]) in grams:
                return True
    return False


def _null_control(pairs: list[tuple[str, list[str]]]) -> int:
    """How often the anchor test fires on evidence that CANNOT be the source of the rationale.

    Each rationale is re-scored against a DIFFERENT check's passages. The offset is half the
    population, a fixed number rather than a random one, so a re-run over the same corpus gives
    the same answer and two runs are comparable rather than merely similar (`_corpus` documents
    the 2026-08-07 case where a moving corpus shifted E15's tau from 0.0589 to 0.0691).

    Read the result this way: a null rate near zero means the real rate is signal. A null rate
    close to the real rate means the metric is reading boilerplate that every passage shares,
    and the real rate is worth nothing.
    """
    n = len(pairs)
    if n < 2:
        return 0
    offset = n // 2
    hits = 0
    for i, (rationale, _own) in enumerate(pairs):
        _other_rationale, other_texts = pairs[(i + offset) % n]
        if _shares_long_run(rationale, other_texts):
            hits += 1
    return hits


class Axis:
    """One row of the report. `value` is a number, or UNOBTAINABLE with a reason."""

    def __init__(self, axis_id: str, name: str, unit: str):
        self.id = axis_id
        self.name = name
        self.unit = unit
        self.value = UNOBTAINABLE
        self.reason = "not attempted"
        self.command = ""
        self.detail: dict = {}

    def set(self, value, command: str = "", **detail):
        self.value = value
        self.reason = ""
        self.command = command
        self.detail = detail
        return self

    def unobtainable(self, reason: str, command: str = ""):
        self.value = UNOBTAINABLE
        self.reason = reason
        self.command = command
        return self

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "unit": self.unit,
            "value": self.value,
            "reason": self.reason,
            "command": self.command,
            "detail": self.detail,
        }


def scan_corpus() -> dict:
    """One pass over the dossier store. Everything downstream is derived from this."""
    dossiers = 0
    checks = 0
    verdicts: Counter = Counter()
    decisions: Counter = Counter()
    retrieval_failed = 0
    provisional = 0
    calls_per_vet: list[int] = []
    full_vets = 0
    ruled_with_passage = 0
    ruled_anchored = 0
    ruled_pairs: list[tuple[str, list[str]]] = []
    dossier_times: list[datetime] = []
    zero_byte: list[str] = []
    non_dossier = 0
    evidence_chars: list[int] = []

    paths = _corpus.dossier_paths()
    for path in paths:
        try:
            if os.path.getsize(path) == 0:
                zero_byte.append(os.path.basename(path))
                continue
        except OSError:
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                dossier = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(dossier, dict):
            continue
        if "checks" not in dossier and "candidate" not in dossier:
            # store/dossiers also holds pack lint reports (`*.lint.json`). Counting those as
            # dossiers drags every rate toward zero while still printing as a measurement.
            non_dossier += 1
            continue

        dossiers += 1
        decisions[str(dossier.get("decision") or "unknown")] += 1
        created = _parse_ts(dossier.get("created_at"))
        if created:
            dossier_times.append(created)

        index = _corpus.source_index(dossier)
        chk_list = dossier.get("checks") or []
        paid = 0
        for chk in chk_list:
            if not isinstance(chk, dict):
                continue
            checks += 1
            paid += 1
            verdict = str(chk.get("verdict") or "unknown")
            verdicts[verdict] += 1
            if chk.get("retrieval_failed"):
                retrieval_failed += 1
            if chk.get("provisional"):
                provisional += 1

            sources, _missing = _corpus.cited_sources(chk, index)
            texts = [str(s.get("text") or "") for s in sources if s.get("text")]
            evidence_chars.append(sum(len(t) for t in texts))
            if verdict in ("supported", "refuted") and texts:
                ruled_with_passage += 1
                rationale = str(chk.get("rationale") or "")
                ruled_pairs.append((rationale, texts))
                if _shares_long_run(rationale, texts):
                    ruled_anchored += 1

        if paid:
            calls_per_vet.append(paid)
        if paid >= FULL_VET_CHECKS:
            full_vets += 1

    return {
        "paths": len(paths),
        "dossiers": dossiers,
        "checks": checks,
        "verdicts": verdicts,
        "decisions": decisions,
        "retrieval_failed": retrieval_failed,
        "provisional": provisional,
        "calls_per_vet": calls_per_vet,
        "full_vets": full_vets,
        "ruled_with_passage": ruled_with_passage,
        "ruled_anchored": ruled_anchored,
        "null_anchored": _null_control(ruled_pairs),
        "dossier_times": dossier_times,
        "zero_byte": zero_byte,
        "non_dossier": non_dossier,
        "evidence_chars": evidence_chars,
    }


def read_health(store: Path) -> dict:
    path = store / "provider_health.json"
    if not path.exists():
        return {"present": False}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"present": True, "error": str(exc)}
    now = _now().timestamp()
    benched = {}
    for tier, entry in raw.items() if isinstance(raw, dict) else []:
        until = entry.get("dead_until") if isinstance(entry, dict) else None
        if isinstance(until, (int, float)) and until > now:
            benched[tier] = round(until - now, 1)
    return {
        "present": True,
        "tiers": list(raw) if isinstance(raw, dict) else [],
        "benched": benched,
    }


def axis_a1(health: dict, moat_primary: list[str]) -> Axis:
    axis = Axis("A1", "availability", "% of configured trusted brains not benched right now")
    cmd = "python3 -c \"import json,pathlib;print(pathlib.Path('store/provider_health.json').read_text())\""
    if not health.get("present"):
        return axis.unobtainable(
            "store/provider_health.json is absent — no brain has ever been marked here, "
            "which on an empty store means the daemon writes elsewhere, not that all is well",
            cmd,
        )
    if not moat_primary:
        return axis.unobtainable("config declares no moat_primary tiers", cmd)
    benched = health.get("benched") or {}
    live = [t for t in moat_primary if t not in benched]
    return axis.set(
        round(100.0 * len(live) / len(moat_primary), 1),
        cmd,
        moat_primary=moat_primary,
        live=live,
        benched=benched,
        note="a tier with no dead mark is UNBENCHED, which is weaker than PROVEN LIVE; "
        "only a real verdict call proves live",
    )


def axis_a2(scan: dict) -> Axis:
    axis = Axis("A2", "throughput", "dossiers written per hour, trailing 24h and 7d")
    times = scan["dossier_times"]
    if not times:
        return axis.unobtainable(
            f"no dossier carries a parseable created_at ({scan['dossiers']} dossiers read)"
        )
    now = _now()
    out = {}
    for label, hours in (("24h", 24), ("7d", 168)):
        cutoff = now - timedelta(hours=hours)
        n = sum(1 for t in times if t >= cutoff)
        out[label] = round(n / hours, 3)
    span_h = max((max(times) - min(times)).total_seconds() / 3600.0, 1e-9)
    return axis.set(
        out["24h"],
        "tools/engine_baseline.py",
        windows=out,
        lifetime_per_hour=round(len(times) / span_h, 3),
        newest=_iso(max(times)),
        oldest=_iso(min(times)),
    )


def axis_a3(scan: dict) -> Axis:
    axis = Axis("A3", "latency", "seconds, candidate in to verdict out, p50 and p95")
    return axis.unobtainable(
        "no per-stage timer is recorded anywhere in a dossier. A dossier carries created_at and "
        "nothing else time-shaped, so start-to-finish cannot be reconstructed after the fact. "
        "Item 1.4 in docs/ENGINE_1000X_ACTION_PLAN.md is the fix and it is not built yet."
    )


def axis_a4(store: Path) -> Axis:
    axis = Axis("A4", "discrimination", "golden-set accuracy, %")
    golden_dir = store / "golden_runs"
    runs = sorted(golden_dir.glob("*.json")) if golden_dir.is_dir() else []
    if not runs:
        return axis.unobtainable(
            f"no stored golden run under {golden_dir}. `.venv/bin/python -m prospector.run "
            "diagnose --deep` writes one and needs a live brain. The mock gate at "
            "tests/test_golden_set.py:163 needs none but asserts a fixed 1.0, so it proves the "
            "harness works and measures nothing about the engine.",
            ".venv/bin/python -m prospector.run diagnose --deep",
        )
    # Filenames are `<operator>_<YYYYmmddTHHMMSSffffff>.json`, so lexical order on the stamp is
    # chronological. Sorting the paths would order by OPERATOR first and pick the wrong run.
    latest = max(runs, key=lambda p: p.name.rsplit("_", 1)[-1])
    try:
        raw = json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return axis.unobtainable(f"{latest.name} unreadable: {exc}")
    value = raw.get("discrimination")
    if value is None:
        return axis.unobtainable(f"{latest.name} carries no discrimination field")

    cases = [c for c in (raw.get("per_case") or []) if isinstance(c, dict)]
    gate_matched = sum(1 for c in cases if c.get("gate_match"))
    detail = {
        "run": latest.name,
        "operator": raw.get("operator"),
        "cases": len(cases),
        "stored_runs": len(runs),
    }
    if cases:
        detail["gate_accuracy_pct"] = round(100.0 * gate_matched / len(cases), 1)
        detail["gate_matched"] = f"{gate_matched}/{len(cases)}"
    detail["note"] = (
        "discrimination on a nine-item set is a SATURATED instrument at 1.00: it can register "
        "neither an improvement nor a regression, which is why E-040..E-045 are unrunnable. "
        "GATE ACCURACY, in the same file and excluded from the score, is not saturated — it is "
        "a live unsaturated number that needs no new labels and no money. Use it as the interim "
        "quality axis while the golden set is being resolved."
    )
    return axis.set(round(100.0 * float(value), 1), f"cat {latest}", **detail)


def axis_a5(scan: dict) -> Axis:
    axis = Axis("A5", "yield", "PASS decisions per 1000 dossiers")
    total = scan["dossiers"]
    if not total:
        return axis.unobtainable("the store holds no readable dossiers")
    decisions = scan["decisions"]
    known = sum(n for d, n in decisions.items() if d.lower() not in ("unknown", "none", ""))
    if not known:
        return axis.unobtainable(
            f"{total} dossiers read and not one carries a decision field, so a PASS rate would "
            "be 0/0 dressed up as 0%"
        )
    passes = sum(n for d, n in decisions.items() if d.upper().startswith("PASS"))
    return axis.set(
        round(1000.0 * passes / total, 1),
        "tools/engine_baseline.py",
        passes=passes,
        dossiers=total,
        decisions=dict(decisions.most_common()),
        note="this is PASSES PER 1000, not survival of founder review. The programme's A5 asks "
        "how many survive review, and nothing records a review outcome, so that half is "
        "still UNOBTAINABLE.",
    )


def axis_a6(store: Path, scan: dict) -> Axis:
    """Cost per candidate vetted, joined on the candidate id the cost row itself carries.

    This axis used to divide TOTAL ledger spend by the check count of the dossier corpus. Those
    are two different populations over two different time windows — on the canonical store
    2026-08-20 the ledger's cost rows were hours old while the corpus was months old — so the
    quotient was arithmetic rather than a measurement. It is now a self-join: only rows that
    name a `candidate_id` count, and the denominator is the distinct ids in those same rows.

    The row is emitted by the Claude CLI adapter and carries the provider's OWN billed figure,
    not a price table of ours, so this is a meter reading rather than an estimate. Rows with a
    cost but no candidate id (a warm-up or a non-vetting call) are reported separately and never
    folded into the per-candidate number.
    """
    axis = Axis("A6", "cost", "USD per candidate vetted (median)")
    ledger = store / "prospector.jsonl"
    if not ledger.exists():
        return axis.unobtainable("store/prospector.jsonl is absent", f"wc -l {ledger}")

    rows = 0
    per_candidate: dict[str, float] = {}
    calls_per_candidate: Counter[str] = Counter()
    attributed_calls = 0
    unattributed_usd = 0.0
    unattributed_calls = 0
    with ledger.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows += 1
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict):
                continue
            cost = None
            for key in ("cost_usd", "cost", "usd"):
                val = rec.get(key)
                if isinstance(val, (int, float)):
                    cost = float(val)
                    break
            if cost is None or cost <= 0:
                continue
            cid = str(rec.get("candidate_id") or "").strip()
            if not cid:
                unattributed_usd += cost
                unattributed_calls += 1
                continue
            per_candidate[cid] = per_candidate.get(cid, 0.0) + cost
            calls_per_candidate[cid] += 1
            attributed_calls += 1

    if not per_candidate:
        priced = unattributed_calls
        return axis.unobtainable(
            f"no ledger row in {rows} carries BOTH a cost field and a candidate_id, so cost per "
            f"candidate cannot be joined ({priced} priced row(s) name no candidate). Check the "
            "store: a cost meter that reads zero on one store and non-zero on another is a "
            "pointer bug, not an absent meter.",
            f"wc -l {ledger}",
        )

    costs = sorted(per_candidate.values())
    calls = sorted(calls_per_candidate.values())
    return axis.set(
        round(statistics.median(costs), 4),
        f"wc -l {ledger}",
        ledger_rows=rows,
        candidates_priced=len(costs),
        priced_calls=attributed_calls,
        mean_usd=round(sum(costs) / len(costs), 4),
        min_usd=round(costs[0], 4),
        max_usd=round(costs[-1], 4),
        calls_per_candidate_median=statistics.median(calls),
        attributed_usd=round(sum(costs), 4),
        unattributed_usd=round(unattributed_usd, 4),
        unattributed_calls=unattributed_calls,
        note=(
            "MEDIAN, not mean: the spread is wide (a vet that retries costs several times a vet "
            "that does not), so the mean tracks the tail rather than the typical candidate. "
            "Both are printed. This counts only what a provider billed and reported back; a "
            "provider that reports no cost is invisible here and its calls are free of charge to "
            "this number, not free of charge to the business."
        ),
    )


def axis_a7(scan: dict) -> Axis:
    axis = Axis(
        "A7",
        "grounding fidelity",
        f"% of ruled checks whose rationale shares a {ANCHOR_NGRAM_WORDS}-word literal "
        "run with a passage it cites",
    )
    n = scan["ruled_with_passage"]
    if not n:
        return axis.unobtainable("no ruled check in the store resolves to a stored passage")
    k = scan["ruled_anchored"]
    lo, hi = _corpus.wilson(k, n)
    null_k = scan["null_anchored"]
    null_rate = round(100.0 * null_k / n, 2)
    nlo, nhi = _corpus.wilson(null_k, n)
    verdict = (
        "SIGNAL: the real rate sits above the null interval"
        if 100 * lo > 100 * nhi
        else "NOT SIGNAL: the real rate overlaps the null control, so this metric is reading "
        "shared boilerplate rather than grounding — do not use it as an axis"
    )
    return axis.set(
        round(100.0 * k / n, 2),
        "tools/engine_baseline.py",
        anchored=k,
        ruled_with_passage=n,
        ci95=[round(100 * lo, 2), round(100 * hi, 2)],
        null_control_pct=null_rate,
        null_ci95=[round(100 * nlo, 2), round(100 * nhi, 2)],
        control_verdict=verdict,
        note="this is a LOWER BOUND on fidelity and an upper bound on nothing. A faithful "
        "rationale that paraphrases every clause scores 0 here. It is deterministic, free, "
        "and it moves when the engine changes, which is what an instrument has to do. "
        "It does NOT replace E15's entailment measurement or human labels.",
    )


def axis_a8(scan: dict) -> Axis:
    axis = Axis("A8", "abstention", "% of checks attempted (supported or refuted)")
    total = scan["checks"]
    if not total:
        return axis.unobtainable("the store holds no checks")
    verdicts = scan["verdicts"]
    attempted = verdicts.get("supported", 0) + verdicts.get("refuted", 0)
    return axis.set(
        round(100.0 * attempted / total, 2),
        "tools/engine_baseline.py",
        attempted=attempted,
        checks=total,
        verdicts=dict(verdicts.most_common()),
        note="CALIBRATION — accuracy on the attempted fraction — is the other half of A8 and is "
        "UNOBTAINABLE until a human-labelled set exists (action plan item 1.2). Percent "
        "attempted alone can be raised to 100 by a model that guesses, so this number is "
        "meaningless without its partner.",
    )


def cost_anatomy(scan: dict) -> dict:
    """Where the money goes. This is the measurement that justified merging the six calls."""
    calls = scan["calls_per_vet"]
    out: dict = {}
    if calls:
        ordered = sorted(calls)
        out["vets"] = len(calls)
        out["calls_per_vet_mean"] = round(sum(calls) / len(calls), 3)
        out["calls_per_vet_median"] = ordered[len(ordered) // 2]
        out["full_vets"] = scan["full_vets"]
        out["full_vet_pct"] = round(100.0 * scan["full_vets"] / len(calls), 1)
    ev = [c for c in scan["evidence_chars"] if c]
    if ev:
        ev.sort()
        out["evidence_chars_median"] = ev[len(ev) // 2]
        out["evidence_chars_mean"] = round(sum(ev) / len(ev))
    return out


def build_report(store: Path, moat_primary: list[str]) -> dict:
    scan = scan_corpus()
    health = read_health(store)
    axes = [
        axis_a1(health, moat_primary),
        axis_a2(scan),
        axis_a3(scan),
        axis_a4(store),
        axis_a5(scan),
        axis_a6(store, scan),
        axis_a7(scan),
        axis_a8(scan),
    ]
    return {
        "generated_at": _iso(_now()),
        "store": str(store),
        "corpus_fingerprint": _corpus.corpus_fingerprint(),
        "corpus": {
            "dossier_files": scan["paths"],
            "dossiers_read": scan["dossiers"],
            "checks": scan["checks"],
            "retrieval_failed_checks": scan["retrieval_failed"],
            "provisional_checks": scan["provisional"],
            "zero_byte_dossiers": scan["zero_byte"],
            "non_dossier_json": scan["non_dossier"],
        },
        "cost_anatomy": cost_anatomy(scan),
        "axes": [a.as_dict() for a in axes],
        "unobtainable": [a.id for a in axes if a.value == UNOBTAINABLE],
    }


def render(report: dict) -> str:
    lines = [
        f"ENGINE BASELINE  {report['generated_at']}",
        f"store: {report['store']}",
        f"corpus: {report['corpus_fingerprint']['corpus_dir']}",
        f"fingerprint: {report['corpus_fingerprint']['sha256']}  "
        f"frozen={report['corpus_fingerprint']['frozen']}  "
        f"newest={report['corpus_fingerprint']['newest_mtime_utc']}",
        "",
    ]
    corpus = report["corpus"]
    lines.append(
        f"corpus: {corpus['dossiers_read']} dossiers read of {corpus['dossier_files']} files, "
        f"{corpus['checks']} checks, {corpus['retrieval_failed_checks']} retrieval_failed, "
        f"{corpus['provisional_checks']} provisional, "
        f"{corpus['non_dossier_json']} non-dossier json skipped"
    )
    if corpus["zero_byte_dossiers"]:
        lines.append(
            f"  ZERO-BYTE DOSSIERS: {len(corpus['zero_byte_dossiers'])} — "
            + ", ".join(corpus["zero_byte_dossiers"][:8])
        )
    lines.append("")

    for axis in report["axes"]:
        head = f"{axis['id']:<4} {axis['name']:<20} "
        if axis["value"] == UNOBTAINABLE:
            lines.append(head + "UNOBTAINABLE")
            lines.append(f"       why: {axis['reason']}")
        else:
            lines.append(head + f"{axis['value']}  ({axis['unit']})")
            for key, val in axis["detail"].items():
                if key == "note":
                    continue
                lines.append(f"       {key}: {val}")
            note = axis["detail"].get("note")
            if note:
                lines.append(f"       note: {note}")
        if axis["command"]:
            lines.append(f"       reproduce: {axis['command']}")
        lines.append("")

    anatomy = report["cost_anatomy"]
    if anatomy:
        lines.append("COST ANATOMY")
        for key, val in anatomy.items():
            lines.append(f"       {key}: {val}")
        lines.append("")

    missing = report["unobtainable"]
    lines.append(
        f"UNOBTAINABLE AXES: {len(missing)} of {len(report['axes'])}"
        + (f" — {', '.join(missing)}" if missing else "")
    )
    lines.append(
        "An axis with no unit cannot be improved by 1000x, because nobody can say what 1000x of "
        "it is. Each line above names what it would take to read it."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--store", help="store directory (default: PROSPECTOR_STORE_DIR or config)")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of the text report")
    parser.add_argument(
        "--write", action="store_true", help="also save a dated copy under <store>/baselines/"
    )
    args = parser.parse_args(argv)

    if args.store:
        store = Path(args.store).expanduser().resolve()
        # _corpus resolves its directory per call from the environment, so setting these two
        # is what makes --store actually redirect the READ as well as the report header. Without
        # it the harness reads one store's dossiers and prints another store's ledger, and the
        # two numbers look like they came from the same place.
        os.environ.setdefault("PROSPECTOR_CORPUS_DIR", str(store / "dossiers"))
        os.environ.setdefault("PROSPECTOR_CORPUS_DB", str(store / "prospector.db"))
    else:
        from prospector.config import store_root

        store = store_root()

    moat_primary: list[str] = []
    try:
        from prospector import operator as op_mod
        from prospector.config import load_config

        load_config()  # installs process-global config the readers below depend on
        moat_primary = sorted(op_mod.moat_primary())
    except Exception as exc:  # config problems must not stop the axes that need no config
        print(f"[warn] config unreadable, A1 will report UNOBTAINABLE: {exc}", file=sys.stderr)

    report = build_report(store, moat_primary)
    text = json.dumps(report, indent=2, sort_keys=True) if args.json else render(report)
    print(text)

    if args.write:
        out_dir = store / "baselines"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = report["generated_at"].replace(":", "").replace("-", "")
        (out_dir / f"baseline-{stamp}.json").write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
        )
        (out_dir / f"baseline-{stamp}.txt").write_text(render(report), encoding="utf-8")
        print(f"\nwritten: {out_dir}/baseline-{stamp}.{{json,txt}}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
