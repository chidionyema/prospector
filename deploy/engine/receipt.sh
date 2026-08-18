#!/usr/bin/env bash
# Run a command and leave a durable record of how it went, on the volume.
#
# WHY. Hermes grades this estate from ~/.hermes/state/capability_receipts.jsonl. Those receipts
# were written by a launchd wrapper on the laptop. The jobs moved to Fly, launchd is not here, and
# three capabilities - store_backup, prospector_watchdog, prospector_generation - would grade DARK
# forever while the jobs ran perfectly. A monitor that cannot see the thing it monitors is worse
# than no monitor, because it reports a state.
#
# The receipt goes on the VOLUME, not to stdout. supervisord sends stdout to /dev/stdout, which
# Fly keeps for a short window; a nightly job graded on a log that ages out is graded on nothing.
# A file on the volume survives restarts, redeploys and log rotation, and `engine_failover.py
# receipts` pulls it down to the laptop and signs it into the Hermes ledger.
#
# usage: receipt.sh <script-key> <command...>
#
# <script-key> must match `observable.script` in ~/.hermes/capabilities.json exactly. That string
# is the join between the two systems.
#
# The exit code passed through is the child's, unchanged. Observing a job must never fail it, so
# every failure in here is swallowed after the child has already run.
set -uo pipefail

KEY="${1:?usage: receipt.sh <script-key> <command...>}"
shift

# No default. The one resolver for this path is config.store_root(), which reads this
# variable; a second copy of the answer hardcoded here is how a job ends up writing beside
# the code instead of onto the volume, which is exactly the bug that broke the nightly
# backup on Fly. If the variable is missing the job should fail loudly, not guess.
SDIR="${PROSPECTOR_STORE_DIR:?receipt.sh needs PROSPECTOR_STORE_DIR}"
OUT="$SDIR/ops/receipts"

STARTED=$(date +%s)
"$@"
CODE=$?
ENDED=$(date +%s)

mkdir -p "$OUT" 2>/dev/null || true
cat > "$OUT/$KEY.json.tmp" 2>/dev/null <<JSON || true
{"script": "$KEY",
 "label": "fly:prospector-engine",
 "source": "fly",
 "started_at": $STARTED,
 "ended_at": $ENDED,
 "duration_s": $((ENDED - STARTED)),
 "exit_code": $CODE,
 "artifact_count": 0,
 "attribution": "container"}
JSON
mv "$OUT/$KEY.json.tmp" "$OUT/$KEY.json" 2>/dev/null || true

exit $CODE
