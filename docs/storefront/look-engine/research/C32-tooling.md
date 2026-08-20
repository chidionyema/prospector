# C32 — what makes shipping a broken layout mechanically impossible

The founder's words: *"we constantly have layout issues, junk design"*, *"all screens, all devices,
everything scientific"*.

The research this rests on was run by a subagent that died mid-report on an API error. Its 15
searches and 17 primary-doc fetches survived in its transcript and are extracted verbatim to
`qa-agent-findings.md`; the URL list is `qa-agent-urls.txt`. Nothing below is quoted from memory.
One live constraint found the same way: that session exhausted the web-search budget (200 of 200),
so no further searches are available until it is raised.

## The finding that decides the design

Nothing off the shelf gates a layout. The tools split cleanly in two:

**Pixel comparators** — Playwright `toHaveScreenshot`, Chromatic, Percy, Argos, BackstopJS. They
compare this render to the last render. They tell you a page CHANGED. They cannot tell you a page
is WRONG, so they cannot gate a page that has never been right, which is every page in a redesign.
They also cost: Argos Pro $100/month, Chromatic per-snapshot
(`https://argos-ci.com/pricing`, `https://www.chromatic.com/pricing`).

**Property checkers** — a small number of DOM measurements that are true or false regardless of
history. These gate. The academic work is ReDeCheck, which names the five failure classes worth
detecting: **element collision, element protrusion, viewport protrusion, small-range, wrapping**
(`https://github.com/redecheck/redecheck`). Verve classifies which of its reports a human would
actually see.

So: our gate is property-based, and the pixel comparator is a later, optional layer for
regressions once a look is signed off.

## What we already gate (`verify.mjs`, 80 cells = 10 looks x 4 viewports x 2 themes)

- contrast refusals — every pair in `PALETTE.PAIRS`, measured on the rendered page
- viewport protrusion — `scrollWidth > clientWidth` on the document, plus any element whose box
  escapes the viewport (`overflow.mjs` repeats this at 7 widths: 320/390/744/834/1024/1440/2560)
- tap targets under 24px, controls under 44px
- blank plates, console errors

## What the research says we are missing

1. **Element collision.** Two elements that did not overlap at a wider viewport overlapping at a
   narrower one. Detection is pairwise `getBoundingClientRect()` intersection over the visible,
   non-ancestor element set. This is ReDeCheck's headline class and we do not check it.
2. **Text truncation / clipping.** `el.scrollWidth > el.offsetWidth` on a text-bearing element
   means content is being cut, whether or not an ellipsis makes it look deliberate.
3. **Deterministic screenshots**, for when the pixel layer does arrive: fixed color profile and
   font rendering, animations frozen, clock frozen (`https://playwright.dev/docs/clock`,
   `https://playwright.dev/docs/test-snapshots`). `maxDiffPixels` / `threshold` are the tolerance
   knobs; both are unset by default.

## Standards the numbers come from, so nobody re-invents them

- **Target size, WCAG 2.2 SC 2.5.8 (AA): 24x24 CSS pixels**, with five exceptions, the load-bearing
  one being spacing — an undersized target passes if a 24px-diameter circle centred on it
  intersects no other target's circle
  (`https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html`).
  axe-core implements this as `target-size` and **it is OFF by default** until WCAG 2.2 is more
  widely required. A gate that runs axe with defaults is not checking target size at all — ours
  checks it directly, which is why it stays ours.
- **Core Web Vitals, at the 75th percentile: LCP 2.5s, INP 200ms, CLS 0.1**
  (`https://web.dev/articles/vitals`, page last updated 2024-10-31). All three stable.

## Decision

Extend `verify.mjs` with collision and truncation detection. Do not buy a visual-regression
service. Do not add axe-core as the gate for target size — add it later for the rules we do not
implement ourselves, and only with the WCAG 2.2 ruleset explicitly enabled.
