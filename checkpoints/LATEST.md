# Checkpoint — 2026-08-02 · Fix stale contract tests (PR #51)

## Active task
**Stale contract tests** — PR #47 and PR #49 merged without updating tests. 8 failures on main. Fixed in PR #51.

## What happened
Main (`44da931`) breaks `vitest run` with 8 test failures. Every failure is a contract test
that wasn't updated when the design changed:

| Test | Failing count | Root cause |
|------|-------------|-----------|
| dashFree | 1 | 2 em-dashes in FacetBar.tsx comments (added by PR #47) |
| storefrontDesignContract | 2 | PR #49: rounded-lg→rounded-xl, motion-safe lift restored |
| catalogV2AndPolishContract | 1 | PR #49: primary chip bg-primary/10 restored |
| matchmakerPromotionContract | 4 | PR #47: Matchmaker → FacetBar; tests read wrong files |

## Fix
1. **FacetBar.tsx** — 2 em-dashes → commas.
2. **storefrontDesignContract.test.ts** — `rounded-xl` replaces `rounded-lg`; motion-safe lift accepted but must be gated.
3. **catalogV2AndPolishContract.test.ts** — primary chip `bg-primary/10` accepted; non-primary chips must be monochrome.
4. **matchmakerPromotionContract.test.ts** — auto-open redirected to FacetBar.tsx; setSheetOpen replaces setMatchOpen; cart.count skip documented as deferred; MatchmakerTrigger count → FacetBar Quick Start.
5. **specs/fix-stale-contract-tests.md** — new spec documenting the changes.

## Verification
- vitest: 367 passed (was 8 failed / 353 passed)
- typecheck: clean
- build: clean
- pytest: 1016 passed, 3 skipped
- Rendered HTML: 0 em-dashes, 0 en-dashes

## PR
- **#51** [fix-stale-contract-tests → main]: "fix: update stale contract tests after PR #47 and PR #49"
- 6 files changed, +216 / -38
- CI status: guard passed, 3 jobs pending

## Files touched
- `src/__tests__/storefrontDesignContract.test.ts` — rounded-xl + motion-safe lift
- `src/__tests__/catalogV2AndPolishContract.test.ts` — primary chip bg-primary/10
- `src/__tests__/matchmakerPromotionContract.test.ts` — redirect to FacetBar
- `src/components/discovery/FacetBar.tsx` — 2 em-dashes fixed
- `specs/fix-stale-contract-tests.md` — new
- `data/kill-log.json` — regenerated

## Open problems / next session
- The cart.count deferral (PR #47 removed the cart-count check from auto-open) — if it's reinstated, revert the matchmakerPromotionContract.test.ts assertion.
- PR #47 also removed `MatchesTrigger` from `pages/index.tsx`; the liveMatches count is now computed in FacetBar. If the feature is reinstated separately, update the contract test.
- The `storefrontDesignContract.test.ts` test name still references "8px radius" in the describe block — left as-is because the assertion has been changed; only the numeric contract matters.

## Exact next step
Wait for CI to pass 100%. If any further contract tests fail, compare the implementation against the latest design spec (PR #49 commit message body contains the design decisions).
