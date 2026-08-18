"""Report-only: how far the prose already on disk sits outside the human register.

Zero model calls. Grades every prose artifact in every PASS dossier with the SAME functions
the engine uses (`register_lint.measurable_prose` + `prose_target.grade_text`), which is what
`artifacts._prose_findings` calls on draft one. So the "documents with findings" figure below
IS the share of drafts that would spend a repair turn under `listing.human_register_repair`.
"""
import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from prospector import prose_target
from prospector.register_lint import measurable_prose

PROSE = ("build_spec", "gtm_plan", "ops_plan")
root = pathlib.Path("/Users/chidionyema/Documents/code/prospector/store/dossiers")

docs = 0
with_findings = 0
per_measure = collections.Counter()
per_type = collections.Counter()
per_type_total = collections.Counter()
unreadable = 0

for f in sorted(root.glob("*.pass.json")):
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        continue
    arts = ((d.get("candidate") or {}).get("tags") or {}).get("artifacts") or {}
    if not isinstance(arts, dict):
        continue
    for t in PROSE:
        content = arts.get(t)
        if not isinstance(content, str) or not content.strip():
            continue
        docs += 1
        per_type_total[t] += 1
        try:
            findings = prose_target.grade_text(measurable_prose(content))
        except Exception as exc:
            unreadable += 1
            print("GRADE FAILED", f.name, t, exc)
            continue
        if findings:
            with_findings += 1
            per_type[t] += 1
            for fi in findings:
                per_measure[fi["measure"]] += 1

print("########## REGISTER BASELINE (draft one, on disk, no model calls)")
print(f"prose documents graded : {docs}")
print(f"grade failed           : {unreadable}")
pct = (100.0 * with_findings / docs) if docs else 0.0
print(f"outside human range    : {with_findings}  ({pct:.1f}%)")
print("-- by artifact type (outside / total)")
for t in PROSE:
    print(f"   {t:14s} {per_type[t]:4d} / {per_type_total[t]:4d}")
print("-- findings by measure (a document can carry several)")
for m, n in per_measure.most_common():
    print(f"   {m:24s} {n}")
print("########## END")
