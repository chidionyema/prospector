#!/usr/bin/env bash
# Attach a custom domain to the two Fly apps and print the exact DNS records to create.
#
# Run this AFTER `fly auth login` and AFTER both apps are deployed on their .fly.dev hostnames.
# It does not touch .env.production: the URL switch must happen only once the certificates are
# actually issued, otherwise the Stripe success redirect points at a hostname that still
# resolves to the registrar's parking page — a paying buyer would land there instead of their
# download. Sequence is: deploy on fly.dev -> this script -> add DNS -> wait for cert -> flip.
#
# Usage:
#   bash store_platform/scripts/setup_domain.sh mumchimp.com
#   bash store_platform/scripts/setup_domain.sh mumchimp.com --check   # re-check cert status only
set -euo pipefail

DOMAIN="${1:-}"
MODE="${2:-}"
WEB_APP="${WEB_APP:-prospector-store-web}"
API_APP="${API_APP:-prospector-store-api}"

red() { printf '\033[31m%s\033[0m\n' "$1"; }
grn() { printf '\033[32m%s\033[0m\n' "$1"; }
ylw() { printf '\033[33m%s\033[0m\n' "$1"; }
bld() { printf '\033[1m%s\033[0m\n' "$1"; }

[ -n "$DOMAIN" ] || { red "Usage: setup_domain.sh <domain> [--check]"; exit 1; }
command -v fly >/dev/null || { red "flyctl is not installed."; exit 1; }
fly auth whoami >/dev/null 2>&1 || { red "Not logged in. Run: fly auth login"; exit 1; }

APEX="$DOMAIN"
API_HOST="api.$DOMAIN"

if [ "$MODE" != "--check" ]; then
  echo "==> Requesting certificates"
  # fly certs add is idempotent — re-running an existing hostname is a no-op, so this is safe
  # to run repeatedly while DNS is still propagating.
  fly certs add "$APEX"     --app "$WEB_APP" >/dev/null 2>&1 || true
  fly certs add "www.$APEX" --app "$WEB_APP" >/dev/null 2>&1 || true
  fly certs add "$API_HOST" --app "$API_APP" >/dev/null 2>&1 || true
  grn "  requested: $APEX, www.$APEX (-> $WEB_APP), $API_HOST (-> $API_APP)"
fi

echo
bld "==> DNS records to create at your registrar (123-reg panel: dcc.123-reg.co.uk -> DNS Management)"
echo

# An apex name cannot be a CNAME in ordinary DNS, so it needs literal A/AAAA records pointing
# at the web app's own addresses. Subdomains can CNAME, which is why the API host is simpler
# and why www can just follow the apex.
# `fly ips list` renders a table whose columns are separated by U+2502 box-drawing bars, so
# splitting on whitespace puts a bar in $1 and prints a bar as the address. Split on the bar
# and strip the padding instead.
fly_ip() { # version: v4 | v6
  fly ips list --app "$WEB_APP" 2>/dev/null \
    | awk -F'│' -v want="$1" '{gsub(/^[ \t]+|[ \t]+$/,"",$1); gsub(/^[ \t]+|[ \t]+$/,"",$2);
                               if ($1==want) {print $2; exit}}' || true
}
V4="$(fly_ip v4)"
V6="$(fly_ip v6)"

if [ -z "$V4" ]; then
  ylw "  $WEB_APP has no IPv4 yet. Allocate one, then re-run:"
  ylw "    fly ips allocate-v4 --app $WEB_APP     # dedicated, billed by Fly"
  ylw "    fly ips allocate-v4 --shared --app $WEB_APP   # free, works for A records"
else
  printf '  %-6s %-22s %s\n' "A" "@ (apex)" "$V4"
fi
[ -n "$V6" ] && printf '  %-6s %-22s %s\n' "AAAA" "@ (apex)" "$V6"
printf '  %-6s %-22s %s\n' "CNAME" "www" "$WEB_APP.fly.dev"
printf '  %-6s %-22s %s\n' "CNAME" "api" "$API_APP.fly.dev"
echo
ylw "  Delete the existing parked A records on @ first — they point at the registrar's"
ylw "  parking page, and leaving them means some visitors resolve to the wrong host."
echo
echo "  Email (support@$APEX) is separate and NOT required to go live: it needs MX records,"
echo "  which nothing above provides. Until they exist the address bounces, so the storefront"
echo "  keeps using the operator's real mailbox from src/lib/config.ts."

echo
bld "==> Certificate status"
for pair in "$APEX:$WEB_APP" "www.$APEX:$WEB_APP" "$API_HOST:$API_APP"; do
  host="${pair%%:*}"; app="${pair##*:}"
  status="$(fly certs show "$host" --app "$app" 2>/dev/null | awk -F' *= *' '/^ *Status/{print $2; exit}' || true)"
  case "$status" in
    Ready) grn "  ready    $host" ;;
    "")    ylw "  unknown  $host (not requested, or fly returned nothing)" ;;
    *)     ylw "  $status  $host — Fly issues the cert once DNS resolves; re-run with --check" ;;
  esac
done

echo
echo "When all three say ready, switch over with:"
echo "  bash store_platform/scripts/switch_domain.sh $DOMAIN"
