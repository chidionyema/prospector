# Storefront critique, 2026-08-19: every finding, its receipt, its verdict

An 18-persona teardown of the storefront was run on 2026-08-19 against the live site
`https://mumchimp.com`. This file is the ledger. Every finding that critique raised has a row here,
whether it was fixed, corrected, refuted, or handed to the founder. Nothing was dropped for being
inconvenient.

Read this before re-critiquing the storefront. Six sessions finding the same eight defects and
fixing them six times is the cost this file exists to stop.

## How the critique was run, and what it could not see

Ten public pages were fetched and text-extracted. Home and `/pack/08b22037fc2afc07` were
screenshotted at 1440x900 and 390x844. Checkout was NOT run: it mints a real Stripe session on the
live money rail, which is a side effect on production. The account area was not tested.

**The critique graded the DEPLOYED build, and this checkout is newer.** Some findings describe copy
this checkout no longer produces. Those rows say so, and the deployed build is the thing to fix by
shipping, not by editing. Detail in C3 below.

## Status key

| Word | Meaning |
| --- | --- |
| FIXED | changed in this branch, with a test that fails if it comes back |
| FOUNDER | a decision, not a defect. The one-line change is written out; the call is his |
| OTHER SESSION | already owned by a live branch. Do not duplicate it |
| CORRECTED | the finding was wrong or incomplete. The correction is the row |
| ENGINE | not fixable in the storefront. It needs a change upstream of the payload |
| OPEN | real, unowned, not yet done |

---

## Fixed in this branch

### F1. The site named no trader. Now every page does.

Severity: legal breach, and Baymard's third-largest abandonment cause.

The critique grepped all ten public pages for a company number, a Companies House registration, a
registered office or a named limited company. It found none. The footer read
`(c) 2026 Mumchimp. All rights reserved.` and gave one email address.

The data was never missing. `src/lib/config.ts` holds `legalName: 'ByteSync Ltd'`,
`companyNumber: '17182157'` and the registered office, all confirmed against Companies House on
2026-08-16, with this note beside them: "Five dissolved companies share the name, which is why the
number is recorded here and not just the name. The name alone does not identify the trader."

It was then rendered nowhere. `LEGAL.companyNumber` reached zero pages. `legalName` and `address`
reached only `/terms`, `/privacy` and `/refund`, which is three clicks from the shop front.

The law asks for more than that. Reg 6 of the Electronic Commerce (EC Directive) Regulations 2002
requires the name, geographic address and registration number to be easily, directly and
permanently accessible. The Consumer Contracts (Information, Cancellation and Additional Charges)
Regulations 2013 require trader identity and geographic address before a distance contract is
concluded.

**What changed.** `traderIdentity()` in `src/lib/config.ts` returns the whole sentence, once, for
every reader. It renders in `.f-bottom` of `src/components/marketing/MarketingLayout.tsx`, which is
the footer of every marketing page, and it replaced the four hand-assembled copies on
`terms.tsx:171`, `refund.tsx:196`, `privacy.tsx:34` and `privacy.tsx:219`.

It is a function and not a string for the same reason `lib/payback.ts:80` gives about the multiple
ceiling: a rule enforced per caller is a rule the next caller forgets. Four call sites each
branching on whether the company number is set is four chances to print "(company number )" the day
it is cleared. One branch, five readers.

No CSS was written. `mumchimp.css:165` already gives `.f-bottom p` its size, colour, measure and
bottom margin, so a second paragraph needs nothing new.

**Guard.** Three tests in `src/__tests__/crossCuttingSweep.test.ts`, all mutation-proven:

* the sentence must contain the legal name, the address and the registration number
* `MarketingLayout.tsx` must call `traderIdentity()` inside the always-rendered footer
* no file outside `config.ts` may inline the registration number

Deleting the footer call fails test 2. Typing the number into a new file fails test 3. Both were
run in the broken state and both failed as designed.

**One thing for the founder, not for me.** `LEGAL.address` is a residential address. It is already
published on three legal pages and is public at Companies House, so the footer does not change
whether it is public. It does change how visible it is. If you want a different service address
filed at Companies House, change it there and in `config.ts`, and every one of the five render sites
follows.

### F2. The credibility ceiling was declared twice.

Severity: a live drift risk on the one number that decides which claims the shop makes.

Found while reading the shelf code for the critique, not raised by the critique itself.

`CREDIBLE_MULTIPLE_CEILING` bounds the payback multiple a card may print. `lib/payback.ts:80`
declares it, with the founder's 2026-08-15 reasoning and the live distribution beside it, and
`paybackEquation` applies it at the source. `lib/packStat.ts` had declared its own second copy of
the number, with a near-copy of the argument above it, and then re-checked the already-bounded
value twice.

