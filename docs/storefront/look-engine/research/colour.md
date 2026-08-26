# Colour, contrast and tokens — what the look engine must do

Full brief: task output `a91f6b8cd285b2654.output`. Every number below was measured by a command
in that session, not recalled.

## The headline, and it governs the architecture

**Guaranteed-accessible palette generation is NOT a solved problem. Nothing surveyed guarantees
WCAG.** The reason is structural: **OKLCH L is not a contrast handle.**

Measured, scanning hue and chroma at fixed OKLCH L:

    OKLCH L=0.5: Y ranges 0.0983 .. 0.1371 -- 1.40x spread
                 contrast vs white 5.612 .. 7.082

At one L, moving only hue and chroma spans "fails AAA" to "passes AAA". An engine that fixes
OKLCH L per role and varies hue per look has no contrast guarantee at all. It has a lottery.

Why CIE L* does not have this problem, and OKLCH does: WCAG relative luminance IS CIE Y, and CIE
L* is a function of Y alone. At constant L*, WCAG luminance is constant to 5e-5 across every hue
and chroma (and that residual is just WCAG's rounded 0.2126/0.7152/0.0722). Oklab's L is not a
function of Y. That is the whole difference.

**Second rule: gamut mapping breaks contrast.** The CSS algorithm holds L and cuts chroma, and
luminance varies with chroma at constant L. Measured swing: **6.37** (oklch(0.3 0.4 39) goes from
7.881 against white to 14.249 after mapping). Evaluate contrast on the final mapped sRGB triple,
never before.

**Third rule: a binary search alone is not enough.** Contrast is non-monotonic in OKLCH L in
1 of 288 hue/chroma slices (worst upward dip 1.23e-2). That is exactly the kind of "almost
monotonic" that ships as a bug. The verify step is not optional.

## Two hard limits to design around

For a background at luminance Y the best possible contrast is max(1.05/(Y+0.05), (Y+0.05)/0.05).

- **AA (4.5:1) is always solvable** — but the worst background (Y=0.1791, CIE L*=49.4) affords
  only **4.5826:1**, 1.8% headroom. The solver has to be exact; there is no slack.
- **AAA (7:1) is impossible for any background with Y in (0.10, 0.30)** — CIE L* 37.8 to 61.7,
  about a quarter of the lightness range. Constrain the background first; no foreground
  cleverness rescues a mid-tone ground. Reject those seeds rather than emit a look that cannot pass.

## The mechanism that works: solve, verify, repair

1. Choose the background first and constrain its luminance to the solvable band.
2. Binary-search OKLCH L at fixed hue and chroma, evaluating `contrast(gamutMap(L,C,h), bg)` —
   the mapped value.
3. **Verify** against the bar. On failure, walk chroma down, then L to the extreme.
4. Still failing: fall back to black or white, which always suffices for 3:1 and 4.5:1.

Step 3 is what every surveyed library omits, and it is the difference between "targets" and
"guarantees". Property-tested over 2000 random (hue, chroma, bg lightness, bg chroma) quadruples:
zero failures, zero cases needing the extreme fallback.

## Vendor nothing — write ~1.8KB

A hand-written core of Ottosson's direct linear-sRGB matrices + the signed sRGB transfer function
+ CSS Color 4 gamut mapping + WCAG contrast measured **2,752 bytes source, 1,784 minified, 1,038
gzipped**, and matched colorjs.io's "css" gamut map to **1.241e-7** over 1,560 samples.

Nearest alternatives: colorjs.io 45,431 bytes tree-shaken (78,627 as shipped), culori 64,322 as a
droppable IIFE (16,479 tree-shaken but needs a bundler), chroma.js 22,767 light build. So a
dependency costs 25-44x the bytes in a file whose whole premise is being self-contained.

Use Ottosson's **direct linear-sRGB** matrices, not the XYZ route. Ottosson's M1 does not map D65
white to LMS (1,1,1) exactly (CSS recalculated it; max element difference 3.04e-4), but his direct
sRGB matrices are internally consistent and never meet that discrepancy. Licence: public domain,
or MIT if you prefer one.

## The spec numbers

CSS Color 4 is at **s14** (not 13), CRD 6 August 2026, and there are now **three** algorithms —
Binary Search with Local MINDE, EdgeSeeker (pseudocode still a TODO) and Ray Trace. Binary search
constants: **JND = 0.02, epsilon = 0.0001**, loop bounded by `max - min > epsilon` (13 iterations
worst case for chroma in [0,0.5]). Ray Trace is a fixed 4 iterations. deltaEOK is plain Euclidean
distance in Oklab — note the spec also defines deltaEOK2, which the gamut map does NOT use.

WCAG 2.2 (Recommendation, 12 Dec 2024) is the only normative contrast standard. Use **0.04045**,
not 0.03928 — the value changed in May 2021 and Adobe Leonardo still ships the old one
(`leo_utils.js:382`). Contrast is (L1+0.05)/(L2+0.05).

Use the **signed** transfer function (branch on abs, re-apply sign). Clamping at zero breaks the
gamut-mapping loop, which must evaluate out-of-gamut colours by construction.

## APCA: do not touch

**Zero mentions of APCA in the WCAG 3.0 Working Draft of 3 March 2026** (grepped, 741,587 bytes).
WCAG 3.0 itself says it is "inappropriate to cite this document as other than a work in progress".
And the licence is the worst in the survey: patents pending, all rights reserved, field-of-use
restricted to web content, a no-modification clause, a duty to keep current, a right to audit
commercial integrations, and an AGPL-3.0 fallback via its `colorparsley` dependency. Source-
available, not open source.

## Prior art, measured rather than described

- **Adobe Leonardo** (Apache-2.0) targets and silently under-delivers. Measured: asked for 4.5,
  got 4.4948 (inside its own epsilon=0.01, outside a strict assertion); asked for 21, got black at
  19.26 with no flag. No throw, no -1.
- **Material `Contrast.lighter/darker`** (Apache-2.0) is the right *shape* — closed-form solve,
  returns -1 when impossible, adds a 0.4-tone margin explicitly to survive gamut mapping. But it
  works on CIE L*. Copy the pattern, not the code.
- **Radix** (MIT) guarantees APCA Lc 60, which is not WCAG. Measured across all 31 light scales:
  **6 of 31 fail WCAG AA** at step 11, the step they sell for text (orange 4.25, teal 4.34).
- **Tailwind** (MIT) makes no contrast claim and should not be read as one: `*-500` fails AA
  against white in **17 of 26** scales, and OKLCH L inside one step number varies by up to 0.253.

## Tokens and testing

DTCG **Format Module 2025.10** is a Final Community Group Report and contains **zero** mentions of
oklch — colour lives in the **Color Module**, a third editors' draft with `Latest published
version: none`. Neither is on the W3C standards track. Do not build internals on it; add a
~20-line `toDTCG()` export emitting `colorSpace: "oklch"` with the `hex` fallback we already
compute. (`https://tr.designtokens.org/format/` currently serves a preview that says outright
"Do not attempt to implement this version". Link designtokens.org/TR/2025.10/ instead.)

fast-check (MIT) ships **no browser bundle** — ESM with an external `pure-rand` import. It bundles
to a working 164KB IIFE with one offline esbuild run, but that is 92x the whole colour core. For
"every seed emits passing pairs", a seeded PRNG and a loop is ~20 lines and gives the one feature
that matters: a reproducible counterexample seed. Ship the loop behind `?selftest`; keep
fast-check dev-only.
