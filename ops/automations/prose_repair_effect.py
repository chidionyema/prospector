"""Prose repair effect — is the rewrite turn actually moving the number it is spent on.

Generic engine. It knows nothing about this business: the store path, the document types, the
target file and the thresholds all come from the declaration file (default
`ops/config/prose_repair_effect.yaml`). See `docs/OPS_AUTOMATION_PRINCIPLES.md` for the
contract this implements.

WHAT IT IS FOR, and why it is a META-diagnostic rather than a diagnostic. `human_register`
already answers "which packs sit outside the human band". It cannot answer "is the repair that
exists to fix that doing anything", because a pack outside the band looks identical whether the
repair ran and failed or never ran at all. `listing.human_register_repair` has been ON since
2026-08-16, spending a model turn on most drafts. On 2026-08-21 the effect of those turns was
measured for the first time, by hand:

    measure                n     pre    post   change   human p5-p95
    punct_hyphen_per_1k  273   31.84   16.45     -48%   0.69 - 7.05
    punct_comma_per_1k   273   61.30   48.87     -20%   13.27 - 49.11
    hedges_per_1k        273    3.51    3.69      +5%   5.67 - 23.05
    mattr                272    0.77    0.76      -2%   0.63 - 0.71

Two of four armed measures had not responded at all, for five days, and no panel could show
it. That is the gap this closes.

NO BLACK BOXES. Every figure this prints carries the population it came from, the instrument
that produced it, and the band it is judged against. Two honest caveats are printed with the
numbers rather than buried:

  1. `pre` is the target's own `ours_mean`, measured on the corpus that BUILT the target — a
     different and larger population than the one graded here, though with the same function
     (`prose_measure.document_measures`). It is a baseline, not a paired before/after.
  2. Documents are split by the dossier file's mtime against the target's `measured_on`. A
     dossier rewritten later moves across that line. Both counts are reported so the split is
     visible rather than assumed.

There is deliberately NO `--fix`. Nothing here is mechanically repairable: when a measure is
not responding the fix is a change to `prose_target.PROMPT_RULE` or to the repair preamble,
which is a judgement about English and belongs in a diff a person reads. An automation that
offered to "fix" it would be claiming a power it does not have.

Interface (the standard shape, `OPS_AUTOMATION_PRINCIPLES.md` R2):

    python -m ops.automations.prose_repair_effect             # read-only, human output
    python -m ops.automations.prose_repair_effect --json      # what the console calls
    python -m ops.automations.prose_repair_effect --config PATH

Exit codes: 0 every armed measure is responding, 1 at least one is not, 2 could not establish
(missing config, no store, PyYAML absent, too few documents, target unreadable).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - the declaration format is YAML by design
    yaml = None  # type: ignore[assignment]

AUTOMATION = "prose_repair_effect"

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_UNKNOWN = 2

DEFAULT_CONFIG = "ops/config/prose_repair_effect.yaml"

#: Printed with the numbers, never buried. Two of these are honest limits on what
#: the comparison can support, and the third says what is not graded at all.
CAVEATS = [
        "`pre` is the target's own ours_mean, measured on the corpus that built the target "
        "(a larger, earlier population) with the same function. It is a baseline, not a "
        "paired before/after on these documents.",
        "Documents are split by dossier mtime against the target's measured_on date. A "
        "dossier rewritten later counts as after; both counts are shown.",
        "A measure with no armed flag in the target is not graded here at all.",
    ]


@dataclass
class MeasureResult:
    """One armed measure, with everything needed to check the verdict by hand."""

    measure: str
    side: str
    pre: float
    post: float
    n: int
    p5: float
    p95: float
    outside_after: int
    closed_fraction: float
    responding: bool

    @property
    def change_pct(self) -> float:
        return 100.0 * (self.post - self.pre) / self.pre if self.pre else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"measure": self.measure, "side": self.side,
                "pre": round(self.pre, 4), "post": round(self.post, 4),
                "change_pct": round(self.change_pct, 1), "n": self.n,
                "human_p5": self.p5, "human_p95": self.p95,
                "outside_after": self.outside_after,
                "closed_fraction": round(self.closed_fraction, 3),
                "responding": self.responding}


@dataclass
class Report:
    ok: bool = True
    exit_code: int = EXIT_OK
    reason: str = ""
    store: str = ""
    target: str = ""
    measured_on: str = ""
    documents: int = 0
    documents_before: int = 0
    results: list[MeasureResult] = field(default_factory=list)
    #: Shipped with every report, including the ones that establish nothing. An error
    #: report with no provenance is the black box this automation exists to avoid: the
    #: reader most needs to know what was measured exactly when the answer is "could not".
    caveats: list[str] = field(default_factory=lambda: list(CAVEATS))

    def as_dict(self) -> dict[str, Any]:
        return {
            "automation": AUTOMATION,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "ok": self.ok,
            "exit_code": self.exit_code,
            "reason": self.reason,
            "provenance": {
                "store": self.store,
                "target": self.target,
                "target_measured_on": self.measured_on,
                "instrument": "prospector.prose_measure.document_measures",
                "pre_source": "the target's own ours_mean, from the corpus that built it",
                "documents_graded_after": self.documents,
                "documents_graded_before": self.documents_before,
            },
            "caveats": self.caveats,
            "summary": {
                "armed": len(self.results),
                "responding": sum(1 for r in self.results if r.responding),
                "not_responding": sum(1 for r in self.results if not r.responding),
            },
            "findings": [r.as_dict() for r in self.results if not r.responding],
            "measures": [r.as_dict() for r in self.results],
        }


def _unknown(reason: str) -> Report:
    return Report(ok=False, exit_code=EXIT_UNKNOWN, reason=reason)


def _load_config(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is not installed; the declaration format is YAML")
    if not path.exists():
        raise RuntimeError(f"declaration not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"declaration is not a mapping: {path}")
    return data


def _store_dir(repo_root: Path, declared: str) -> Path:
    """PROSPECTOR_STORE_DIR wins, exactly as every other store path resolves."""
    try:
        from prospector import config as _config
        root = _config.store_root()
    except Exception:
        return repo_root / declared
    tail = Path(declared).name
    return root / tail


def _outside_distance(value: float, p5: float, p95: float) -> float:
    """How far a value sits OUTSIDE the human band. Zero anywhere inside it.

    Distance to the nearest EDGE is the wrong measure and was the first version of this
    function. A value that starts above p95, crosses into the band and keeps going gets
    FURTHER from the edge while getting strictly better, so the edge version scored a
    complete success as a regression: on 2026-08-21 `punct_semicolon_per_1k` moved 4.58 to
    2.26 against a band of 0.00-3.72 and was reported "NOT RESPONDING" at -0.72. Inside the
    band there is nothing left to close, so the distance is zero and stays zero.
    """
    if value > p95:
        return value - p95
    if value < p5:
        return p5 - value
    return 0.0


def _closed_fraction(pre: float, post: float, p5: float, p95: float, side: str) -> float:
    """How much of the distance outside the human band the population closed.

    1.0 means it reached the band from wherever it started. 0.0 means it did not move.
    Negative means it moved further out. `side` is unused now and kept in the signature
    because the target declares it and a caller may want to log it.
    """
    before = _outside_distance(pre, p5, p95)
    if before <= 0:
        return 1.0
    return (before - _outside_distance(post, p5, p95)) / before


def run(config_path: Path, repo_root: Path) -> Report:
    try:
        cfg = _load_config(config_path)
    except Exception as exc:
        return _unknown(str(exc))

    try:
        from prospector.prose_measure import document_measures
        from prospector.register_lint import measurable_prose
    except Exception as exc:  # pragma: no cover - import guard
        return _unknown(f"measurement function unimportable: {exc}")

    target_path = repo_root / str(cfg.get("target_path") or "")
    try:
        target = json.loads(target_path.read_text(encoding="utf-8"))
        measures_spec = target["measures"]
        measured_on = str(target.get("measured_on") or "")
    except Exception as exc:
        return _unknown(f"target unreadable ({target_path}): {exc}")

    store = _store_dir(repo_root, str(cfg.get("store_dir") or "store/dossiers"))
    if not store.is_dir():
        return _unknown(f"store directory not found: {store}")

    prose_keys = list(cfg.get("prose_keys") or [])
    glob = str(cfg.get("dossier_glob") or "*.pass.json")
    min_docs = int(cfg.get("min_documents") or 0)
    min_closed = float(cfg.get("min_closed_fraction") or 0.0)

    armed = {name: spec for name, spec in measures_spec.items() if spec.get("armed")}
    if not armed:
        return _unknown(f"no armed measures in {target_path}")

    cutoff = None
    if measured_on:
        try:
            cutoff = datetime.fromisoformat(measured_on).date()
        except ValueError:
            cutoff = None

    after: dict[str, list[float]] = {m: [] for m in armed}
    before_count = 0
    after_count = 0
    for dossier in sorted(store.glob(glob)):
        try:
            data = json.loads(dossier.read_text(encoding="utf-8"))
        except Exception:
            continue
        artifacts = ((data.get("candidate") or {}).get("tags") or {}).get("artifacts") or {}
        if not isinstance(artifacts, dict):
            continue
        written = datetime.fromtimestamp(dossier.stat().st_mtime, timezone.utc).date()
        is_after = cutoff is None or written >= cutoff
        for key in prose_keys:
            content = artifacts.get(key)
            if not (isinstance(content, str) and content.strip()):
                continue
            if not is_after:
                before_count += 1
                continue
            try:
                got = document_measures(measurable_prose(content))
            except Exception:
                continue
            after_count += 1
            for name in armed:
                value = got.get(name)
                if isinstance(value, (int, float)):
                    after[name].append(float(value))

    report = Report(store=str(store), target=str(target_path), measured_on=measured_on,
                    documents=after_count, documents_before=before_count)
    if after_count < min_docs:
        report.ok = False
        report.exit_code = EXIT_UNKNOWN
        report.reason = (f"graded {after_count} documents, below the declared floor of "
                         f"{min_docs}; this store cannot establish the effect")
        return report

    for name, spec in sorted(armed.items()):
        values = after[name]
        if not values:
            continue
        pre = float(spec.get("ours_mean") or 0.0)
        post = statistics.mean(values)
        p5, p95 = float(spec["p5"]), float(spec["p95"])
        side = str(spec.get("side") or ("above" if pre > p95 else "below"))
        outside = sum(1 for v in values if v > p95 or v < p5)
        closed = _closed_fraction(pre, post, p5, p95, side)
        report.results.append(MeasureResult(
            measure=name, side=side, pre=pre, post=post, n=len(values),
            p5=p5, p95=p95, outside_after=outside, closed_fraction=closed,
            responding=closed >= min_closed))

    if not report.results:
        report.ok = False
        report.exit_code = EXIT_UNKNOWN
        report.reason = "no armed measure could be computed on this population"
        return report

    stalled = [r for r in report.results if not r.responding]
    if stalled:
        report.ok = False
        report.exit_code = EXIT_FINDINGS
        report.reason = (f"{len(stalled)} of {len(report.results)} armed measures have not "
                         f"moved a tenth of the way toward the human band since the repair "
                         f"turn shipped: " + ", ".join(r.measure for r in stalled))
    else:
        report.reason = (f"all {len(report.results)} armed measures are responding to the "
                         f"repair turn")
    return report


def _render(report: Report) -> str:
    d = report.as_dict()
    out = [f"########## PROSE REPAIR EFFECT ({'OK' if report.ok else 'FINDINGS'})", ""]
    p = d["provenance"]
    out.append(f"store              : {p['store']}")
    out.append(f"target             : {p['target']}  (measured_on {p['target_measured_on']})")
    out.append(f"instrument         : {p['instrument']}")
    out.append(f"documents graded   : {p['documents_graded_after']} after the target landed, "
               f"{p['documents_graded_before']} before it (not graded)")
    out.append("")
    if report.results:
        out.append(f"{'MEASURE':22s} {'n':>4s} {'PRE':>9s} {'POST':>9s} {'CHANGE':>8s} "
                   f"{'CLOSED':>7s} {'HUMAN BAND':>18s}  OUTSIDE NOW")
        for r in report.results:
            band = f"{r.p5:.2f} - {r.p95:.2f}"
            mark = "" if r.responding else "   <-- NOT RESPONDING"
            out.append(f"{r.measure:22s} {r.n:4d} {r.pre:9.2f} {r.post:9.2f} "
                       f"{r.change_pct:+7.0f}% {r.closed_fraction:7.2f} {band:>18s}  "
                       f"{r.outside_after}/{r.n}{mark}")
        out.append("")
    out.append(f"verdict            : {report.reason}")
    out.append("")
    out.append("HOW TO CHECK THIS BY HAND")
    for c in d["caveats"]:
        out.append(f"  - {c}")
    out.append("")
    out.append("  There is no --fix. When a measure stops responding the change is to the")
    out.append("  wording in prospector/prose_target.py (PROMPT_RULE, ADVICE, or the")
    out.append("  repair_feedback preamble), which is a judgement about English and belongs")
    out.append("  in a diff a person reads.")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    ap.add_argument("--json", action="store_true", help="machine output for the console")
    ap.add_argument("--config", default=None, help="a different declaration file")
    args = ap.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[2]
    config_path = Path(args.config) if args.config else repo_root / DEFAULT_CONFIG
    report = run(config_path, repo_root)

    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        print(_render(report))
    return report.exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
