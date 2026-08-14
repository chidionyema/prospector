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
# Advisory, for build-time vars whose absence degrades reporting but not the site.
ylw() { printf '\033[33m%s\033[0m\n' "$*"; }

TARGET="${1:-}"; shift || true
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    *) red "unknown arg: $arg"; exit 2 ;;
  esac
done

# .env carries BOTH Stripe pairs side by side (test + live), so the key is chosen by target
# rather than read from one fixed name. Reading a single NEXT_PUBLIC_ name would mean editing
# .env to switch modes, and an .env edited per deploy is an .env that eventually ships the
# wrong mode.
case "$TARGET" in
  prod) EXPECT_MODE="pk_live_"; PK_VARS="STRIPE_LIVE_PUBLISHABLE_KEY NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY" ;;
  test) EXPECT_MODE="pk_test_"; PK_VARS="NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY STRIPE_TEST_PUBLISHABLE_KEY" ;;
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

# Search-console ownership tokens. OPTIONAL, and therefore reported rather than validated below:
# an unset one emits no meta tag, which is the correct absent state. They are still read here
# because they are build-time (NEXT_PUBLIC_, inlined by Next), so a token set only as a runtime
# Fly secret would never reach the page — the silent failure this script exists to catch.
GOOGLE_VERIFY="${NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION:-$(read_var NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION)}"
BING_VERIFY="${NEXT_PUBLIC_BING_SITE_VERIFICATION:-$(read_var NEXT_PUBLIC_BING_SITE_VERIFICATION)}"

# First var for this target that holds a key of the right mode wins, so the live and test pairs
# can coexist in .env under their own names.
PK=""; PK_SRC=""
for _v in $PK_VARS; do
  _candidate="$(read_var "$_v")"
  [ -n "$_candidate" ] || continue
  if [ -z "$PK" ]; then PK="$_candidate"; PK_SRC="$_v"; fi
  if [ "${_candidate#"$EXPECT_MODE"}" != "$_candidate" ]; then PK="$_candidate"; PK_SRC="$_v"; break; fi
done

fail=0
echo "==> Validating build-time public vars for target '$TARGET'"

if [ -z "$API_URL" ]; then red "  MISSING   NEXT_PUBLIC_API_URL"; fail=1
else grn "  ok        NEXT_PUBLIC_API_URL=$API_URL"; fi

if [ -z "$SITE_URL" ]; then
  red "  MISSING   NEXT_PUBLIC_SITE_URL (site would ship with no canonical URL or social card)"
  fail=1
else grn "  ok        NEXT_PUBLIC_SITE_URL=$SITE_URL"; fi

# Reported, never fatal: the site indexes fine without them, they only unlock the consoles'
# own reporting. Saying so out loud is the point — a token that is set in .env but silently
# dropped looks identical to one that was never obtained.
if [ -z "$GOOGLE_VERIFY" ]; then ylw "  absent    NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION (Search Console will report unverified)"
else grn "  ok        NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION set (len ${#GOOGLE_VERIFY})"; fi
if [ -z "$BING_VERIFY" ]; then ylw "  absent    NEXT_PUBLIC_BING_SITE_VERIFICATION (Bing Webmaster Tools will report unverified)"
else grn "  ok        NEXT_PUBLIC_BING_SITE_VERIFICATION set (len ${#BING_VERIFY})"; fi

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
  grn "  ok        publishable key from \$$PK_SRC = ${EXPECT_MODE}… (len ${#PK})"

  # The prefix proves the MODE; it does not prove the key WORKS. A revoked, truncated or
  # paste-mangled key passes every offline check and then fails inside Stripe.js — after the
  # buyer has opened checkout. This happened for real: a live key carried a trailing '=' from a
  # copy-paste, which Stripe rejects with 401 while every string check above was happy.
  #
  # /v1/elements/sessions is the cheapest probe a PUBLISHABLE key may authenticate against: it
  # creates nothing, and with no params a valid key gets 400 "Missing required param: type"
  # while an invalid one gets 401. So 401 is the only failing verdict; any other status (or an
  # unreachable Stripe) means the key itself is not the problem and must not block a deploy.
  echo "==> Proving the publishable key authenticates with Stripe"
  pk_status="$(curl -s -o /dev/null -m 15 -G https://api.stripe.com/v1/elements/sessions \
                 --data-urlencode "key=$PK" -w '%{http_code}' || echo 000)"
  case "$pk_status" in
    401)
      red "  REJECTED  Stripe returned 401 Invalid API Key for \$$PK_SRC"
      red "            The key is well-formed and correctly moded but NOT VALID (revoked,"
      red "            truncated, or carrying a stray character). Stripe.js would load and then"
      red "            fail inside the checkout overlay. Refusing to build."
      fail=1 ;;
    000)
      red "  UNKNOWN   could not reach Stripe to validate the key (network/timeout)."
      red "            Not treating this as a key failure; re-run when Stripe is reachable." ;;
    *)
      grn "  ok        Stripe accepted the key (http=$pk_status, 401 would mean invalid)" ;;
  esac
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
# NOT `exec`. This line used to be `exec flyctl deploy …`, and `exec` replaces the process image,
# which meant that by construction nothing could ever run after a deploy. Every gate in this
# script fires BEFORE shipping — clean tree, five build args, a live Stripe key — and nothing
# fired after, so the only instrument ever pointed at production was somebody opening the site on
# a phone. That is the mechanism behind defects recurring: a fix is proven on localhost, shipped,
# and never measured again.
flyctl deploy . --config ../../deploy/fly/web.fly.toml \
  --build-arg "NEXT_PUBLIC_API_URL=$API_URL" \
  --build-arg "NEXT_PUBLIC_SITE_URL=$SITE_URL" \
  --build-arg "NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=$PK" \
  --build-arg "NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION=$GOOGLE_VERIFY" \
  --build-arg "NEXT_PUBLIC_BING_SITE_VERIFICATION=$BING_VERIFY"
deploy_status=$?

if [ "$deploy_status" -ne 0 ]; then
  red "==> flyctl deploy failed (exit $deploy_status) — not measuring; nothing new is live"
  exit "$deploy_status"
fi

# The other half of the rail: measure what buyers now get. This cannot block the deploy (it has
# already happened) but it must be impossible to ship and walk away without a verdict on the
# result, printed at the end where the operator is already looking.
echo "==> Measuring what just went live"
python3 "$SCRIPT_DIR/prove_live.py" --site "$SITE_URL" --api "$API_URL"
live_status=$?
if [ "$live_status" -ne 0 ]; then
  red "==> DEPLOYED, but the live storefront is not clean (prove_live.py exit $live_status)"
  red "    The deploy itself succeeded. Read the failures above and decide: fix forward or roll back."
fi
exit "$deploy_status"
