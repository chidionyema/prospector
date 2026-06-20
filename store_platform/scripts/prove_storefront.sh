#!/usr/bin/env bash
# Prove the NON-PAYMENT storefront API: boot Store.Api on a copy of the real catalogue db and
# assert catalogue listing, stats, pack detail, 404s, admin auth gates, and CORS
# (prove_storefront.py). No Stripe/R2 needed. Read-only: runs against a copy.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="$(cd "$SCRIPT_DIR/../src/Store.Api" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PORT="${STOREFRONT_PROOF_PORT:-5294}"
ORIGIN="${ALLOWED_ORIGIN:-http://localhost:3000}"

REAL_DB="${STORE_DB:-$API_DIR/store.db}"
[ -f "$REAL_DB" ] || { echo "FATAL: catalogue db not found at $REAL_DB"; exit 1; }
PY="${PYTHON:-$REPO_ROOT/.venv/bin/python}"; [ -x "$PY" ] || PY="python3"

TMP_DIR="$(mktemp -d)"
DB_COPY="$TMP_DIR/catalog.db"
cp "$REAL_DB" "$DB_COPY"

cleanup() {
  [ -n "${API_PID:-}" ] && kill "$API_PID" 2>/dev/null || true
  lsof -ti "tcp:$PORT" 2>/dev/null | xargs -r kill -9 2>/dev/null || true
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

echo "==> Building Store.Api (Release)"
dotnet build "$API_DIR/Store.Api.csproj" -c Release -v quiet >/dev/null
DLL="$API_DIR/bin/Release/net9.0/Store.Api.dll"

echo "==> Booting Store.Api on :$PORT (copy of real catalogue)"
(
  cd "$API_DIR"
  ASPNETCORE_ENVIRONMENT=Development \
  ASPNETCORE_URLS="http://localhost:$PORT" \
  ConnectionStrings__DefaultConnection="Data Source=$DB_COPY" \
  Store__AllowedOrigin="$ORIGIN" \
  exec dotnet "$DLL" >"$TMP_DIR/api.log" 2>&1
) &
API_PID=$!

echo "==> Waiting for API health"
for i in $(seq 1 60); do
  curl -fsS "http://localhost:$PORT/catalog" >/dev/null 2>&1 && { echo "    up after ${i}s"; break; }
  kill -0 "$API_PID" 2>/dev/null || { echo "API died during boot:"; tail -40 "$TMP_DIR/api.log"; exit 1; }
  sleep 1
done

echo "==> Proving non-payment storefront API"
set +e
API_BASE="http://localhost:$PORT" \
ALLOWED_ORIGIN="$ORIGIN" \
PROOF_FILE="$REPO_ROOT/store/launch/storefront-proof.md" \
"$PY" "$SCRIPT_DIR/prove_storefront.py"
RC=$?
set -e
[ "$RC" -ne 0 ] && { echo "==> Storefront proof failed. Last API log:"; tail -30 "$TMP_DIR/api.log"; }
exit "$RC"
