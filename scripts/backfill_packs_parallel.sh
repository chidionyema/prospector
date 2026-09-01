#!/usr/bin/env bash
# Backfill the P5 pack artefacts (Complete_Pack.pdf, First_Fortnight.html,
# Assumptions.csv, Evidence_and_Constraints.md) into the packs already listed.
#
# Runs tools/backfill_bundle_html.py in N parallel slots, one process per slot,
# each handling an interleaved subset of the live catalogue via --only.
#
# The tool itself is unchanged: it fetches each pack's CURRENT zip from R2 using
# the db pointer (GET /internal/catalog/{id}/content), rebuilds it with the
# generated files re-rendered and the .md deliverables copied byte-identical,
# uploads to a NEW content-addressed key, then repoints the listing via
# PATCH /internal/catalog/{id}/content. The old object is left in place, so a
# buyer who already downloaded is unaffected and a rollback is a repoint.
#
# MUST run under .venv/bin/python: fpdf2 is not installed in the system
# interpreter, and pack_pdf degrades to "no PDF" rather than failing loudly.
#
# Usage:
#   scripts/backfill_packs_parallel.sh            # dry run, 10 slots
#   scripts/backfill_packs_parallel.sh --apply    # upload + repoint
#   SLOTS=4 scripts/backfill_packs_parallel.sh --apply
set -euo pipefail

cd "$(dirname "$0")/.."
SLOTS="${SLOTS:-10}"
APPLY="${1:-}"
OUT="${OUT:-.backfill-logs}"
API="${STORE_API_URL:-https://api.${ESTATE_ZONE:?set ESTATE_ZONE, the estate zone}}"

[ -x .venv/bin/python ] || { echo "FATAL: .venv/bin/python missing"; exit 1; }
.venv/bin/python -c 'import fpdf' 2>/dev/null \
  || { echo "FATAL: fpdf2 not importable in .venv — the PDF would be silently skipped"; exit 1; }

mkdir -p "$OUT"; rm -f "$OUT"/slot*.log "$OUT"/slot*.ids

curl -fsS --max-time 30 "$API/catalog" -o "$OUT/catalog.json"
.venv/bin/python - "$OUT" "$SLOTS" <<'PY'
import json, os, sys
out, slots = sys.argv[1], int(sys.argv[2])
d = json.load(open(os.path.join(out, "catalog.json")))
items = d if isinstance(d, list) else next(v for v in d.values() if isinstance(v, list))
ids = [i["id"] for i in items if isinstance(i, dict) and "id" in i]
for s in range(slots):
    with open(os.path.join(out, f"slot{s}.ids"), "w") as fh:
        # Trailing newline is load-bearing: `while read -r id` in the shell loop
        # below drops the final line of a file that does not end in one, which
        # silently took one pack per slot out of the run (49 of 59 processed).
        fh.write("\n".join(ids[s::slots]) + "\n")
print(f"{len(ids)} packs -> {slots} slots: {[len(ids[s::slots]) for s in range(slots)]}")
PY

set -a; . ./.env; set +a

for s in $(seq 0 $((SLOTS - 1))); do
  args=()
  while read -r id; do [ -n "$id" ] && args+=(--only "$id"); done < "$OUT/slot$s.ids"
  [ ${#args[@]} -eq 0 ] && continue
  .venv/bin/python -u tools/backfill_bundle_html.py ${APPLY:+--apply} "${args[@]}" \
    > "$OUT/slot$s.log" 2>&1 &
done

wait
echo "=== all slots finished (${APPLY:-dry-run}) ==="
grep -hoE '^\s*\[[^]]+\]' "$OUT"/slot*.log | tr -d ' []' | sort | uniq -c | sort -rn
echo "--- logs in $OUT/ ---"
