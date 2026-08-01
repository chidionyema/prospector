# Deferred Stories — Mumchimp Storefront

> Written 2026-08-01 after the heuristic evaluation and five polish PRs (#39–#43).
> Each story was flagged during the audit and deferred for a specific reason —
> design assets, legal review, engine data, or substantive rearchitecture.
> Pick one up by reading the story, resolving its blocker, and opening a new PR.

---

## 1. Hero illustration / dossier mockup

**Status:** Blocked — needs design assets.

**Why deferred.** `pages/index.tsx:831-891` is the hero section — title, one-line pitch, two CTA buttons, and a reassurance line. It's text-only by design (the rationale comments at lines ~817-828 explain the deliberate brevity: the hero was 606px at 1280×720, pushing the first product card below the fold). Adding a visual anchor would help first-time buyers understand what a "vetted blueprint" looks like, but it needs a real asset — a stylized mockup, an isometric dossier graphic, or a blurred pack preview — not a development placeholder.

**What's needed to unblock:**
- A designer to produce one of:
  - An isometric mockup of a dossier (`public/dossier-mockup.png` or `.webp`), ~400px wide, light background
  - A blurred screenshot of a real pack page rendered as a document thumbnail
  - A decorative abstract illustration (data-timeline, six-check diagram, etc.)
- The asset should sit in `public/` and be referenced from the hero via `<img>` or `next/image`.

**Scope:**
- `public/` — new asset file
- `pages/index.tsx` — add the asset to the `SectionBand` hero block, after the CTA buttons or aligned to one side
- `specs/hero-illustration.md` — spec for the placement

**Effort:** 1 day (mostly asset production; the code change is ~10 lines).

**Related:** Critique §2 from the first heuristic evaluation.

---

## 2. Social proof / testimonials

**Status:** Blocked — violates source-or-die invariant.

**Why deferred.** `pages/kill-log.tsx:15-24` documents the project's position explicitly: *"The conventional fix is testimonials, which we cannot honestly show — there are no reviews to quote, and inventing one is both a lie and an offence under the DMCCA 2024 fake-review rules. On a storefront whose entire pitch is source-or-die it would also be self-refuting."*

The kill-log is the honest substitute. If a buyer writes a genuine testimonial (purchaser, verifiable email domain, not solicited with an incentive), it can be added. Until then, do not fabricate.

**What's needed to unblock:**
- A real buyer testimonial — email, name, company, quote, date.
- Confirmation that the buyer consented to publication.
- Store this as a new file `src/data/testimonials.json` with the same source-read pattern as `kill-log.json`.

**Scope:**
- `src/data/testimonials.json` — new
- New component `components/discovery/TestimonialRow.tsx` — renders between catalog rows
- `pages/index.tsx` — insert the row component
- `__tests__/testimonialContract.test.ts` — source-level contract

**Effort:** 1 day once a real testimonial exists. Cannot start without one.

**Related:** Critique §6.

---

## 3. Cookie consent banner (UK GDPR compliance)

**Status:** Blocked — needs legal sign-off.

**Why deferred.** The site uses `localStorage` for the cart (`lib/cart.ts`) and the Matchmaker auto-open flag (PR #42). PECR reg 6(4)(b) exempts storage that is "strictly necessary for a service explicitly requested by the user." The cart qualifies; the Matchmaker flag arguably does too (it enables the matchmaker feature), but a regulator may see it as optional UX convenience. `lib/analytics.ts:10-13` already documents that analytics uses zero storage specifically to stay within the exemption.

A consent banner is a regulatory compliance feature. Implementing one incorrectly (e.g., pre-ticked, no "reject" path, storing consent that isn't honored) is worse than having none. Get an attorney to review before any code is written.

**What's needed to unblock:**
- Legal opinion on whether the Matchmaker auto-open flag (`mumchimp.matchmaker.autoOpened.v1`) needs consent.
- If yes: a spec for the consent flow (opt-in/opt-out, persistence, preference center, cookie policy page).
- If no: document the rationale in `lib/analytics.ts` or create a new `docs/cookie-compliance.md`.

**Scope (if needed):**
- `_app.tsx` — mount `CookieConsent` provider
- New `components/ui/CookieConsent.tsx` — banner + preference center
- `lib/consent.ts` — consent state management
- `pages/privacy.tsx` — update to mention the consent mechanism
- `specs/cookie-consent.md` — implementation spec

**Effort:** 2-3 days once the legal question is resolved. Do not start without the opinion.

---

## 4. Reading time on pack detail

**Status:** Blocked — `PackDetails` has no `wordCount`.

**Why deferred.** The API type `PackDetails` (from `@/lib/api/client`) does not include a word count. Computing one on the frontend would require fetching the pack's Markdown content via a new API call, which is a backend change. A simpler approach: if the API exposes `wordCount` on the pack response, the frontend renders `~{N} min read`.

**What's needed to unblock:**
- API change: add `wordCount: number` to the `GET /catalog/{id}` response.
- OR: add a client-side word-count utility that estimates from `whatYouGet` + `sampleExtract` + `oneLine` + `whoPays` fields already on `PackDetails` (approximate — not as accurate but zero API work).

**Scope:**
- `pages/pack/[id].tsx` — render the estimate near the title or right-rail price area
- `lib/api/client.ts` — add `wordCount` to the `PackDetails` type (if API-driven)
- `__tests__/ultraPolishContract.test.ts` — update the reading-time assertion

**Effort:** 3h (API-driven) or 1h (client-side estimate from existing fields).

---

## 5. Shortlist-for-guests (save / star packs without account)

**Status:** Deferred — substantive feature, not polish.

**Why deferred.** Saving packs to a personal shortlist without creating an account is a genuine UX improvement — buyers who browse 60 packs need a way to narrow to their top 3-5 before deciding. The basket is for purchase, not for comparison. This is a new feature, not a copy change, and needs its own design pass.

Implementation would use `localStorage` (like the cart — `mumchimp.shortlist.v1`) for guests and merge into the account-bound shortlist on sign-in. The "Compare" mode (story 6 below) is a separate downstream feature that depends on the shortlist.

**Scope:**
- New `lib/shortlist.ts` — localStorage-backed state management (like `lib/cart.ts`)
- New `components/discovery/ShortlistButton.tsx` — star / unstar affordance on each PackCard
- New `components/discovery/ShortlistDrawer.tsx` — modal or slide-in showing the shortlist grid
- `pages/index.tsx` — mount the shortlist provider, render the button on each card
- `pages/pack/[id].tsx` — add the star affordance near the title
- `specs/shortlist-for-guests.md` — design spec

**Effort:** 3-4 days. Design decisions (where the shortlist drawer lives, how it transitions to the basket, whether it's a modal or a sidebar) should be settled in the spec before code.

---

## 6. Compare-packs side-by-side

**Status:** Deferred — edge case at <100 items, depends on shortlist (story 5).

**Why deferred.** Comparing 2-3 packs in a table (price, market, payer, time-to-revenue, source count, facets) is a nice power-user feature but an edge case on a 60-item catalogue. Most buyers compare via back-and-forth browser tabs or the basket. The shortlist (story 5) is the prerequisite — compare mode operates on the shortlist, not on the full shelf.

**Scope:**
- New `components/discovery/CompareTable.tsx` — side-by-side comparison grid
- `components/discovery/ShortlistDrawer.tsx` — add "Compare selected" button
- `pages/compare.tsx` — standalone compare page (or inline modal)
- `specs/compare-packs.md` — design spec

**Effort:** 4-5 days, blocked until shortlist ships.

---

## 7. "Risk Tolerance" facet

**Status:** Blocked — not in the engine's data model.

**Why deferred.** The heuristic critique proposed a "My Risk Tolerance" filter (Low / High / Guaranteed). No pack data carries this — the closest existing facets are `commitment` (time, not risk) and `payer_solvency` (whether the target payer can pay, not the buyer's risk tolerance). Adding this would require the engine to produce a new `risk_tolerance` field and backfill 60+ packs. That's a multi-week engine story, not a UI change.

**What's needed to unblock:**
- Engine change: add `risk_tolerance` to the scoring pipeline.
- Data backfill: re-vet every pack against the new facet.
- API change: expose `risk_tolerance` on the catalogue response.

**Scope (frontend only, after backend is done):**
- `lib/facets.ts` — add `risk_tolerance` to `FacetKind`
- `components/discovery/FacetBar.tsx` — add the facet group
- `components/discovery/Matchmaker.tsx` — add Q4 ("My Risk Tolerance") to the router
- `__tests__/facets.test.ts` — add assertions

**Effort:** Backend: 2-3 weeks. Frontend: 1 day.

---

## 8. Anti-search hero rebuild (Mad-Libs sentence)

**Status:** Deferred — UX redesign, not polish.

**Why deferred.** The proposal from the second heuristic evaluation — replace the hero's static headline with a dynamic "I have [Time] and [Skills]. Show me what works." Mad-Libs sentence — is a compelling UX concept but a significant rework of the page's entry point. It needs:
- A UX research pass (does this actually convert better?)
- A data pass (which facets map to the Mad-Libs blanks?)
- A motion design pass (the countdown from 60 → N → 3 needs to feel sharp)

The Matchmaker promotion in PR #42 (auto-open on first visit, "Find my fit" trigger, dynamic count) captures ~70% of this proposal without the hero rebuild. Start there before redesigning the hero.

**What's needed to unblock:**
- UX research or A/B test plan
- Answer: which 2-3 facets are the Mad-Libs blanks? (Proposal: Time + Skills, adding risk_tolerance only if story 7 ships)
- Motion spec: does the tick-down animate? Fade? Stagger?

**Scope:**
- `pages/index.tsx` — hero section rewrite (60-80 lines)
- New `components/discovery/ConstraintSentence.tsx` — the dynamic Mad-Libs block
- `specs/anti-search-hero.md` — full design spec

**Effort:** 3-4 days after UX research. Blocked by stories 7 (risk_tolerance) and the research pass.

---

## 9. "You might also like" upsell on /orders/success

**Status:** Deferred — cross-sell feature.

**Why deferred.** The current `/orders/success` page gives the buyer their download link, a permanent-link backup, and "Browse more packs" / "Back to pack" buttons. Adding "Packs similar to the one you bought" is a cross-sell that could feel intrusive ("you just paid £49 and we're already asking for more"). Deferred until there are enough survival metrics or customer feedback to justify it.

If implemented, the recommendation would key on the same `similarPacks` function already used in `SimilarPacks.tsx` (mechanism-keyed, not sector-keyed), so the engine is ready.

**Scope:**
- `pages/orders/success.tsx` — add a similar-packs row below the download button
- `lib/discovery.ts` — `similarPacks` already exists, just call it
- `specs/upsell-success.md` — small spec

**Effort:** 3h. Low effort, but gated on product decision.

---

## 10. SEO landing page richness (`/ideas/[slug]`)

**Status:** Deferred — content / writing job.

**Why deferred.** The `/ideas/[slug]` pages are topical landing pages that exist to capture search traffic. They render a grid of matching packs with sibling cross-links — but no introductory prose about the niche. A page like `/ideas/b2b-business-ideas` would rank better with 150 words explaining the category's unique challenges, typical buyer profile, and how the engine vets B2B ideas specifically. That's a writing job, not a code job.

The code infrastructure (`getServerSideProps`, JSON-LD, `PackGrid`) is already solid. Content is the blocker.

**What's needed to unblock:**
- 150-200 words of prose per landing page category (current count: varies by catalogue). The content should name the niche, describe the typical buyer, and cite 1-2 kill-log entries as proof the engine has researched it.

**Scope:**
- `pages/ideas/[slug].tsx` — add a `<div className="prose">` block above `<PackGrid>`
- `specs/seo-landing-content.md` — content brief

**Effort:** 2 days (mostly writing). Code change: ~15 lines.

---

## 11. Horizontal-swipe carousel on mobile

**Status:** **Not recommended.** Documented for completeness.

**Why deferred and why not recommended.** Proposed in the first heuristic evaluation as a Tinder-like card-swipe experience for mobile. Strongly not recommended for a 60-item marketplace catalogue:
- Buyers compare prices, facets, and titles across cards — swipe prevents comparison.
- Going back to a previous card requires reverse-swipe, which is undiscoverable.
- No serious SaaS marketplace (Stripe, Linear, Notion, ProductHunt, App Store) uses horizontal swipe for the main catalogue.

If you still want it, treat it as an A/B test, not a default. The current mobile layout (`grid-cols-1`, vertical scroll, facet disclosure button) works.

**Scope (if forced):**
- `pages/index.tsx` — replace the grid with a swipeable container on mobile
- CSS: `overflow-x: scroll; scroll-snap-type: x mandatory;`
- `specs/mobile-swipe-catalogue.md`

**Effort:** 2-3 days (including the accessibility work to make swipe keyboard-accessible).

---

## 12. Multi-language support

**Status:** Deferred — market decision.

**Why deferred.** The site is UK-only (GBP pricing, UK companies law, UK GDPR, England & Wales governing law). The `/markets` infrastructure exists (`config.yaml` US market is open via probe readiness), but the storefront copy is all English.

Multi-language would need:
- An i18n framework (next-intl or similar)
- Translated copy for all 18 pages + components
- Market-aware pricing/language switching

Deferred until a non-UK market is live and generating revenue.

---

## 13. Account deletion (UK GDPR Article 17)

**Status:** Deferred — needs API support.

**Why deferred.** Under UK GDPR, users have the right to erasure of their personal data. The account page (`pages/account/index.tsx`) has no "Delete account" affordance. Adding one requires:
- An API endpoint (`DELETE /account`) that soft-deletes the user record, anonymizes order history, and retains only what is legally required (financial records for HMRC — 6 years).
- An audit trail (who requested deletion, when, what was erased).
- Confirmation UI (double-confirm modal with "this cannot be undone").

The frontend is the easy part. The backend is 3-5 days of work across `Store.Api` + database migrations.

**Scope (frontend only):**
- `components/account/AccountPanel.tsx` — add "Delete account" button in the Security tab
- `components/account/DeleteAccountModal.tsx` — confirmation dialog
- `lib/api/auth.ts` — call the `DELETE /account` endpoint

**Effort:** Frontend: 1 day. Backend: 3-5 days. Blocked until the API endpoint exists.

---

## 14. Confirmation email on purchase

**Status:** Blocked — Mailjet API secrets not configured.

**Why deferred.** `src/pages/orders/success.tsx:175-179` comment: *"No confirmation email is sent while MAILJET_API_KEY / MAILJET_API_SECRET are unset in production."* The `Store.Api` has the email sender infrastructure (`MailjetEmailSender.cs`), but the env vars are not populated.

The success page compensates by emphasizing the permanent link as the buyer's sole recovery mechanism. Once Mailjet is configured, the page can restore the "we emailed you a copy" line.

**What's needed to unblock:**
- `MAILJET_API_KEY` and `MAILJET_API_SECRET` set in the production environment (Fly.io secrets or equivalent).
- Verify the email sends by running `store_platform/scripts/storeops delivery --session cs_live_…` on a real purchase.
- Restore the "We emailed you a copy" copy on the success page.

**Scope:**
- Infrastructure: set Fly.io secrets
- `pages/orders/success.tsx` — uncomment or re-add the "email a copy" line
- `store_platform/OPERATIONS.md` — document the Mailjet setup

**Effort:** 1h (infra), 15min (code). The infra is the blocker.

---

## Priority order for the next developer

| Priority | Story | Blocked by |
|----------|-------|------------|
| **1** | Cookie consent (legal review) | — |
| **2** | Reading time (wordCount on API) | — |
| **3** | Confirmation email (Mailjet secrets) | — |
| **4** | Shortlist for guests | — |
| **5** | Hero illustration (design assets) | Designer |
| **6** | Account deletion (API endpoint) | Backend |
| **7** | SEO landing content (writer) | Writer |
| **8** | Upsell on success | Product decision |
| **9** | Compare packs | Shortlist (story 5) |
| **10** | Testimonials | Real buyer testimonials exist |
| **11** | Anti-search hero | UX research + risk_tolerance (story 7) |
| **12** | Risk tolerance facet | Engine data model |
| — | Horizontal swipe | **Not recommended** |
| — | Multi-language | Market decision |