Nothing failed, because the two numbers agreed. That is the trap. The day someone raises one of
them, the shelf and the pack page start making different claims about the same pack, and the lower
of the two silently wins.

The file's own comment already contradicted the code four lines below it: "No ceiling check here on
purpose ... A rung that re-checked it here would be a second ceiling to keep in step with the
first."

**What changed.** The second declaration and both redundant re-checks are gone from
`src/lib/packStat.ts`. `paybackMultiple` is now one line. `packLeadStat` tests only whether the
equation returned anything.

**Guard.** `crossCuttingSweep.test.ts` walks every `.ts` and `.tsx` under `src/` and fails if a
second declaration of that constant appears anywhere. It carries a vacuity check, because a walk
that finds nothing passes for the wrong reason. Mutation-proven: a fresh file declaring the constant
made it fail, and removing that file made it pass.

The walk is deliberately not a fixed list of files. A fixed list is the same defect as a per-caller
bound.

---

## Corrections to the critique

### C1. "77 packs" against "80 survivors" is not a stale counter.

The critique read the home footer's `Killed 1,364 / Researched 1,444` against the hero's
`77 packs in the catalogue` and called three packs unaccounted for.

Both numbers are correct and both are live. The gap is the difference between surviving the filter
and being published, and `lib/stats.ts` already says so in its own comment. The defect is not a
stale number. It is that the page prints two counters whose difference a reader can compute, and
then names a third figure that does not match it.

Founder decision, because the fix is a copy change to a directive of 2026-08-13. Two honest options:
print the survivor count next to the catalogue count, or stop printing the pair that lets a reader
derive it.

### C2. "Name the eighth check" cannot be done in the storefront.

The critique asked why the page says a pack cleared 7 of 8 checks without naming the one it lost.

It cannot. `PackDetails` carries no per-check verdicts, so naming one would be invention. The pack
page already reasons this out at `pages/pack/[id].tsx:1161`: "What is still NOT said, because the
page cannot source it: WHICH check this pack lost."

The related half of the finding, that the visible list of six contradicted the claimed denominator
of eight, was already fixed on this checkout. The page now says how many run on every idea and how
many extra the lane added.

To name the check, `bridge.py::_trust_fields` has to put per-check verdicts in the payload. Engine
work, not storefront work.

### C3. The live site is running an older build than this checkout.

The critique quoted `Month 1 revenue £640 · Earned back per customer won 21.9× · Payback 1 month`
from the pack page and called it an unevidenced earnings claim.

That string appears nowhere in this repository. `rg` returns zero hits, and the buy box in this
checkout does not render that trio. It was deleted on 2026-08-13 for exactly the reason the critique
gives, and the deletion is documented in `lib/packStat.ts:32-46`.

So the finding is real about the deployed site and already fixed in the source. It ships by
deploying, not by editing. It also means any other row here that quotes live copy may be grading a
build this checkout does not produce, which is why each row names the file it verified against.

### C4. The site is not free of images.

The critique said zero `<img>` tags site-wide. `components/marketing/FounderNote.tsx:50` renders
one, a self-hosted portrait. The wider point stands for the shelf and the pack pages, which carry no
imagery at all.

### C5. A transfer size in the performance section was measured wrong.

An earlier measurement labelled "the biggest JS chunk" actually fetched the first bundle in
alphabetical order, `_buildManifest.js` at 768 bytes. The 191,556 bytes of HTML and the count of 17
JS files stand. The per-asset number does not, and is not used anywhere in this ledger.

---

## Confirmed, and owned elsewhere

### O1. `--subtle #8B9096` fails AA contrast.

3.21:1 on white against the 4.5:1 floor, at `src/styles/tokens.css:177`, and it is the colour of
most supporting copy on the site.

Confirmed. **Another session owns it** on branch `fix/a11y-subtle-contrast`. Do not fix it here. Two
sessions changing one token is how a shared checkout produces a merge conflict on a colour.

---

## Confirmed and open

### P1. Breadcrumb links measure 2.31:1 with no underline.

`Catalogue / Browse by category /` sits at the top of every pack page and is the least readable text
on the site. Same class as O1 and probably the same branch's business, so it is listed rather than
touched.

### P2. The mobile stylesheet hyphenates mid-word.

`src/styles/mumchimp.css:417` sets `@media(max-width:520px){.d,.desc{hyphens:auto}}`.

Confirmed on disk. Not fixed here, because `mumchimp.css` is byte-locked by a test: the shipped
bundle must stay verbatim, and deviations belong in `globals.css`. That is a deliberate rule and
this defect is not worth breaking it without the founder saying so.

### P3. The ribbon truncates its own message on phones.

