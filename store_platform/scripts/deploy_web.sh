#!/usr/bin/env bash
# Deploy Store.Web with every build-time public var proven present and correctly moded.
#
# Why this exists: NEXT_PUBLIC_* values are baked into the client bundle at BUILD time, and a
# --build-arg for an ARG the Dockerfile does not declare is SILENTLY DISCARDED. Both known
# instances of that failed without an error anywhere:
#   - NEXT_PUBLIC_SITE_URL missing  -> no canonical URLs, no social preview card
#   - NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY missing -> stripeConfigured=false, so the embedded
#     checkout surface never engages and every buyer silently falls back to hosted checkout
# The second degrades *safely*, which is precisely why it can sit unnoticed for weeks.
#
# The mode check is the one that protects money: a pk_test_ bundle talking to an API holding a
# live secret key cannot confirm a live PaymentIntent, and a pk_live_ bundle against a test API
# fails the same way. Elements would render and then fail at confirmation — after the buyer has
# typed their card in.
#
# Read-only until the final deploy line. Exit non-zero = nothing was built or shipped.
#
#   bash store_platform/scripts/deploy_web.sh prod
#   bash store_platform/scripts/deploy_web.sh test --dry-run
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$PLATFORM_DIR/.." && pwd)"
WEB_DIR="$PLATFORM_DIR/src/Store.Web"

red() { printf '\033[31m%s\033[0m\n' "$*"; }
grn() { printf '\033[32m%s\033[0m\n' "$*"; }

TARGET="${1:-}"; shift || true
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    *) red "unknown arg: $arg"; exit 2 ;;
  esac
done

case "$TARGET" in
  prod) EXPECT_MODE="pk_live_" ;;
  test) EXPECT_MODE="pk_test_" ;;
  *) red "usage: deploy_web.sh {prod|test} [--dry-run]"; exit 2 ;;
esac

ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"
[ -f "$ENV_FILE" ] || { red "FATAL: $ENV_FILE not found"; exit 1; }

# Read the three baked values without exporting the whole env file into this shell.
# `|| true` is load-bearing: under `set -o pipefail` a grep that matches nothing fails the whole
# pipeline, and the assignment below would abort the script with no output at all — turning a
# "variable is missing" report into a silent exit, which is the exact failure class this guards.
read_var() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"'\r' || true; }

API_URL="${NEXT_PUBLIC_API_URL:-$(read_var NEXT_PUBLIC_API_URL)}"
SITE_URL="${NEXT_PUBLIC_SITE_URL:-$(read_var NEXT_PUBLIC_SITE_URL)}"
PK="${NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY:-$(read_var NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY)}"

fail=0
echo "==> Validating build-time public vars for target '$TARGET'"

if [ -z "$API_URL" ]; then red "  MISSING   NEXT_PUBLIC_API_URL"; fail=1
else grn "  ok        NEXT_PUBLIC_API_URL=$API_URL"; fi

if [ -z "$SITE_URL" ]; then
  red "  MISSING   NEXT_PUBLIC_SITE_URL (site would ship with no canonical URL or social card)"
  fail=1
else grn "  ok        NEXT_PUBLIC_SITE_URL=$SITE_URL"; fi

if [ -z "$PK" ]; then
  red "  MISSING   NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY"
  red "            -> embedded checkout would ship dark; buyers silently get hosted checkout."
  fail=1
elif [ "${PK#"$EXPECT_MODE"}" = "$PK" ]; then
  red "  WRONG MODE NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY is '$(printf '%s' "$PK" | cut -c1-8)…'"
  red "            target '$TARGET' requires a key starting ${EXPECT_MODE}"
  red "            A mode mismatch fails AFTER the buyer enters their card. Refusing to build."
  fail=1
else
  grn "  ok        NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=${EXPECT_MODE}… (len ${#PK})"
fi

# Never ship an uncommitted working tree: fly builds the WORKING TREE, not HEAD.
echo "==> Proving the tree"
bash "$SCRIPT_DIR/predeploy_guard.sh" || fail=1

[ "$fail" -eq 0 ] || { red "==> REFUSING TO DEPLOY"; exit 1; }

if [ "$DRY_RUN" -eq 1 ]; then
  grn "==> dry run: validation passed, nothing built"
  exit 0
fi

echo "==> Deploying Store.Web"
cd "$WEB_DIR"
exec flyctl deploy . --config ../../deploy/fly/web.fly.toml \
  --build-arg "NEXT_PUBLIC_API_URL=$API_URL" \
  --build-arg "NEXT_PUBLIC_SITE_URL=$SITE_URL" \
  --build-arg "NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=$PK"
