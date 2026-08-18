#!/usr/bin/env bash
# Install the two laptop-side watch jobs that make automatic failover real.
#
#   com.prospector-control.failover-watch   every 60s   engine_failover.py check
#   com.prospector-control.standby-sync     every 900s  engine_failover.py sync
#
# Three deliberate choices, each of which is a defect we have already had:
#
#  1. The label prefix is `com.prospector-control.`, NOT `com.prospector.`. `laptop.sh` t_stop and
#     decommission.sh both match `com.prospector.` and disable everything they find. If the
#     watchdog carried that prefix, stopping the laptop would disable the very job whose purpose
#     is to bring the laptop back.
#
#  2. The plist runs a LAUNCHER, not a path into a checkout. A disaster-recovery tool that lives
#     inside a git worktree dies when someone deletes the worktree, and it dies silently, once a
#     minute, at exactly the moment it is needed. The launcher prefers the main checkout, falls
#     back to whatever worktree still has the script, and falls back again to a frozen copy under
#     ~/.prospector/bin. It prints which one it used on every run.
#
#  3. PATH names /usr/local/bin explicitly. launchd does not inherit a login shell's PATH, and
#     `fly` lives in /usr/local/bin. Without this the check cannot reach Fly's API, and rule 3 of
#     failover turns every poll into "unreachable" - which alerts and does nothing, so the failure
#     is quiet.
set -euo pipefail

BIN="$HOME/.prospector/bin"
AGENTS="$HOME/Library/LaunchAgents"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
mkdir -p "$BIN" "$AGENTS" "$HOME/.prospector/logs"

# The frozen fallback copy. Refreshed on every install, so it is never older than the last time
# anyone deployed this.
if grep -qE "^(import|from) " "$REPO/scripts/engine_failover.py" \
   && grep -E "^(import|from) " "$REPO/scripts/engine_failover.py" \
      | grep -qvE "^(import|from) (__future__|argparse|json|os|shutil|subprocess|sys|time|datetime|pathlib)"; then
    echo "engine_failover.py imports something outside the standard library." >&2
    echo "The watch job runs it under /usr/bin/python3, which has no site-packages." >&2
    exit 1
fi
cp "$REPO/scripts/engine_failover.py" "$BIN/engine_failover.frozen.py"
chmod +x "$BIN/engine_failover.frozen.py"

cat > "$BIN/failover" <<'LAUNCHER'
#!/usr/bin/env bash
# Run the frozen copy of engine_failover.py under the system python.
#
# It deliberately does NOT look inside ~/Documents for a newer copy. macOS protects that
# directory, and a launchd agent that globs into it does not fail - it BLOCKS, forever, waiting
# for a consent dialog nobody will ever see. Measured 2026-08-18: the first version of this
# launcher sat in bash's glob_filename for as long as it was left, wrote nothing to its log, and
# reported `state = running` the whole time. A watchdog that hangs is worse than no watchdog,
# because launchctl list shows it alive.
#
# The frozen copy is refreshed by install_failover_watch.sh, which runs from a terminal where
# ~/Documents is readable. That is the only place the repo and this copy ever meet.
#
# engine_failover.py imports nothing but the standard library, checked at install time, so the
# system python is enough and no virtualenv under ~/Documents is needed.
set -uo pipefail
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

SRC="$HOME/.prospector/bin/engine_failover.frozen.py"
if [ ! -f "$SRC" ]; then
    echo "failover: $SRC is missing - the watchdog is BLIND; re-run deploy/install_failover_watch.sh" >&2
    exit 2
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
exec /usr/bin/python3 "$SRC" "$@"
LAUNCHER
chmod +x "$BIN/failover"

plist() {   # plist <label> <interval_seconds> <arg>
    cat > "$AGENTS/$1.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$1</string>
  <key>ProgramArguments</key>
  <array><string>$BIN/failover</string><string>$3</string></array>
  <key>StartInterval</key><integer>$2</integer>
  <key>RunAtLoad</key><true/>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>StandardOutPath</key><string>$HOME/.prospector/logs/$1.log</string>
  <key>StandardErrorPath</key><string>$HOME/.prospector/logs/$1.log</string>
</dict>
</plist>
EOF
}

plist com.prospector-control.failover-watch 60  check
plist com.prospector-control.standby-sync   900 sync
# Hermes decides what is broken from its receipt ledger. The engine's jobs run on Fly now, so
# something has to carry their real exit codes back to this laptop or three capabilities grade
# DARK while the jobs work. Same cadence as the sync; both are cheap SSH reads.
plist com.prospector-control.receipt-bridge 900 receipts

for L in com.prospector-control.failover-watch com.prospector-control.standby-sync \
         com.prospector-control.receipt-bridge; do
    launchctl bootout "gui/$(id -u)/$L" 2>/dev/null || true
    # enable BEFORE bootstrap: bootstrap silently refuses a disabled label, so the other order
    # reads as success while starting nothing.
    launchctl enable "gui/$(id -u)/$L" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$AGENTS/$L.plist"
    echo "installed $L"
done

echo "--- launchctl list ---"
launchctl list | grep prospector-control || echo "NOTHING LOADED - the watchdog is not running"
