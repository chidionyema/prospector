"""Put a `human_register` block on every existing `<id>.lint.json`. Report first, `--fix` second.

WHY THIS EXISTS. The ops dashboard panel wants `human_register` in the lint record and no record
carries one, because the block shipped after every pack on disk was linted. The obvious answer is
"run a batch", which costs a full generation cycle for a number that needs no model at all:
`register_lint.register_metrics` is pure measurement over text, and `pack_linter` builds the block
out of exactly three of its return values (pack_linter.py:1858).

SO THIS RE-MEASURES RATHER THAN REGENERATING. Zero model calls, zero network.

ONE HONEST DIFFERENCE FROM A REAL LINT, recorded in the block itself so nobody reads a backfilled
record as a fresh one. `lint_pack` grades `pack_sections or prose` — the assembled 14-section read
when the caller has it, the four model-written documents otherwise. A dossier does not store the
assembled read, so this grades the prose artifacts: the same fallback `lint_pack` takes for a
caller that has no sections, not a shortcut invented here. Every backfilled block carries
`"backfilled": true` and `"corpus": "prose_artifacts"`.
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from prospector.register_lint import register_metrics  # noqa: E402

PROSE = ("build_spec", "gtm_plan", "ops_plan", "financial_model")
STORE = pathlib.Path("/Users/chidionyema/Documents/code/prospector/store/dossiers")

ap = argparse.ArgumentParser()
ap.add_argument("--fix", action="store_true",
                help="write the block into each lint.json (default: report only)")
ap.add_argument("--limit", type=int, default=0)
args = ap.parse_args()

lints = sorted(STORE.glob("*.lint.json"))
if args.limit:
    lints = lints[:args.limit]

already = 0
no_dossier = 0
no_prose = 0
measured = 0
written = 0
outside_any = 0
per_measure: collections.Counter = collections.Counter()
errors = 0

for lint_path in lints:
    pid = lint_path.name[:lint_path.name.find(".")]
    try:
        report = json.loads(lint_path.read_text(encoding="utf-8"))
    except Exception:
        errors += 1
        continue
    if "human_register" in report:
        already += 1
        continue

    dossier = None
    for suffix in (".pass.json", ".kill.json", ".defer.json"):
        p = STORE / f"{pid}{suffix}"
        if p.exists():
            dossier = p
            break
    if dossier is None:
        no_dossier += 1
        continue

    try:
        d = json.loads(dossier.read_text(encoding="utf-8"))
    except Exception:
        errors += 1
        continue
    arts = ((d.get("candidate") or {}).get("tags") or {}).get("artifacts") or {}
    corpus = {t: arts[t] for t in PROSE
              if isinstance(arts.get(t), str) and arts[t].strip()}
    if not corpus:
        no_prose += 1
        continue

    try:
        m = register_metrics(corpus)
    except Exception as exc:
        errors += 1
        print(f"MEASURE FAILED {pid}: {exc}")
        continue

    measured += 1
    outside = m["human_register"]
    if outside:
        outside_any += 1
        for f in outside:
            per_measure[f["measure"]] += 1

    if args.fix:
        report["human_register"] = {
            "measures": m["prose_measures"],
            "outside": outside,
            "error": m["human_register_error"],
            # Provenance, so a backfilled block is never mistaken for a fresh lint.
            "backfilled": True,
            "corpus": "prose_artifacts",
            "backfilled_at": _dt.datetime.now(_dt.timezone.utc)
                              .strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        tmp = lint_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(lint_path)
        written += 1

mode = "FIX" if args.fix else "REPORT ONLY"
print(f"########## HUMAN REGISTER BACKFILL ({mode})")
print(f"lint records seen        : {len(lints)}")
print(f"already had the block    : {already}")
print(f"no dossier for the id    : {no_dossier}")
print(f"dossier had no prose     : {no_prose}")
print(f"read/measure errors      : {errors}")
print(f"measured                 : {measured}")
print(f"written                  : {written}")
pct = (100.0 * outside_any / measured) if measured else 0.0
print(f"outside the human range  : {outside_any}  ({pct:.1f}% of measured)")
for k, n in per_measure.most_common():
    print(f"   {k:24s} {n}")
print("########## END")
