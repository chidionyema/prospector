#!/usr/bin/env bash
# "Is the store production-ready?" as a command instead of a sentence.
#
# This is the standing probe for AC-7 of STORY_PRODUCTION_READY.md. It answers one question —
# can a stranger safely give us GBP49 right now — and it answers it by checking, not asserting.
#
# Verdicts:
#   PASS  checked and good
#   FAIL  checked and broken            -> exit 1
#   SKIP  could NOT be checked          -> exit 3
#
# SKIP is never folded into PASS. A check that could not run is not a check that passed, and a
# probe that green-lights on missing evidence is the exact failure this file exists to prevent.
# Exit 0 therefore means every gate was actually verified.
#
#   bash store_platform/scripts/verify_store.sh
#   bash store_platform/scripts/verify_store.sh --quick   # skip the live Stripe + e2e checks
#
# Read-only, with one exception: without --quick it MINTS a Stripe checkout session to prove
# the money rail still mints. Unpaid sessions cost nothing and expire on their own.
set -uo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
DOMAIN="${STORE_DOMAIN:-mumchimp.com}"
SITE="${SITE_URL:-https://$DOMAIN}"
API="${STORE_API_BASE:-https://api.$DOMAIN}"
ENV_FILE="${PROSPECTOR_ENV_PATH:-$REPO_ROOT/.env}"
DKIM_SELECTOR="${MAILJET_DKIM_SELECTOR:-mailjet}"
SPF_INCLUDE="${MAILJET_SPF_INCLUDE:-include:spf.mailjet.com}"
FLY_API_APP="${FLY_API_APP:-prospector-store-api}"

QUICK=0
[ "${1:-}" = "--quick" ] && QUICK=1

fail=0
skip=0
hr()   { printf '%s\n' "============================================================"; }
ok()   { printf '  PASS  %s\n' "$1"; }
bad()  { printf '  FAIL  %s\n' "$1"; fail=$((fail + 1)); }
skp()  { printf '  SKIP  %s\n' "$1"; skip=$((skip + 1)); }
info() { printf '  ....  %s\n' "$1"; }

hr; printf 'STORE PRODUCTION PROBE — %s\n' "$DOMAIN"; hr

# Stripe key, read the same way provision_prices.py reads it. Mode matters: a test key proves
# nothing about the store that takes real money, so live-only checks SKIP rather than pretend.
SKEY="${STRIPE_API_KEY:-}"
if [ -z "$SKEY" ] && [ -f "$ENV_FILE" ]; then
  SKEY=$(grep -E '^STRIPE_API_KEY=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'"'"' ')
fi
case "$SKEY" in
  *_live_*) SMODE=live ;;
  *_test_*) SMODE=test ;;
  "")       SMODE=none ;;
  *)        SMODE=unknown ;;
esac

# ---------------------------------------------------------------- 1. storefront reachable
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$SITE/" 2>/dev/null)
if [ "$code" = "200" ]; then ok "storefront $SITE returns 200"
else bad "storefront $SITE returned '$code' — buyers cannot reach the shop"; fi

