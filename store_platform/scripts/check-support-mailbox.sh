#!/usr/bin/env bash
# Is the customer-facing support address actually able to receive mail?
#
# Exit 0 = the address shown on refund.tsx / terms.tsx / privacy.tsx / the footer / every pack page
#          can receive mail. Exit 1 = it bounces at the sender and refund requests vanish silently.
#
# Why this exists: on 2026-07-30, config.ts shipped support@mumchimp.com to production (release v9,
# commit a46db6e, message "reachable support address") while the mumchimp.com zone had NO MX record.
# The commit message asserted reachable; the zone said otherwise. This script is the check that
# would have caught it, so status stops being a sentence and becomes a command.
#
#   bash store_platform/scripts/check-support-mailbox.sh
#   bash store_platform/scripts/check-support-mailbox.sh --live   # also assert the live pages agree
set -uo pipefail

DOMAIN="${SUPPORT_DOMAIN:-mumchimp.com}"
ADDR="${SUPPORT_ADDR:-support@$DOMAIN}"
SITE="${SITE_URL:-https://mumchimp.com}"
fail=0

hr() { printf '%s\n' "------------------------------------------------------------"; }
ok()   { printf '  PASS  %s\n' "$1"; }
bad()  { printf '  FAIL  %s\n' "$1"; fail=1; }
info() { printf '  ....  %s\n' "$1"; }

hr; printf 'support mailbox probe — %s\n' "$ADDR"; hr

# 1. MX. No MX record => the domain cannot receive mail at all. This is the hard gate.
#    Queried against the resolver AND 8.8.8.8, because a stale local cache is not evidence.
mx_local=$(dig +short MX "$DOMAIN" 2>/dev/null | tr -d ' ')
mx_pub=$(dig +short MX "$DOMAIN" @8.8.8.8 2>/dev/null | tr -d ' ')
if [ -n "$mx_local" ] || [ -n "$mx_pub" ]; then
    ok "MX present: $(dig +short MX "$DOMAIN" @8.8.8.8 2>/dev/null | tr '\n' ' ')"
else
    bad "NO MX record on $DOMAIN (local and 8.8.8.8 both empty) — mail to $ADDR BOUNCES"
    info "NS: $(dig +short NS "$DOMAIN" 2>/dev/null | tr '\n' ' ')"
    info "fix: add MX at the registrar above, e.g. a free forwarder into the Gmail already in use,"
    info "     or point the zone at a mail provider. MX-only changes do not touch A/CNAME, so the"
    info "     live site is unaffected. Re-run this script; it flips to PASS within the TTL."
fi

# 2. SPF/DKIM TXT. Not required to RECEIVE, but required for Postmark to SEND as this domain,
#    which is the other half of the order-delivery chain (POSTMARK_FROM_EMAIL in .env.production).
txt=$(dig +short TXT "$DOMAIN" @8.8.8.8 2>/dev/null)
if printf '%s' "$txt" | grep -qi 'v=spf1'; then
    ok "SPF present"
else
    info "no SPF TXT on $DOMAIN — Postmark cannot verify this sender, so order emails will not send"
    info "     (POSTMARK_FROM_EMAIL=orders@$DOMAIN). Not fatal for RECEIVING; fatal for SENDING."
fi

# 3. Optional: assert the deployed pages actually show this address. Catches the reverse drift —
#    DNS fixed but the build still shipping an old address, or vice versa.
if [ "${1:-}" = "--live" ]; then
    for p in /refund /terms /privacy; do
        body=$(curl -fsS --max-time 15 "$SITE$p" 2>/dev/null)
        if [ -z "$body" ]; then
            bad "$p did not respond"
        elif printf '%s' "$body" | grep -q "$ADDR"; then
            ok "$p shows $ADDR"
        else
            found=$(printf '%s' "$body" | grep -oiE '[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}' | sort -u | tr '\n' ' ')
            bad "$p does NOT show $ADDR (shows: ${found:-none})"
        fi
    done
fi

hr
if [ "$fail" -eq 0 ]; then
    printf 'SUPPORT MAILBOX: OK — %s can receive mail\n' "$ADDR"
else
    printf 'SUPPORT MAILBOX: BROKEN — refund and privacy requests are being lost\n'
fi
hr
exit "$fail"
