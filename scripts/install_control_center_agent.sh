#!/usr/bin/env bash
# (Re)install the Control Center launchd agent, bound to the CURRENT tailnet address (R24).
#
# WHY THIS EXISTS AS A SCRIPT AND NOT AS A SMARTER LAUNCHER. The obvious design — point the
# plist at scripts/run_control_center.sh and let the shell resolve the address at launch — does
# not work on this Mac, and fails in a way that reads as a broken script rather than a policy
# decision: launchd execs /bin/bash, bash has no TCC grant for ~/Documents, and the agent dies
# with `Operation not permitted` before a single line of the script runs. The grant follows the
# EXECUTABLE, and the one that already has it is the venv's Python (via the streamlit shebang) —
# so the plist must keep exec'ing streamlit directly, and the address has to be resolved HERE,
# at install time, by a process that can read the repo.
#
# The address is therefore pinned in the plist, which is exactly the drift this script exists to
# repair: re-run it after the tailnet address changes. It is never hand-typed. This machine is
# registered on the tailnet twice — `chidis-macbook-pro-1` (the live node) and a stale
# `chidis-macbook-pro` — so typing "the" tailnet IP has a real chance of pinning a node that
# does not answer, and `tailscale ip -4` keeps serving the last-known address even while the
# backend is Stopped. Only BackendState == Running is trusted.
#
# Read-only by default. Pass --apply to write the plist and reload the agent.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST="${HOME}/Library/LaunchAgents/com.prospector.control-center.plist"
LABEL="com.prospector.control-center"
PORT="${CONTROL_CENTER_PORT:-8601}"
APPLY=0
[[ "${1:-}" == "--apply" ]] && APPLY=1

ADDRESS="${CONTROL_CENTER_ADDRESS:-}"
if [[ -z "${ADDRESS}" ]]; then
  ts_state="$(tailscale status --json 2>/dev/null \
    | /usr/bin/python3 -c 'import sys,json;print(json.load(sys.stdin).get("BackendState",""))' \
    2>/dev/null || true)"
  if [[ "${ts_state}" == "Running" ]]; then
    ADDRESS="$(tailscale ip -4 2>/dev/null | grep -E '^100\.' | head -1 || true)"
  else
    echo "Tailscale BackendState is '${ts_state:-unknown}', not Running. Run 'tailscale up' first," >&2
    echo "or the console will be reinstalled on loopback and the phone will not reach it." >&2
  fi
fi
[[ -z "${ADDRESS}" ]] && ADDRESS="127.0.0.1"

echo "label:   ${LABEL}"
echo "address: ${ADDRESS}:${PORT}"
[[ -f "${PLIST}" ]] || { echo "ERROR: ${PLIST} not found — nothing to reinstall." >&2; exit 1; }
if [[ ${APPLY} -eq 0 ]]; then
  echo "(dry run — pass --apply to write and reload)"
  exit 0
fi

cp "${PLIST}" "${PLIST}.bak"
ROOT="${ROOT}" ADDRESS="${ADDRESS}" PORT="${PORT}" /usr/bin/python3 - "${PLIST}" <<'PY'
import os, plistlib, sys
path = sys.argv[1]
with open(path, "rb") as fh:
    d = plistlib.load(fh)
root, addr, port = os.environ["ROOT"], os.environ["ADDRESS"], os.environ["PORT"]
# streamlit, not bash: the TCC grant for ~/Documents follows this executable (see header).
d["ProgramArguments"] = [
    f"{root}/.venv/bin/streamlit", "run", f"{root}/prospector/control_center/app.py",
    "--server.port", port, "--server.address", addr,
    "--server.fileWatcherType", "none",
]
d.setdefault("WorkingDirectory", root)
d["KeepAlive"] = True
d["RunAtLoad"] = True
env = d.setdefault("EnvironmentVariables", {})
if not env.get("CONTROL_CENTER_PASSWORD"):
    # The portal fails closed without it; installing a plist that cannot render is worse than
    # refusing, because KeepAlive would restart the failure every few seconds forever.
    raise SystemExit("REFUSED: the existing plist carries no CONTROL_CENTER_PASSWORD.")
with open(path, "wb") as fh:
    plistlib.dump(d, fh)
print("plist written")
PY

launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
sleep 1
launchctl bootstrap "gui/$(id -u)" "${PLIST}"
sleep 6

# Verify by REACHING it. `launchctl list` reports a happy PID for a process that is failing to
# bind (memory: macos-ps-and-launchctl-probes-report-false-pass), so the probe is the socket.
if ! lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null | grep -q "${ADDRESS}:${PORT}"; then
  echo "FAILED: nothing is listening on ${ADDRESS}:${PORT}." >&2
  tail -20 /tmp/prospector_control_center.log >&2 2>/dev/null || true
  exit 1
fi
code="$(curl -s -o /dev/null -m 10 -w '%{http_code}' "http://${ADDRESS}:${PORT}/" || true)"
echo "listening on ${ADDRESS}:${PORT}, HTTP ${code}"
[[ "${code}" == "200" ]] || { echo "FAILED: bound but not serving." >&2; exit 1; }