The dark strip above the header prints the latest killed idea. `mumchimp.css:250` sets
`overflow:hidden;text-overflow:ellipsis;white-space:nowrap`, and `:416` clamps it to two lines below
640px. The live example was `Sound Check Rounds, the monthly noise test that keeps a small...`.

The site's own rule forbids the easy fix: shorten and wrap the label, never hide the overflow. The
overflow rule is already in the byte-locked bundle, so the honest fix is a shorter title. Titles come
from `src/data/latest-kill.json`, written by `tools/make_kill_log.py`. That is where a length bound
belongs, and it is one place, which is the right number of places.

### P4. "payback" is used 34 times on the home page and defined nowhere.

`rg` finds no definition of the word anywhere in `src/`. The card label is the bare word `payback`
and the proof line reads `17x payback`.

Real gap. Not fixed here because adding marketing copy that nobody asked for has been a defect
every time it has been tried on this site. The change is one sentence near its first use on the home
page. Founder's wording, founder's call.

### P5. No trust marks at the payment step.

`Secure checkout via Stripe` is one line of small mono text with no Stripe mark. Baymard puts
average cart abandonment at 70.22%, with 19% of abandoners in the last three months citing not
trusting the site with card details. F1 addresses part of that 19%. The payment mark is the rest.

### P6. Pack URLs are hex, category URLs are slugs.

`/pack/08b22037fc2afc07` against `/ideas/business-ideas-for-developers`. The pages that convert have
the worst URLs.

Real, and it is not a small change: it needs a slug on the pack payload, a redirect from every hex
URL already indexed and shared, and a decision about what happens when a title changes. Ticket it,
do not slip it into a copy branch.

### P7. The pack page never answers the category's central objection.

The answer exists, is good, and is question 4 of 12 on another page behind an accordion: almost
nobody executes, and most packs win on a local patch where the first mover in your area is the only
one who matters. It belongs next to the price.

### P8. `1x payback` renders as a proof badge.

At a multiple of 1, month-one revenue is between 1.0 and 1.99 times the price, so "payback" is
literally true. It is weak, not dishonest.

Raising the floor is one character in `lib/payback.ts`: reject `multiple < 2` instead of
`multiple < 1`. It costs the packs at exactly 1x their lead figure and drops them to the source
count. Product call, so it is the founder's.

---

## Founder decisions, written out so they can be decided

| ID | The decision | The change if yes |
| --- | --- | --- |
| D1 | Does the home page's evidence promise survive Terms section 6? Home says nothing rests on a number we cannot show you. `pages/terms.tsx:112` says we make no warranty that pack content is accurate, complete or current. A disclaimer in the terms does not cure a claim on the shop front, and under the DMCC Act 2024 the CMA now decides infringements itself. | Soften the home claim to what the terms can support, or tighten the terms to what the home page promises. Both are copy. |
| D2 | Publish the survivor count, or stop printing the pair that lets a reader derive it? (C1) | One line in the footer stats or the hero sub. |
| D3 | Raise the payback floor from 1x to 2x? (P8) | One character in `lib/payback.ts`. |
| D4 | Define "payback" on the home page? (P4) | One sentence, your words. |
| D5 | Is the registered office the address you want on every page? (F1) | Change the service address at Companies House and in `config.ts`. Five render sites follow automatically. |
| D6 | What is the extract-length policy for quoted sources? The packs quote statute and journals thousands of times across the catalogue. The terms bar buyers from training models on pack content while the packs are themselves model output built from other people's pages. | A stated policy, applied by the renderer. |

---

## What the critique got right and nobody should touch

The refund page. "Fourteen days, no questions." "A pack is a file you own, so downloading it does
not waive the refund." "A human reads every email and replies in under one business day."
Explicitly voluntary and additional to statutory rights. It is the best writing on the site.

The one improvement worth making is putting "14 days, no questions, download included" in the sticky
mobile buy bar, where the decision is actually taken.

---

## Proof

Run from `store_platform/src/Store.Web`:

```
npx tsc --noEmit -p tsconfig.json          # exit 0
npx vitest run src/__tests__/crossCuttingSweep.test.ts
                                           # Test Files 1 passed, Tests 31 passed
npx vitest run                             # Tests 849 passed
```

The full run reports one test FILE unloadable, `src/components/ui/__tests__/Button.test.tsx`. It is
an environment gap, not a failure: `@testing-library/jest-dom` is declared in `package.json` and
absent from the cloned `node_modules` in this worktree. No test in it ran, and none of the changes
here touch it.

`verify.mjs` was NOT run. It needs a live site, and the local Store.Api renders zero packs. The
footer change was checked against its checks by reading them: a wrapping paragraph cannot overflow
at 390px, it carries no ellipsis, it is not a link, and its wording contains none of the banned
strings.
