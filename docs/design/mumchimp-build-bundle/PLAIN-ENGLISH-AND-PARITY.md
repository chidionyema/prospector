# Plain English & Pixel Parity

Two problems, two mechanisms. Part 1 stops the site sounding like it was written for people who already work in this world. Part 2 stops the built site drifting from the approved mockups.

---

# PART 1 — THE PLAIN ENGLISH SWEEP

## The rule

**Site chrome and marketing copy: only words a reader would use with a friend in a pub.**

Inside a pack, a term the buyer uses daily is allowed — a cannabis SaaS founder knows what a schema is, a bricklayer does not. The test is never "is this the correct term", it is **"does the person this page is for already say this word?"**

If a word needs a glossary, needs a definition on first use, or would make a reader feel they walked into the wrong meeting, it is banned.

## Banned, with replacements

### Words I introduced — my fault, ban them

| Banned | Use instead |
|---|---|
| shelf, on the shelf | **available now**, **for sale**, **in the catalogue** |
| collection, collections | **types**, **what it suits**, or just name it: *Good for developers* |
| artefact | **file**, **document** |
| surface (as a noun) | **page** |
| grammar (as in "section grammar") | (internal only — never user-facing) |

### Words already live on your site

| Banned | Where it appears | Use instead |
|---|---|---|
| beachhead | Document 07 | **the first group to sell to** |
| non-goals for v1 | Document 06 | **what to leave out at first** |
| on what stack | Document 06 | **what to build it with** |
| the machine-readable record / structured data | File list | **a version other software can read** |
| claim-checked | Document 11 | **checked against the sources** |
| drip feed | Pack page | **you get everything at once** |
| dossier | Sample pack title | **pack**, **file** |
| GTM plan | Meta description | **how you get your first customers** |
| unit economics | Meta description, pack page | **the numbers** |
| LTV : CAC | Pack page | **you earn back 3.7× what a customer costs to win** |
| adversarial pass | How it works, kill log | **a second round of checks** |
| the engine | Meta description | **the checks** |
| productised service | Category name | **fixed-price service** |
| vertical software | Category name | **software for one trade** |
| marketplace and broker | Category name | **connecting two sides of a deal** |
| operators | Category name | **people who run things well** |
| micro-hedge | Pack description | **small cover that pays out if prices jump** |
| parametric bond | Pack description | **pays out automatically when it happens** |
| documentary research | Pricing page | **desk research** (already used elsewhere — pick one) |
| cold-start problem | Category description | **getting the first people on both sides** |

### Generic startup fog — ban outright, no replacement needed

leverage · seamless · robust · solution · platform (unless it literally means Uber or Deliveroo) · onboarding · utilise · empower · unlock · supercharge · game-changing · best-in-class · frictionless · scalable · bespoke · curated · journey · space (as in "the space") · ecosystem · learnings · deliverable · touchpoint · at scale · deep dive · circle back

### Grammar and punctuation bans

- No sentence starting with **"Not"** — "Not a mock-up and not a summary" reads robotic
- No **em-dash-heavy** stacking: one per paragraph maximum
- No **full stop at the end of a link or button**
- No **Title Case** headings
- No **"we're excited to"**, no **"simply"**, no **"just"** as a softener
- No **exclamation marks**, anywhere

## The naming problem you flagged

You have two different taxonomies and I called the second one "Collections", which you're right to reject. Plain-English options for `/ideas`:

1. **Good for** — *Good for developers*, *Good for evenings*, *Good for people who can sell*. Reads as a sentence, needs no explanation.
2. **Ways in** — friendly, but slightly vague.
3. **Browse by what you're good at** — long as a nav label, perfect as a page heading.

My pick: nav label **"Good for"**, page heading **"Find one that suits how you work."** The subject taxonomy keeps the word **Categories**, which everyone understands.

And for "shelf": the honest replacement in your closing line is —

> *A claim without a source dies before it ever goes on sale.*

## The sweep, as a task

1. `grep -ri` every banned word across templates, pack documents, meta tags and email templates
2. Replace using the table; where no replacement is listed, rewrite the sentence
3. Add the list to your pack-generation prompt so new packs never reintroduce them
4. Re-run the grep as a CI check — a banned word fails the build

---

# PART 2 — HOW TO GUARANTEE PIXEL PARITY

The gap you're seeing has one cause: **the agent is writing its own CSS from a description.** No amount of prose will fix that, because prose is interpretable and CSS is not.

## The mechanism

### Step 1 — Ship my stylesheet, don't recreate it

`mumchimp.css` (beside this file) is every rule from the approved mockups, extracted into one production stylesheet. Drop it in. Import it. **The agent writes no CSS at all** except page-level layout that doesn't exist in it.

Rule for the agent: *if a style you need isn't in `mumchimp.css`, stop and ask — do not invent it.*

### Step 2 — Templates copy markup, they don't reinterpret it

For every component, open the mockup, copy the element structure and class names exactly, and bind data into the slots. Same tags, same nesting, same classes. A `.row` inside a `.rows` — not a `.card` inside a `.grid` because the developer preferred it.

### Step 3 — A structural diff test

For each key component, snapshot the mockup's markup and assert the built markup matches on tags and classes (ignoring text):

```js
// tests/parity.spec.js
const strip = html => html
  .replace(/>[^<]*</g, '><')                 // drop text
  .replace(/\s(href|src|id|aria-label)="[^"]*"/g,'') // drop instance data
  .replace(/\s+/g,' ').trim();

test('catalogue row matches the mockup', async ({page}) => {
  await page.goto('/');
  const built = await page.locator('.rows .row').first().innerHTML();
  expect(strip(built)).toBe(strip(MOCKUP_ROW));   // MOCKUP_ROW read from mockups/index.html
});
```

Run it for: catalogue row, hero figure, featured card, check row, kill row, buy box, header, footer. Eight assertions, and drift becomes a failing build rather than a screenshot you notice a week later.

### Step 4 — Visual regression against the mockup

```js
for (const w of [390, 1280]) {
  await page.setViewportSize({width:w, height:1200});
  await page.goto('file://mockups/index.html');  const a = await page.screenshot({fullPage:true});
  await page.goto('http://localhost:3000/');     const b = await page.screenshot({fullPage:true});
  expect(diff(a,b)).toBeLessThan(0.02);          // 2% tolerance for real data differing
}
```

Real content will never match the mockup byte for byte, so 2% is the working threshold. What it catches reliably is the things that have actually gone wrong: missing sections, wrong card model, changed type scale, absent signature devices.

### Step 5 — One data source, one copy source

Every string that appears on more than one page comes from a constants file, not from a template. That includes the H1, the CTA labels, the proof-line format and the six check names. A rewritten headline then becomes a one-line diff in a file someone has to justify, rather than a quiet edit inside a template.

## What to tell the agent

> `mumchimp.css` in this bundle is the complete stylesheet for the site. Import it unchanged. Do not write CSS. Do not rename classes. Do not "tidy" it. If a style you need is not in that file, stop and ask.
>
> For every component, open the matching file in `/mockups`, copy the element structure and class names exactly, and bind data into it. Your markup must match the mockup's markup on tags and classes — a test asserts this.
>
> Then run the parity tests and the visual regression at 390px and 1280px. Report the diff percentage per page. Do not report done while any page exceeds 2%.

## Why this works when prose didn't

The brief asked for the right outcome and trusted the agent to reach it. This makes the outcome mechanically checkable: the stylesheet is copied not written, the markup is asserted not described, and the screenshots are compared not eyeballed. Drift stops being a matter of judgement.
