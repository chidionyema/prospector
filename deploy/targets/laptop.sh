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

# The TOOLS come from the checkout this adapter is in; only the STORE and the interpreter come
# from the main checkout. Those are two different questions and conflating them broke the
# 02:30 cutover: `$REPO/scripts/store_migrate.py` does not exist, because store_migrate.py is
# new on this branch and $REPO is main. The store must be the canonical one; the script must be
# the one being tested. Same distinction the estate already makes for the live checkout, where
# PROSPECTOR_STORE_DIR pins the store while the code moves.
TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Discovered, never hardcoded: a hardcoded list silently misses a job someone added.
_labels() { launchctl list 2>/dev/null | awk '$3 ~ /^com\.prospector\./ {print $3}'; }

t_name() { echo "laptop"; }

t_preflight() {
  [ -x "$PY" ] || { echo "no interpreter at $PY" >&2; return 1; }
  [ -d "$STORE" ] || { echo "no store at $STORE" >&2; return 1; }
  # Checked HERE, in phase 1, because t_pack runs in phase 5 - after the engine has been
  # stopped and the downtime window is open. A missing tool must fail before the window opens,
  # not inside it. It cost six seconds of downtime at 02:30 on 2026-08-18; it could as easily
  # have been a failure with no clean rollback.
  [ -f "$TOOLS/scripts/store_migrate.py" ] \
    || { echo "no store_migrate.py under $TOOLS - the adapter is running from a checkout that does not have it" >&2; return 1; }
}

t_provision() { :; }
t_secrets()   { :; }   # .env on this box IS the source of truth; nothing to push
t_release()   { :; }   # the code is already here

t_start() {
  local n=0
  # Paired with the assertion in t_stop. Starting the laptop means the laptop is the platform
  # again, so its roll-forward follower belongs back on.
  rm -f "$STORE/scheduler/NO_AUTO_UPDATE"
  for l in $(_labels); do :; done
  for f in "$AGENTS"/com.prospector.*.plist; do
    [ -e "$f" ] || continue
    launchctl bootstrap "gui/$(id -u)" "$f" 2>/dev/null || launchctl enable "gui/$(id -u)/$(basename "$f" .plist)" 2>/dev/null || true
    n=$((n+1))
  done
  echo "laptop: bootstrapped $n launchd jobs"
}

WRITERS='prospector.scheduler.run_scheduled|prospector\.run|prospector\.ops\.'

t_stop() {
  # Three rounds, and the repetition is the point. On cutover attempt 5 the first round reported
  # "no writers live" at 02:44:09, and then a fresh generation run started at 02:46:59 - three
  # minutes into the pack - and appended 17 lines to prospector.jsonl. Whatever brought it back
  # (a watchdog tick, a launchd job outside the loop, a child re-exec), a single stop-and-check
  # cannot see it: the check passes before the thing returns. So: stop, kill, let it settle,
  # look again, and only call the store quiet when a round finds nothing to do.
  # The proper answer to com.prospector.live-update, which runs every 60 seconds and, when it
  # sees a new origin/main, fast-forwards the live checkout and RESTARTS the daemon - putting
  # back the very jobs this function just stopped. `launchctl bootout` cannot prevent that on
  # its own, because the job only has to fire once in the gap. The estate already has the right
  # switch for it: scripts/live_checkout.py:298 refuses --update while
  # store/scheduler/NO_AUTO_UPDATE exists, the same convention as the scheduler's PAUSE file.
  # So the fence is asserted here, before anything is stopped, and lifted in t_start - which
  # means a rollback restores the auto-update and a successful migration leaves it off, which
  # is the correct end state for a laptop that is being decommissioned.
  mkdir -p "$STORE/scheduler" && : > "$STORE/scheduler/NO_AUTO_UPDATE"
  echo "laptop: NO_AUTO_UPDATE asserted (live-update cannot restart the daemon)"

  local round n l
  for round in 1 2 3; do
    n=0
    for l in $(_labels); do
      launchctl bootout "gui/$(id -u)/$l" 2>/dev/null || true
      n=$((n+1))
    done
    [ "$round" = 1 ] && echo "laptop: stopped $n launchd jobs"

    # A bootout does not kill a tick already in flight, and a generation call can sit on a model
    # for four minutes. Ask politely, then insist.
    pkill -f "$WRITERS" 2>/dev/null || true
    for _ in $(seq 1 24); do
      pgrep -f "$WRITERS" >/dev/null || break
      sleep 5
    done
    pkill -9 -f "$WRITERS" 2>/dev/null || true

    sleep 10   # the settle window: long enough for anything that restarts things to do it
    if ! pgrep -f "$WRITERS" >/dev/null && [ "$n" = 0 ]; then
      echo "laptop: no writers live (quiet after round $round)"
      return 0
    fi
    echo "laptop: round $round left $n job(s) to re-stop; going again"
  done
  pgrep -f "$WRITERS" >/dev/null \
    && { echo "laptop: writers STILL live after three rounds; refusing" >&2; return 1; }
  echo "laptop: no writers live"
}

t_exec() { ( cd "$REPO" && /bin/sh -lc "$*" ); }

t_put() { cp "$1" "$2"; }

t_pack() { "$PY" "$TOOLS/scripts/store_migrate.py" pack "$1" --store "$STORE"; }

t_logs() { tail -f "$REPO"/store/logs/*.log 2>/dev/null || true; }

# See fly.sh. Healthy here means the scheduler is running and the ledger is on disk.
t_health() {
  pgrep -f 'prospector.scheduler.run_scheduled' >/dev/null \
    || { echo "laptop: scheduler is not running" >&2; return 1; }
  [ -f "$STORE/prospector.jsonl" ] || { echo "laptop: no ledger at $STORE/prospector.jsonl" >&2; return 1; }
  echo "laptop: scheduler running, ledger present"
}
