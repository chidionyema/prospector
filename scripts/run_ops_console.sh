#!/usr/bin/env bash
# Launch the Ops Console (Next.js) — the replacement for the Streamlit control centre.
#
# Binding, and why it is not a preference:
#   The console has one shared password and no other access control. It therefore binds ONE
#   address, never 0.0.0.0. The founder opens it from a phone over Tailscale, so the default is
#   this machine's tailnet address; set OPS_CONSOLE_HOST to override (127.0.0.1 for a desk-only
#   run). A password-only portal listening on whatever wifi the laptop joined is not acceptable.
#
# The interpreter comes from here, not from the app. `pythonBin()` in src/lib/ops.ts deliberately
# has no hardcoded path: Turbopack constant-folds a literal joined to process.cwd(), turns it into
# a build-time file dependency, and then panics on `.venv/bin/python` because that symlink leaves
# the project root in a worktree. Measured 2026-08-16: `next build` failed outright until the
# literal moved out of bundled code and into this script.
set -euo pipefail

PORT="${OPS_CONSOLE_PORT:-8611}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="${ROOT}/store_platform/src/Ops.Console"

if [[ -z "${CONTROL_CENTER_PASSWORD:-}" ]]; then
  echo "ERROR: CONTROL_CENTER_PASSWORD is not set." >&2
  echo "       The console fails closed: every route answers 503 and says why, including login." >&2
  echo "       export CONTROL_CENTER_PASSWORD='<a secret>' and re-run." >&2
  exit 1
fi

# Same variable as the Streamlit portal, so there is one password to remember.
export CONTROL_CENTER_PASSWORD

export PROSPECTOR_ROOT="${PROSPECTOR_ROOT:-$ROOT}"
export PROSPECTOR_PYTHON="${PROSPECTOR_PYTHON:-$ROOT/.venv/bin/python}"

if [[ ! -x "$PROSPECTOR_PYTHON" ]]; then
  echo "ERROR: no interpreter at $PROSPECTOR_PYTHON — the console cannot run the engine gateway." >&2
  echo "       Create the venv, or set PROSPECTOR_PYTHON." >&2
  exit 1
fi

# The tailnet address, if Tailscale is up. `tailscale ip -4` prints exactly one address.
HOST="${OPS_CONSOLE_HOST:-}"
if [[ -z "$HOST" ]]; then
  for ts in /usr/local/bin/tailscale /opt/homebrew/bin/tailscale "$(command -v tailscale || true)"; do
    if [[ -x "$ts" ]]; then
      HOST="$("$ts" ip -4 2>/dev/null | head -1 || true)"
      [[ -n "$HOST" ]] && break
    fi
  done
fi
if [[ -z "$HOST" ]]; then
  echo "ERROR: no tailnet address found and OPS_CONSOLE_HOST is not set." >&2
  echo "       Start Tailscale, or run desk-only with OPS_CONSOLE_HOST=127.0.0.1." >&2
  exit 1
fi

MODE="${1:-start}"   # start = production build; dev = hot reload

cd "$APP"

if [[ "$MODE" == "dev" ]]; then
  echo "Ops Console (dev) on http://${HOST}:${PORT}"
  exec npx next dev -H "$HOST" -p "$PORT"
fi

if [[ ! -d .next ]]; then
  echo "No build found. Building once (npm run build)…"
  npm run build            # exit status is this command's own; nothing is piped
fi

echo "Ops Console on http://${HOST}:${PORT}"
exec npx next start -H "$HOST" -p "$PORT"
