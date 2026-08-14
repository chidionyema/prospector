# Designer brief: mumchimp.com

Written 2026-08-14 for a designer joining cold. Read it once end to end before you open the site.
It is written to tell you what you are walking into, not to sell you the job.

---

## 1. The business, and who buys

Mumchimp sells researched business ideas. Each one is a "pack": a single opportunity worked up into
eight plain documents covering what the business does, who pays for it, what the numbers look like,
how you would start, and what we could not verify. The rule the whole company runs on is that every
factual claim in a pack either cites a retrievable source or is marked unverifiable, and nothing
unsourced ever ships. Ideas are generated and then put through six checks (is the pain real, does
the value last, who already does this, can the payer actually pay, can you reach the buyer, is it
legal), and most of them die. The ones that die are published too, with the reason and the evidence,
in a public kill log. Packs are a one-time payment, currently between £29 and £149, priced by how
big the opportunity is rather than by how much writing is in the file. No subscription, no account,
no seat fees. The buyer is a sole trader: someone with a trade, a skill, a redundancy payment or a
spare evening, who is trying to work out what to actually start and who does not want to spend three
weekends checking whether the idea is nonsense. They are not a developer, not a founder in the
venture sense, and not a technical audience. That last sentence is the most consequential line in
this brief and section 4 explains why.

---

## 2. The honest state of the design, and how it got there

The founder's verdict on the live site today, after a full day of fixes, is "still looks crap". His
diagnosis a few hours earlier is the one worth acting on:

> "This isn't cluttered, it's under-designed. It reads as a wireframe someone shipped, not as
> minimalism. Minimal designs fail when the restraint isn't backed by precision. Right now the
> restraint is there and the precision isn't, so it reads as unfinished rather than austere."

And on the homepage specifically: it is "a landing page and a store index welded together".

Here is how it got that way, because the shape of the failure tells you where to start. The site has
been improved by working down critique lists. A list arrives, each item on it is fixed, the list is
closed, another list arrives. Every individual item was a real problem and most of them are genuinely
better now. But nobody has ever stood back and asked what the page is supposed to be. That is the
gap you are being hired to close, and it is why the last few passes have produced a site that is
locally correct and globally unresolved. You are not being brought in to work down a longer list.

What that means practically: the foundations are in better shape than the screen suggests. There is
a real design system, documented at an unusual level of detail, with reasoning attached to almost
every value.

- The type scale is six steps and no more, with weights, line heights and tracking declared on the
  size token so a heading gets its whole treatment from one class. It is a variable face (Switzer,
  self-hosted) so 520 and 560 are real cuts.
- The colour system is a true-neutral zinc ramp with four surface steps, every pair carrying a
  measured WCAG ratio beside it in the file, and a rule that red and green mean killed and survived
  and nothing else. Twelve category hues exist under an explicit rule that hue is decoration and the
  label identifies.
- Radius is 2px everywhere. There are no box shadows; depth is a surface step plus a hairline.

None of that is the problem. The problem is composition and hierarchy: what sits next to what, how
much space separates them, what the eye is meant to do first, second and third, and which of the
three or four visual languages currently on the homepage is the real one. Sound tokens assembled
without a composition read exactly as this site reads, which is as a wireframe with good defaults.

You should also know that a critique from 2026-08-14 was written up as a work order and has only
partly been executed. It lives in `docs/SITE_SPEC_PROGRAM.md` under "v5, 2026-08-14" and names, among
other things: an orphaned teal in the logo that nothing else on the page picks up; roughly a full
screen of dead air in the middle of the homepage; two calls to action at opposite extremes with no
middle tier; headline tracking very tight while body copy is loose, so the two blocks read as coming
from different sites. Read it. Do not treat it as your task list. It is evidence of what a careful
eye saw, gathered before anyone asked the question in section 4.

### Already fixed in the last day, so you do not re-diagnose them

All in `store_platform/src/Store.Web`:

- The header is opaque. Content no longer ghosts through it as it scrolls under.
- The mobile menu button lost the redundant word "Menu" beside the hamburger.
- "Catalogue" is gone from the nav; the wordmark already linked to the same place.
- Inline links are on one treatment, with the underline offset raised so it stops cutting descenders.
- Five full-bleed hairline dividers are gone, replaced by vertical spacing.
- The primary call to action is intrinsic width and flush left, not a full-width slab with a centred
  label.
