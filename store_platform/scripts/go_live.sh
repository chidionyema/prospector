#!/usr/bin/env bash
# WS0.2 — one-command Stripe LIVE cutover.
#
# The founder's only manual jobs are: (1) paste live keys into store_platform/.env.production,
# (2) register the live webhook endpoint in the Stripe dashboard, (3) make one real low-value
# purchase + refund on the deployed checkout. Everything else is automated here:
#   - validates every required secret is present, non-placeholder, and correctly shaped
#   - reprovisions the catalogue packs onto LIVE Stripe prices (reprovision_stripe.py)
#   - boots Store.Api in Production to PROVE MoneyRailConfigGate accepts the live config
#     (the gate is fail-closed: a bad secret means the API refuses to start)
#
# Usage:
#   bash store_platform/scripts/go_live.sh                 # full cutover
#   bash store_platform/scripts/go_live.sh --dry-run       # validate + show reprovision plan, change nothing
#   bash store_platform/scripts/go_live.sh --skip-reprovision   # only re-run the boot gate check
#   ENV_FILE=/path/to/env bash store_platform/scripts/go_live.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$PLATFORM_DIR/.." && pwd)"
API_DIR="$PLATFORM_DIR/src/Store.Api"
ENV_FILE="${ENV_FILE:-$PLATFORM_DIR/.env.production}"

DRY_RUN=0; SKIP_REPROVISION=0; SKIP_BOOTCHECK=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --skip-reprovision) SKIP_REPROVISION=1 ;;
    --skip-bootcheck) SKIP_BOOTCHECK=1 ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

red()  { printf '\033[31m%s\033[0m\n' "$*"; }
grn()  { printf '\033[32m%s\033[0m\n' "$*"; }
ylw()  { printf '\033[33m%s\033[0m\n' "$*"; }

[ -f "$ENV_FILE" ] || { red "FATAL: $ENV_FILE not found."; echo "Copy store_platform/.env.production.example to it and fill in live keys."; exit 1; }

echo "==> Loading $ENV_FILE"
set -a; . "$ENV_FILE"; set +a

# ---- validation: fail BEFORE we touch Stripe or boot anything ----
fail=0
need_real() { # name, value, placeholder-substr
  local name="$1" val="${2:-}" bad="$3"
  if [ -z "$val" ]; then red "  MISSING  $name"; fail=1; return; fi
  if printf '%s' "$val" | grep -qiE "REPLACE_ME|change-me|$bad"; then red "  PLACEHOLDER $name (still a template value)"; fail=1; return; fi
  grn "  ok       $name"
}
echo "==> Validating live configuration"
need_real "Stripe__ApiKey"          "${Stripe__ApiKey:-}"          "REPLACE_ME"
need_real "Stripe__WebhookSecret"   "${Stripe__WebhookSecret:-}"   "REPLACE_ME"
need_real "Store__InternalApiKey"   "${Store__InternalApiKey:-}"   "dev-test-key-change-in-production"
need_real "Store__EntitlementsApiKey" "${Store__EntitlementsApiKey:-}" "dev-entitlements-key-change-in-production"
need_real "R2_ACCOUNT_ID"           "${R2_ACCOUNT_ID:-}"           "REPLACE_ME"
need_real "R2_ACCESS_KEY_ID"        "${R2_ACCESS_KEY_ID:-}"        "REPLACE_ME"
need_real "R2_SECRET_ACCESS_KEY"    "${R2_SECRET_ACCESS_KEY:-}"    "REPLACE_ME"
need_real "R2_BUCKET"               "${R2_BUCKET:-}"               "REPLACE_ME"

case "${Stripe__ApiKey:-}" in
  sk_live_*) grn "  ok       Stripe__ApiKey is a LIVE key" ;;
  sk_test_*) ylw "  WARNING  Stripe__ApiKey is a TEST key — this will provision TEST prices, not live" ;;
  *) red "  Stripe__ApiKey is neither sk_live_ nor sk_test_"; fail=1 ;;
