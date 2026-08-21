# First run and navigation

**What this programme owns: what a stranger meets, in the order they meet it, and whether they can
get anywhere from there.** It is not a page. It is a property of every route, and until 2026-08-21
no gate in the estate graded it.

Opened 2026-08-21 on the founder's report. His words, verbatim:

> "first tine user just gets hit with kill log no contexxt no idea wtf is going on"
> "NOno brand acquainyance"
> "just a static headline about kill log"
> "this is a whole project not a page"
> "i dont want to repeat ghis this is why we need research tooling autonation etc"
> "we need to not nake rookie ninstakes"

---

## 1. What is actually on the site

Measured 2026-08-21 against live mumchimp.com, one HTTP fetch per route, text extracted in
document order. Not from a doc, not from a memory.

**All twelve marketing routes open with the same line, printed above the logo:**

```
Killed 7 Aug · Sound Check Rounds, the monthly noise test that keeps a small music
venue's licence safe · Read the verdict →
```

The first sentence a stranger reads on this shop is a dated rejection of a business they have never
heard of, attached to a word ("Killed") that only means something if you already know what we do.
The brand appears second. The founder's report is not a homepage complaint; it is every page.

| route | h1 | forward links in `<main>` | house words above the h1 |
|---|---|---|---|
| `/` | yes | 64 | killed, kill log, verdict |
| `/ideas` | yes | 15 | killed, kill log, verdict |
| `/how-it-works` | yes | 1 | killed, kill log, verdict |
| `/kill-log` | yes | 1 | killed, kill log, verdict |
| `/sample` | yes | 1 | killed, kill log, verdict |
| `/pricing` | yes | 1 | killed, kill log, verdict |
| `/faq` | yes | **0** | killed, kill log, verdict |
| `/about` | yes | **0** | killed, kill log, verdict |
| `/terms` | yes | **0** | killed, kill log, verdict |
| `/privacy` | yes | **0** | killed, kill log, verdict |
| `/refund` | yes | **0** | killed, kill log, verdict |
| `/account` | yes | **0** | killed, kill log, verdict |

Two findings, both measured:

1. **Nothing orients before the jargon.** Twelve of twelve.
2. **Six routes are dead ends.** Nothing inside `<main>` leads to a pack, the catalogue or a
   category. A visitor who finishes reading the FAQ has to go back up to the header to find out
   what is for sale.

## 2. Why it shipped, and the class

`TodayRibbon` was added 2026-08-18 for **pixel parity**. The drawings put a dark strip above the
header on all eleven pages, the app had none, so every built page rendered 44px higher than its
drawing and missed on 5.96% of pixels at 1280. That defect was real and that fix was correct.

The drawings document **two** variants of that strip
(`docs/design/mumchimp-build-bundle/components.html:541`):

- **"Ribbon — a kill"** — red tag, "Killed today", links to `/kill-log`.
- **"Ribbon — a survivor"** — teal tag (`.tag.s`), "New today", links to **a pack**, with the line
  "survived all six checks on 41 sources" and "Open the pack →".

**Only the kill variant was built.** The survivor variant, which would have put a product and a
survival claim in front of a stranger, exists in the CSS (`mumchimp.css:249`) and in no component.

Nothing caught it, because every gate we had grades the **shape** of the first screen and none
grades what it **says**:

| gate | what it compares | why it passes a kill-first page |
|---|---|---|
| `scripts/component_parity.mjs` | tag names and classes | a kill ribbon and a survivor ribbon are the same DOM |
| `scripts/visual_regression.mjs` | pixels vs the drawing | the drawing also shows a kill |
| `e2e/fold-budget.spec.ts` | geometry: is the shelf on the first screen | a page can be perfectly composed and incomprehensible |
| `scripts/site_spec_probe.py` | the source tree vs the spec ledger | reading order is not in the ledger |

**The class of mistake: we graded how the first screen looks and never graded what it says.** It is
the same class as the parity work itself — a correct fix to a measured defect, whose side effect on
a different axis was nobody's property.

## 3. The gate

`store_platform/src/Store.Web/e2e/first-run.spec.ts`, running in CI's `nextjs` job against a
locally built server, **before merge** — deliberately alongside `fold-budget.spec.ts`, because that
file is the same idea one axis over and the two should be read together.

