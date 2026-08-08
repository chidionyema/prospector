# Home polish — evidence on phones, the 320 shift, and the two contrast tokens

Source: `docs/DESIGN_UX_AUDIT_PROGRAM.md` F-014, F-013 (§ consequences 2–3), F-002, F-003.
Baseline: production `https://mumchimp.com` at `origin/main`, measured 2026-08-08 with
`AUDIT_ONLY=home node scripts/design-audit/audit.mjs` after the F-013 instrument fix.

**Not in scope: any redesign.** PR 134 (61 files, the §3 dark design system) was rejected on sight as
objectively worse. Every change below is a visibility, token or layout-reservation change to what
already renders. Programme rule 0.1 still holds: S1 is the auditor's to fix, S3 is never
auto-implemented.

**Withdrawn before you start, so nobody works it:** the "desktop LCP 4964ms" finding was the
harness measuring after a `fullPage` screenshot. Real home LCP is 472–612ms at all six viewports.
There is no performance story here.

---

## Story 1 (S1) — a phone can see the proof without scrolling

**As** someone landing on mumchimp.com from a phone,
**I want** to see at least one real verdict or the kill count in the first screen,
**so that** "the research already done" is a thing I can check, not a claim I have to trust.

Today `HeroEvidenceStrip` is `hidden md:block` (`src/pages/index.tsx:1673`) and the featured pack is
`hidden lg:block` (`:1681`), so below 768px the fold is a headline, a sub-line and two CTAs.

**Do:** make a mobile-sized form of the evidence strip render below 768px. Prefer shrinking the
existing artefact (fewer rows, tighter type) over authoring a second component — a mobile-only
duplicate is what `:1489` and `:935` warn against.

**Acceptance — all measured, none adjectival:**
1. At 320/360/390, the fold screenshot contains at least one rendered verdict row **or** the kill
   total. Check: `home-<vp>-fold.png` plus a DOM assertion that the strip's root has a non-zero
   height and `getBoundingClientRect().top < viewportHeight`.
2. The fold still passes at all four phone widths in `measure-fold.mjs` with ≥40px of the primary
   CTA visible (360 has 236px of margin today — spending some is fine, going under is not).
3. CLS at 360/390 stays ≤0.002 (today 0.001/0.002). Reserve the strip's box; do not let it push.
4. LCP at 320/360/390 stays under 1200ms (today 472–564ms).
5. `tsc --noEmit` = 0, `vitest run` green, `npm run lint` = 0, `npm run build` = 0.

## Story 2 (S2) — the 320px layout stops moving

**As** a visitor on a 320px-wide phone, **I want** the page to stop shifting after it paints.

CLS is **0.033** at 320 against T6's 0.000 bar, and 0.017 at 768. It survived the F-013 correction
unchanged, so it is the page, not the instrument. 360/390 are effectively clean (0.001/0.002), which
localises it to whatever only wraps or reflows at the narrowest width.

**Do first, before proposing any fix:** identify the shifting nodes. The observer at
`audit.mjs:335-341` already receives `layout-shift` entries — record `entry.sources[].node` and
report the top contributors at 320. *A number with no element names no fix.*

**Acceptance:** CLS ≤0.002 at 320 and ≤0.005 at 768, with the identified sources named in the PR
description and no regression at the other four viewports.

## Story 3 (S1/S2) — the two failing colour tokens reach production

**As** a low-vision reader, **I want** body text to clear the contrast bar on the site that is
actually served.

The sweep found `rgb(161,161,170)` at **2.56:1** on 8 nodes (F-002, below the AA 4.5:1 floor) and
`rgb(113,113,122)` at **4.63/4.83:1** (F-003, passes AA, misses the 7:1 house bar) live on
production. The a11y pass that fixed F-002 landed on `fix/storefront-a11y`, not on what is served.

**Do:** get the F-002 token change onto `main` and deployed; then decide F-003 separately — moving
the muted token to 7:1 is a palette decision, not a bug fix, and belongs to whoever owns the tokens.

**Acceptance:**
1. Zero contrast failures below 4.5:1 at every viewport on production (today 8).
2. `axe-core` reports 0 `color-contrast` violations at 360 and 1440.
3. F-003 either lands or is recorded in the ledger as an accepted deviation with a reason — not
   left silently open.

---

## Verification, one command

```bash
cd store_platform/src/Store.Web
AUDIT_ONLY=home AUDIT_OUT=/tmp/audit-after node scripts/design-audit/audit.mjs
```

Compare against the corrected baseline table in `docs/DESIGN_UX_AUDIT_PROGRAM.md` F-013. The bar is
"objectively better than current", so a claim ships only with the before/after row that proves it.
