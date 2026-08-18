# AGENT FIX PROMPT — MUMCHIMP

Paste everything below the line into the agent. It assumes the previous build exists and needs correcting.

---

## STOP. READ THIS FIRST.

The previous build re-implemented the pages from prose descriptions and drifted. That approach is wrong and must not be repeated.

**The mockup HTML files in `/mockups` are the specification, not illustrations of it.** For every page you touch:

1. Open the corresponding mockup file.
2. **Copy its markup structure and class names verbatim.** Same elements, same nesting, same classes.
3. Bind real data into those elements.
4. Change nothing else. No re-interpretation, no improvements, no substitutions.

**Do not rewrite a single word of copy.** All copy in the mockups is either the site's published copy or copy that has been approved. If you find yourself composing a sentence, you have already made a mistake — stop and use the mockup's sentence.

When you finish a page, open the mockup and your build side by side and confirm they match structurally. If they differ, your build is wrong.

---

## DEFECTS TO FIX

### D1 — The hero signature device is missing (BLOCKER)

`mockups/index.html` contains, in the right column of `.hero`, a `<figure class="gridwrap">` holding:
- `<p class="ratiofig num">6 in 100</p>`
- a one-line explanation
- `<div class="ratio">` — 100 `<i>` elements, exactly 6 with `class="alive"`
- `.gridkey` with the two counts
- `<figcaption class="gridcap">` with the kill-log link

The current build omits all of it, leaving an empty column and a void under the CTA. **Port this figure exactly as written, including the CSS rules `.ratio`, `.ratio i`, `.ratio i.alive`, `.ratiofig`, `.ratiosub`.**

The hero is `grid-template-columns:1fr 400px` with `align-items:center` above 900px, single column below. Do not restyle it.

### D2 — The H1 was rewritten (BLOCKER)

Current: "Business ideas with the research and starter packs ready."
Required, exactly: **"Business ideas with the research already done."**

Keep `text-wrap: balance` and `max-width:12ch` so it breaks across three lines without orphaning "done."

### D3 — Text truncation, two separate bugs

**D3a — server-side truncation.** Descriptions are being cut mid-sentence with an ellipsis: "the tool emits a…", "turns every…", "enabling UK deep-tech…". The API must return the description **whole**. Remove every character-budget cut in the data layer. Clamping is CSS only:

```css
.row .d{ display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
```

**D3b — horizontal overflow.** The proof line "2× the price back in month one, modelle" runs off the right edge of the card. Nothing may overflow a card horizontally. Proof lines wrap or are shortened at the source; they are never clipped by the container.

Verification: no rendered description ends mid-word, and no text crosses a card boundary at 390px width.

### D4 — One proof-line format, sitewide

Three formats are live right now: `38 sources`, `16 cited sources behind it`, `2× the price back in month one, modelled`.

Build **one component** used everywhere. It takes `sources` and `payback` and renders exactly:

- `41 sources`
- `17× payback · 28 sources`

Delete the strings "cited sources behind it" and "the price back in month one, modelled" from all card and row components. They may remain in long-form documents inside a pack.

### D5 — Wrong card container model

The build renders each pack as a separate rounded card with a gap between them. The mockup renders one container with internal hairline dividers:

```html
<div class="rows">
  <a class="row" href="…"> … </a>
  <a class="row" href="…"> … </a>
</div>
```

```css
.rows{ background:var(--surface); border:1px solid var(--line); border-radius:12px; overflow:hidden }
.row{ border-bottom:1px solid var(--line) }
.row:last-child{ border-bottom:0 }
```

One border around the group, hairlines between rows, no gaps, no per-card shadows or radii.

### D6 — Link copy and layout

- `"Read a full pack free, no email needed."` → **`Read a full pack free — no email needed`**. Em dash, no trailing full stop. Links never end in a full stop.
- The arrow must not wrap to its own line. Either drop it (the mockup has no arrow on this link) or bind it with `white-space:nowrap` on the final word plus the glyph.

### D7 — Reverted strings

- Market tag: `US · CA market` → **`US · CA`**
- Kill-cause labels must use the canonical names from the kill-log mockup, not renamed variants. Currently showing "Ungrounded / Durability / Affordability". Required: **Scored below the bar overall · Incumbents already own the space · The defensibility claim was not evidence-backed · It did not survive the adversarial pass · The value would not last · The payer cannot actually pay**.
- The band's closing line "Every kill published with its reason — read the kill log" is being clipped at the card edge. It must render in full.

### D8 — Sections not in the mockup

"Based on your browsing / Same mechanics as the last pack you opened" is not in `mockups/index.html`. Either remove it, or if it is a deliberate retained feature, restyle it to the mockup's section grammar: `h2.sec` heading, `.lede` subline, `.rows` container. It currently uses its own type scale.

---

## WHAT WAS DONE CORRECTLY — DO NOT REGRESS IT

- Pack count is now 74 on every page, from one source. Keep it that way.
- The engagement band on the kill log ("624 — The check that kills most ideas is not the one people expect") matches the mockup and uses real data. It is the reference example of a correctly ported component. Build the rest to that standard.

---

## VERIFICATION — RUN AND REPORT

Do not report done until every line below is confirmed with evidence.

1. `grep -c "cited sources behind it"` across the codebase → **0**
2. `grep -c "the price back in month one"` in card/row components → **0**
3. `grep -c "no email needed\."` → **0** (no trailing full stop)
4. `grep "6 in 100"` in the homepage template → **found**
5. `grep "ratio\b"` in homepage CSS → **found**, and the rendered page contains exactly 100 `<i>` in `.ratio`, of which 6 have `.alive`
6. Homepage H1 string equals `Business ideas with the research already done.` exactly
7. No description in any API response is shorter than its stored value
8. Screenshot every page at **390px** and **1280px**. On each, confirm: no text crosses a card edge, no description ends mid-word, every pack row sits inside one bordered container with hairline dividers
9. Paste the rendered HTML of one catalogue row and one hero figure so both can be compared against the mockup

If any check fails, fix it before reporting.
