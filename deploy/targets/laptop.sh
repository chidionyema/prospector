#!/usr/bin/env bash
# This laptop. It is a platform like any other, so it gets an adapter like any other.
#
# Two reasons this file exists rather than the cutover script special-casing the Mac:
#   1. The migration and the rollback are then the same command with the ends swapped.
#   2. "Come back to the laptop" stays a tested path, which is what makes leaving Fly safe.
#
# Its jobs are launchd, not Docker, so t_release is a no-op: the code is already here.

set -euo pipefail

REPO="${PROSPECTOR_REPO:-/Users/chidionyema/Documents/code/prospector}"
LIVE="${PROSPECTOR_LIVE:-/Users/chidionyema/Documents/code/prospector-live}"
STORE="${PROSPECTOR_STORE_DIR:-$REPO/store}"
PY="${PROSPECTOR_PYTHON:-$REPO/.venv/bin/python}"
AGENTS="$HOME/Library/LaunchAgents"

# Discovered, never hardcoded: a hardcoded list silently misses a job someone added.
_labels() { launchctl list 2>/dev/null | awk '$3 ~ /^com\.prospector\./ {print $3}'; }

t_name() { echo "laptop"; }

t_preflight() {
  [ -x "$PY" ] || { echo "no interpreter at $PY" >&2; return 1; }
  [ -d "$STORE" ] || { echo "no store at $STORE" >&2; return 1; }
}

t_provision() { :; }
t_secrets()   { :; }   # .env on this box IS the source of truth; nothing to push
t_release()   { :; }   # the code is already here

t_start() {
  local n=0
  for l in $(_labels); do :; done
  for f in "$AGENTS"/com.prospector.*.plist; do
    [ -e "$f" ] || continue
    launchctl bootstrap "gui/$(id -u)" "$f" 2>/dev/null || launchctl enable "gui/$(id -u)/$(basename "$f" .plist)" 2>/dev/null || true
    n=$((n+1))
  done
  echo "laptop: bootstrapped $n launchd jobs"
}

t_stop() {
  local n=0
  for l in $(_labels); do
    launchctl bootout "gui/$(id -u)/$l" 2>/dev/null || true
    n=$((n+1))
  done
  echo "laptop: stopped $n launchd jobs"
  # A launchd bootout does not kill a tick already in flight. Wait for the writers to finish
  # rather than tarring a half-written dossier.
  for _ in $(seq 1 60); do
    pgrep -f 'prospector.scheduler.run_scheduled|prospector\.run' >/dev/null || break
    sleep 5
  done
  pgrep -f 'prospector.scheduler.run_scheduled|prospector\.run' >/dev/null \
    && { echo "laptop: writers STILL live after 5 minutes; refusing" >&2; return 1; }
  echo "laptop: no writers live"
}

t_exec() { ( cd "$REPO" && /bin/sh -lc "$*" ); }

t_put() { cp "$1" "$2"; }

t_pack() { "$PY" "$REPO/scripts/store_migrate.py" pack "$1" --store "$STORE"; }

t_logs() { tail -f "$REPO"/store/logs/*.log 2>/dev/null || true; }