- **FR1 — the brand is first.** Nothing with visible text may render above the `<header>` box. The
  skip link is exempt; it is off-screen until focused. It measures against the HEADER's box, not
  the wordmark's, because nav links sit a pixel or two above the wordmark's glyph box and the
  first version of this check flagged the site's own nav.
- **FR2 — the product is named before the house words.** No element containing `killed`, `kill log`,
  `verdict`, `prescreen`, `dossier` or `the moat` may render above the page's own `h1`.
  `/kill-log` is exempt by being outside the route list: a visitor who clicked "Kill log" asked for
  exactly that and is oriented by their own click. The `<header>` is exempt too, and only the
  header: a nav label sits in a list of its peers — Categories, How it works, Kill log, FAQ,
  Account — and a stranger reads that list as navigation, not as a claim. What the founder was hit
  by was a SENTENCE above the brand with nothing around it.
- **FR3 — no dead ends.** Every route's `<main>` must contain at least one link to a pack, the
  catalogue, or a category.

**FR3 ships with five routes waived** — `/faq`, `/about`, `/terms`, `/privacy`, `/refund` — so the
gate is green on main and refuses any *new* dead end. That waiver list is the work queue in §5.
Emptying it closes the item. Adding to it to make a build pass is forbidden.

**`/ideas` is the one conditional skip, and it is conditional on DATA, not on the route.** Every
forward link on that page is catalogue content, and CI serves the built site with no API behind
it, so the page honestly renders "No categories are available right now" and has nowhere to send
anyone — a fact about the harness, not about the page. The gate therefore skips it only after
proving this server has no catalogue at all: if `/` serves a single `/pack/` link, the data is
there and `/ideas` is graded like every other route. Against live it carries 15 forward links.

**Measured, both directions, with the identical spec** (2026-08-21):

| target | total | passed | failed | skipped |
|---|---|---|---|---|
| live mumchimp.com, before the fix | 30 | 5 | **20** | 5 |
| local build, kill ribbon scoped to `/kill-log` | 30 | 24 | **0** | 6 |
| live mumchimp.com, after that shipped (`f5ca8e52`) | 30 | 25 | **0** | 5 |
| local build, FR3 waiver emptied, five dead ends fixed | 30 | 29 | **0** | 1 |

The one remaining skip is FR3 on `/ideas`, which is data-conditional: the CI `nextjs` job serves
the site with no API behind it, so the page honestly renders "No categories are available right
now". Against live it passes.

The 20 live failures are FR1 on all ten routes and FR2 on all ten routes — the defect was on
every marketing page, not only the home page the founder happened to open. FR3 passed on the
five routes it was not waived on, in both runs. The sixth local skip is `/ideas` on FR3, which
is the no-catalogue condition above and not a waiver.

Alongside: `npm run lint` 0 errors (108 pre-existing warnings), `npm test` 896 passed across 85
files, `next build` typecheck clean, and the POPDD gate PASS on the commit.

## 4. The method, and what it is not

**It is not A/B testing.** Founder, 2026-08-21: "non a/b testing". He is right on the arithmetic as
well as the preference — the storefront has taken zero sales ever
(`docs/SUBSCRIPTION_PROGRAM.md §1.4`), so there is no traffic to split and no conversion signal to
compare. A split test needs thousands of sessions to separate a real effect from noise. We have
none.

**It is not analytics first, either.** With zero traffic, an analytics install measures nothing on
day one. Instrumentation is worth having before launch so the first real visitors are not wasted,
but it cannot find today's defects. Today's defects are found by looking, and then pinned by a gate
so they cannot come back.

**The method is: measure the served HTML, grade it mechanically, and keep the list.** That is what
§1 and §3 are. It costs nothing, needs no traffic, and it runs on every pull request.

Instrumentation, for when there is traffic (a cookie banner is acceptable — founder, 2026-08-21:
"a cokkie bannner is no end of the world"):

| option | licence | what it costs to run | verdict |
|---|---|---|---|
| Stripe `checkout.session.completed` / `.expired` webhooks | already integrated | £0 | **do this first.** A real started-vs-completed funnel on the money leg, at zero cost. Blind to everything before checkout. |
| GoatCounter | self-host, single Go binary + SQLite | negligible | **the page-level answer.** ~3.5 KB of script, no separate database. |
| Umami | MIT | needs Postgres | more than we need |
| Plausible CE | AGPLv3 | needs ClickHouse **and** Postgres | more than we need |
| PostHog self-hosted | MIT | 4 vCPU / 16 GB RAM / 30 GB disk, about €30–40 a month | the only one with session replay, and a real recurring bill against a shop with no revenue. Not yet. |

