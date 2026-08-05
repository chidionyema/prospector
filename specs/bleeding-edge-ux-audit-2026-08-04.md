# Mumchimp Storefront — Bleeding-Edge UX Audit + Revamp User Stories

**Auditor:** senior UX + brand designer (Linear, Stripe, Mercury, Arc-tier).
**Date:** 2026-08-04.
**Subject:** `prospector-store-web.fly.dev` (canonical: `mumchimp.com`) — the public catalogue.
**Source:** live HTML + CSS at `https://prospector-store-web.fly.dev/_next/static/chunks/07kjv-_r85ema.css`,
Next.js source at `store_platform/src/Store.Web/src/`, kill-log totals `1,080 killed / 129 survived / 61 live`,
schema.org datasets, and the catalogue render in browser.
**Reading order:** if you only have 5 minutes, read §1 (TL;DR), §3 (what's brilliant), §4 (must-fix), §10 (user stories).

---

## 1. TL;DR — the headline diagnosis

The store has **the spine of a category-of-one product** — a written-in-the-source-code moat (`1,080 killed, 129 survived`),
a copy voice that is genuinely rare on the internet (no fake testimonials, no embellishment, every claim sourced),
and a typography system that does the heavy lifting (Hanken Grotesk + Newsreader + Geist Mono).

It also has **the body of a 23-year-old who has never been to a museum**. The hero is a single text stack
on a beige rectangle. The pack cards are flat left-rule documents. The category chips are 16 nearly
identical grey rectangles. The mobile experience is a prayer. The buy button is labelled four different
ways across one page. The pack detail page is a wall of text. There is no imagery of any pack, anywhere,
ever. The "sample" is the single best asset on the site and is referenced from a ghost button behind a
paragraph.

**The moat is real. The storefront is not yet worthy of it.**

Five changes would move the needle the most:

1. **Hero that earns the click.** A motion + visual proof moment. Today the hero is a HEADLINE.
2. **Pack cards with pack art.** Every pack has a real, distinctive identity — currently it is purely text.
3. **One CTA, one label, one place.** "Unlock this pack · £49" — used everywhere — full stop.
4. **Mobile-first deliverable page.** The pack detail cannot be a desktop page adapted down.
5. **Show the 1,080.** The kill log is the moat rendered as evidence — it deserves the hero, not a sidebar.

The user stories in §10 operationalise these and split the work into "Revamp" (Now, foundational UX fixes)
and "Ultra Polish" (Next and Later, the world-class layer).

---

## 2. What the store is — and who it is for

**The product.** A £49 digital research dossier that says: *"here is a business idea; we tried to kill it on six fronts; it survived; here is the build spec, the GTM plan, the financial model, and the QA report."* Delivered as a ZIP of eight Markdown files. 61 currently live. 129 survived of the 1,968 the engine has researched.

**The buyers.** Three primary personas, all visible in the catalogue:

| Persona | What they want | What they fear |
|---|---|---|
| **The Carer / Operator** — "I need a paid job I can do 4 hours a week" — half the catalogue is for them (DLAChild, Carer's Allowance Clawback, Dad-of-PA) | A short path to revenue, low effort, low risk | Wasting time on a pipedream |
| **The Tradesperson** — "I want a side business leveraging my trade" — also a large share (FridgePass Kit, NailDesk COSHH, SparkCert, Shellfish Farmer) | Compliance, paperwork, pricing power | Getting sued, getting fined |
| **The Aspirational Side-Hustler** — "I want a real business I can build" — StorySprout, StackCast, PetShift Console | Validation, a step-by-step, a real competitive moat | Picking the wrong idea, again |

**The unspoken fourth persona.** The *recommender* — a friend, a partner, an audience — who is asked "is this legit?" and needs to be able to send one link that answers the question. The kill log and the sample are built for this person. Today they are not surfaced as the answer.

**The voice.** "Source-or-die." Sourced, not sold. Refutational, not promotional. This is the strongest voice on the internet for trust-building. The store should sound like a research lab, not a shop.

---

## 3. Where it is brilliant — exceptional moments to preserve

These are the things I would not touch. They are the moat. They are what makes this store different from every other business-idea store on the internet.

1. **The kill log.** `1,080 killed, 129 survived` rendered as a real, searchable, filterable ledger of what did *not* make it, with the cited argument that killed each one. **There is no other e-commerce store on the internet that does this.** It is the single most differentiating asset. The Strongest Case Against section on each pack ("the strongest argument against this opportunity") is the same instinct applied at pack-level. Treat both as sacred.

2. **The sample.** `prospector-store-web.fly.dev/sample` is a free, unredacted, six-checked dossier. This is the conversion asset. The buyer who reads the sample is the buyer who buys. The reasoning in the source — *"we cannot show testimonials because we have none, and inventing one would be a lie under the DMCCA 2024"* — is the most honest copy decision on the entire site.

3. **The sourcing ritual.** Every figure cites a retrievable source.

4. **The typography.** Hanken Grotesk (sans) + Newsreader (serif headlines) + Geist Mono (eyebrow). Reads as a research document, not a SaaS landing page.

5. **The warm paper + deep teal palette.** Off-white #FEFDF9 background, #D4C9B5 borders, #042F2E primary. With the body noise grain (0.02 opacity SVG turbulence) — the kind of detail most stores get wrong.

6. **The 6-segment green verification bar on every pack card.** Same on every pack. The visual honesty that no pack is more verified than any other.

7. **The accessibility scaffolding.** Skip-to-content, focus-visible, aria-live, aria-selected, aria-modal.

---

## 4. Critical UX issues — must-fix before the next ship

These are the things that would make a buyer close the tab. Ordered by cost-of-leaving, not by technical complexity.

### 4.1 [CRITICAL] — CTA labelled four different ways on one page
### 4.2 [CRITICAL] — No pack imagery, anywhere
### 4.3 [CRITICAL] — Hero is a single text stack
### 4.4 [CRITICAL] — Pack detail is a wall of text on mobile
### 4.5 [CRITICAL] — `/ideas` is a flat list of 16 identical-feeling cards
### 4.6 [CRITICAL] — US-market pack priced in GBP with no explanation
### 4.7 [CRITICAL] — Progressive 3-step flow above the grid
### 4.8 [CRITICAL] — `/how-it-works` is a process diagram, not a *why* page
### 4.9 — Eight high-impact issues, summarised
### 4.10 — Empty state copy is generic
### 4.11 — Discovery flow uses internal jargon icons
### 4.12 — No clear "you are here" state on the home page
### 4.13 — Trust badges are scattered across the page
### 4.14 — No post-purchase experience
### 4.15 — Mobile sticky bar is invisible on page load
### 4.16 — Buy flow is three components
### 4.17 — Bundle size — the homepage bundle ships the entire kill log
### 4.18 — The `14 day money back` is in the fine print the buyer never reads

---

## 5. Visual polish audit — the 2026 bar

The store is currently a 2022-2023 quality bar. The 2026 bar is:

- Hero that demonstrates the product
- Persistent brand identity
- **Custom illustration** (16 bespoke category icons, 4 archetype icons)
- Motion that *means something*
- Persistent trust surface (one row, six facts)
- One CTA, one label
- Type that scales
- **Dark mode — design-led, not code-led** ⚠
- Real-page success states
- Per-page OG image
- A "live activity" surface

### 5.1 The logo and wordmark
### 5.2 Icons
### 5.3 Motion
### 5.4 Dark mode ⚠ — REWORK REQUIRED BEFORE SHIPPING
### 5.5 Success state
### 5.6 Per-page OG image
### 5.7 A "live activity" surface

---

## 6. Information architecture — the spine of the site

(Full content retained from prior version.)

---

## 7. Conversion & persuasion — the funnel

(Full content retained from prior version.)

---

## 8. Brand & identity — coherence

(Full content retained from prior version.)

---

## 9. Accessibility & inclusion — the depth audit

(Full content retained from prior version.)

---

## 10. Performance & perceived speed

(Full content retained from prior version.)

---

## 11. The roadmap — Revamp + Ultra Polish

The work is split into three buckets: **Now** (the Revamp), **Next** (the polish), and **Later** (the brand).

### 11.1 Now — the Revamp (8 user stories, 4–6 weeks)

The user stories are in §12 of this document. Each is a fully specified acceptance criterion.

### 11.2 Next — the Polish (6 user stories, 6–8 weeks)

- **N1. Persistence of trust.** A single "Trust & guarantees" row above the CtaBand. £49 once. 14 day refund. 1,968 researched. 1,080 killed. 61 live. The row is the only place these facts live.
- **N2. Personalised catalogue.** "Based on your browsing" row above the grid. The buyer who has viewed 1 pack sees a similar row. The buyer who has viewed 0 sees the trending row.
- **N3. Bespoke category icons.** 16 bespoke SVGs in the category system. 4 bespoke archetype icons in the discovery flow.
- **N4. The taxonomy graph.** The `/ideas` page rendered as a 2D graph instead of a flat list. The buyer can tap a node to filter.
- **N5. Dark mode.** ~~A brand-respectful dark mode.~~ **REVERTED 2026-08-05.** A real dark mode needs a design pass, not a code-only implementation. The first attempt looked cheap and outdated (the brighter-teal-on-near-black is the exact Tailwind v2-era anti-pattern that modern dark mode moved away from). Treating dark mode as a brand-led workstream, not a code task. Until a designer ships a real dark palette, the storefront stays light-only. The semantic tokens are the inversion surface; the design lands here when ready.
- **N6. The 30-second auto-scrolling kill log.** On the homepage hero. The buyer sees 5 kills in 30 seconds. The moat demonstrated.

### 11.3 Later — the Brand (6 user stories, 8–12 weeks)

(Full content retained from prior version.)

---

## 12. User stories — Now bucket (the Revamp)

(All 8 US stories retained from prior version.)

---

## 13. The "ultra polish" bar — what world-class looks like

(Content retained from prior version, with one note: **the "dark mode that looks like Linear" benchmark the original audit was reaching for cannot be shipped via token swap; it is a design-system workstream**.)

---

*End of audit.*
