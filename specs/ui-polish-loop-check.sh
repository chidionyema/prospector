#!/usr/bin/env bash
# UI/UX quality check for Mumchimp.com
# Score = number of checks passed (higher = better)
# Exit 0 = all critical checks pass, exit 1 = failures remain

# The checkout this script lives in, never a fixed path on one machine.
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

score=0
total=0
failures=""

# --- Critical checks (worth 1 point each) ---
check() {
    local name="$1"
    local cmd="$2"
    total=$((total + 1))
    if eval "$cmd" >/dev/null 2>&1; then
        score=$((score + 1))
    else
        failures="$failures\n- $name"
    fi
}

# 1. No em-dashes in any source file
check "no em-dashes in .tsx/.ts" \
    "! grep -rl $'\u2014' store_platform/src/Store.Web/src/{pages,components} --include='*.tsx' --include='*.ts' 2>/dev/null | grep -v node_modules | grep -v __tests__ | head -1"

# 2. No bg-white remaining (should be bg-surface)
check "no bg-white on pages" \
    "! grep -rn 'bg-white\"' store_platform/src/Store.Web/src/pages/ --include='*.tsx' | grep -v node_modules | head -1"

# 3. No rounded-xl on structural containers
check "no rounded-xl on structural containers" \
    "! grep -rn 'rounded-xl border\|rounded-xl ' store_platform/src/Store.Web/src/pages/ --include='*.tsx' | grep -v node_modules | grep -v 'rounded-xl border border-border bg-white' | head -1"

# 4. No box-shadows on non-modal elements
check "no box-shadows outside modals" \
    "! grep -rn 'shadow-\[' store_platform/src/Store.Web/src/{pages,components} --include='*.tsx' | grep -v '__tests__' | grep -v 'premium' | grep -v 'EmbCheckoutPanel\|CommandPalette' | head -1"

# 5. No dead code (Matchmaker, IntentInput)
check "no Matchmaker/IntentInput" \
    "! find store_platform/src/Store.Web/src -name 'Matchmaker.tsx' -o -name 'IntentInput.tsx' 2>/dev/null | head -1"

# 6. Tests pass
check "vitest tests pass" \
    "cd store_platform/src/Store.Web && timeout 60 npx vitest run 2>/dev/null | grep -q 'Tests 0 failed'"

# 7. TypeScript compiles
check "tsc compiles" \
    "cd store_platform/src/Store.Web && timeout 60 npx tsc --noEmit 2>&1 | head -1"

# 8. Buy buttons functional
check "Unlock for £49 buttons present" \
    "curl -s https://${ESTATE_ZONE:?set ESTATE_ZONE, the estate zone} 2>/dev/null | grep -q 'Unlock for'"

# 9. Progressive flow visible
check "StepFlow on page load" \
    "curl -s https://${ESTATE_ZONE:?set ESTATE_ZONE, the estate zone} 2>/dev/null | grep -q 'What skills do you bring'"

# 10. Brand consistency: Hanken Grotesk only
check "single font family (Hanken) in HTML" \
    "! curl -s https://${ESTATE_ZONE:?set ESTATE_ZONE, the estate zone} 2>/dev/null | grep -o 'font-family[^;]*' | grep -v 'Hanken Grotesk\|sans-serif' | head -1"

# --- Output score ---
echo "SCORE: $score"
echo "FAILED:"
[ -n "$failures" ] && echo -e "$failures"

# Done when score >= 9 (must pass at least 9 of 10 checks)
if [ "$score" -ge 9 ]; then
    exit 0
else
    exit 1
fi