All of them need a same-origin path proxy (a Next.js `rewrites()` entry) because the CSP is
`connect-src 'self'` (`next.config.ts`). That is a rewrite, not a CSP change.

## 5. The work queue

| # | item | state |
|---|---|---|
| FR-1 | Build the drawings' **survivor** ribbon variant and lead with it; the kill ribbon stays on `/kill-log`, where the visitor asked for it | not started |
| FR-2 | `/faq` — add a forward link in `<main>` | **done 2026-08-21** — the button was already there, pointing at `/`. Now `/#catalog` |
| FR-3 | `/about` — add a forward link in `<main>` | **done 2026-08-21** — same, `/` → `/#catalog` |
| FR-4 | `/refund` — add a forward link in `<main>` | **done 2026-08-21** — in `components/LegalDoc.tsx`, so it fixed `/terms` and `/privacy` too |
| FR-5 | `/terms`, `/privacy` — decide whether a legal page should sell, or be waived permanently with a reason | **decided 2026-08-21: it should.** A reader who opens the refund policy before buying is the most likely buyer on the site, and the closing block was already selling — it just pointed at `/faq`. `FR3_WAIVED` is now empty |
| FR-10 | **14 of 77 packs are 3 clicks from everywhere.** Measured 2026-08-21 against live: home links 63, `/ideas` links 0 packs (its 15 links are categories), and the union of the 15 category pages is 77. The 14 are behind the home page's collapsed groups (`pages/index.tsx:1445` shows 2 of N groups, `:1494` shows 3 of each until `showAll`), so they exist in the sitemap and in no server-rendered listing a reader or a crawler can walk in two clicks. Needs a design call: render all groups, paginate, or add a plain index | not started |
| FR-6 | `/sample` promises differ from delivery | **done 2026-08-21.** The page was right and every link into it was wrong. `data/sample-report.json` ships `sectionsShown: 3` against `sectionsTotal: 14` and names the other eleven in `withheld`; the founder settled that on 2026-08-15 and `pages/sample.tsx` was rewritten the same day. The three strings in `lib/siteCopy.ts` were not: `sampleLinkHero` (homepage hero), `sampleLinkPanel` (the pack page buy rail) and `sampleLink` (`/faq`, `/ideas`, the mobile bar) all still said "a full pack free". All three now say "the opening of a real pack". `__tests__/sampleOfferIsTrue.test.ts` reads the fixture and fails if any of them claims a whole pack while the fixture withholds sections |
| FR-7 | `/sample` has no buy call to action | **withdrawn 2026-08-21 — the row was stale.** `pages/sample.tsx:495` is an `id="buy"` block headed "Now read one that survived all of it.", whose primary button is "Browse the packs" → `/#catalog`, with "See how the filter works" beside it. The waitlist form sits UNDER it, deliberately. Nothing to do |
| FR-8 | Stripe checkout-session webhooks into a funnel table | not started |
| FR-9 | GoatCounter behind a same-origin rewrite | not started |

## 6. Rules this programme adds

- **A new route is not finished until someone has read it cold.** FR1–FR3 run on it, and it goes in
  the `ROUTES` list in `first-run.spec.ts` by hand — the moment that costs is the moment someone
  asks what the page looks like to a stranger.
- **A parity fix is not finished until reading order is checked.** Pixel and DOM parity say nothing
  about meaning, and this programme exists because that gap shipped for three days on every page.
- **Never add a route to `FR3_WAIVED` to make a build pass.** Add the link.

## 7. The axis, the baseline and the target

`ENGINE_1000X_ACTION_PLAN.md` has one rule: **a row that moves no axis is not work.** A gate plus
five missing links is a snag list, not a 1000x answer. So this programme registers an axis, with a
baseline and a target that are numbers.

**Axis N1 — entry coverage.** Of every (entry route x pack) pair, what fraction can a stranger
actually reach, and in how many clicks? It needs no traffic, no analytics and no split test, which
is why it can be measured today and why it can gate a pull request.

### The instrument

`store_platform/src/Store.Web/scripts/reachability.mjs`, added 2026-08-21. Before it, this section
carried a hand-crawled table and the sentence "the measurement script is the gate" — and there was
no script, so the baseline could not be re-run, so it could not be a target. Run it:

