# Mumchimp — Polish Layer

Everything here is additive to `MASTER-BRIEF.md`. None of it changes the design; all of it changes how the site *feels*. Ordered by impact per hour.

---

## 1 · PERCEIVED SPEED

Users don't experience milliseconds, they experience waiting. These remove the waiting rather than shortening it.

### 1.1 Prefetch on intent — highest single win

```js
// Fires ~300ms before the tap completes. By the time the finger lifts, the page is cached.
const seen = new Set();
function warm(href){
  if (!href || seen.has(href) || !href.startsWith('/')) return;
  seen.add(href);
  const l = document.createElement('link');
  l.rel = 'prefetch'; l.href = href; l.as = 'document';
  document.head.appendChild(l);
}
document.addEventListener('pointerenter', e => {
  const a = e.target.closest?.('a[href^="/"]'); if (a) warm(a.getAttribute('href'));
}, {capture:true});
document.addEventListener('touchstart', e => {
  const a = e.target.closest?.('a[href^="/"]'); if (a) warm(a.getAttribute('href'));
}, {capture:true, passive:true});
```

Respect data saving: skip entirely when `navigator.connection?.saveData` is true.

### 1.2 Cross-document view transitions

```css
@view-transition { navigation: auto; }
@media (prefers-reduced-motion: reduce){ @view-transition { navigation: none; } }
```

Catalogue → pack page becomes a continuous movement instead of a white flash. Degrades silently where unsupported.

### 1.3 Don't break bfcache

No `unload` handlers anywhere. Use `pagehide`. Back-button navigation then restores instantly from memory — this is free and routinely destroyed by analytics snippets.

### 1.4 Long lists stay cheap

```css
.row, .klrow { content-visibility:auto; contain-intrinsic-size:auto 150px; }
```

The kill log has hundreds of rows. This stops the browser laying out what nobody has scrolled to. `contain-intrinsic-size` is what keeps the scrollbar honest — omit it and scrolling jumps.

### 1.5 Skeletons match the real thing

A skeleton row must have the same height as the row that replaces it, or you have traded a spinner for a layout shift. Reserve `min-height` on the results container so filtering never moves the page under a thumb.

---

## 2 · TOUCH AND POINTER FEEL

### 2.1 Pressed states — the most-missed detail in web UI

```css
.btn:active, .chip:active, .row:active { transform: scale(.985); }
.btn, .chip, .row { transition: transform .06s ease, background-color .12s ease; }
@media (prefers-reduced-motion: reduce){ * { transition:none !important; transform:none !important } }
```

A control that doesn't acknowledge a press feels like an image of a control.

### 2.2 Kill the tap artefacts

```css
html { -webkit-tap-highlight-color: transparent; }
a, button, .chip, .row { touch-action: manipulation; }
```

`touch-action:manipulation` removes the double-tap-zoom wait. Every tap on the site becomes measurably faster.

### 2.3 Hover effects only where hover exists

```css
@media (hover:hover) and (pointer:fine){
  .row:hover{ background:#FCFCFA }
  .btn:hover{ background:#000 }
}
```

Without this, mobile browsers leave hover states stuck after a tap — that "why is this row still highlighted" feeling.

### 2.4 Sheets and modals

```css
.filter-sheet { overscroll-behavior: contain; }
```

Stops the page behind scrolling when the sheet reaches its end.

### 2.5 Selection and caret carry the brand

```css
::selection { background: var(--brand-tint); color: var(--ink); }
input, textarea { caret-color: var(--brand); }
```

Nobody notices consciously. Everybody notices the default blue.

---

## 3 · TYPOGRAPHIC MICRO-CRAFT

### 3.1 Non-breaking spaces where a break would look wrong

Bind these at render time, not by hand:

- `£19.99` — never break between symbol and figure
- `14 days`, `34 sources`, `17× payback` — number and unit stay together
- `6 in 100` — the whole phrase
- Last two words of any heading — prevents a single-word final line

```js
const nbsp = s => s
  .replace(/(\d)\s(sources|days|packs|documents|checks)/g, '$1\u00a0$2')
  .replace(/\s+(\S+)$/, '\u00a0$1');   // headings only
```

### 3.2 Wrapping

```css
h1, h2, h3 { text-wrap: balance; }
p, li, .lede, .d { text-wrap: pretty; }   /* kills orphans in body copy */
```

### 3.3 Real punctuation

Curly quotes and apostrophes, en dashes in ranges (`4–12 weeks`), em dashes in asides. `'` in "tradesperson's" is a straight quote in most CMS output and it reads cheap next to Inter.

### 3.4 Hyphenation only where measure is tight

```css
@media (max-width:520px){ .d, .lede { hyphens:auto } }
```

Off everywhere else — hyphenated headings look broken.

---

## 4 · FORMS

