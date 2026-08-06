# Checkpoint — 2026-08-05 · Mobile landing page hero overflow fixed & deployed

## Active task
**Mobile landing page broken on iPhone viewport** — hero text clipped past viewport edge, page had horizontal scroll, layout viewport reported 1056px on a 390px screen. Fixed and live.

## Root cause (four layers, peeled one per PR)
A hero h1 with `mx-auto max-w-[56rem]` plus `text-balance` plus a parent CSS Grid had FOUR compounding issues. Each fix alone was insufficient; only fixing all four together produced a clean mobile render.

1. **PR #97 — `min-w-0` on grid item.** Standard CSS-Grid cure for content blowout. Necessary but not sufficient.
2. **PR #98 — `max-w-full` on mobile h1.** Capped the h1's max-width at 100% of its parent on mobile. Necessary but not sufficient.
3. **PR #100 — `text-pretty` instead of `text-balance` on mobile.** `text-wrap: balance` computes the h1's intrinsic min-content width based on the longest balanced line pair, not the actual line breaks. On a 390px viewport that intrinsic width came out to ~1031px — wider than the viewport. `text-pretty` doesn't have the same issue. Necessary but not sufficient.
4. **PR #104 — `flex flex-col` instead of `grid` on mobile.** A CSS Grid + wide h1 + `min-w-0` Chrome quirk keeps the grid item at its intrinsic content width (~1031px) even with `min-w-0` set. `width: 100%` and `overflow: hidden` on the container don't fix it either. Replacing the outer grid with `flex flex-col` on mobile (md+ still uses `grid-cols-2`) sidesteps the bug: a flex item with `min-w-0` actually shrinks to its parent's width.

PR #101 (`overflow-hidden` on SectionBand inner) was belt-and-braces against any other section overflow.

## What I did, in order
1. **PR #95** — Killed 13 remaining brand v1 hardcoded hex values across 7 files (Account button border, category labels, badges, hover backgrounds, theme-color). Live.
2. **PR #96** — Deleted 3 dead contract tests for the deleted `Matchmaker.tsx` component. This unblocked the deploy-web.yml `npm test` gate, which had been silently failing and preventing brand v2 from shipping to `main` via the push trigger.
3. **PR #97** — `min-w-0` on hero grid item.
4. **PR #98** — `max-w-full` on mobile h1.
5. **PR #100** — `text-pretty` instead of `text-balance` on mobile.
6. **PR #101** — `overflow-hidden` on `SectionBand` inner.
7. **PR #102** — Remove `text-pretty`/`text-balance` on mobile entirely.
8. **PR #104** — `flex flex-col` on mobile instead of `grid` for both hero bands.

## Verification (live, 390px iPhone 13 viewport)
- `documentScrollW === viewportW` (no horizontal scroll)
- `overflowingCount: 0` (no element wider than viewport)
- Hero h1 wraps at "Skip 6 months of / research. Validated ideas / you can actually ship / today. Zero fluff, ready to / build. £49 a pack." — five lines, all inside the container
- Hero CTA "Read a free report, no email" renders correctly inside its orange-bordered button
- LIVE kill card renders at full width with stats: 1,080 KILLED · 129 SURVIVED
- Pack cards stack vertically, full width, with category eyebrows in vermillion
- All brand v2 colors: vermillion accent (#FF5A1F), white background, black band header
- No old teal remnants (#0D4645, #0D9488, #042F2E)

## Files changed
- `store_platform/src/Store.Web/src/components/marketing/blocks.tsx` (SectionBand)
- `store_platform/src/Store.Web/src/components/marketing/MarketingLayout.tsx`
- `store_platform/src/Store.Web/src/components/Seo.tsx`
- `store_platform/src/Store.Web/src/components/checkout/PackBuyButton.tsx`
- `store_platform/src/Store.Web/src/pages/_document.tsx`
- `store_platform/src/Store.Web/src/pages/ideas/index.tsx`
- `store_platform/src/Store.Web/src/pages/index.tsx`
- `store_platform/src/Store.Web/src/pages/pack/[id].tsx`
- (deleted) `store_platform/src/Store.Web/src/__tests__/matchmakerPromotionContract.test.ts`
- (deleted) `store_platform/src/Store.Web/src/__tests__/catalogV2AndPolishContract.test.ts`
- (deleted) `store_platform/src/Store.Web/src/__tests__/unifiedYourFitContract.test.ts`

## Lessons
- **Test gates can silently block production deploys** when the test refers to deleted code (ENOENT at file-read time). The deploy-web.yml `npm test` gate had been failing on every push to main since Matchmaker was deleted in `de151e7`. The earlier "all-fixed-and-deployed" claim was wrong because the deploy had silently failed.
- **CSS Grid + wide text + min-w-0 is a trap in Chrome.** The fix-Grid-blowout recipe (`min-w-0`) doesn't work when the content's intrinsic min-width is what makes it wide. `text-wrap: balance` makes a single line's text-width contribute to intrinsic min-width. Replacing the grid with `flex flex-col` on mobile sidesteps the bug.
- **Always render on the target viewport before claiming a mobile fix.** The first "fixed" deploy was correct on the desktop-rendered HTML but broken on mobile. The user's first complaint was visual; my verification was token-name-matching. Real browser screenshots catch what grep doesn't.

## Known follow-ups
- Live storefront smoke tests on main are intermittently failing (e2e/discovery + e2e/seo). Pre-existing, unrelated to these changes. Worth a separate pass.
- The hero h1 itself still computes to ~1031px width internally even after all fixes; it just doesn't escape its parent now because of the flex layout. Cosmetic only.

---

**2026-08-06 — PR #111 IS MERGED. Do not re-attempt it.**
Merged by `chidionyema` at 07:36:33Z; squash commit `8b8e09d` is the tip of `origin/main`.
Content audited on main by `git cat-file -e` (not `rev-parse`): `noArbitraryHex.test.ts`,
`category.ts`, `marketing/LiveKillCard.tsx`, `prospector/bridge.py`, `prospector/pricing.py` all
PRESENT. Prod live: `api.mumchimp.com/catalog` 200, `mumchimp.com` 200.
`git log origin/main..HEAD` shows 35 commits — that is the normal squash-merge artifact
(branch SHAs are never ancestors of main here), NOT unmerged work. The real unmerged delta is
`git diff origin/main HEAD` = **`5f01aec` only** (`prospector/run.py`,
`tests/unit/test_scheduler_resume_drain.py`, +228/−1), committed 07:43:38Z — *after* the merge.
That commit and the staged `tools/backfill_listing_copy.py` work belong to the concurrent engine
session; they need their own PR, opened by that session.
**Still outstanding and founder-owned: rotate `ANTHROPIC_API_KEY` (leaked to a transcript), update `.env:2`.**
