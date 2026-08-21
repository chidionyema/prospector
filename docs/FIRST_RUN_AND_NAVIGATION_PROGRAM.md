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
| FR-2 | `/faq` — add a forward link in `<main>` | not started |
| FR-3 | `/about` — add a forward link in `<main>` | not started |
| FR-4 | `/refund` — add a forward link in `<main>` | not started |
| FR-5 | `/terms`, `/privacy` — decide whether a legal page should sell, or be waived permanently with a reason | not started |
| FR-6 | `/sample` promises differ from delivery: the homepage says "Read a full pack free — no email needed", `/sample` is titled "Read the opening of a real pack, free". One of the two is wrong | not started |
| FR-7 | `/sample` has no buy call to action at all — its only button is "Put it in the queue" | not started |
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
baseline measured today and a target that is a number.

**Axis N1 — entry coverage.** Of every (entry route x pack) pair, what fraction can a stranger
actually reach? It needs no traffic, no analytics and no split test, which is why it can be measured
today and why it can gate a pull request.

Measured 2026-08-21 against live, following links inside `<main>` only, 12 entry routes x 77 packs
= 924 possible pairs:

| | reachable pairs | coverage |
|---|---|---|
| within 1 click | 63 | **6.8%** |
| within 2 clicks | 329 | **35.6%** |
| target | 878+ | **95%** |

Per entry route, packs reachable in two clicks:

| entry | 1 click | 2 clicks |
|---|---|---|
| `/ideas` | 0 | **77** |
| `/` | 63 | 63 |
| `/kill-log` | 0 | 63 |
| `/sample` | 0 | 63 |
| `/pricing` | 0 | 63 |
| `/how-it-works` | 0 | **0** |
| `/faq` | 0 | **0** |
| `/about` | 0 | **0** |
| `/terms` | 0 | **0** |
| `/privacy` | 0 | **0** |
| `/refund` | 0 | **0** |
| `/account` | 0 | **0** |

**Seven of twelve entry routes reach no product at all in two clicks.** A stranger who lands on the
FAQ from a search result cannot get to anything we sell without going back to the header and
guessing.

**And the homepage is not the catalogue.** It links 63 distinct packs. There are 77. Fourteen packs
are reachable only through `/ideas`, and `/ideas` is labelled "Categories" in the navigation, which
is not a word that promises "everything we have".

**Cost class: ONE-OFF.** Every number above comes from HTTP fetches of pages we already serve. No
new service, no subscription, no rented box. The measurement script is the gate.

**Proof, two angles.** Angle one is the reachability crawl above. Angle two is FR1-FR3 in
`e2e/first-run.spec.ts`, which runs in a real browser against a built server and grades geometry
rather than parsed HTML. They can fail differently: the crawl cannot see an element that is present
but `display:none`, and the browser gate cannot see a route nobody listed.

**Why this is the right axis and conversion is not.** Conversion needs sales, and the storefront has
had none. Entry coverage is upstream of conversion, is fully determined by our own markup, and is
already 93.2% short of its ceiling. There is no measurement problem here; there was only ever a
missing gate.
