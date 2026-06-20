#!/usr/bin/env bash
# Prove ALL money paths in one command. Run this before every launch and after any change to
# checkout / webhook / fulfilment / delivery code. Two phases, each boots its own Store.Api:
#
#   Phase A (prove_checkout.sh)   — the BUY BUTTON: real Checkout Session created for every
#                                   listed pack against the real catalogue (catches stale
#                                   price ids + checkout/tax misconfig).
#   Phase B (prove_money_path.sh) — FULFILMENT + negative paths: signed webhook -> order ->
#                                   entitlement -> presigned R2 download; idempotency;
#                                   underpayment guard; refund + dispute revocation; forged
#                                   signature rejected; download cap; expiry.
#   Phase C (prove_storefront.sh) — NON-PAYMENT API: catalogue listing + fields, survivorship
#                                   stats, pack detail, 404 handling, admin auth gates, CORS.
#
# (The rendered web UI is proven separately by prove_web.sh — a browser smoke.)
#
# Requires in env: STRIPE_TEST_SECRET_KEY, R2_ACCOUNT_ID, R2_ACCESS_KEY_ID,
# R2_SECRET_ACCESS_KEY, R2_BUCKET. Exit 0 only if every assertion in every phase passes.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "########################################################################"
echo "#  PROVE ALL PATHS — Phase A: buy button (real checkout, every pack)    #"
echo "########################################################################"
bash "$SCRIPT_DIR/prove_checkout.sh"; A=$?

echo
echo "########################################################################"
echo "#  PROVE ALL PATHS — Phase B: fulfilment + negative paths               #"
echo "########################################################################"
bash "$SCRIPT_DIR/prove_money_path.sh"; B=$?

echo
echo "########################################################################"
echo "#  PROVE ALL PATHS — Phase C: non-payment storefront API                #"
echo "########################################################################"
bash "$SCRIPT_DIR/prove_storefront.sh"; C=$?

echo
echo "================================  SUMMARY  ============================="
printf "  Phase A  buy button / checkout : %s\n" "$([ $A -eq 0 ] && echo PASS || echo FAIL)"
printf "  Phase B  fulfilment + negatives: %s\n" "$([ $B -eq 0 ] && echo PASS || echo FAIL)"
printf "  Phase C  non-payment API       : %s\n" "$([ $C -eq 0 ] && echo PASS || echo FAIL)"
echo "  Proofs: store/launch/{checkout,test-card,storefront}-proof.md"
echo "  (web UI: bash store_platform/scripts/prove_web.sh)"
echo "======================================================================="
[ $A -eq 0 ] && [ $B -eq 0 ] && [ $C -eq 0 ] && { echo "ALL PATHS PROVEN ✅"; exit 0; }
echo "LAUNCH BLOCKED — at least one path failed ❌"; exit 1
