#!/usr/bin/env bash
# Prove the rendered storefront UI (non-payment) with a headless-Chromium Playwright smoke:
# home lists packs, pack detail renders with a buy button, order-success renders, unknown route
# 404s. Boots Store.Api (copy of the real catalogue) on :5291 and Store.Web (next dev) on :3000,
# runs e2e/storefront.spec.ts, tears down. The smoke stops at the buy button, so no card/Stripe
# key is needed (the money path is proven separately by prove_launch.sh).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="$(cd "$SCRIPT_DIR/../src/Store.Api" && pwd)"
WEB_DIR="$(cd "$SCRIPT_DIR/../src/Store.Web" && pwd)"
API_PORT="${WEB_PROOF_API_PORT:-5291}"
WEB_PORT="${WEB_PROOF_WEB_PORT:-3000}"

REAL_DB="${STORE_DB:-$API_DIR/store.db}"
[ -f "$REAL_DB" ] || { echo "FATAL: catalogue db not found at $REAL_DB"; exit 1; }

TMP_DIR="$(mktemp -d)"
DB_COPY="$TMP_DIR/catalog.db"
cp "$REAL_DB" "$DB_COPY"

cleanup() {
  [ -n "${WEB_PID:-}" ] && kill "$WEB_PID" 2>/dev/null || true
  [ -n "${API_PID:-}" ] && kill "$API_PID" 2>/dev/null || true
  # Port-based SIGKILL is the reliable backstop: `next start` spawns a child that outlives the
  # npm wrapper, and the listener is what actually holds the port. One lsof per port — a single
  # `lsof -ti tcp:A tcp:B` treats the second as a file path, silently skipping it.
  for p in "$API_PORT" "$WEB_PORT"; do
    lsof -ti "tcp:$p" 2>/dev/null | xargs -r kill -9 2>/dev/null || true
  done
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

# Free the ports up front and verify — otherwise a stale server would silently serve the smoke
# (the new boot would EADDRINUSE while Playwright tested the wrong process).
echo "==> Freeing ports :$API_PORT and :$WEB_PORT"
for p in "$API_PORT" "$WEB_PORT"; do
  lsof -ti "tcp:$p" 2>/dev/null | xargs -r kill -9 2>/dev/null || true
done
sleep 1
for p in "$API_PORT" "$WEB_PORT"; do
  lsof -ti "tcp:$p" >/dev/null 2>&1 && { echo "FATAL: port $p still occupied; stop the process and retry"; exit 1; }
done

echo "==> Building Store.Api (Release)"
dotnet build "$API_DIR/Store.Api.csproj" -c Release -v quiet >/dev/null
DLL="$API_DIR/bin/Release/net9.0/Store.Api.dll"

echo "==> Booting Store.Api on :$API_PORT (copy of real catalogue)"
(
  cd "$API_DIR"
  ASPNETCORE_ENVIRONMENT=Development \
  ASPNETCORE_URLS="http://localhost:$API_PORT" \
  ConnectionStrings__DefaultConnection="Data Source=$DB_COPY" \
  Store__AllowedOrigin="http://localhost:$WEB_PORT" \
  exec dotnet "$DLL" >"$TMP_DIR/api.log" 2>&1
) &
API_PID=$!
for i in $(seq 1 60); do
  curl -fsS "http://localhost:$API_PORT/catalog" >/dev/null 2>&1 && { echo "    API up"; break; }
  kill -0 "$API_PID" 2>/dev/null || { echo "API died:"; tail -30 "$TMP_DIR/api.log"; exit 1; }
  sleep 1
done

# Production build, not `next dev`: dev compiles routes on demand and the dynamic /pack/[id]
# page intermittently 404s on first hit (PageNotFoundError). `next build` pre-compiles every
# route, so the smoke exercises the bundle that actually ships. NEXT_PUBLIC_API_URL is baked
# from .env.local at build time and already points at :5291 (our API port).
echo "==> Building Store.Web (next build)"
( cd "$WEB_DIR"; npm run build >"$TMP_DIR/build.log" 2>&1 ) \
  || { echo "FATAL: next build failed"; tail -30 "$TMP_DIR/build.log"; exit 1; }

echo "==> Booting Store.Web (next start) on :$WEB_PORT"
( cd "$WEB_DIR"; PORT="$WEB_PORT" npm run start >"$TMP_DIR/web.log" 2>&1 ) &
WEB_PID=$!
for i in $(seq 1 90); do
  curl -fsS "http://localhost:$WEB_PORT" >/dev/null 2>&1 && { echo "    Web up after ${i}s"; break; }
  sleep 1
done

echo "==> Running Playwright UI smoke"
set +e
( cd "$WEB_DIR"; WEB_BASE_URL="http://localhost:$WEB_PORT" npx playwright test --reporter=list )
RC=$?
set -e
[ "$RC" -ne 0 ] && { echo "==> Web smoke failed. Last web log:"; tail -20 "$TMP_DIR/web.log"; }
exit "$RC"