```bash
node scripts/reachability.mjs                        # live
node scripts/reachability.mjs http://localhost:3000  # a local build
```

The pack universe comes from `sitemap.xml`, never from a listing page, because a pack that no
listing links must not be invisible to the measurement that exists to find it.

### The baseline, measured 2026-08-21 against live

11 entry routes x 77 packs = 847 pairs.

| | reachable pairs | coverage |
|---|---|---|
| within 1 click | 63 | **7.4%** |
| within 2 clicks | 707 | **83.5%** |
| target, within 2 clicks | 805+ | **95%** |

| entry | 1 click | 2 clicks |
|---|---|---|
| `/ideas` | 0 | **77** |
| `/` | 63 | 63 |
| `/how-it-works`, `/faq`, `/about`, `/sample`, `/pricing`, `/terms`, `/privacy`, `/refund`, `/kill-log` | 0 | 63 each |

### The five dead-end fixes moved this number by zero, and that is not a failure

Re-measured against live at 13:0x on 2026-08-21, after FR-2 to FR-5 shipped and deployed: 7.4% and
83.5%, identical to the row above. Nobody should read that as "the fix did nothing".

Axis N1 follows every same-origin link, the header included. Every page on the site already reached
`/` through the header logo, so every page was already two clicks from those 63 packs before a
single dead end was fixed. And `reachability.mjs` strips fragments, so the new `/#catalog` buttons
are recorded as links to `/` — the same edge the logo already provided.

What the five fixes moved is the instrument that grades the page's own argument: FR3 in
`e2e/first-run.spec.ts` counts forward links inside `<main>` only. Against live it went from **20
failed to 0 failed**, and with `FR3_WAIVED` emptied it is now **30 passed, 0 failed, 0 skipped**
against production.

Two instruments, two numbers, one honest reading: a reader who uses the nav could always get to the
shelf, and a reader who follows the page they are on could not. Axis N1 is the wrong instrument for
a dead end, and FR-10 is the work that will actually move it.

### Two instruments disagreed, and that is the finding

This table replaces one measured the same day by hand that read **6.8% @1 click and 35.6% @2**, with
seven of twelve entry routes at zero. Neither number is wrong. They model different readers:

- the hand crawl followed links inside `<main>` only — a reader who follows the page's own argument;
- `reachability.mjs` follows every same-origin link, header nav included — a reader who uses the nav.

The nav is why `/faq` jumps from 0 to 63: the wordmark and the crumb both reach `/`, and `/` carries
63 packs. **The target is set against the script**, because a nav click is a real click and the
script is the re-runnable one. FR3 in `e2e/first-run.spec.ts` keeps grading `<main>` only, and that
asymmetry is deliberate: FR3 asks "does this page lead anywhere", the script asks "can the shelf be
got to at all". Keeping both is what surfaced the disagreement.

### The whole remaining gap is 14 packs

`/` reaches 63 packs at one click **and still 63 at two**. The other 14 are reachable only through a
category page — `/ideas` -> `/ideas/<category>` -> pack, three clicks from anywhere else on the
site. They are in the sitemap and in no server-rendered listing a reader or a crawler can walk in
two. The cause is at `pages/index.tsx:1445`, which renders 2 of N groups until `showAll`, and
`:1494`, which renders 3 packs of each.

Arithmetic: every entry route that reaches 63 would reach 77, and the total goes 707 -> 847.

**Fixing FR-10 alone takes Axis N1 from 83.5% to 100% at two clicks**, and 7.4% to 9.1% at one. It is
the only work left on this axis, and it needs a design call rather than a link: render every group
server-side, paginate, or add a plain index page.

**Cost class: ONE-OFF.** Every number above comes from HTTP fetches of pages we already serve. No new
service, no subscription, no rented box.

**Proof, two angles.** Angle one is `reachability.mjs`, which parses served HTML. Angle two is
FR1-FR3 in `e2e/first-run.spec.ts`, which runs in a real browser against a built server and grades
geometry. They fail differently: the crawl cannot see an element that is present but `display:none`,
and the browser gate cannot see a route nobody listed.

**Why this is the right axis and conversion is not.** Conversion needs sales, and the storefront has
had none. Entry coverage is upstream of conversion, is fully determined by our own markup, and is
measurable today.
