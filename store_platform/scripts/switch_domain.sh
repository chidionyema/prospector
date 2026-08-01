#!/usr/bin/env bash
# Cut the store over from the .fly.dev hostnames to a custom domain.
#
# This is the step with the sharp edge. Two ways to get it wrong, both of which look fine:
#
#  1. Flipping the URLs before the certificate is issued and DNS resolves to Fly. The Stripe
#     success redirect would then send paying buyers to whatever the old A records point at —
#     for a freshly-bought domain that is the registrar's parking page. Same class of failure
#     as the /orders/success 404, in a new costume. So this script refuses to flip until it has
#     checked both.
#
#  2. Updating the URLs but not rebuilding the web image. NEXT_PUBLIC_API_URL is inlined into
#     the JS bundle at BUILD time, and next.config.js derives the CSP connect-src from it. Ship
#     without rebuilding and the storefront renders perfectly while the browser silently blocks
#     every API call — errors appear only in the devtools console. So this script does not
#     consider the switch done until the rebuild has run.
#
# Usage: bash store_platform/scripts/switch_domain.sh mumchimp.com
set -euo pipefail

DOMAIN="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${ENV_FILE:-$PLATFORM_DIR/.env.production}"
WEB_APP="${WEB_APP:-prospector-store-web}"
API_APP="${API_APP:-prospector-store-api}"

red() { printf '\033[31m%s\033[0m\n' "$1"; }
grn() { printf '\033[32m%s\033[0m\n' "$1"; }
ylw() { printf '\033[33m%s\033[0m\n' "$1"; }

[ -n "$DOMAIN" ] || { red "Usage: switch_domain.sh <domain>"; exit 1; }
[ -f "$ENV_FILE" ] || { red "No $ENV_FILE"; exit 1; }

STORE_URL="https://$DOMAIN"
API_URL="https://api.$DOMAIN"

echo "==> Pre-flight: refusing to switch onto a domain that is not actually serving yet"
fail=0

# Certificates. Without these the browser shows a security interstitial, not the store.
for pair in "$DOMAIN:$WEB_APP" "api.$DOMAIN:$API_APP"; do
  host="${pair%%:*}"; app="${pair##*:}"
  # `|| true`: fly exits non-zero for a hostname it has never seen, and under `set -e` +
  # pipefail that would kill this script with no output at all — a silent abort that looks
  # identical to success. An unrequested cert must report NOT READY, loudly.
  status="$(fly certs show "$host" --app "$app" 2>/dev/null | awk -F' *= *' '/^ *Status/{print $2; exit}' || true)"
  # Fly reports a live certificate as "Issued"; older output said "Ready". Accepting only one of
  # them turns a perfectly good cert into a refused cutover — a false negative that reads exactly
  # like a real DNS failure. Both are accepted; anything else still fails loudly.
  if [ "$status" = "Issued" ] || [ "$status" = "Ready" ]; then grn "  ok       certificate $host ($status)"
  else red "  NOT READY certificate $host (status: ${status:-none}) — run setup_domain.sh $DOMAIN --check"; fail=1; fi
done

# Reachability is NOT enough on its own: a freshly-bought domain's parking page answers 200
# perfectly happily, so "it responds" would wave through a switch onto the registrar's holding
# page. Each host is therefore checked for a marker only our own app emits.
#
# The apex must serve the storefront. BRAND.name is rendered into every page by MarketingLayout,
# so its absence means we reached something that is not the store.
if curl -fsS --max-time 15 "$STORE_URL" 2>/dev/null | grep -qi "Prospector Store"; then
  grn "  ok       $STORE_URL serves the storefront"
else
  red "  WRONG HOST $STORE_URL did not serve the storefront (parking page, or DNS not propagated)"
  fail=1
fi

# The API must answer as our API. /catalog is unauthenticated and returns JSON, so a parking
# page cannot fake it.
if curl -fsS --max-time 15 "$API_URL/catalog" >/dev/null 2>&1; then
  grn "  ok       $API_URL/catalog answers as the store API"
else
  red "  WRONG HOST $API_URL/catalog did not respond as the store API"
  fail=1
fi

[ "$fail" -eq 0 ] || { red "==> Aborted. Nothing changed."; exit 1; }

echo "==> Rewriting URLs in $ENV_FILE"
DOMAIN="$DOMAIN" STORE_URL="$STORE_URL" API_URL="$API_URL" ENV_FILE="$ENV_FILE" python3 - <<'PY'
import os, re
path = os.environ["ENV_FILE"]
updates = {
    # Where a buyer is sent after paying, and the CORS origin. Both are the STOREFRONT.
    "STORE_STOREFRONT_URL": os.environ["STORE_URL"],
    "STORE_ALLOWED_ORIGIN":  os.environ["STORE_URL"],
    # The magic-link email base. This one is the API — it serves /orders/{token}.
    "STORE_PUBLIC_URL":      os.environ["API_URL"],
    # Verification / password-reset / OAuth-landing base. Also the STOREFRONT. Its baked default
    # in deploy/fly/api.fly.toml still names the OLD domain, and a secret overrides that file, so
    # it must be re-set here or account emails keep pointing at the domain you just left.
    "Email__WebBaseUrl":     os.environ["STORE_URL"],
}
with open(path) as fh:
    text = fh.read()
for key, val in updates.items():
    line = f"{key}={val}"
    text, n = re.subn(rf"(?m)^{key}=.*$", lambda _m, l=line: l, text)
    if n == 0:
        text = text.rstrip("\n") + "\n" + line + "\n"
    print(f"  {key}={val}")
with open(path, "w") as fh:
    fh.write(text)
PY

cat <<EOF

==> Remaining steps — these cannot be skipped

1. Rebuild the storefront so the new API origin is baked into the bundle and the CSP:
     cd $PLATFORM_DIR/src/Store.Web
     fly deploy . --config ../../deploy/fly/web.fly.toml --app $WEB_APP \\
       --build-arg NEXT_PUBLIC_API_URL=$API_URL \\
       --build-arg NEXT_PUBLIC_SITE_URL=$STORE_URL

2. Push the new URLs to the API:
     fly secrets set --app $API_APP \\
       STORE_STOREFRONT_URL=$STORE_URL \\
       STORE_ALLOWED_ORIGIN=$STORE_URL \\
       STORE_PUBLIC_URL=$API_URL \\
       Email__WebBaseUrl=$STORE_URL

   Then update the baked default in deploy/fly/api.fly.toml ([env] Email__WebBaseUrl) to the same
   value and commit it, so the config file and the secret do not disagree about which domain
   account emails point at.

3. Re-point the Stripe webhook at the new API host (the old endpoint still targets .fly.dev):
     bash $SCRIPT_DIR/register_stripe_webhook.sh --recreate
     fly secrets set --app $API_APP Stripe__WebhookSecret="\$(grep '^Stripe__WebhookSecret=' $ENV_FILE | cut -d= -f2-)"

4. Confirm: bash $SCRIPT_DIR/go_live.sh --dry-run
EOF
