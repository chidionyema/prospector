#!/usr/bin/env bash
# Prove the buy-button leg: boot Store.Api on a COPY of the real catalogue db with a real
# Stripe key, then create a real Checkout Session for every listed pack (prove_checkout.py).
# Catches stale/invalid ProviderPriceId and checkout config errors that the synthetic-webhook
# money-path proof cannot. Read-only intent: runs against a copy so the real store.db is never
# touched. Repeatable for the live cutover (point STRIPE_TEST_SECRET_KEY at a live key).
#
# Requires in env: STRIPE_TEST_SECRET_KEY (a real Stripe secret), R2_ACCOUNT_ID, R2_BUCKET.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="$(cd "$SCRIPT_DIR/../src/Store.Api" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PORT="${CHECKOUT_PROOF_PORT:-5293}"

: "${STRIPE_TEST_SECRET_KEY:?set STRIPE_TEST_SECRET_KEY (a real Stripe secret key)}"
: "${R2_ACCOUNT_ID:?set R2_ACCOUNT_ID}"; : "${R2_BUCKET:?set R2_BUCKET}"

REAL_DB="${STORE_DB:-$API_DIR/store.db}"
[ -f "$REAL_DB" ] || { echo "FATAL: catalogue db not found at $REAL_DB"; exit 1; }
PY="${PYTHON:-$REPO_ROOT/.venv/bin/python}"; [ -x "$PY" ] || PY="python3"

TMP_DIR="$(mktemp -d)"
DB_COPY="$TMP_DIR/catalog.db"
cp "$REAL_DB" "$DB_COPY"

cleanup() {
  [ -n "${API_PID:-}" ] && kill "$API_PID" 2>/dev/null || true
  lsof -ti "tcp:$PORT" 2>/dev/null | xargs -r kill 2>/dev/null || true
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

echo "==> Building Store.Api (Release)"
dotnet build "$API_DIR/Store.Api.csproj" -c Release -v quiet >/dev/null
DLL="$API_DIR/bin/Release/net9.0/Store.Api.dll"

echo "==> Booting Store.Api on :$PORT (copy of real catalogue: $(basename "$REAL_DB"))"
(
  cd "$API_DIR"
  ASPNETCORE_ENVIRONMENT=Development \
  ASPNETCORE_URLS="http://localhost:$PORT" \
  ConnectionStrings__DefaultConnection="Data Source=$DB_COPY" \
  Stripe__ApiKey="$STRIPE_TEST_SECRET_KEY" \
  Stripe__WebhookSecret="${STRIPE_WEBHOOK_SECRET:-whsec_checkoutproof}" \
  payments__active_provider="stripe" \
  Stripe__AutomaticTax="${STRIPE_AUTOMATIC_TAX:-false}" \
  dotnet "$DLL" >"$TMP_DIR/api.log" 2>&1
) &
API_PID=$!

echo "==> Waiting for API health"
for i in $(seq 1 60); do
  curl -fsS "http://localhost:$PORT/catalog" >/dev/null 2>&1 && { echo "    up after ${i}s"; break; }
  kill -0 "$API_PID" 2>/dev/null || { echo "API died during boot:"; tail -40 "$TMP_DIR/api.log"; exit 1; }
  sleep 1
done

echo "==> Proving checkout for every listed pack"
set +e
API_BASE="http://localhost:$PORT" \
PROOF_FILE="$REPO_ROOT/store/launch/checkout-proof.md" \
"$PY" "$SCRIPT_DIR/prove_checkout.py"
RC=$?
set -e
[ "$RC" -ne 0 ] && { echo "==> Checkout proof failed. Last API log:"; tail -30 "$TMP_DIR/api.log"; }
exit "$RC"