esac
case "${Stripe__WebhookSecret:-}" in
  whsec_*) grn "  ok       Stripe__WebhookSecret shape" ;;
  *) red "  Stripe__WebhookSecret must start with whsec_"; fail=1 ;;
esac
[ "${payments__active_provider:-}" = "stripe" ] && grn "  ok       payments__active_provider=stripe" \
  || { red "  payments__active_provider must be 'stripe' for the Stripe cutover"; fail=1; }

if [ "$fail" -ne 0 ]; then red "==> Validation failed. Fix the above in $ENV_FILE and re-run."; exit 1; fi
grn "==> Validation passed."

# ---- step 1: reprovision catalogue packs onto LIVE Stripe prices ----
if [ "$SKIP_REPROVISION" -eq 0 ]; then
  PY="${PYTHON:-$REPO_ROOT/.venv/bin/python}"; [ -x "$PY" ] || PY="python3"
  echo "==> Reprovisioning catalogue packs onto Stripe ($([ "$DRY_RUN" -eq 1 ] && echo dry-run || echo LIVE))"
  STRIPE_API_KEY="$Stripe__ApiKey" "$PY" "$SCRIPT_DIR/reprovision_stripe.py" $([ "$DRY_RUN" -eq 1 ] && echo --dry-run)
else
  ylw "==> Skipping reprovision (--skip-reprovision)"
fi

# ---- step 2: boot Store.Api in Production to PROVE the fail-closed gate accepts live config ----
if [ "$SKIP_BOOTCHECK" -eq 0 ]; then
  echo "==> Building Store.Api (Release)"
  dotnet build "$API_DIR/Store.Api.csproj" -c Release -v quiet >/dev/null
  DLL="$API_DIR/bin/Release/net9.0/Store.Api.dll"
  TMP_DIR="$(mktemp -d)"; PORT=5292
  cleanup() { [ -n "${API_PID:-}" ] && kill "$API_PID" 2>/dev/null || true; lsof -ti tcp:$PORT 2>/dev/null | xargs -r kill 2>/dev/null || true; rm -rf "$TMP_DIR"; }
  trap cleanup EXIT
  echo "==> Booting Store.Api in PRODUCTION (throwaway db; proves MoneyRailConfigGate accepts your live secrets)"
  (
    cd "$API_DIR"
    ASPNETCORE_ENVIRONMENT=Production \
    ASPNETCORE_URLS="http://localhost:$PORT" \
    ConnectionStrings__DefaultConnection="Data Source=$TMP_DIR/bootcheck.db" \
    dotnet "$DLL" >"$TMP_DIR/api.log" 2>&1
  ) &
  API_PID=$!
  ok=0
  for i in $(seq 1 40); do
    if curl -fsS "http://localhost:$PORT/catalog" >/dev/null 2>&1; then ok=1; break; fi
    if ! kill -0 "$API_PID" 2>/dev/null; then break; fi
    sleep 1
  done
  if [ "$ok" -eq 1 ]; then
    grn "==> PRODUCTION boot gate PASSED — the live money rail is configured and fail-closed."
  else
    red "==> PRODUCTION boot FAILED — MoneyRailConfigGate rejected the config (this is the gate working)."
    echo "    Last log lines:"; tail -25 "$TMP_DIR/api.log"; exit 1
  fi
else
  ylw "==> Skipping boot gate check (--skip-bootcheck)"
fi

cat <<EOF

$(grn "Automated cutover steps complete.")
Remaining HUMAN-ONLY steps (cannot be automated):
  1. Deploy this API with $ENV_FILE exported in its environment.
  2. In the Stripe dashboard, register the LIVE webhook endpoint at
     https://<your-api-domain>/webhooks/stripe for events:
       checkout.session.completed, charge.refunded, charge.dispute.created
     Copy its signing secret (whsec_...) into Stripe__WebhookSecret if it changed.
  3. Make ONE real low-value purchase on the live storefront, confirm the download,
     then refund it in the dashboard and confirm access is revoked. To replay the
     full gate suite against live instead:
       STRIPE_TEST_SECRET_KEY="\$Stripe__ApiKey" bash store_platform/scripts/prove_money_path.sh
EOF
