#!/usr/bin/env bash
# WS0.1 — boot Store.Api on TEST keys + a throwaway sqlite db, drive the full money path,
# tear down. Repeatable: same script re-runs the proof for the WS0.2 live cutover (point
# STRIPE_TEST_SECRET_KEY at a live key + register the live webhook secret).
#
# Requires in the environment: STRIPE_TEST_SECRET_KEY, R2_ACCOUNT_ID, R2_ACCESS_KEY_ID,
# R2_SECRET_ACCESS_KEY, R2_BUCKET. The webhook secret is local to this proof (events are
# self-signed with it); override with STRIPE_WEBHOOK_SECRET to use a `stripe listen` secret.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$(cd "$SCRIPT_DIR/../src" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
API_DIR="$SRC_DIR/Store.Api"

: "${STRIPE_TEST_SECRET_KEY:?set STRIPE_TEST_SECRET_KEY (Stripe TEST secret)}"
: "${R2_ACCOUNT_ID:?set R2_ACCOUNT_ID}"
: "${R2_BUCKET:?set R2_BUCKET}"
export STRIPE_WEBHOOK_SECRET="${STRIPE_WEBHOOK_SECRET:-whsec_localproof}"

TMP_DIR="$(mktemp -d)"
DB_PATH="$TMP_DIR/proof.db"
PY="${PYTHON:-$REPO_ROOT/.venv/bin/python}"
[ -x "$PY" ] || PY="python3"

cleanup() {
  [ -n "${API_PID:-}" ] && kill "$API_PID" 2>/dev/null || true
  # belt-and-braces: kill whatever is still bound to 5291 from this run
  lsof -ti tcp:5291 2>/dev/null | xargs -r kill 2>/dev/null || true
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

echo "==> Building Store.Api (Release)"
dotnet build "$API_DIR/Store.Api.csproj" -c Release -v quiet >/dev/null
DLL="$API_DIR/bin/Release/net9.0/Store.Api.dll"
[ -f "$DLL" ] || { echo "DLL not found: $DLL"; exit 1; }

# Run the built DLL directly, NOT `dotnet run`: the run host applies launchSettings.json and
# does not propagate these inline env overrides to the app, so ConnectionStrings/Stripe
# secret would silently fall back to ambient config (proof would hit the wrong db + secret).
echo "==> Booting Store.Api on :5291 (fresh db: $DB_PATH)"
(
  cd "$API_DIR"
  ASPNETCORE_ENVIRONMENT=Development \
  ASPNETCORE_URLS="http://localhost:5291" \
  ConnectionStrings__DefaultConnection="Data Source=$DB_PATH" \
  Stripe__ApiKey="$STRIPE_TEST_SECRET_KEY" \
  Stripe__WebhookSecret="$STRIPE_WEBHOOK_SECRET" \
  payments__active_provider="stripe" \
  Delivery__MaxDownloadsPerEntitlement="${DELIVERY_MAX_DOWNLOADS:-2}" \
  dotnet "$DLL" >"$TMP_DIR/api.log" 2>&1
) &
API_PID=$!

echo "==> Waiting for API health"
for i in $(seq 1 60); do
  if curl -fsS "http://localhost:5291/catalog" >/dev/null 2>&1; then
    echo "    up after ${i}s"; break
  fi
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo "API died during boot. Log:"; tail -40 "$TMP_DIR/api.log"; exit 1
  fi
  sleep 1
done

echo "==> Driving money-path gates"
set +e
STORE_DB_PATH="$DB_PATH" \
DELIVERY_MAX_DOWNLOADS="${DELIVERY_MAX_DOWNLOADS:-2}" \
PROOF_FILE="$REPO_ROOT/store/launch/test-card-proof.md" \
"$PY" "$SCRIPT_DIR/prove_money_path.py"
RC=$?
set -e

if [ "$RC" -ne 0 ]; then
  echo "==> Gates failed. Last API log lines:"; tail -30 "$TMP_DIR/api.log"
fi
exit "$RC"
