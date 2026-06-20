#!/usr/bin/env bash
# Launch the FULL storefront in Stripe TEST mode for end-to-end manual testing:
#   - `stripe listen` forwarding live test webhooks to the local API (real webhook leg)
#   - Store.Api on :5291 (test key, real store.db catalogue)
#   - Store.Web (Next.js) on :3000
# Buy a pack with test card 4242 4242 4242 4242, any future expiry/CVC. Refund in the
# Stripe TEST dashboard. Ctrl-C the API/web yourself, or run scripts/stop_test_stack.sh.
#
# Requires in env: STRIPE_TEST_SECRET_KEY, R2_ACCOUNT_ID, R2_ACCESS_KEY_ID,
# R2_SECRET_ACCESS_KEY, R2_BUCKET. Needs the Stripe CLI installed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
API_DIR="$PLATFORM_DIR/src/Store.Api"
WEB_DIR="$PLATFORM_DIR/src/Store.Web"
RUN_DIR="$PLATFORM_DIR/.test-stack"
mkdir -p "$RUN_DIR"

: "${STRIPE_TEST_SECRET_KEY:?set STRIPE_TEST_SECRET_KEY (Stripe TEST secret sk_test_...)}"
: "${R2_ACCOUNT_ID:?set R2_ACCOUNT_ID}"; : "${R2_BUCKET:?set R2_BUCKET}"
command -v stripe >/dev/null || { echo "FATAL: stripe CLI not installed"; exit 1; }

echo "==> Building Store.Api (Release)"
dotnet build "$API_DIR/Store.Api.csproj" -c Release -v quiet >/dev/null
DLL="$API_DIR/bin/Release/net9.0/Store.Api.dll"

echo "==> Starting stripe listen -> :5291/webhooks/stripe"
nohup stripe listen --api-key "$STRIPE_TEST_SECRET_KEY" \
  --forward-to "localhost:5291/webhooks/stripe" \
  >"$RUN_DIR/stripe.log" 2>&1 &
echo $! > "$RUN_DIR/stripe.pid"

# pull the session signing secret the CLI just minted (the API must verify with this exact one)
WHSEC=""
for i in $(seq 1 20); do
  WHSEC="$(grep -oE 'whsec_[A-Za-z0-9]+' "$RUN_DIR/stripe.log" | head -1 || true)"
  [ -n "$WHSEC" ] && break
  sleep 0.5
done
[ -n "$WHSEC" ] || { echo "FATAL: stripe listen did not report a webhook secret. Log:"; cat "$RUN_DIR/stripe.log"; exit 1; }
echo "    webhook secret captured (${WHSEC:0:11}…)"

echo "==> Starting Store.Api on :5291 (real store.db catalogue, test Stripe key)"
( cd "$API_DIR"
  ASPNETCORE_ENVIRONMENT=Development \
  ASPNETCORE_URLS="http://localhost:5291" \
  Stripe__ApiKey="$STRIPE_TEST_SECRET_KEY" \
  Stripe__WebhookSecret="$WHSEC" \
  payments__active_provider="stripe" \
  Stripe__AutomaticTax="false" \
  nohup dotnet "$DLL" >"$RUN_DIR/api.log" 2>&1 & echo $! > "$RUN_DIR/api.pid" )

echo "==> Waiting for API health"
for i in $(seq 1 60); do
  curl -fsS "http://localhost:5291/catalog" >/dev/null 2>&1 && { echo "    API up"; break; }
  sleep 1
done

echo "==> Starting Store.Web (Next.js) on :3000"
( cd "$WEB_DIR"; nohup npm run dev >"$RUN_DIR/web.log" 2>&1 & echo $! > "$RUN_DIR/web.pid" )
for i in $(seq 1 60); do
  curl -fsS "http://localhost:3000" >/dev/null 2>&1 && { echo "    Web up"; break; }
  sleep 1
done

cat <<EOF

================  TEST STACK UP  ================
  Storefront : http://localhost:3000
  API        : http://localhost:5291/catalog
  Webhooks   : stripe listen -> :5291/webhooks/stripe (test mode)
  Test card  : 4242 4242 4242 4242, any future date, any CVC, any postcode
  Logs       : $RUN_DIR/{web,api,stripe}.log
  Stop       : bash $SCRIPT_DIR/stop_test_stack.sh
=================================================
EOF
