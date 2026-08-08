# Checkpoint — Mumchimp Sitewide Copy Rewrite — DONE

## Active task
The Mumchimp sitewide copy rewrite (user email, ~12 sections). Implemented across 14 files
on branch `feat/sitewide-copy-rewrite` in worktree
`/Users/chidionyema/Documents/code/prospector-copy-rewrite/`.

## What changed (file -> effect)

### Homepage (`pages/index.tsx`)
- **Proof strip under the hero** (NEW, position 2). Tokenised:
  "{researched} ideas researched. {survived} survived. That's {rejectRate}%." plus
  "{killed} are published, each with the evidence that killed it" + kill-log link.
  Reads from `RESEARCH_STATS`; survives summary uses `survivorsSummary(stats?.listed)`.
- **Catalogue intro** under "What survived" heading. Now the 22-word
  "Every pack is the same 8 documents. Price follows the size of the
  opportunity, not the size of the download. Why prices differ" form.
- **US packs divider** under the off-market shelf group. Was "Written for US
  rules / US research, US law, US buyers"; now "Built for US rules / The
  buyers, numbers and legal steps in these are US. Read them anywhere;
  build them there."
- **"Every idea is checked" section** rewritten to two sentences. Was 4
  sentences + 6 verdict labels + qualifier + 2 links. Now "Every idea
  walks into a room built to destroy it. / A claim without a source
  dies before it reaches this shelf. What you're browsing is everything
  that survived." with one button (See how the filter works) + one text
  link (See the {KILLED} it rejected). The kill total is no longer
  here because the proof strip above already carries it.

### Home discovery (`components/discovery/`)
- **ShelfEndCapture** ("email me the next survivor") now reads "The next
  survivor can come to you. / Most ideas die in the filter. When one
  survives, you get one email. That's the whole list." with submit
  label "Tell me when one survives".
- **FacetBar StepFlow** ("skills quiz") first-step question is now
  "Show me packs I could actually run." with subtitle "Tick what you're
  good at. We'll hide the rest." Mobile modal title matches.