- The hero display size went back from 72px to the spec's own 48px, because 72px was approved from a
  specimen of two words and the real headline is eight words long and wrapped to three lines.

In flight and not yet confirmed at the time of writing: removing the black cover plate from each pack
card, reconciling three conflicting counts on the shelf, cutting duplicate calls to action and a
repeated kill count down to one each, and merging two email capture forms into one.

---

## 3. The question you are actually being hired to answer

**What is the homepage?**

Right now it is a landing page and a store index welded together. It opens with a headline and a
proposition, the way a marketing page does, and then partway down it becomes a shelf of products,
the way a shop does. Neither half is committed to, so the page argues with itself: the hero wants
the first screen, the shelf wants the first screen, and the compromise gives the visitor a wall of
headline followed by an apologetic row of cards.

There are three defensible answers and we do not have a preference, only a requirement that you pick
one and follow it all the way through.

1. **It is a shop.** The shelf is the first thing you see. The proposition is carried by the products
   themselves and by a short, dense band above them. Everything explanatory moves to the pages that
   already exist for it.
2. **It is a landing page.** It sells the method, and the shelf is a curated three or four packs with
   a route into the catalogue. The catalogue becomes the real shop and gets the design attention the
   homepage currently absorbs.
3. **It legitimately does both**, in which case you have to show the mechanism that makes it one page
   rather than two stacked ones, and defend it. This is a real answer, but it is the hardest, and
   "both" without a mechanism is what the page already is.

What follows from the answer is most of the work: the hierarchy of the first screen, whether the
hero survives, what a pack card has to carry (a shop card and a landing-page card are not the same
object), how the catalogue relates to the homepage, and where the kill log sits, given that it is the
most persuasive thing the business owns and is currently a page you have to go looking for.

Answer this first, in whatever form you work in. Do not begin by restyling components.

---

## 4. The constraints that are real

