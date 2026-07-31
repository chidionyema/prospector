#!/usr/bin/env bash
# Publish all non-provisional PASSes that lack store/listings receipts.
#
# Stopping this used to be a fight (2026-07-31). Two structural reasons, both fixed here:
#   1. The driver loop treated a killed batch as a normal iteration — `subprocess.run` just
#      returned a negative code and the loop launched the NEXT batch. Killing a child was
#      therefore indistinguishable from a batch finishing. The `exit=-15` / `exit=-9` rows in
#      the log are that bug. Fixed by a signal handler that sets a stop flag AND by treating a
#      signal-killed child (negative returncode) as fatal.
#   2. Nothing stopped two backfills running at once. An earlier run whose shell had died left
#      an orphaned driver grinding batches for 5h23m, interleaved into this same log, and was
#      invisible to anyone reading `ps` for the shell. Fixed by a single-instance lock, which
#      lives in the Python driver on fcntl.flock — NOT in this script, because the flock(1)
#      command does not exist on macOS and a shell-level lock silently refused every run.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"
# Do NOT pin concurrency here. This used to default to 2, and the env var WINS over config
# (cursor_cli.configure_concurrency returns early when it is set), so this line silently
# overrode retrieval.cursor_concurrency and kept the backfill at 2 slots forever. Oversubscription
# was the real reason a low number looked necessary, and prospector/cli_governor.py now enforces
# the cap machine-wide via flock — every pipeline draws from ONE shared pool of slot files, so
# config can be the single source of truth again. An explicit env var still overrides for debugging.
if [ -n "${PROSPECTOR_CURSOR_CONCURRENCY:-}" ]; then
  export PROSPECTOR_CURSOR_CONCURRENCY
fi
LOG="${ROOT}/store/control_center/runs/backfill_all_listings.log"
mkdir -p "$(dirname "$LOG")"

exec >>"$LOG" 2>&1

# Run the driver in its own process group so one kill reaches the driver, the current
# publish_passes batch, and its cursor-agent grandchildren together. Killing only the shell
# used to orphan the whole subtree (`ppid=1`), which then had to be hunted down by hand.
cleanup() {
  trap - TERM INT EXIT
  if [ -n "${DRIVER_PID:-}" ] && kill -0 "$DRIVER_PID" 2>/dev/null; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] stopping backfill process group -$DRIVER_PID"
    kill -TERM -- "-$DRIVER_PID" 2>/dev/null || kill -TERM "$DRIVER_PID" 2>/dev/null || true
    for _ in $(seq 1 30); do
      kill -0 "$DRIVER_PID" 2>/dev/null || break
      sleep 1
    done
    kill -KILL -- "-$DRIVER_PID" 2>/dev/null || true
  fi
}
trap cleanup TERM INT EXIT

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backfill_missing_listings start (pid $$)"

# `set -m` (job control) puts the background job in its OWN process group, which is what makes
# `kill -- -$DRIVER_PID` in cleanup() reach the driver, its publish_passes batch and the
# cursor-agent grandchildren in one signal. setsid(1) would be the obvious tool and is what
# Linux notes recommend — it is NOT installed on macOS, this project's host, same trap as
# flock(1). Job control is in bash itself, so it works on both.
set -m
set +e
"$PY" -u "${ROOT}/tools/_backfill_driver.py" "$@" &
DRIVER_PID=$!
wait "$DRIVER_PID"
RC=$?
set -e
set +m
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backfill_missing_listings exit=$RC"
exit "$RC"
