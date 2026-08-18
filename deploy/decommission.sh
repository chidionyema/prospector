#!/usr/bin/env bash
# Turn a platform off for good, after another one has taken over.
#
#   deploy/decommission.sh --side laptop --proven fly            # report only, changes nothing
#   deploy/decommission.sh --side laptop --proven fly --yes      # actually turn it off
#   deploy/decommission.sh --restore ~/Library/LaunchAgents/prospector-decommissioned-2026-08-18
#
# WHAT IT DOES NOT DO: delete state. The store, the ledger and the dossiers are left exactly
# where they are. "Decommissioned" here means "cannot start itself again", not "erased". The
# founder's instruction was that the laptop is preserved as a backup and turned off after a
# successful migration, and those are two different things.
#
# WHY IT REFUSES WITHOUT --proven: turning off the old engine while the new one is not actually
# running leaves nothing running at all, and the failure is silent - no alert fires, because
# the thing that would have alerted is the thing that was turned off.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIDE=""; PROVEN=""; GO=0; RESTORE=""
AGENTS="$HOME/Library/LaunchAgents"

while [ $# -gt 0 ]; do
  case "$1" in
    --side) SIDE="$2"; shift 2 ;;
    --proven) PROVEN="$2"; shift 2 ;;
    --restore) RESTORE="$2"; shift 2 ;;
    --yes) GO=1; shift ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

say() { printf '\n\033[1m[%s] %s\033[0m\n' "$(date +%H:%M:%S)" "$*"; }
call() { local side="$1"; shift; ( set -euo pipefail; . "$HERE/targets/$side.sh"; "$@" ); }

# ---------------------------------------------------------------- restore

if [ -n "$RESTORE" ]; then
  [ -d "$RESTORE" ] || { echo "no such directory: $RESTORE" >&2; exit 1; }
  say "restoring launchd jobs from $RESTORE"
  n=0
  for f in "$RESTORE"/com.prospector.*.plist; do
    [ -e "$f" ] || continue
    mv "$f" "$AGENTS/"
    launchctl bootstrap "gui/$(id -u)" "$AGENTS/$(basename "$f")" 2>/dev/null || true
    n=$((n+1))
  done
  echo "  restored and bootstrapped $n jobs"
  rmdir "$RESTORE" 2>/dev/null || true
  exit 0
fi

[ -n "$SIDE" ] || { echo "usage: decommission.sh --side <adapter> --proven <adapter> [--yes]" >&2; exit 2; }
[ -f "$HERE/targets/$SIDE.sh" ] || { echo "no adapter deploy/targets/$SIDE.sh" >&2; exit 2; }

# ---------------------------------------------------------------- the proof gate

if [ "$GO" = 1 ]; then
  [ -n "$PROVEN" ] || { echo "--yes needs --proven <adapter>: name the platform that took over" >&2; exit 2; }
  [ -f "$HERE/targets/$PROVEN.sh" ] || { echo "no adapter deploy/targets/$PROVEN.sh" >&2; exit 2; }
  say "proving $PROVEN is actually running before turning $SIDE off"
  if ! call "$PROVEN" t_health; then
    echo "  $PROVEN is NOT healthy — refusing to turn $SIDE off" >&2
    exit 1
  fi
fi

# ---------------------------------------------------------------- report, always

say "decommission plan for $(call "$SIDE" t_name)"

if [ "$SIDE" = "laptop" ]; then
  echo "  launchd jobs that would be stopped and unlinked:"
  launchctl list 2>/dev/null | awk '$3 ~ /^com\.prospector\./ {print "    " $3}' || true
  echo "  plists that would be moved out of $AGENTS:"
  ls "$AGENTS"/com.prospector.*.plist 2>/dev/null | sed 's/^/    /' || echo "    (none)"
  STORE="${PROSPECTOR_STORE_DIR:-/Users/chidionyema/Documents/code/prospector/store}"
  echo "  state that would be LEFT ALONE: $STORE ($(du -sh "$STORE" 2>/dev/null | cut -f1))"
else
  echo "  the adapter's t_stop would be called, and nothing else."
  echo "  Only the laptop keeps jobs that survive a reboot, so only the laptop needs unlinking."
fi

if [ "$GO" != 1 ]; then
  echo
  echo "  REPORT ONLY — nothing was changed. Add --yes to do it."
  exit 0
fi

# ---------------------------------------------------------------- do it

say "stopping $SIDE"
call "$SIDE" t_stop

if [ "$SIDE" = "laptop" ]; then
  DEST="$AGENTS/prospector-decommissioned-$(date +%Y-%m-%d)"
  mkdir -p "$DEST"
  n=0
  for f in "$AGENTS"/com.prospector.*.plist; do
    [ -e "$f" ] || continue
    # `disable` as well as moving the file: a bare move leaves launchd's own record of the
    # label behind, and a later `bootstrap` of a same-named job would come back enabled.
    launchctl disable "gui/$(id -u)/$(basename "$f" .plist)" 2>/dev/null || true
    mv "$f" "$DEST/"
    n=$((n+1))
  done
  say "DONE — $n plists moved to $DEST"
  echo "  The laptop can no longer start the engine, including after a reboot."
  echo "  Its state is untouched. Bring it back with:"
  echo "    deploy/decommission.sh --restore $DEST"
else
  say "DONE — $SIDE stopped"
fi
