#!/usr/bin/env bash
# Launch the Prospector Control Center, bound to loopback and behind the operator gate.
#
# The portal has no other access control, so it is NEVER bound to 0.0.0.0. For remote use,
# tunnel the loopback port over SSH:
#     ssh -L 8601:localhost:8601 <host>
# then open http://localhost:8601 locally. See DEPLOYMENT.md.
set -euo pipefail

PORT="${CONTROL_CENTER_PORT:-8601}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -z "${CONTROL_CENTER_PASSWORD:-}" ]]; then
  echo "ERROR: CONTROL_CENTER_PASSWORD is not set. The portal fails closed and will not render." >&2
  echo "       export CONTROL_CENTER_PASSWORD='<a secret>' and re-run." >&2
  exit 1
fi

exec streamlit run "${ROOT}/prospector/control_center/app.py" \
  --server.port "${PORT}" \
  --server.address 127.0.0.1
