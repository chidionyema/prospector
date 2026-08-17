#!/usr/bin/env bash
# Launch the Prospector Control Center behind the operator gate, on the tailnet when there is
# one and on loopback when there is not (R24).
#
# It is NEVER bound to 0.0.0.0: the password gate is the only access control, and 0.0.0.0 puts
# it on whatever café wifi the laptop is joined to. The tailnet is the remote surface — the
# phone reaches it because it is a node on the same private network, not because a port is open.
# Without Tailscale running this falls back to loopback and remote use is an SSH tunnel:
#     ssh -L 8601:localhost:8601 <host>
#
# The address is RESOLVED AT LAUNCH and never pinned. This machine is registered on the tailnet
# TWICE — `chidis-macbook-pro-1` (100.93.240.113, the live node) and a stale `chidis-macbook-pro`
# (100.112.51.80) — so a hardcoded IP is a coin flip between "binds fine" and "Can't assign
# requested address" at start, or worse, a bind the phone cannot reach.
set -euo pipefail

PORT="${CONTROL_CENTER_PORT:-8601}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

ADDRESS="${CONTROL_CENTER_ADDRESS:-}"
if [[ -z "${ADDRESS}" ]]; then
  # Only Running counts. `tailscale ip -4` keeps answering the last-known address while the
  # backend is Stopped, so the IP alone would have us bind an address the interface has torn
  # down. Ask the state, not the cache.
  ts_state="$(tailscale status --json 2>/dev/null \
    | /usr/bin/python3 -c 'import sys,json;print(json.load(sys.stdin).get("BackendState",""))' \
    2>/dev/null || true)"
  if [[ "${ts_state}" == "Running" ]]; then
    ADDRESS="$(tailscale ip -4 2>/dev/null | grep -E '^100\.' | head -1 || true)"
  fi
fi
if [[ -z "${ADDRESS}" ]]; then
  ADDRESS="127.0.0.1"
  echo "NOTE: Tailscale is not Running — binding loopback only. The phone will not reach this." >&2
fi

if [[ -z "${CONTROL_CENTER_PASSWORD:-}" ]]; then
  echo "ERROR: CONTROL_CENTER_PASSWORD is not set. The portal fails closed and will not render." >&2
  echo "       export CONTROL_CENTER_PASSWORD='<a secret>' and re-run." >&2
  exit 1
fi

echo "Control Center on http://${ADDRESS}:${PORT}" >&2

exec streamlit run "${ROOT}/prospector/control_center/app.py" \
  --server.port "${PORT}" \
  --server.address "${ADDRESS}" \
  --server.fileWatcherType none