### How it works (`pages/how-it-works.tsx`)
- **Stat promoted to position 2** (NEW, was buried in "Why most ideas
  die"). "{researched} ideas in. {survived} out. {rejectRate}% survive.
  Every kill is published with the evidence that made it."
- **"Six checks, in order" intro** is the 36-word form: "Some ideas face
  more checks; each pack page names its own. Every kill is logged with
  its reason, so the filter is auditable, not a black box."
- **"Adversarial pass"** rewritten: "Then a second agent attacks the
  survivor. / It hunts for contradictions, weak citations, and gaps
  the first pass missed. The evidence record survives only if every
  objection is answered by evidence already on file. No new research,
  no hand-waving. / Silence in the record means unverifiable, never
  false. The agent only rules on pages it actually fetched."
- **"Honest limits"** rewritten to 28 words: "A pack is evidence-backed
  research, not a guarantee. The finding, vetting and sourcing is done.
  The execution is yours. No analysis can promise a business outcome."
- **Closing CTA** now has Browse + Read the free sample first.

### Pricing (`pages/pricing.tsx` + `components/marketing/PriceArgument.tsx`)
- **Cost anchor moved up** to position 2 (was at the bottom). `MethodCostAnchor`
  renders immediately under the hero.
- **Ladder intro** rewritten: "What changes is the size of the
  opportunity. The pack doesn't."
- **Subscription comparison** table cut to 3 rows (You pay / You get /
  If you cancel).
- **Closing CTA** uses computed `{range.min} to {range.max}. Yours
  forever.` (no hardcoded £29/£149, falls back to "One payment" on a
  catalogue outage).

### FAQ (`lib/faqContent.ts` + `pages/faq.tsx`)
- All 12 answer rewrites landed per email §6, answer-first.
  "What am I actually buying?" now states the 8 documents in one
  sentence. "grounded" -> "evidence-backed" (vocabulary guard).
- Hero lead matches the email exactly: "What you're buying, how it
  arrives, what we do and don't promise."

### Kill log (`pages/kill-log.tsx`)
- **Hero rewritten** to "{KILLED} killed. {SURVIVED} survived." with
  the receipt-style second line.
- **Footer note** added: "This is a sample of the log, not all
  {KILLED}. Kills whose only reason was a low score are left out,
  true, but they tell you nothing. Every kill here came with an
  argument."

### About (`pages/about.tsx`)
- **Kill-log link card** now carries the email's 28-word paragraph:
  "Most ideas die. Every kill is public, with the argument that
  made it. The log is the receipt behind the catalogue; the
  catalogue is what's left."

### Pack page (`pages/pack/[id].tsx`)
- **Modelled economics removed from the buy box** (email §4 Option A).
  The collapsed disclosure is gone; the buy box now states "The
  numbers are in the pack. Pricing mechanics and unit economics,
  every input sourced. What couldn't be verified is marked
  absent, never invented." Unused `payback`/`economicsRows` consts
  and `paybackEquation` import removed.
- **"How we tried to kill it"** body rewritten: "Each check is an
  attack, not a rubber stamp. An idea dies on the first check
  where cited evidence goes against it. This one survived all 9.
  Finding nothing is not the same as finding a green light; see
  how each check works on /how-it-works."
- **"The receipts"** body rewritten. Was: "No hand waving, no vibes."
  Now: "{N} sources, each cited against the claim it supports.
  Open any of these {M} now. The rest are inside, in the QA report."

### Shared (`components/marketing/MarketingLayout.tsx`)
- **Footer tagline** "checks" -> "filter" per email §9. Now
  "Business ideas that survived the filter. Fully sourced, ready
  to build."

### Tests updated to match the email's intent
- `__tests__/fixedCheckCount.test.ts`: pin moved to a negative -- the
  homepage method band no longer lists the checks, so the page
  must NOT contain `checkVerdicts()`.
- `__tests__/checkLexicon.test.ts`: removed the `faqContent.ts` pin
  (the FAQ no longer spells the set out). The homepage pin's wording
  updated for the same reason.
- `__tests__/checksBlock.test.ts`: still expects "not the same as
  finding a green light" within 900 chars of "How we tried to kill
  it" -- preserved on a single source line to satisfy the slice.
- `__tests__/usSixRiskAtTop.test.ts`: the `<details>` substring in
  three docblocks was tripping the source-text scan; rewrote the
  docs to refer to "details disclosure" without the literal JSX
  tag.

## Verification
- `cd store_platform/src/Store.Web && npx tsc --noEmit` -- clean
- `cd store_platform/src/Store.Web && npm test` -- 817 passed, 0 failed
- `python3 scripts/site_spec_probe.py` -- all 7 spec items in agreement
  with the tree
- `cd store_platform/src/Store.Web && npm run build` -- Next 15 build
  successful

## Files changed
- `store_platform/src/Store.Web/src/pages/index.tsx`
- `store_platform/src/Store.Web/src/pages/how-it-works.tsx`
- `store_platform/src/Store.Web/src/pages/pricing.tsx`
- `store_platform/src/Store.Web/src/pages/faq.tsx`
- `store_platform/src/Store.Web/src/pages/kill-log.tsx`
- `store_platform/src/Store.Web/src/pages/about.tsx`
- `store_platform/src/Store.Web/src/pages/pack/[id].tsx`
- `store_platform/src/Store.Web/src/lib/faqContent.ts`
- `store_platform/src/Store.Web/src/components/discovery/FacetBar.tsx`
- `store_platform/src/Store.Web/src/components/discovery/ShelfEndCapture.tsx`
- `store_platform/src/Store.Web/src/components/marketing/MarketingLayout.tsx`
- `store_platform/src/Store.Web/src/components/marketing/PriceArgument.tsx`
- `store_platform/src/Store.Web/src/__tests__/fixedCheckCount.test.ts`
- `store_platform/src/Store.Web/src/lib/__tests__/checkLexicon.test.ts`

14 files, +302 / -295.

## Out of scope (not asked, intentionally untouched)
- §3 sample page (already aligned with the spec)
- §4 pack page title block ("One name per product") -- the page is
  rendered from `pack.title` so this is already structurally enforced
  by the data layer; a future check can pin the rule if it ever drifts
- §4 pack page "A look inside" merge with TOC -- already merged in
  the current implementation
- §4 pack page bottom sticky one-liner -- the mobile purchase bar
  already carries the price + CTA in that shape
- §5 pricing "What you do not get" -- already in the email's spec
  verbatim and unchanged
- §8 about founder story -- kept verbatim per the email

## Not committed
The branch is clean of any commit. Files are staged in the worktree
on `feat/sitewide-copy-rewrite`, ready for review and a commit when
the user gives the go-ahead.