**The buyer is a sole trader, and the register must change to match.** This is a founder decision
taken on 2026-08-14 and it explicitly overrides parts of his own spec, specifically §3 (design
system) and §5.2 (vocabulary). The site currently speaks in developer-tools register: "the kill log",
"the engine", monospace facet chips, verdict glyph strips, a dark instrument panel, and a product
that arrives as Markdown in a zip with an ASCII tree in the index. A developer reads that as rigour.
A sole trader reads it as software they are not qualified to buy. The subject matter is not the
mismatch and the sourcing discipline is not the mismatch; the costume is. In particular, the existing
spec makes monospace a semantic device ("grotesk means a human wrote it, monospace means the engine
produced it"). It is a genuinely good idea and it is also the single largest contributor to the
terminal feel. Deciding what happens to it is yours. Deciding to keep it unchanged by default is not.

**British English throughout.** Catalogue, not catalog. There is an existing house style you should
follow in anything you write: plain, precise, warm, no jargon, answer first, say each thing once
across the whole site. The founder's own bans include em dashes in prose.

**No stock imagery, no decorative icons.** This is one line of the site spec, quoted in full:
"Restraint + real data + zero latency. No stock imagery, no decorative icons, every visual is
earned" (`docs/SITE_SPEC_PROGRAM.md:28`). That is the whole of the rule as the founder wrote it.

Everything that has been built on top of it was written by the engineers, not by him, and you
should know which is which. The argument in the code is that a business whose proposition is that
every claim is sourced cannot illustrate itself with a purchased photograph of a stranger at a
laptop, so each pack's art is computed from that pack's own data (`src/lib/packMark.ts:5`,
`src/components/ui/Logo.tsx:61`). That reasoning is defensible and it also hardened, over several
sessions, into a flat ban nobody actually issued.

The result is visible on the shelf right now: the computed mark encodes almost nothing, so the
rule was obeyed and the meaning was lost. The cards read as empty. So treat "every visual is
earned" as the constraint and the flat ban as a previous team's reading of it. If you can defend
photography or illustration that is genuinely about a specific pack rather than about business in
general, make that case to the founder. Finding imagery that is derived from each pack and is not
a decorative bar chart is one of the two hardest problems in this job, and the current answer to
it is not working.

**The deliverable is in scope.** A pack is currently eight Markdown files in a zip. That is what the
buyer pays between £29 and £149 for and it is the last thing they see. Its presentation is explicitly
part of your remit: what the reader opens first, what a document looks like, how a cited claim is
shown, how the "we could not verify this" marks read to someone who is not used to being told what a
document does not know. Changing the format itself (a rendered page, a PDF, something in the browser)
is a proposal you are allowed to make.

**Numbers on the site come from live data.** Pack counts, kill counts, price ranges and category
counts are all rendered from the running system, and there is a standing rule that each number has
exactly one source. If you mock a screen, treat every figure in it as a placeholder, and never design
a layout that only works at one specific count.

**Accessibility is a floor, not a goal.** Every colour pair in the token file carries a measured
contrast ratio. Keep that practice: if you change a value, measure it and record the ratio next to it.

---

## 5. What is yours, and what is not

Yours, without asking:

- The homepage, entirely, starting from the question in section 3.
- The catalogue, its cards, its filtering and its search.
- The pack page and the free sample page.
- Hierarchy, spacing, composition and layout everywhere.
- The register: how formal, how warm, how technical the site sounds and looks.
- Typography, including the faces, if you can argue the change. The scale is documented, not sacred.
- The colour system above the constraints below, including the decision on whether the teal in the
  logo becomes a real accent system or is dropped for committed monochrome. Straddling it is the one
  option that is closed.
- Iconography and the verdict marks.
- The pack deliverable, as set out above.

Not yours, and why:

- **The sourcing rules themselves.** Every claim cites a source or is marked unverifiable, and killed
  ideas are published with their reasons. That is the product. You can change how it is expressed and
  how loudly; you cannot remove or soften the fact of it.
- **"Every visual is earned."** The spec line, not the flat ban the code built on top of it. A visual
  has to carry a fact about the thing it sits next to. What satisfies that is yours to argue; see the
  imagery note above, including the case for reopening photography.
- **The one-time price and the accountless checkout.** No subscription, no login, no gate before
  someone can read the free sample. These are business decisions and they constrain the flows you
  design.
- **Live counts as the source of numbers.** No hard-coded figures in shipped work.
- **The one-payment, no-upsell promise on the pricing page.** The copy can be rewritten; the promise
  stays.
- **British English.**

Everything else in the spec is a decision, and decisions can be overridden. The spec has been
overridden by the founder at least four times already and each override is recorded in the document
with its date and reasoning. Do the same: if you overturn something, say what you are overturning and
why, in writing. The one thing the project cannot absorb is a change whose reasoning is lost, because
the next person will helpfully change it back.

---

## 6. What you get on day one

- **`docs/SITE_SPEC_PROGRAM.md`.** The full spec and its status ledger. Roughly a thousand lines. Read
  §3 (design system), the page-by-page work orders in §6, and the "v5, 2026-08-14" section in full.
  Skim the ledger at the top to see what is claimed done. Treat the ledger as claims with receipts
  attached, not as gospel; it has been wrong in both directions before and says so.
- **`store_platform/src/Store.Web/src/styles/tokens.css`.** Every token, with long comment blocks
  recording why each value is what it is, what it replaced, and what broke last time. Read the
  comments. They are the most useful document in the repository and they will stop you re-making
  three or four decisions that have already been paid for.
- **The live site**, mumchimp.com, which is the thing being judged.
- **This brief.**

The stack is Next.js with Tailwind v4. One practical trap, recorded here because it has bitten this
codebase repeatedly: in Tailwind v4 a colour utility whose token is not mapped into the `@theme`
block emits no CSS at all. It fails silently and looks like nothing, not like an error. If you add a
token, map it in the same change.

---

## 7. How the work will be judged

By the founder's own bar, in his words:

> "Minimal designs fail when the restraint isn't backed by precision. Right now the restraint is
> there and the precision isn't, so it reads as unfinished rather than austere."

So: restraint backed by precision. Concretely, that means every vertical gap lands on a declared
spacing scale and none of them is arbitrary; type sits on a consistent optical rhythm rather than one
block being tightly tracked and the next loose; the first screen has one clear job and the eye knows
where to go second; nothing on the page is a placeholder standing in for a decision nobody has taken;
and every element that is present can be justified as carrying meaning rather than filling a slot.
The test is not whether a screenshot looks clean. A wireframe looks clean. The test is whether the
page reads as deliberate at every scale, from the first screen down to the space under a caption.

And there is one prior question you have to answer before any of it counts, which is section 3. If
the homepage still cannot say whether it is a landing page or a shop, the rest is decoration on an
unresolved argument.
