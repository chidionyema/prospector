#!/usr/bin/env bash
# Copy audit across BOTH lanes. Read-only: reports, changes nothing.
#
#   lane 1  MARKETING  — hardcoded storefront prose (.tsx), audited by Vale
#   lane 2  PACK       — engine-authored dossier/listing prose, audited by the same
#                        deterministic checks the publish gate runs (prospector/copy_lint.py)
#
# The publish gate is the enforcement point and runs automatically per pack; this script is
# for sweeping the whole estate at once, e.g. after changing a rule.
#
# Exit 0 = clean. Non-zero = at least one lane found an error-severity defect.
set -uo pipefail
cd "$(dirname "$0")/.."
RC=0

echo "== lane 1: MARKETING copy (storefront .tsx) =================================="
if command -v vale >/dev/null 2>&1; then
  vale --no-exit --output=line store_platform/src/Store.Web/src 2>&1 | tail -40
  vale --no-exit --output=JSON store_platform/src/Store.Web/src 2>/dev/null \
    | python3 -c '
import json,sys
d=json.load(sys.stdin) or {}
n=sum(len(v) for v in d.values())
print(f"  marketing defects: {n} across {len(d)} file(s)")
sys.exit(1 if n else 0)
' || RC=1
else
  echo "  vale not installed (brew install vale) — lane skipped, NOT clean"
  RC=1
fi

echo
echo "== lane 2: PACK copy (dossiers + listings) ==================================="
python3 - <<'PY' || RC=1
import glob, json, sys
sys.path.insert(0, ".")
from prospector.copy_lint import check_house_dashes, check_identifier_leak

NON_PROSE = {"id", "dossierRef", "paymentProvider", "providerProductId",
             "providerPriceId", "contentKey", "contentHash", "market", "verifiedAt"}
problems = 0
files = 0
for f in sorted(glob.glob("store/listings/*.json")):
    d = json.load(open(f, encoding="utf-8"))
    fields = {k: v for k, v in d.items()
              if isinstance(v, str) and k not in NON_PROSE}
    ps = check_house_dashes(fields) + check_identifier_leak(fields)
    if ps:
        files += 1
        problems += len(ps)
        print(f"  {f.split('/')[-1]}")
        for p in ps[:3]:
            print(f"     [{p['severity']}] {p['check']} @ {p['where']}")
print(f"  pack defects: {problems} across {files} listing(s)")
sys.exit(1 if problems else 0)
PY

echo
echo "== RESULT: $([ $RC -eq 0 ] && echo CLEAN || echo DEFECTS FOUND) =="
exit $RC
