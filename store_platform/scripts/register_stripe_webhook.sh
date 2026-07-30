#!/usr/bin/env bash
# Register the live Stripe webhook endpoint and capture its signing secret.
#
# Replaces step 5 of deploy/PROD_DEPLOY.md ("in the dashboard, add an endpoint, copy the
# signing secret"). That step was manual only because the secret is shown once — but Stripe
# returns it in the CREATE response, so it can be captured here and written straight into
# .env.production without ever being printed to a terminal or pasted by hand.
#
# Usage:
#   bash store_platform/scripts/register_stripe_webhook.sh            # uses Stripe__ApiKey from .env.production
#   bash store_platform/scripts/register_stripe_webhook.sh --recreate # delete + recreate to re-issue the secret
#
# Prerequisite: Stripe__ApiKey in .env.production must already be a real sk_live_ key.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${ENV_FILE:-$PLATFORM_DIR/.env.production}"

RECREATE=0
[ "${1:-}" = "--recreate" ] && RECREATE=1

red() { printf '\033[31m%s\033[0m\n' "$1"; }
grn() { printf '\033[32m%s\033[0m\n' "$1"; }
ylw() { printf '\033[33m%s\033[0m\n' "$1"; }

[ -f "$ENV_FILE" ] || { red "No $ENV_FILE"; exit 1; }
set -a; . "$ENV_FILE"; set +a

API_KEY="${Stripe__ApiKey:-}"
case "$API_KEY" in
  sk_live_REPLACE_ME|"") red "Stripe__ApiKey is not set yet. Paste the sk_live_ key into $ENV_FILE first."; exit 1 ;;
  *REPLACE_ME*)          red "Stripe__ApiKey is still a template value."; exit 1 ;;
  sk_live_*)             ;;
  sk_test_*)             ylw "Stripe__ApiKey is a TEST key — this registers a TEST-mode endpoint." ;;
  *)                     red "Stripe__ApiKey is neither sk_live_ nor sk_test_."; exit 1 ;;
esac

# The webhook must point at the API host, not the storefront. STORE_PUBLIC_URL is the API base
# (it is what the magic-link emails use); the storefront lives at STORE_STOREFRONT_URL.
API_BASE="${STORE_PUBLIC_URL:-}"
[ -n "$API_BASE" ] || { red "STORE_PUBLIC_URL is not set — cannot derive the webhook URL."; exit 1; }
HOOK_URL="${API_BASE%/}/webhooks/stripe"

# Must match what StripeProvider.cs actually handles: checkout.session.completed grants the
# entitlement, the other two revoke it. Registering more just costs noise; registering fewer
# means a refund silently leaves the buyer with a working download link.
EVENTS=(checkout.session.completed charge.refunded charge.dispute.created)

api() { # method, path, [curl form args...]
  local method="$1" path="$2"; shift 2
  curl -sS -X "$method" "https://api.stripe.com/v1$path" -u "$API_KEY:" "$@"
}

echo "==> Looking for an existing endpoint at $HOOK_URL"
EXISTING_ID="$(api GET "/webhook_endpoints?limit=100" | python3 -c '
import json,sys
url = sys.argv[1]
data = json.load(sys.stdin)
if "error" in data:
    sys.stderr.write("Stripe API error: %s\n" % data["error"].get("message", "unknown"))
    sys.exit(2)
for e in data.get("data", []):
    if e.get("url") == url:
        print(e["id"]); break
' "$HOOK_URL")"

if [ -n "$EXISTING_ID" ]; then
  if [ "$RECREATE" -eq 0 ]; then
    ylw "An endpoint already exists: $EXISTING_ID"
    ylw "Stripe reveals a signing secret only when the endpoint is created, so it cannot be"
    ylw "read back. Either copy it from the dashboard, or re-run with --recreate to delete"
    ylw "this endpoint and issue a fresh secret."
    ylw "Re-creating is safe while no live traffic is flowing; mid-flight it drops any event"
    ylw "Stripe is retrying against the old endpoint."
    exit 3
  fi
  echo "==> Deleting $EXISTING_ID so a fresh secret can be issued"
  api DELETE "/webhook_endpoints/$EXISTING_ID" >/dev/null
fi

echo "==> Creating endpoint"
ARGS=(-d "url=$HOOK_URL" -d "description=Prospector store fulfilment")
for e in "${EVENTS[@]}"; do ARGS+=(-d "enabled_events[]=$e"); done

# The response carries the signing secret. It is piped straight into the env file and never
# echoed — printing it here would leave a live credential in scrollback and shell history.
api POST "/webhook_endpoints" "${ARGS[@]}" | ENV_FILE="$ENV_FILE" python3 -c '
import json, os, re, sys

data = json.load(sys.stdin)
if "error" in data:
    sys.stderr.write("Stripe API error: %s\n" % data["error"].get("message", "unknown"))
    sys.exit(2)

secret = data.get("secret")
if not secret or not secret.startswith("whsec_"):
    sys.stderr.write("Stripe did not return a signing secret; nothing written.\n")
    sys.exit(2)

path = os.environ["ENV_FILE"]
with open(path) as fh:
    text = fh.read()

line = "Stripe__WebhookSecret=%s" % secret
text, n = re.subn(r"(?m)^Stripe__WebhookSecret=.*$", lambda _: line, text)
if n == 0:
    text = text.rstrip("\n") + "\n" + line + "\n"

with open(path, "w") as fh:      # rewrite in place; existing 0600 mode is preserved
    fh.write(text)

print("endpoint  %s" % data["id"])
print("url       %s" % data["url"])
print("events    %s" % ", ".join(sorted(data.get("enabled_events", []))))
print("secret    written to %s (not printed)" % path)
'

grn "==> Done. Re-run scripts/go_live.sh --dry-run to confirm."
