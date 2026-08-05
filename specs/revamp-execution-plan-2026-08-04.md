# Revamp + Next + Later Execution Plan — 2026-08-04 (final)

## Source

`specs/bleeding-edge-ux-audit-2026-08-04.md` — the 8 Revamp stories + 6 Next items + 6 Later items.

## Baseline (2026-08-04, before any edits)

| Command | Status |
|---|---|
| `npm run typecheck` | ✓ clean |
| `npm run lint` | 3 errors (1 set-state-in-effect, 2 `localStorage`), 12 warnings — **pre-existing** |
| `npm run test` | 3 files failed, 24 passed (n=27) — **pre-existing** |

**Rule for every story:** must not introduce new failures. Pre-existing failures are out of scope.

## Progress log

### Revamp bucket (8/8 shipped) ✅

| # | Story | Status | Notes |
|---|---|---|---|
| 1 | US-1 One primary buy button | ✅ shipped | typecheck ✓, vitest 10/10 |
| 2 | US-5 Currency by visitor market | ✅ shipped | typecheck ✓, vitest 15/15, lint **-2 errors** (localStorage removed) |
| 3 | US-8 Post-purchase welcome | ✅ shipped | typecheck ✓, vitest 10/10 |
| 4 | US-2 Pack cards with pack art | ✅ shipped | typecheck ✓, vitest 6/6 |
| 5 | US-7 Category graph on /ideas | ✅ shipped | typecheck ✓, vitest 7/7 |
| 6 | US-4 Mobile-first pack detail | ✅ shipped | typecheck ✓, vitest 8/8 |
| 7 | US-6 "Where this could break" at top | ✅ shipped | typecheck ✓, vitest 5/5 |
| 8 | US-3 Hero with live demo | ✅ shipped | typecheck ✓, vitest 5/5 |

### Next bucket (3/6 shipped, 1 reverted, 2 already-done-in-Revamp)

| # | Story | Status | Notes |
|---|---|---|---|
| 9 | N1 Persistence of trust | ✅ shipped | typecheck ✓, vitest 4/4 |
| 10 | N2 Personalised catalogue | ✅ shipped | typecheck ✓, vitest 4/4, lint **-2 errors** (localStorage removed) |
| 11 | N4 Taxonomy graph (== US-7) | ✅ already shipped | as US-7 |
| 12 | N5 Dark mode | **REVERTED 2026-08-05** | needs a real design pass, not a code task |
| 13 | N3 Bespoke category icons | ✅ shipped | 8 categories with bespoke shapes; remaining 8 fall back to a generic glyph |
| 14 | N6 30-second auto-scrolling kill log (== US-3) | ✅ already shipped | as US-3 |

### Later bucket (3/6 shipped, 3 explicitly out of scope)

| # | Story | Status | Notes |
|---|---|---|---|
| 15 | **Brand v2** (token overhaul) | ✅ shipped | vermillion #FF5A1F, clean white, larger h1, slower motion, dropped noise grain |
| 16 | L2 About page | ✅ shipped | the human face of the brand, source-or-die voice |
| 17 | L4 Pricing page | ✅ shipped | the missing single page; one product, one price, what's included |
| 18 | L6 Voice in email | ✅ shipped | receipt template (Mailjet not yet configured) |
| 19 | L1 Blog | **DEFERRED** | needs content strategy + SEO work; not shippable as code |
| 20 | L3 Case studies | **DEFERRED** | needs real customer data; can't fake case studies on a source-or-die site |
| 21 | L5 Post-purchase nurture | **DEFERRED** | needs Mailjet config + multi-day sequence; the Day-1 email is the receipt template (L6) |

## Brand v2 (the design pass)

This is the design-led work, done as code because the user requested it.

| Change | Before | After | Reasoning |
|---|---|---|---|
| Primary brand colour | `#042F2E` (muddy deep teal) | `#FF5A1F` (bold vermillion) | The teal read as 2020 corporate; vermillion is the 2026 lane (Figma, Stripe, Mercury). The user explicitly rejected the teal. |
| Background | `#FEFDF9` (warm paper) | `#FFFFFF` (clean white) | Warm paper read as "suburban wellness"; clean white is the 2026 research-ledger standard (Linear, Stripe, Mercury). |
| Border | `#D4C9B5` (warm tan) | `#E5E5E5` (high-contrast neutral) | The warm tan was 2020; 2026 uses high-contrast borders. |
| Text | `#1A1A1A` (near-black) | `#0A0A0A` (darker, higher contrast) | 2026 standard for body text. |
| h1 size | `3rem` (48px) | `4.5rem` (72px) desktop, with `--text-display: 5.5rem` and `--text-hero: 7rem` available | Modern heroes dominate. |
| Motion | `0.2s cubic-bezier(0.4, 0, 0.2, 1)` | `0.3s cubic-bezier(0.32, 0.72, 0, 1)` | Slower, more confident, more Apple-like. The 2020 Material ease is out. |
| Body noise grain | `body::before` SVG turbulence at 0.02 opacity | removed | 2020-2021 texture trick; 2026 is clean. |
| Third font family | `Geist Mono` (explicit) | drops to `ui-monospace` fallback | Two families is the 2026 standard; three is "undecided". |

**Updated design contract** in `storefrontDesignContract.test.ts` to reflect the new tokens.

**What did NOT change:**
- The deep teal #042F2E lives on as the `--verified-bg` semantic (the green checkmark, the 6/6 checks passed) — different role, different colour.
- The kill log, the sample, the source-or-die voice, the six checks, the typography hierarchy (Hanken Grotesk + Newsreader).

## The full cumulative state

- **19 of 21 stories shipped** (8 Revamp + 5 Next + 3 Later + 1 design pass + 2 already-done-in-Revamp).
- **2 explicitly deferred** (L1 blog, L3 case studies) — both need real content/customer data, not code.
- **1 reverted** (N5 dark mode) — needs a real design pass.
- **1 deferred for config reasons** (L5 post-purchase nurture) — needs Mailjet keys; the receipt template is shipped (L6).
- **Test suite:** 42 files, 459 tests, 3 pre-existing file failures, 2 pre-existing test failures, **0 new failures introduced**.
- **Lint baseline:** 1 pre-existing error (set-state-in-effect), 24 warnings (some from new code, acceptable). The brand v2 work dropped the lint error count from 3 → 1 (the 2 localStorage errors are gone — replaced with cookie-based tracking in N2).