# ---------------------------------------------------------------- 2. catalogue has stock
cat_json=$(curl -s --max-time 20 -w '\n%{http_code}' "$API/catalog" 2>/dev/null)
cat_code=$(printf '%s' "$cat_json" | tail -1)
cat_json=$(printf '%s' "$cat_json" | sed '$d')
cat_n=$(printf '%s' "$cat_json" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(len(d) if isinstance(d,list) else len(d.get("items",[])))' 2>/dev/null)
if [ "$cat_code" != "200" ]; then
  # "API down" and "API up but empty" need different people out of bed. Don't merge them.
  bad "$API/catalog returned HTTP '$cat_code' — the store API is not serving"
elif [ -n "$cat_n" ] && [ "$cat_n" -ge 1 ] 2>/dev/null; then
  ok "$API/catalog: 200 with $cat_n pack(s)"
else
  bad "$API/catalog is 200 but lists no packs — nothing is for sale"
fi

# ---------------------------------------------------------------- 3. checkout still mints
if [ "$QUICK" = "1" ]; then
  skp "checkout mint (--quick)"
elif [ "$cat_n" = "" ] || [ "${cat_n:-0}" -lt 1 ] 2>/dev/null; then
  skp "checkout mint — no pack to test against"
else
  pack=$(printf '%s' "$cat_json" | python3 -c 'import sys,json;d=json.load(sys.stdin);i=d if isinstance(d,list) else d.get("items",[]);print(i[0].get("id",""))' 2>/dev/null)
  url=$(curl -s --max-time 30 -X POST "$API/packs/$pack/checkout" \
        -H 'Content-Type: application/json' -d '{}' 2>/dev/null |
        python3 -c 'import sys,json;print(json.load(sys.stdin).get("url",""))' 2>/dev/null)
  # The session id is in the redirect url, and its prefix is the only outside-the-box proof of
  # which Stripe mode the DEPLOYED api is in. A cs_test_ session takes fake cards and pays us
  # nothing while looking, to a buyer, exactly like a real checkout.
  case "$url" in
    *cs_live_*) ok "checkout mints a LIVE Stripe session (cs_live_) for pack $pack" ;;
    *cs_test_*) bad "checkout minted a TEST session (cs_test_) — prod is on a test key and takes no real money" ;;
    "")         bad "POST $API/packs/$pack/checkout returned no url — buyers cannot pay" ;;
    *)          bad "checkout returned an unexpected url: $url" ;;
  esac
fi

# ---------------------------------------------------------------- 4. webhook registered
if [ "$SMODE" != "live" ]; then
  skp "Stripe webhook registration — need a LIVE key (have: $SMODE)"
else
  wh=$(curl -s --max-time 20 https://api.stripe.com/v1/webhook_endpoints -u "$SKEY:" 2>/dev/null |
       python3 -c "
import sys,json
d=json.load(sys.stdin).get('data',[])
want={'checkout.session.completed','charge.refunded','charge.dispute.created'}
for e in d:
    if '$DOMAIN' in e.get('url','') and e.get('status')=='enabled':
        missing = want - set(e.get('enabled_events',[]))
        print('OK' if not missing else 'MISSING:'+','.join(sorted(missing)));break
else: print('NONE')
" 2>/dev/null)
  case "$wh" in
    OK)       ok "Stripe webhook enabled with all 3 required events" ;;
    MISSING:*) bad "Stripe webhook missing events: ${wh#MISSING:}" ;;
    *)        bad "no enabled Stripe webhook pointing at $DOMAIN — payments would never fulfil" ;;
  esac
fi

# ---------------------------------------------------------------- 5. MX (can we receive?)
if [ -n "$(dig +short MX "$DOMAIN" @8.8.8.8 2>/dev/null)" ]; then
  ok "MX present — support@$DOMAIN can receive"
else
  bad "NO MX on $DOMAIN — refund/support mail BOUNCES at the sender (chargeback feeder)"
fi

# ---------------------------------------------------------------- 6. SPF / DKIM (can we send?)
# An SPF record that exists but does not authorise Mailjet is the false-green this check exists
# to stop: the domain looks configured, and every order email still fails SPF at the recipient.
spf_txt=$(dig +short TXT "$DOMAIN" @8.8.8.8 2>/dev/null | grep 'v=spf1')
if [ -z "$spf_txt" ]; then
  bad "NO SPF on $DOMAIN — Mailjet cannot send as @$DOMAIN, so no order emails"
elif printf '%s' "$spf_txt" | grep -q "$SPF_INCLUDE"; then
  ok "SPF present on $DOMAIN and authorises Mailjet ($SPF_INCLUDE)"
else
  bad "SPF on $DOMAIN does not contain $SPF_INCLUDE — Mailjet sends will fail SPF at the recipient"
fi

if [ -n "$(dig +short TXT "${DKIM_SELECTOR}._domainkey.$DOMAIN" @8.8.8.8 2>/dev/null)" ]; then
  ok "DKIM present (${DKIM_SELECTOR}._domainkey.$DOMAIN)"
else
  bad "NO DKIM at ${DKIM_SELECTOR}._domainkey.$DOMAIN — order email will spam-file or be rejected"
fi