Your only form is the email box, so it should be perfect.

```html
<input type="email" name="email" autocomplete="email" inputmode="email"
       enterkeyhint="go" spellcheck="false" autocapitalize="off"
       aria-describedby="email-help">
```

- **Validate on blur, never on keystroke.** Telling someone their email is invalid while they're typing it is hostile.
- **Never disable the submit button.** Let them press it and tell them what's wrong — a disabled button gives no reason.
- Errors go **below** the field, tied by `aria-describedby`, in `--warn-t` not red.
- Success replaces the form **in place**. No redirect, no page reload — they were reading something.
- Never autofocus on mobile; it throws up the keyboard and hides the content they came for.

---

## 5 · THE COMMERCE MOMENTS

Most sites polish the shop and abandon the buyer at checkout. These are the highest-value screens you own.

### 5.1 Mobile pack page

The desktop buy box is sticky; the mobile equivalent must be a bottom bar showing price and one button, appearing once the top box scrolls away. Without it the price is unreachable from anywhere on a 5,000-word page.

### 5.2 Before payment

State what happens next, above the button: *"Card details next. The download appears the moment payment clears, and we email the link as well."* Uncertainty at the payment step is the biggest single cause of abandonment, and one sentence removes most of it.

### 5.3 After payment

The post-purchase page is a product surface, not a receipt:

- The download button, large, first
- What's in the folder (the six files, named)
- "Where to start" — one line pointing at `index.html` and `First_Fortnight.html`
- Re-download link that works forever, and a note that it does
- The related pack that shares mechanics

### 5.4 The receipt email

Uses the same tokens, the same wordmark, the same voice. Contains the download link. This is the artefact that sits in their inbox for years.

---

## 6 · SHAREABILITY

### 6.1 Per-pack OG images, generated

Title, price, source count, `6 of 6 survived`, wordmark. Generate at build or on demand from the pack data. Every shared link becomes a small advert carrying your proof, instead of one generic logo card.

### 6.2 Deep-link every check

```html
<div class="checkrow" id="check-4">
  <h3><a href="#check-4" class="anchor">Can the payer actually pay?</a></h3>
```

Give each check a stable anchor and a copy-link button on hover/focus. Your product is arguments-with-sources; a single argument should be quotable on its own. Do the same for each kill-log entry.

### 6.3 Unique, factual `<title>` per page

`Material price cover — 34 sources, survived 6 checks · Mumchimp` beats `Pack · Mumchimp`. Search result text is a design surface.

### 6.4 The whole icon set

`favicon.svg`, `apple-touch-icon.png` (180px), `icon-maskable.png` (512px), and a `site.webmanifest`. A missing apple-touch-icon gives you a screenshot-of-the-page icon when someone adds you to their home screen, which looks broken.

---

## 7 · ACCESSIBILITY THAT READS AS POLISH

- **Focus return.** Close the filter sheet, focus goes back to the button that opened it. Nothing signals sloppiness faster than focus jumping to the top of the document.
- **Announce results**: `aria-live="polite"` on the count, so a filter change is audible.
- `prefers-reduced-transparency` and `prefers-contrast: more` — cheap to honour, and the people who set them notice immediately.
- **Visible focus on dark surfaces**: your ink buttons need a light ring, not `--link` blue on near-black.
- **Text spacing resilience**: the site must survive a user stylesheet at 1.5 line-height and 0.12em letter-spacing without clipping. It's a WCAG criterion and it catches fixed-height buttons.

---

## 8 · MEASUREMENT

- **INP (Interaction to Next Paint)** is the Core Web Vital nobody watches, and your filter chips are exactly where it degrades — every tap recomputing facet counts on the main thread. Measure it with `web-vitals`, budget under 200ms, and debounce the recount.
- **Rage clicks** on non-interactive elements tell you where people expect a control that isn't there. Cheap to log, unusually informative.
- **Scroll depth on the kill log** answers the one open question in the whole strategy: do people actually read the kills?

---

## 9 · THE UNGLAMOROUS THREE

Every list, every async surface, needs all three states designed — not one and two afterthoughts:

- **Empty** — names the cause and offers the single action that fixes it
- **Loading** — same shape as the loaded state
- **Error** — plain language, a retry, and never a stack trace

You have the empty state. Loading and error are almost certainly unbuilt.

**Plus a print stylesheet.** You sell printable PDFs; someone will print the free sample. Hide nav, filters and CTAs, set body to 11pt serif, and print link URLs after the anchor text:

```css
@media print {
  .hdr, .filterbar, .btn, footer nav { display:none }
  a[href^="http"]::after { content:" (" attr(href) ")"; font-size:9pt; color:#555 }
  .card { break-inside: avoid; border:1px solid #ccc }
}
```

Ten lines, and it's precisely on-brand for a research product.
