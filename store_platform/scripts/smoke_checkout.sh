#!/usr/bin/env bash
# Open a LIVE embedded checkout priced at the smoke-test token amount, and print the URL.
#
# The overlay is the one layer no API call can prove: Stripe.js accepts a malformed publishable
# key and fails only once Elements paints, and checkoutRoute falls back to hosted only when the
# session REQUEST fails, never when the RENDER is wrong. So the proof has to be a human watching
# it paint against the live key — which at £49 a pack is a bill for looking at a form.
#
# What this does: asks the API for an embedded session carrying X-Smoke-Test-Key, which reprices
# every line to Stripe:SmokeTestPriceId, then prints a pack URL that opens the overlay on it.
# The listed price is untouched for everyone else — see SmokeTestPricing for why a buyer cannot
# reach this, and why a wrong key is refused rather than sold at full price.
#
# It also reads the amount back FROM STRIPE with the secret key, so the figure shown is Stripe's,
# not this repo's claim about itself.
#
#   bash store_platform/scripts/smoke_checkout.sh                     # first listed pack
#   bash store_platform/scripts/smoke_checkout.sh f71ad0c4cf8b5344    # a specific pack
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"
API="${API_URL:-https://api.${ESTATE_ZONE:?set ESTATE_ZONE, the estate zone}}"
SITE="${SITE_URL:-https://${ESTATE_ZONE:?set ESTATE_ZONE, the estate zone}}"

red() { printf '\033[31m%s\033[0m\n' "$*"; }
grn() { printf '\033[32m%s\033[0m\n' "$*"; }

[ -f "$ENV_FILE" ] || { red "FATAL: $ENV_FILE not found"; exit 1; }
# `|| true`: under pipefail a non-matching grep would abort the script with no output at all.
read_var() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"'\r' || true; }

KEY="$(read_var STORE_INTERNAL_API_KEY)"
SK="$(read_var STRIPE_LIVE_API_KEY)"
[ -n "$KEY" ] || { red "FATAL: STORE_INTERNAL_API_KEY missing from $ENV_FILE"; exit 1; }

PACK="${1:-}"
if [ -z "$PACK" ]; then
  PACK="$(curl -sf "$API/catalog" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["id"])')"
fi

echo "==> Requesting a token-priced embedded session for $PACK"
resp="$(curl -s -X POST "$API/packs/$PACK/checkout" \
  -H 'Content-Type: application/json' -H "X-Smoke-Test-Key: $KEY" \
  -d '{"embedded":true}' -w '\n%{http_code}')"
code="$(printf '%s' "$resp" | tail -1)"
body="$(printf '%s' "$resp" | sed '$d')"

if [ "$code" != "200" ]; then
  red "  API returned $code — no session created."
  red "  401 = STORE_INTERNAL_API_KEY does not match the deployed Store__InternalApiKey."
  red "  503 = Stripe__SmokeTestPriceId is not set on the API app."
  printf '%s\n' "$body" | head -3
  exit 1
fi

# encodeURIComponent, not raw: the secret contains literal '%2F', which a browser would decode
# to '/', handing Stripe a different string than it issued and failing the session in a way that
# looks like a broken overlay.
URL="$(printf '%s' "$body" | SITE="$SITE" PACK="$PACK" python3 -c '
import json,sys,os,urllib.parse
cs=json.load(sys.stdin).get("clientSecret")
if not cs:
    sys.stderr.write("no clientSecret: the provider answered with a hosted session\n"); sys.exit(1)
site, pack = os.environ["SITE"], os.environ["PACK"]
print(site + "/pack/" + urllib.parse.quote(pack, safe="") + "?checkout_session=" + urllib.parse.quote(cs, safe=""))
')"

if [ -n "$SK" ]; then
  SID="$(printf '%s' "$body" | python3 -c 'import json,sys; print(json.load(sys.stdin)["clientSecret"].split("_secret_")[0])')"
  echo "==> Reading the amount back from Stripe (not from our own API)"
  curl -s "https://api.stripe.com/v1/checkout/sessions/$SID" -u "$SK:" | python3 -c '
import json,sys
d=json.load(sys.stdin)
if "error" in d: print("   could not read session:", d["error"].get("message"))
else:
    p=(d.get("amount_total") or 0)/100
    cur = (d.get("currency") or "").upper()
    print("   Stripe will charge {:.2f} {}  livemode={}".format(p, cur, d.get("livemode")))
'
fi

grn "==> Open this to see the LIVE overlay at the token price:"
printf '%s\n' "$URL"
echo
echo "Completing it charges the token amount and grants the REAL pack (PackId is preserved),"
echo "so this exercises fulfilment and delivery too. Refund from the Stripe dashboard after."