dmarc=$(dig +short TXT "_dmarc.$DOMAIN" @8.8.8.8 2>/dev/null)
case "$dmarc" in
  *onsecureserver.net*) bad "DMARC still points at the GoDaddy default rua — nobody reads those reports" ;;
  "")                   bad "no DMARC record on $DOMAIN" ;;
  *)                    ok "DMARC set to a policy we control" ;;
esac

# ---------------------------------------------------------------- 7. fulfilment email configured
# Proven from the outside: the API logs DELIVERY-DEGRADED at boot when Mailjet is unset. The
# storefront cannot report this, so use the deploy's own secret list when fly is available.
# Mailjet authenticates with a key PAIR — a key without its secret 401s on every send, so both
# must be present or this is not configured.
if ! command -v fly >/dev/null 2>&1; then
  skp "Mailjet config — fly CLI not available here"
# An unauthenticated `fly` also prints nothing, which would read as "the secret is missing" and
# send someone chasing a config bug that does not exist. Separate "could not ask" from "not set".
elif ! secrets=$(fly secrets list -a "$FLY_API_APP" 2>/dev/null); then
  skp "Mailjet config — 'fly secrets list -a $FLY_API_APP' failed (not logged in, or no such app)"
elif printf '%s' "$secrets" | grep -q MAILJET_API_KEY \
  && printf '%s' "$secrets" | grep -q MAILJET_API_SECRET; then
  ok "MAILJET_API_KEY + MAILJET_API_SECRET present in fly secrets"
elif printf '%s' "$secrets" | grep -q MAILJET_API_KEY; then
  bad "MAILJET_API_SECRET absent (key is set) — Mailjet 401s on every send; buyers get NO email"
else
  bad "MAILJET_API_KEY absent from fly secrets — buyers get NO email, only the browser tab"
fi

# ---------------------------------------------------------------- 8. deployable from git
if [ -z "$(git -C "$REPO_ROOT" status --porcelain -- store_platform 2>/dev/null)" ]; then
  ok "store_platform/ is clean — a deploy would ship exactly $(git -C "$REPO_ROOT" rev-parse --short HEAD)"
else
  bad "store_platform/ is dirty — fly deploy ships the working tree, so prod could not be rebuilt"
fi

# ---------------------------------------------------------------- 9. reconcile (AC-4)
if [ "$SMODE" != "live" ]; then
  skp "paid-vs-delivered reconcile — need a LIVE Stripe key (have: $SMODE)"
else
  rec=$(python3 "$REPO_ROOT/store_platform/scripts/reconcile_orders.py" --days 7 --json 2>/dev/null)
  und=$(printf '%s' "$rec" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(len(d.get("undelivered",[]))+len(d.get("unreachable",[])))' 2>/dev/null)
  if [ "${und:-1}" = "0" ]; then ok "reconcile clean — every paid buyer can download"
  else bad "reconcile: ${und:-?} paid buyer(s) without delivery — run reconcile_orders.py"; fi
fi

# ---------------------------------------------------------------- 10. storefront smoke
if [ "$QUICK" = "1" ]; then
  skp "Playwright smoke (--quick)"
elif [ ! -d "$REPO_ROOT/store_platform/src/Store.Web/node_modules" ]; then
  skp "Playwright smoke — node_modules not installed"
else
  if (cd "$REPO_ROOT/store_platform/src/Store.Web" && WEB_BASE_URL="$SITE" npx playwright test >/tmp/verify_store_pw.log 2>&1); then
    ok "Playwright storefront smoke passed against $SITE"
  else
    bad "Playwright smoke FAILED against $SITE — see /tmp/verify_store_pw.log"
  fi
fi

# ---------------------------------------------------------------- verdict
hr
if [ "$fail" -gt 0 ]; then
  printf 'STORE: NOT SELLABLE — %d check(s) failed, %d unverified\n' "$fail" "$skip"; hr; exit 1
elif [ "$skip" -gt 0 ]; then
  printf 'STORE: UNPROVEN — 0 failures but %d check(s) could not run\n' "$skip"
  printf '       Not the same as ready. Re-run where the missing credentials exist.\n'; hr; exit 3
else
  printf 'STORE: SELLABLE — every gate verified\n'; hr; exit 0
fi
