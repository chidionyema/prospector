# Storefront Redesign — the founder's brief, verbatim, and the bar it must clear

> **Why this file exists.** The founder's words on 2026-08-20: *"not all the founder's criteria,
> write it down and save it so you can reference"*. Every previous redesign lived in a chat
> transcript and evaporated. This file is the contract. It is READ before any design decision and
> APPENDED to as work lands. It never moves into `CLAUDE.md`.
>
> **Status is a probe, not a paragraph.** Every acceptance criterion below carries the command that
> proves it. A criterion with no command is not a criterion, it is a wish.

Branch: `design/storefront-v2`. Base: `origin/main` @ `8f6e0805`.
Opened: 2026-08-20.

---

## Part 1 — The founder's criteria, verbatim

Recorded as spoken, in order. Typos preserved; the reading is given after each. These are the
source of truth. If a decision below contradicts one of these, the criterion wins.

| # | Verbatim | Reading |
|---|----------|---------|
| C1 | "get atest fron nain, new branch and worktree" | Work off latest `main`, on a new branch, in a fresh worktree. |
| C2 | "ur nission is ui topdown redesign" | Top-down redesign of the UI. Not a patch pass — the whole thing, from foundations up. |
| C3 | "do research , nainun craft annd crativity, run eperirents, use realworld data" | Research first. Maximum craft and creativity. Run experiments. Use real data, not lorem ipsum. |
| C4 | "i want the net version of the site a 1000 inprovenet i every way possible" | The next version of the site: a 1000x improvement in every way possible. |
| C5 | "you have free reign over everything inncling branding, previous desions can be overridden as long as you can neet the 100 bar" | Free rein over everything **including branding**. Any previous decision may be overridden — if the result clears the bar. |
| C6 | "the cirrent site is a ness and a no go" | The current site is a mess and is rejected. |
| C7 | "thjis is busiesss critical we have redesigned so nay tines its ehausting" | Business critical. This has been redesigned many times already. Exhausting. Do not produce another round that has to be redone. |
| C8 | "our foundations, designwise are weak and haky we constantly have layout issues junk design" | The design **foundations** are weak and flaky. Layout issues and junk design recur. Fix the foundation, not the symptoms. |
| C9 | "i need you to do wide research onlie" | Wide online research. |
| C10 | "ths is eistential for the business and brand, everything nust be considered and explored and docunent rigorously and deno often" | Existential for business and brand. Consider and explore everything. Document rigorously. **Demo often.** |
| C11 | "i want diffrent looks and a/b testing drive fe with the tooling ready" | Multiple different looks. A/B testing driving the front end. The tooling ready to run. |
| C12 | "reseach oss, research design and u tooling and reusabke skills, nodules etc anythig yyou need to nake this a perfect 100/100 success" | Research OSS, design tooling, UX tooling. Build reusable skills and modules. Whatever it takes for 100/100. |
| C13 | "i want options and each option 1000/1000 so the hardest part of ny job will be picking which i prefer and they are all as good" | Give options. **Every option must be 1000/1000.** The founder's only difficulty should be preference, never quality. |
| C14 | "eanless annd fciritonless ultra user eperience also" | Seamless and frictionless. Ultra user experience. |
| C15 | "layout , structure, all creens, all devices, everything scienntific" | Layout and structure, on all screens and all devices. Everything scientific — measured, not asserted. |
| C16 | "piel ultrultra ultra is keyword, everything you do willbe nainun ultra ultra grade" | **Pixel.** "Ultra" is the keyword. Everything at maximum ultra grade. |
| C17 | "fron page to page the layou t nnust be seanless, user nust never notice anything off, presentation and polish 1000x better , ultra" | Page-to-page layout must be seamless. The user must never notice anything off. Presentation and polish 1000x better. |
| C18 | "also reeaserch how we can geet quality inages for free" | Research how to get quality images for free. |
| C19 | "our packs need sone quality grapihc" | The packs need quality graphics. |
| C20 | "think newspapers and engagenent, headine teaser, graphic/etc, snall content lining to page" + "linking" | Newspaper model. Engagement. Headline, teaser, graphic, a small piece of content **linking** to the full page. |
| C21 | "we need to engage user before we can sell, reseach psychology" | Engage the user **before** selling. Research the psychology. |
| C22 | "not ll the foundeers criteria, wirte it down and save it so you can reference, acceptance criteria nust be string and neasurabel and objectie annd subjectively obvious" | Write down all the founder's criteria and save them. Acceptance criteria must be **strong, measurable, objective — and subjectively obvious**. |

### The two hardest criteria, stated plainly

**C13 — every option is 1000/1000.** This forbids the usual "three concepts, one real, two straw
men". Each direction shipped must be complete, live, on real data, and defensible as the final
answer on its own. The founder picks on taste alone.

**C22 — objective AND subjectively obvious.** A criterion passes only when a machine can prove it
*and* a person can see it at a glance. A number nobody can feel is not enough; a look nobody can
measure is not enough. Both, every time.

---

## Part 2 — Acceptance criteria

Two tiers, per C22. **Tier A is machine-provable** — a command exits 0 or the criterion fails.
**Tier B is human-obvious** — a named person can see it in under 5 seconds without being told
what to look for. Nothing ships on Tier A alone; nothing ships on Tier B alone.

Status glyphs: ❌ not started · 🟡 partial · ✅ done with a receipt in the same row.

### Tier A — machine-provable gates

| ID | Criterion | Threshold | Proof command | Status |
|----|-----------|-----------|---------------|--------|
| A1 | **No horizontal overflow**, any screen, any route | 0 routes where `scrollWidth > clientWidth` at any tested viewport | design gate: overflow probe (to build) | ❌ |
| A2 | **No element collision** — no two non-nested elements overlap unintentionally | 0 unexpected bounding-box intersections per route/viewport | design gate: collision probe (to build) | ❌ |
| A3 | **No clipped or truncated text** | 0 elements where `scrollHeight > clientHeight` on text nodes without an explicit clamp | design gate: truncation probe (to build) | ❌ |
| A4 | **Tap targets** | 100% of interactive elements ≥ 44×44 CSS px on touch viewports (WCAG 2.2 AA 2.5.8 min 24×24; we hold the higher Apple bar) | design gate: tap-target probe (to build) | ❌ |
| A5 | **Viewport matrix coverage** | Every route rendered and probed at every viewport in the device matrix, ≥ 12 viewports from 320px to 2560px | screenshot matrix runner (to build) | ❌ |
| A6 | **Visual regression** | 0 unintended pixel diffs vs. approved baselines, deterministic across runs | Playwright `toHaveScreenshot` suite (to build) | ❌ |
| A7 | **Accessibility** | 0 axe-core violations at serious/critical, every route, both themes | `@axe-core/playwright` gate (to build) | ❌ |
| A8 | **Contrast** | Every text/background pair ≥ WCAG 2.2 AA (4.5:1 body, 3:1 large); computed from rendered pixels, not from the token file | contrast probe (to build) | ❌ |
| A9 | **Core Web Vitals** | LCP ≤ 2.5s, INP ≤ 200ms, CLS ≤ 0.1 — and our own tighter house bar: LCP ≤ 1.2s, CLS ≤ 0.02 | Lighthouse CI budgets (to build) | ❌ |
| A10 | **Navigation CLS** | CLS ≤ 0.01 measured *across a route change*, not just on load — this is C17 made numeric | navigation-jank probe (to build) | ❌ |
| A11 | **Grid continuity** | The same content column edges land on the same x-coordinates on every route, at every viewport, within 0.5px | grid-continuity probe (to build) | ❌ |
| A12 | **Token purity** | 0 hardcoded colours, 0 off-scale font sizes, 0 off-scale spacing values in application CSS/JSX; every value resolves to a token | stylelint + a token-conformance probe (to build) | ❌ |
| A13 | **No magic numbers** | 0 arbitrary Tailwind values (`[13px]`), 0 `!important`, 0 fixed pixel heights on text containers | lint rules (to build) | ❌ |
| A14 | **Bundle budget** | First-load JS per route within a declared budget; no route regresses without a deliberate raise | size budget check (to build) | ❌ |
| A15 | **Every look passes every gate** | A1–A14 pass for **each** design variant independently — C13's "all as good" made mechanical | gate matrix over variants (to build) | ❌ |
| A16 | **Real data only** | 0 placeholder strings, 0 lorem ipsum, 0 fake numbers in any rendered route — every figure traceable to the engine (C3) | content-provenance probe (to build) | ❌ |
| A17 | **Experiment assignment is sound** | Variant assignment is stable per visitor, evenly split within tolerance, and recorded with every conversion event | experiment harness tests (to build) | ❌ |
| A18 | **Zero-flicker variants** | No variant flash: the correct look is in the first paint, CLS contribution 0 | first-paint probe (to build) | ❌ |

### Tier B — subjectively obvious, judged on sight

Each is judged from a demo, at full size, on a real device, by a person who was not told what to
look for. The test is written so the answer is not arguable.

| ID | Criterion | The test |
|----|-----------|----------|
| B1 | **It looks expensive** | Shown beside three best-in-class reference sites, a stranger cannot tell which one is the small business. |
| B2 | **The front page reads like a front page** | A stranger given 5 seconds can say what the business does and name one specific story/pack they saw. (C20, C21) |
| B3 | **Nothing jumps** | Clicking through every route in sequence, a person is asked "did anything move, flash or resize?" — the answer is no. (C17) |
| B4 | **It is obviously the same site on a phone** | The phone and desktop views are recognisably one design, not a desktop design squeezed. (C15) |
| B5 | **The options are all good** | Shown all directions, the founder's stated reason for rejecting any of them is preference, never a fault. (C13) |
| B6 | **The graphics look commissioned** | Pack graphics read as designed for that pack, not as stock or as a template with the title swapped. (C19) |
| B7 | **You want to click** | A stranger scrolling the front page clicks at least one teaser unprompted. (C20, C21) |
| B8 | **Nothing is off** | A designer given 60 seconds to find a flaw in alignment, spacing or rhythm finds none. (C16, C17) |

---

## Part 3 — Research programme

Seven parallel tracks, all commissioned 2026-08-20. Findings land in `docs/research/` and are cited
by ID from the design decisions that use them.

| Track | Question | Serves | Status |
|-------|----------|--------|--------|
| R1 | Codebase truth: every screen, every token, every layout offender in the current build | C6, C8 | running |
| R2 | Design foundations: tokens (DTCG), fluid/intrinsic layout, Tailwind v4, typography, OKLCH colour, layout-bug prevention as engineering | C8, C15, C16 | running |
| R3 | Experimentation: OSS A/B platforms, Next.js variant delivery without flicker, statistics at low traffic, multi-theme architecture | C11 | running |
| R4 | Proof tooling: visual regression, multi-device probes, overflow/collision detection, a11y and perf gates, design lint | C15, C16, C22 | running |
| R5 | Conversion evidence + best-in-class visual sweep; the distinct design directions available | C4, C13 | running |
| R6 | Free quality imagery, licensing, public-domain archives; generative/programmatic pack graphics | C18, C19 | running |
| R7 | Editorial/newspaper design grammar + seamless page-to-page experience (view transitions, persistent chrome, motion) | C17, C20 | queued |
| R8 | Engagement psychology: first impressions, attention, curiosity, trust without sleaze, pricing psychology, dark patterns to avoid | C21 | queued |

---

## Part 4 — Decisions log

Append-only. Every entry: the decision, the criterion it serves, the evidence, and what it
overrides. C5 permits overriding any previous decision; the override must be recorded here.

| Date | Decision | Serves | Evidence | Overrides |
|------|----------|--------|----------|-----------|
| 2026-08-20 | Work proceeds on `design/storefront-v2` off `origin/main` @ `8f6e0805`, in its own worktree | C1 | `git worktree list` | — |
| 2026-08-20 | This file is the contract; `docs/SITE_SPEC_PROGRAM.md` and `docs/MOBILE_DESIGN_BRIEF_2026-08-15.md` are inputs, not constraints — C5 permits overriding both | C5, C22 | founder directive C5 | prior spec's binding force |

---

## Part 5 — Demo log

C10 requires demoing often. Every demo: what was shown, the link, and what the founder said.

| Date | What | Link | Verdict |
|------|------|------|---------|
| — | — | — | — |

---

## Part 6 — criteria added after the first demos (2026-08-20)

These arrived while directions 1 and 2 were on screen. C23 is not a preference; it changes the
architecture, so it is recorded before anything is built against it.

| # | Founder's words | What it means here |
|---|---|---|
| C23 | "the end goal is 10 different 1000/1000 looks that we can choose dynanically fron the ops console and be applied inneduately" | Ten looks, not three. Chosen at RUNTIME from the ops console. Applied with no rebuild and no deploy. |
| C24 | "also a nini content nanagenet systenn, ocheck if anything oss eists also" / "we need to edit content without deploying" | Copy, headlines, teasers and pack blurbs are editable without a deploy. Research OSS before building anything. |
| C25 | "open source to assist" / "the nore toling the better" | Prefer existing open-source tooling over hand-rolled. More instrumentation is wanted, not less. |

### What C23 does to the design

**Ten looks must never be ten forks.** Ten hand-built pages is precisely the exhausting redo C7
names: every future change is paid for ten times, and the tenth look is always the stale one. So a
"look" is DATA, not a copy of the site:

    look = design tokens          (colour, type, scale, rule weight, radius, density)
         + a small set of switches (hero mode, card mode, plate renderer, rule style)
         + optional scoped CSS    ([data-look="ledger"] { ... }) for the structural difference
                                   a token cannot express

One component tree renders all ten. The ops console writes the active look name; the site reads it
and stamps `data-look` on the root. That makes A/B testing (C11) a consequence rather than a second
system: assignment picks a look name, and the same mechanism delivers it.

### Acceptance criteria added

| # | Gate | How it is proved |
|---|---|---|
| A19 | Switching looks requires no rebuild and no deploy | Change the look in the ops console; the next page load serves it. Measured as elapsed seconds from save to served, target < 5s. |
| A20 | A look switch causes no flash of the previous look | First paint already carries the correct `data-look`. Proved by a Playwright trace: no frame shows look A after the switch to B. |
| A21 | All ten looks pass every Tier A gate independently | The probe matrix runs once per look. 10 looks x 13 routes x 12 viewports. A look that fails any gate is not shippable, which is C13 made mechanical. |
| A22 | No look forks a component | One component tree. A test fails if a component file references a specific look name outside its token map. |
| A23 | Copy is editable without a deploy | Edit a headline in the CMS; the live site serves the new text with no build. Same < 5s measure as A19. |
| A24 | Editing copy cannot break the layout | Every editable string has a declared length budget; the probe's overflow, collision and truncation checks run against the longest permitted value, not the current one. |

### C24 is wider than copy (founder, 2026-08-20: "swap grpghics etc" / "colors" / "font")

The ops console edits the DESIGN, not only the words. Four things are editable live, with no deploy:

| Editable | What it means | Where it lives |
|---|---|---|
| Copy | headlines, teasers, decks, labels, CTA text, pack blurbs | content store |
| Colour | every colour token in the active look, both themes | look store |
| Type | display / body / mono family, the scale, weights, letter-spacing | look store |
| Graphics | the plate renderer per look, and any uploaded or sourced image | asset store + look store |

So a "look" is fully editable data, and the ten shipped looks are STARTING POINTS rather than fixed
options. The founder can take The Ledger, change its ink to indigo, swap Bodoni for Fraunces and
switch the plate renderer to stipple, and that is an eleventh look with no code written.

### Acceptance criteria added for the design control plane

| # | Gate | How it is proved |
|---|---|---|
| A25 | Colour, type and graphics are editable live | Change each of the three in the console; the next page load serves it, < 5s, no rebuild. |
| A26 | An edited look cannot ship a contrast failure | The console re-runs the contrast check on the edited palette before it can be saved. A palette that fails 4.5:1 is refused at save time, not caught later by a probe. |
| A27 | An edited look cannot ship an unloadable font | The console verifies the family resolves and a fallback stack exists before save. |
| A28 | Every edit is reversible and attributed | Each saved change records who, when, what changed, and restores to the previous value in one action. |
| A29 | The repo stays the complete system | The looks, the copy and the assets are files in the repo, and the console writes to them. A fresh clone plus an env file still renders every look. This is the surviving half of the project's hosting rule. |

### C26 — reusable, not mumchimp-shaped (founder, 2026-08-20)

"rhe nore tooling we can find to he beter ain for resuability" / "adaptable to any new project"

The look engine, the design probe, the gates and the ops console are built as a PORTABLE package.
Nothing in them may know what mumchimp sells. The split:

| Portable (goes to any project) | Project-specific (stays here) |
|---|---|
| the look engine: token contract, look packages, runtime switch | the ten look definitions themselves |
| the design probe + the Tier A gates | the route list and viewport matrix values |
| the plate renderer interface | the plate renderers that draw pack evidence |
| the ops console: edit copy, colour, type, graphics | the content schema for packs and kills |
| the A/B assignment + measurement harness | which looks are in the experiment |

| # | Gate | How it is proved |
|---|---|---|
| A30 | The engine carries no project knowledge | A test greps the portable package for project nouns (pack, kill, catalogue, mumchimp) and fails on a hit. |
| A31 | It installs into a bare project | A fresh Next.js app plus the package renders a working look switch with the default look, with no edits to the package. |

---

# Part 7 — Criteria C27–C31, added 2026-08-20 (imagery, craft, and the benchmark)

Founder's words, verbatim, in the order they arrived:

- **C27** — "inages cant be the sane for allpacks no nno" / "we need to hvee relevaant ad
  approptiate inage per pack" / "cant repeat the sane graphic anywheree on the site".
- **C28** — "we need etrene creativity and extrene craft" / "and exterene reusability".
- **C29** — "we need rsearch nd oling" / "to geerate the highest wualiy possible".
- **C30** — "etrene and ultra polish" / "nust be better than aany bainstraan outlet" / "and
  neaasurablly so" / "not even close bbyfar".
- **C31** — "not eveery thig four says". A research agent's recommendation is evidence, not an
  instruction. Take what is proven, drop the rest, and say which is which.

Also standing, from the same exchange: "we are zealots", "we go all the way to vicory",
"note it downw", "we nust never forget".

## What C27 actually rules out

It kills the answer this program was heading toward. Deterministic seeded artwork gives every
pack a DIFFERENT picture, but it gives every pack the SAME KIND of picture — an abstract mark
whose geometry happens to be seeded by that pack's numbers. A buyer reading about scaffolding
permits sees a pattern, not scaffolding. C27 says the picture has to be ABOUT the pack.

It also rules out stock photography, twice over. The licence tier is wrong (Unsplash and Pexels
both forbid galleries and unaltered resale, in their own words) and the register is wrong: a
photograph of somebody at a laptop is exactly the mainstream look C30 says to beat.

## The decision: SUBJECT × TREATMENT

A pack graphic is two independent choices, and neither one alone can satisfy both C27 and C23.

- **SUBJECT** — a real archival plate matched to what the pack is about. Scaffolding permits get
  an 18th-century engraving of erected scaffolding; a cold-chain audit gets a wall thermometer;
  chargeback defence gets a balance scale. Sourced CC0, so there is no attribution debt and no
  revocation risk.
- **TREATMENT** — how the ACTIVE LOOK renders that subject: halftone, threshold, stipple,
  dither, engraved hatch, duotone, blueprint invert, woodcut. The subject is the pack's; the
  treatment is the look's.

77 packs × 10 looks is 770 distinct images and no repeats, which is C27 satisfied by
construction rather than by discipline. It is also C28's reusability: the treatment layer knows
nothing about packs, and the subject layer knows nothing about looks.

## Sources, measured 2026-08-20, not quoted from a summary

| Source | Licence | Key | Verified reachable |
|---|---|---|---|
| **The Met Open Access** | CC0 1.0 where `isPublicDomain: true` | none | YES — searched, fetched, CC0 items returned with `primaryImageSmall` URLs |
| Rijksmuseum | CC0 / PDM for out-of-copyright works | none | not yet probed |
| Smithsonian Open Access | CC0 1.0 | free key, 1,000/hr | not yet probed |
| NASA / NOAA / USDA | US public domain, 17 U.S.C. §105 | none | not yet probed |

Deliberately NOT used, with the reason: **Unsplash and Pexels** — their own licences forbid
compiling galleries and reselling unaltered, and the look is wrong. **BHL on Flickr** — "no
known copyright restrictions" is explicitly not a grant, and most of that collection is
commercially barred. **NYPL Repository API** — its terms restrict it to non-commercial use and
it carries a deprecation notice dated 2026-08-01, already passed. **Openverse / Wikimedia /
Internet Archive** — search layers over other people's rights statements, so every item needs
its own check before it ships; usable, but never on a blanket assumption.

## New acceptance gates

- **A32 — no graphic appears twice.** A test hashes every rendered image on the site and fails
  if any hash occurs more than once. Not "we were careful"; a hash collision fails the build.
- **A33 — every pack graphic is topically matched.** Each pack carries a named subject and the
  accession record it came from. A pack whose subject is unset fails the gate, so the fallback
  can never quietly become the site.
- **A34 — every graphic's licence is recorded and is CC0 or statutory public domain.** The
  record carries source, accession id, and licence string. Anything else fails the gate.
- **A35 — the treatment layer names no pack and the subject layer names no look.** A grep test,
  the same shape as A22 and A30.
- **A36 — MEASURABLY better than mainstream outlets.** C30 is only real if it is a number, so
  the design probe runs unchanged against a named benchmark set and our figures must beat every
  one of them on every census metric: distinct font sizes, distinct line-heights, distinct
  spacing values, contrast failures, sub-24px tap targets, and grid continuity spread. The
  benchmark set is written down so it cannot be chosen after the fact: nytimes.com,
  theguardian.com, ft.com, economist.com, bloomberg.com, stripe.com, linear.app.
  "Better" means strictly lower on every defect count, with the numbers published in this doc.

## C31 in practice

Four research agents have reported. What was taken and what was dropped:

- **TAKEN** — the CC0 source tier and its traps (Met/Rijksmuseum/Smithsonian clean; BHL, NYPL,
  Unsplash, Pexels not). Verified independently against the Met API before use.
- **TAKEN** — mulberry32 over `seedrandom` (dead upstream since 2019).
- **TAKEN** — the Unbounce reading-level finding, because the sample is 41,000 pages: plain
  short copy on the storefront, analyst register inside the pack.
- **TAKEN** — a separate linkable methodology page, the way Forrester does it.
- **DROPPED** — the decoy pricing tier. Two JMR replications find the effect at chance levels
  once any attribute is verbal or pictorial, which is our pricing table.
- **DROPPED** — the three-tier pricing rule. The vendor most credited with it publishes no data
  for it.
- **DROPPED** — every subscription-analytics vendor's willingness-to-pay figure (the
  20%-from-design one
  especially). No sample, no method, no underlying study.
- **DROPPED for now** — satori/@vercel/og as the render path. It is build-time JSX-to-SVG with
  a 500KB bundle cap and no CSS Grid, and our graphics are canvas pixel work, not layout.

---

# Part 8 — Criteria C32–C34, added 2026-08-20 (the method itself is the deliverable)

Founder's words, verbatim:

- **C32** — "all research tooling, sources, skills, everything used in this exerinent nusst be
  docunented for future reusability and conposed ttogether with a view o aautonate the process
  of wwhaat we did today. generating website layout for any website" — with the honest caveat
  he added himself: "but that is a bbigger idcusstion that needs fleshi g out".
- **C33** — "we need to iteerate n logo".
- **C34** — "a/b test" — the tooling must be live, not planned. This restates C11 and now applies
  to the logo and to the ten looks, not only to copy.

## What C32 changes

It makes the METHOD a deliverable alongside the site. Every tool, source, prompt and gate used
in this redesign has to survive as something a future project can run, not as a description of
what happened once. Concretely, three things have to come out of this work:

1. **A tool ledger** — every script written here, what it measures, and how to run it. The
   design probe, the contrast solver, the overflow walker, the browser verification matrix, the
   subject fetcher, the treatment renderers.
2. **A source ledger** — every research source consulted, what was TAKEN from it and what was
   DROPPED, so a future project inherits the judgement and not just the links. C31 already
   requires the taken/dropped split; C32 requires it to be written where another project can
   read it.
3. **A composed pipeline** — the sequence run today, expressed as steps a future project can
   execute: measure the existing site, extract the token contract, generate N looks as data,
   gate them on contrast, verify across the device matrix, source the imagery, treat it per
   look, publish demos.

The generalisation to "generating website layout for any website" is deliberately NOT designed
yet. The founder flagged it as needing its own discussion, so the discipline here is to build
the pieces so that generalising them later is possible, and to resist inventing the general
system before the specific one is proven. Gate A26 already forces the direction: nothing in the
engine may name this project.

## New acceptance gates

- **A37 — the tool ledger is complete.** Every script in the redesign has an entry naming what
  it measures, its inputs, and its exact invocation. A script with no entry fails the gate.
- **A38 — the source ledger records taken AND dropped.** Every research source has a verdict.
  A source listed without one fails the gate, because an unjudged source is C31's failure mode.
- **A39 — the pipeline runs end to end on a project that is not this one.** The honest test of
  C26 and C32 together. Until it has been run once against a different site, the reusability
  claim stays marked `unverified` in this document.
- **A40 — the logo is iterated, not inherited.** Multiple candidates, measured against the same
  bar as the ten looks: legible at 16px, works on both grounds, works in one colour, and does
  not require the wordmark to be readable to be recognisable.
- **A41 — the A/B harness is live before launch, not after.** A look, a headline and a logo can
  each be assigned and measured. Shipping ten looks with no way to tell which one sells is the
  failure this gate exists to prevent.

---

# Part 9 — Criterion C35, added 2026-08-20 (ten is a sample, not the target)

Founder's words: "recall we nay have 10 but thzeie zenith of boss gals is to generate ay nany as
you want, hence he cns side of it."

Ten looks was never the goal. The goal is an engine that generates as many as anyone wants, from
the console, and the ten are the proof it works. This is the single most consequential criterion
so far, because it invalidates the way the first ten were built.

## What it invalidates

Two things in the build to date do not survive contact with C35.

**Hand-picked palettes.** Each of the ten carried 32 hand-chosen hex values (16 tokens x 2
themes). That is 320 decisions for ten looks, and it is 3,200 for a hundred. Worse, the contrast
gate then found 19 failures among them and a solver had to walk them back — the hand-picking was
not just slow, it was WRONG, and it was wrong in a way that only a machine caught.

**Structural CSS keyed on look names.** Rules of the form `[data-look="ledger"] .masthead { … }`
cannot generalise: an eleventh look gets no structure at all until somebody writes it CSS, so
the eleventh look is a palette swap of an existing one by construction. This is also exactly
what an adversarial review found and named, independently, before C35 arrived: "ten skins, not
ten looks."

## The replacement

**A look is a SEED plus a SWITCH SET, and everything else is derived.**

- **The seed** is a handful of perceptual decisions — ground lightness, ground hue and chroma,
  accent hue and chroma, contrast target. The 16 tokens are DERIVED from it in OKLCH, then fitted
  against the contrast table until every pair passes. A generated look cannot be inaccessible,
  because the fit is what produces it. This is the difference between a gate that REFUSES bad
  output and a generator that cannot EMIT it.
- **The switch set** is a choice per structural axis — masthead, hero, catalogue, rule weight,
  heading case, figure treatment, opening initial, chrome. The CSS keys off the AXIS VALUE,
  never off a look name, so a new look composes structure that already exists.

With eight axes at three or four values each, the switch space alone is in the thousands, and
the seed space is continuous. "As many as you want" becomes literally true, and every one of them
is contrast-fitted before it renders.

## New acceptance gates

- **A42 — no CSS rule may name a look.** `grep '\[data-look=' ` returns nothing. A rule that
  names a look is a rule the eleventh look does not get.
- **A43 — no look may carry a hand-written colour.** Every token is derived from the seed. A hex
  literal in the look table fails the gate.
- **A44 — a randomly generated seed passes the contrast table.** The test generates N random
  seeds, derives and fits each, and asserts zero failures. This is the machine-checkable form of
  "every look is 1000/1000": the floor is proven for looks nobody has looked at.
- **A45 — the console can add a look without a deploy.** The end state of C23 and C24 together.
- **A54 — a look nobody designed survives the whole browser gate.** The roll button mints a look
  from a fixed seed, and that look goes through the same eight browser checks as the ten designed
  ones. Ten hand-built looks only ever demonstrate ten hand-built looks; C35's claim is "as many
  as you want", and it stays unproven until an unseen one passes. Numbered 54, not 46, because
  A46 is the cold-open test above and a green "A46" here would have read as evidence for a
  criterion nobody has started.

---

# Part 10 — Criteria C36–C38, added 2026-08-20

## C36 — the first-time visitor is the only visitor who matters

Founder's words: "we need to this about first tine visitoors alreday, suprised adverserial reivew
did not consider first tine userexperince, shows we are not being ultr."

He is right and the miss is worth naming precisely, because it is a CLASS of miss rather than an
oversight. The adversarial review was pointed at the ARTEFACT — type scales, accent hues, grid
shapes, contrast pairs — and every finding it returned was true. Not one of them was about a
person arriving cold. A review that grades the thing instead of the encounter will always come
back clean on exactly the failure that costs the most money.

Everyone building this has seen the site hundreds of times. That is the disqualifying
qualification: we cannot experience the first five seconds any more, so the first five seconds
have to be graded by a procedure rather than by looking.

**The five questions, in order, and the second they must be answered by:**

| # | The visitor's question | Answered by | Where |
|---|---|---|---|
| 1 | What is this? | 2s | above the fold, without scrolling, at 320px |
| 2 | Is it for me? | 5s | above the fold |
| 3 | Why should I believe you? | 10s | first scroll |
| 4 | What exactly do I get? | 20s | first scroll |
| 5 | What does it cost and what if I am wrong? | 30s | second scroll |

**Gate A46 — the cold-open test.** Render the top viewport at every device in the matrix, with
NO scroll, and assert that the visible text answers Q1 and Q2. Machine-checkable form: the
first-screen text must contain the product noun, the buyer noun, and the outcome verb, and must
NOT require a hover, a click or a scroll to do it.

**Gate A47 — the five-second reconstruction.** A reader who has seen only the first screen must
be able to state what is sold and to whom. Run it as a written procedure against a person who has
never seen the site, once per look.

**Gate A48 — no unexplained jargon above the fold.** "Kill log", "pack", "moat", "rung",
"dossier" are OUR words. Each may appear above the fold only if the same screen defines it.

**Gate A49 — the entry costs nothing.** A first-time visitor must reach real evidence — a whole
sample, not a teaser — with no account, no email and no payment. Measured as: clicks from the
landing screen to a complete artefact, target 1, ceiling 2.

## C37 — a second sample set: structure and behaviour, not skin

Founder's words: "even the thene kill log etc, and sane graphic, need to get nad creative and
ocne up wuth original ideas set … which basically looks at the engine and brianstorns new ideeas
for narketig and conversiion so totally new look and aldo tructure nd behiur to naxiaise
enganenet and sles and conversion, this is a separate saetof sanples … ttally diffrent graphics,
ideas etc … nothing repeated … i want infinte choices lol."

The ten looks vary PRESENTATION against a fixed page. This second set varies the PAGE: what
sections exist, what order they run in, what the first screen does, what the site asks the
visitor to do, and what the graphics are made of. Two independent axes, deliberately kept
independent so they multiply rather than duplicate:

- **Axis 1, the look** — palette, type, structural switches, image treatment. Ten now, N later.
- **Axis 2, the pitch** — section set, section order, first-screen device, call to action,
  evidence strategy, graphic vocabulary. A separate sample set with its own names.

A pitch is not a look with different colours. It is a different ARGUMENT about why someone should
buy, and it is allowed to delete sections the other pitches consider essential.

**Gate A50 — no graphic vocabulary is shared between pitches.** The kill log's chart in pitch A
may not appear in pitch B in any form. Enforced by the same rendered-image hash test as A32.

**Gate A51 — each pitch names its conversion thesis in one sentence**, and that sentence must be
falsifiable by the A/B harness. A pitch that cannot lose is not a hypothesis.

## C38 — never settle; keep the samples

Founder's words: "retain the sanples oce perfected as i do like then but need even nore etrene
polish first, dont ever attenpt to settle, poush the bar even higher in allwatys possible, even
the laws of physcis cant stop us."

The ten survive. They are not scaffolding to be thrown away once the generator exists; they
become the generator's first ten seeds, so their identity is preserved while the hand-picked
colour is not. Polish continues on them after the generator lands, not instead of it.

---

# Part 11 — C39: every page, or it is not a design system

Founder's words: "ensure no cuurent page on webite is left out, every sigle pge, i dot want to
ever build a ui fro cratch evr again. everything needs to be accounted fir for productio n redy
nextj webite."

A design that covers the landing page is a mood board. A design that covers the 404, the order
receipt and the auth callback is a system. The difference shows up exactly once — the day
somebody needs a page nobody drew, builds it by hand, and the estate is back to where it started.

**The inventory, measured 2026-08-20** from `store_platform/src/Store.Web/src/pages` — 29 files,
of which 22 render to a human:

| Route | File | Covered by the design system? |
|---|---|---|
| `/` | `index.tsx` | yes — the ten looks |
| `/pack/[id]` | `pack/[id].tsx` | **NO — reported missing by the founder** |
| `/pricing` | `pricing.tsx` | not yet |
| `/sample` | `sample.tsx` | not yet |
| `/kill-log` | `kill-log.tsx` | partial — the panel exists on the landing page |
| `/ideas` | `ideas/index.tsx` | not yet |
| `/ideas/[slug]` | `ideas/[slug].tsx` | not yet |
| `/how-it-works` | `how-it-works.tsx` | not yet |
| `/faq` | `faq.tsx` | not yet |
| `/about` | `about.tsx` | not yet |
| `/account` | `account/index.tsx` | not yet |
| `/orders/[token]` | `orders/[token].tsx` | not yet |
| `/orders/success` | `orders/success.tsx` | not yet |
| `/auth/callback` | `auth/callback.tsx` | not yet |
| `/terms` `/privacy` `/refund` | three files | not yet — one long-form template serves all three |
| `/404` `/500` | two files | not yet |
| `_app` `_document` | two files | shell, not a page |
| `/og/pack/[id]` | `og/pack/[id].tsx` | image endpoint — needs a look-aware design |
| `robots.txt` `sitemap.xml` `llms.txt` `indexnow-key.txt` | four files | machine routes, excluded |
| `/api/*` | three files | machine routes, excluded |

**Gate A52 — page coverage.** Every human-facing route above renders in every look with zero
bespoke CSS. Machine-checkable: the design probe walks the route list and fails on any route
whose stylesheet needs a rule that exists for that route alone.

**Gate A53 — the six page ARCHETYPES.** Twenty-two routes are not twenty-two designs. They
reduce to six templates, and a new page must fit one of them or the template set is wrong:
catalogue, artefact, long-form, transactional, account, and status. `/terms`, `/privacy` and
`/refund` are one template with three contents; `/404` and `/500` are one; `/orders/success`,
`/orders/[token]` and `/auth/callback` are one.

---

# Part 12 — The pack page evidence brief (research, 2026-08-20)

Retrieved from primary sources. Each line is here because it changes a decision on the page.

**Trust, when nobody has heard of you.** Fogg et al., CHI 2001, N=1,410, item means on a −3..+3
scale — the best-evidenced thing in the whole programme:

| Raises credibility | | Destroys credibility | |
|---|---|---|---|
| physical address | **+1.86** | ads indistinguishable from content | **−2.08** |
| contact phone number | +1.71 | rarely updated | −1.67 |
| searchable archive | +1.57 | **a single broken link** | **−1.45** |
| looks professionally designed | +1.55 | difficult to navigate | −1.30 |
| **author credentials** | **+1.49** | **a single typographical error** | **−1.28** |
| **citations and references** | **+1.49** | domain doesn't match the name | −1.06 |
| links to outside sources | +1.25 | **requires a paid subscription** | **−0.71** |
| **links to COMPETITORS** | **+1.11** | | |
| few stories, detailed each | +1.10 | | |
| an award badge | +0.45 | requiring registration | +0.07 |

Read the bottom two rows together: a badge and a signup wall are worth approximately nothing,
and the cheapest large wins are an address, a phone number, named credentials and citations. We
already produce citations by the hundred — the page has simply never counted them out loud.

**Section order for a self-serve price point.** Nine of ten report sellers retrieved live.
Self-serve sellers (Statista $495, Leanpub $19–39, NN/g $149) put **price early, proof late**;
enterprise sellers (Gartner, Forrester, IBISWorld) put **proof first, price never**. At £39–£249
we are unambiguously self-serve, so price goes above the fold. Nine of nine show a hard scope
number (47 pages, 127 pages, 184 pages / 36,254 words, 611 pages). Only ONE of ten showed a
money-back guarantee and only one an explicit "who this is for" — both are ours to take.

**What a buyer cannot see, they assume is missing.** Baymard: 63% of test users could not tell
whether a product included its accessories when no image showed them; 31% of sites never show
one. Only **3%** of sites provide a summary of the critical specs; 50% have spec sheets that are
hard to scan. This is the argument for showing the pack's interior, not describing it.

**Reading budget.** NN/g, 45,237 page views: users read at most 28% of the words, 20% is more
likely; half the information is read only on pages of **111 words or less**; time on page ≈ 25s
+ 4.4s per additional 100 words. Every section on this page is written against that budget.

**Price comparison is a legal claim, not a rhetorical one.** UK CTSI/CMA guidance: a third-party
comparison requires the competitor's identity, product and circumstances on record, monitored,
and withdrawn if their price moves. So the IntoTheMinds €4,000–6,000 line is a **cited footnote
with a date**, never a strikethrough. (GB has NOT adopted the EU 30-day-lowest-price rule.)

**Refunds are law before they are marketing.** UK Consumer Contracts Regulations 2013, reg 37:
for digital content the 14-day cancellation right is lost ONLY if the trader obtained express
consent to begin supply during the period AND acknowledgement that the right is thereby lost.
Miss either and the consumer owes nothing. Placement evidence: 44% of sites never link the
return policy from the product page, and a distinct subgroup goes to the FOOTER for it
regardless — so it belongs in both places.

**Free-sample convention.** Amazon KDP is a fixed 10% for ebooks, 20% for print; Google Books is
publisher's choice 20–100%; Leanpub has no default. The 10–20% band is a trained expectation,
not a measured optimum, and should be described as such.

**Banned outright.** Countdown timers and limited-time claims that are not true: UK Digital
Markets, Competition and Consumers Act 2024, Schedule 20 para 7, in force 6 April 2025, makes
falsely stating limited availability "in order to elicit an immediate decision" an unfair
practice. Para 13 bans fake reviews and publishing reviews "in a misleading way", including
hiding the negative ones. US equivalent: 16 CFR Part 465, effective 21 October 2024.
**Carousels** are banned on evidence rather than law: measured across 315,665 rotations, ~1% of
visitors clicked any slide and 84% of those clicks landed on slide one.

**Claims deliberately DROPPED under C31** — they circulate widely and none survived a source
check: "users expect N product images"; any countdown-timer lift figure; guarantee-placement
pixel rules; any optimal refund duration; any optimal giveaway percentage; "an implausible price
anchor backfires" (the one retrievable study, Urbany et al. 1988, found the opposite); "unknown
trust seals hurt"; "blurred previews create converting curiosity"; "7-day trials beat 30-day".

## Parked — low priority (founder, 2026-08-20)

- **C40 — modularise auth and payments, and make the flow seamless.** Raised then
  immediately deprioritised in the same session ("sorry lowest priority that one",
  "not important"), so it is recorded here rather than worked. What is on disk today:
  auth reaches the API through `Store.Web/src/lib/api/auth.ts` and identity lives at
  `Store.Catalog/Domain/Identity/StoreUser.cs`; payments are Stripe, entered through
  `Store.Web/src/lib/preopenedCheckout.ts` with `stripeReachable.ts` as the liveness
  probe and `Store.Catalog/Domain/WebhookEvent.cs` on the return leg. Whether either
  has a real abstraction is UNMEASURED — the scan that would answer it was stopped
  when the founder deprioritised the job. Do not start this without asking.

## C32 tool ledger — the gap, recorded 2026-08-20

The tool ledger C32 asks for is **not written**, and this note exists so the next session does
not assume it is.

Four research files ARE on disk and are the model for the rest, under
`docs/storefront/look-engine/research/`: `colour.md` (the OKLCH contrast measurements and the
solve-verify-repair ladder), `woodcut.md`, `riso.md` and `riso-inks.json`. Each states what was
retrieved, from where, and what the measurement was — not an opinion about a tool.

The missing half is the visual-QA / accessibility / A-B / CMS tooling sweep. The agent running
it died on an API error partway through, before it wrote anything: its transcript is
`4e54f2a4-6ac5-41bf-88eb-cd2653f9da7f/tasks/aecf7de06f378a897.output`, which holds 43 raw search
results and **three assistant text blocks totalling 230 characters, none of them a finding**. The
raw passages are salvageable but unsynthesised; re-running one focused agent is cheaper than
mining them.

What that agent's failure also proves, and what belongs in the ledger when it is written: it
spawned three sub-agents of its own, which is what saturated the machine-wide fence at CAP=3 and
made the next Explore call refuse. A research plan that fans out has to count the agents it will
create, not the ones it directly calls.

## The automation ledger — C32's answer, built 2026-08-20

`docs/storefront/look-engine/tools.html`, generated by `tools.mjs`, which
`docs/storefront/look-engine/build.sh` runs. It lists every
`*.mjs` and `*.sh` in the workspace, what each one is for **in its own words**, and the whole of
its last log with the exit code — not a summary of a run, the run itself.

Three things are derived so none of them can drift: the tool list is the directory; each
description is the tool's own `@ledger` tag and leading comment; each result is the real file in
`logs/`, written by `runlog.sh`. A tool with no tag shows as UNCLASSIFIED, a tool with no log as
NOT RUN. Both are louder than an omission, which is the failure mode of every hand-kept list.

Four classes, and the class decides whether the build may run it: `read-only` runs every build,
`writes` produces an artifact, `mutates` rewrites source (`solve.mjs`, `patch.mjs` both rewrite
`parts/03-looks.js`) and `network` calls an external API (`fetch-subjects.mjs` refetches 443 KB
from the Met). The last two are never run automatically, which is why they are marked rather than
merely absent.

### Three gate defects the ledger surfaced, all the same class

Writing the logs down is what exposed them. Each was a gate that graded the wrong thing and said
so with a green exit code.

1. **`verify.mjs` judged a canvas blank from one pixel row.** `raster` marks rows where
   `y % 3 === 0`, so at tablet-834 the plates are 208×130, mid-row 65, `65 % 3 === 2` — empty by
   design. It read as 6 blank plates on The Instrument at that width alone. Measured before
   changing anything: the failing size draws 846 marks per sampled rows, 9.24%, against 10.06% at
   663×414. It now reads the whole buffer.
2. **`overflow.mjs` reported 6 escaping elements at 320px** on a page whose `scrollWidth` equalled
   its `clientWidth` at every width. They were the look-switcher's chips, inside an
   `overflow-x: auto` strip that is supposed to scroll. 6 findings, 0 real. It now walks ancestors
   and exits non-zero on a real one: `ALL PASS — no sideways scroll and no escaping element at 7
   widths`.
3. **`runlog.sh` named every log after the interpreter**, so `node check.mjs`, `node
   palette-test.mjs` and `node overflow.mjs` all wrote `logs/node.log` and silently overwrote each
   other. Three tools, one log, no error.

The class is **a gate that grades a proxy for the thing it claims to grade** — one row for a
picture, one rectangle test for "does the page scroll", one argument for "which tool ran". Each
passed its own check while the check meant nothing, and the only reason any of them surfaced is
that the ledger forces the output to be read rather than glanced at.

### One thing found on the way, not fixed, and not mine to fix

The `CLAUDE.md` being injected into sessions started in `scratchpad/wt-storeroot` is **in no git
branch**. That directory is an orphaned worktree — its `.git` is an 81-byte file pointing at
`.git/worktrees/wt-storeroot`, which does not exist, so every git command there says "fatal: not
a git repository". Its `CLAUDE.md` is 234 lines against `origin/main`'s 225, and the two diverge
in both directions.

It matters because of what it says. That file tells every session that **`ruff` runs REPO-WIDE
(`scripts/popdd_verify.py:166`)**. Both halves are false: `scope_ruff` at
`scripts/popdd_verify.py:352` points ruff at the `.py` files in the commit, applied at `:759`,
falling back to repo-wide only when there are no paths (`:372`); and `:166` is inside
`_parse_pytest`. The copy of CLAUDE.md on `origin/main` mentions ruff nowhere at all. A session whose commit is
refused reads that sentence and goes hunting for somebody else's untidy file instead of opening
its own diff.

Surfaced to the founder rather than edited: it is a rules file, and correcting it is reconciling
two divergent copies, not a one-line fix.

---

# Part 13 — C35 delivered: the ten looks own seeds now (2026-08-20)

Part 9 said a look must be a seed plus a switch set. As of today it is. The numbers below come
from the tools' own logs in the look-engine scratchpad, not from recollection.

## What changed on disk

- **`parts/03-looks.js`** — every look lost its `light:{16 hex}` and `dark:{16 hex}` blocks and
  gained a `seed:{}` of about 40 perceptual numbers plus a `switches:{}`. Measured by the
  converter: **13,646 bytes of hex became 13,949 bytes of seed**, across ten looks, with
  **0 pair failures, 0 tokens drifted past 0.06 lightness or 12 hue degrees, 0 structural
  changes**. The ten `dot:'#XXXXXX'` picker swatches went too — the chip now paints itself from
  the look's own resolved accent, so a swatch cannot lie about the look it opens.
- **`parts/06-structural.css` → `parts/06-switches.css`** — the same 17 declarations, re-keyed
  from `[data-look="ledger"]` onto `[data-masthead="centred"]` and eleven more axis values.
  `applyLook` clears every known switch attribute and then sets the ones this look declares, so
  a look that says nothing about mastheads gets the default rather than the last look's.
- **`handpicked.json`** — the 320 original hex values, kept deliberately. It is the reference the
  regeneration report grades against.

## The conversion refused itself once, and that is the story

The converter's first run **refused to write**: The Quiet's `hairStrong` moved from `#8B8B86` to
`#1A1A18`, a lightness drift of 0.418. The cause was two lines that assumed rather than measured.
`derive()` hardcoded `hairStrong: ink`, and `fit()` re-mirrored it onto the ink unconditionally,
so any look whose strong hairline was its own colour lost it on the way through.

The fix is the general form: **a mirror is a token that came in EQUAL, not a token that is
usually equal.** `fit()` now mirrors a token onto another only when the two were equal in the
palette it received. The seed recovers `hairStrongL` only when the strong hairline is not the
ink. Second run: zero drift on all 16 tokens of all ten looks in both themes.

## Gate status

| Gate | Verdict | Measured |
|---|---|---|
| A42 — no CSS rule may name a look | **PASS** | 0 rules name a look; 12 switches declared across 10 looks, all implemented |
| A43 — no hand-written colour in a look | **PASS** | 400 pairs (10 looks x 2 themes x 20) green; 0 hex literals in the look table; 10 of 10 own a seed |
| A44 — a random seed passes the table | **PASS** | 2,000 random seeds x 2 themes x 20 pairs = **80,000 assertions**, 0 failing; tightest margin 1.000x |
| A45 — console adds a look without a deploy | **PASS** | `persist.mjs`: rolled over http, survives a reload, opens from `?look=roll-N` on a browser that has never rolled, and can be forgotten |
| A54 — an undesigned look passes the browser gate | **PASS** | 104 cells (10 designed + 3 rolled x 4 viewports x 2 themes), 0 failures, 19,552 painted leaves compared |
| A46 — the cold-open test | **PASS** | `coldopen.mjs`: 40 first screens (10 looks x 4 widths, 320px included). Product noun, buyer address, outcome verb, headline and both buttons above the fold in all 40 |
| A48 — no unexplained jargon above the fold | **PASS** | 0 of our words used above the fold without a definition on the same screen |
| A49 — the entry costs nothing | **PASS** | 2 clicks from the landing screen to a whole sample; ceiling 2, target 1 |
| A47 — the five-second reconstruction | not run | a written procedure against a person who has never seen the site; no machine form exists |

**A42 is two gates, because one half is a proxy.** A stylesheet with no look name in it can still
be ten forks under different attribute names, and a look can declare a switch no stylesheet
implements — which does nothing, silently, forever. The gate therefore also asserts that every
switch value a look declares has a matching rule. It strips CSS comments before grepping: the
banned selector is quoted in the stylesheet's own header as the example of what not to write, and
a guard that greps source grades its comments too.

## C32 — the visual-QA tooling decision

Researched and recorded in `docs/storefront/look-engine/research/C32-tooling.md`. The decision:

- **Extend `verify.mjs`** with element-collision and text-truncation detection. Property checkers
  gate; pixel comparators only report change, and a report is not a gate.
- **Do not buy a visual-regression service.** Argos is $100/mo, Chromatic is per-snapshot, and
  neither answers "is this correct" — both answer "is this different from last time", which is a
  question a page under active redesign answers "yes" to on every commit.
- **Do not use axe-core as the target-size gate.** Its `target-size` rule is off by default, and
  WCAG 2.2 SC 2.5.8 has a spacing exception that a naive check fails to honour. `verify.mjs`
  measures the boxes itself.

## Two more instances of the class, found today

The class from Part 10 is **a gate that grades a proxy for the thing it claims to grade**. Two
more, both found by running the tools rather than reading them:

1. **`check.mjs` scraped the contrast table out of a source file that no longer holds one.** It
   died with `TypeError: PAIRS is not iterable` the moment the engine started importing the table
   instead of declaring it inline. It imports the contract now, so the gate and the page can
   never disagree about what passing means.
2. **`verify.mjs` printed 80 failures and exited 0.** The ledger recorded `exit=0` under a log
   whose body was a wall of red. One line — `process.exitCode = bad.length ? 1 : 0` — and the
   same defect was then found by a peer session in two estate scripts, one of which would have
   reported success on the exact run where a 340-branch-deletion safety interlock failed.

## The layout gate, built the same afternoon (C32's decision, executed)

`verify.mjs` now measures two more failures in the same 80-cell pass: **text clipped to nothing**
and **two elements drawn on top of each other**. Neither is visible in a screenshot taken at the
one width nobody broke, and neither is caught by a contrast gate or a document-overflow gate.

It found one real defect, and it took two rewrites to see it.

**Run 1 — 62 failing cells.** 61 of them were the masthead wordmark "colliding" with the dateline
directly beneath it, in every look, at every width, where nothing touches. The check compared
`getClientRects()`, which returns BOXES. A line box is the font size plus its leading, and the
leading is empty by construction: the ledger's 96px wordmark sits in a 146px box with 25px of
nothing above and below the glyphs. **Box overlap is a proxy for ink overlap**, and the two
disagree by exactly the half-leading — the same class as everything else in Part 10.

**Run 2 — 10 failing cells.** The obvious inset, `(lineHeight - fontSize) / 2`, cleared 52 of
them and then silently gave up on the rest: the ledger's wordmark is 96px text on an 86.4px line,
so the inset is negative and the check falls back to the box it was trying to escape. A display
face set tight is exactly where this fails, which is to say every look worth looking at.

**Run 3 — ALL PASS.** Two changes. `range.selectNodeContents(el).getClientRects()` gives one rect
per LINE of actual text, with no padding and no empty box. Canvas `measureText` gives the real
glyph extent — `actualBoundingBoxAscent/Descent` is where the paint stops — and the CSS
half-leading formula recovers the baseline inside each line box. Verdict:

> 80 cells measured · ALL PASS — 0 contrast refusals, 0 overflow, 0 sub-24px targets, 0 sub-44px
> controls, 0 blank plates, **0 clipped text, 0 collisions (14,960 painted leaves compared)**, 0
> console errors

**The one real finding.** `.prov span { white-space: nowrap }` made the provenance line 647px wide
inside a 320px column at phone-390, clipped to nothing by `.packs { overflow: hidden }`, in all ten
looks. A34 requires every graphic's licence to be recorded on the page, and clipped is not
recorded. The first field wraps now; the short fields keep their nowrap so a break falls between
fields, never mid-licence.

Two rules the gate is built on, both learned the expensive way:

- **Compare leaves only.** An ancestor always overlaps its descendant, so comparing every element
  against every element reports the DOM tree as a wall of collisions. That is the proxy version of
  this check and it is worse than no check, because a person has to read it.
- **Exclude what the author layered on purpose** — positioned, transformed, or given a z-index.
  Deliberate stacking is what those three properties are for. A check that flags them flags every
  badge on every card, and gets switched off within a day.

---

# Part 14 — the rolled look, 2026-08-20

## What C35 actually claimed, and what was actually proven

The claim is "as many looks as you want". The evidence up to this afternoon was ten looks that a
person designed and then converted to seeds. That evidence is compatible with the engine only
being able to render the ten. `parts/09-roll.js` closes the gap: `rollLook(n)` takes a number and
returns a whole look — palette seed, type pairing, form metrics, plate, treatment and switches —
from one seeded PRNG (`mulberry32`), with exactly one pairing rule, that the display and body
faces must not be the same family.

The catalogue it rolls from is the same one A42 grades: 11 switch axes, 9 display faces, 5 body,
5 mono. The switch space alone is 3,072 structures before a single colour is chosen.

## Gate A54

`verify.mjs` now measures three looks nobody designed — `window.rollNewLook(101/102/103)` — through
the same eight checks as the ten. The numbers are fixed so a failure is reproducible: the same
call brings the same look back forever. A palette the fitter refuses counts as a gate failure, not
as a skip, because "the generator declined to build this one" is the failure A44 exists to make
impossible.

> 104 cells measured (10 designed + 3 rolled looks x 4 viewports x 2 themes)
> ALL PASS — 0 contrast refusals, 0 overflow, 0 sub-24px targets, 0 sub-44px controls, 0 blank
> plates, 0 clipped text, **0 collisions (19,552 painted leaves compared)**, 0 console errors

The fonts the three rolled looks resolved to — Fraunces, Chivo, EB Garamond — are read out of the
browser, not out of the look table, so a face that failed to load reads as a fallback rather than
as a pass.

## The console button, and gate A45

"Roll a look" sits next to the theme toggle. It mints a look, adds it to the table, re-renders the
chip strip and applies it — no deploy, no rebuild, no edit. Three things make that an addition
rather than a preview:

- **The number is stored, never the look.** `localStorage.rolled` holds `[1, 2]`. `rollLook(n)` is
  deterministic in n, so the number is the whole record. Storing the built palette and type stack
  would freeze a copy of a generator that is still changing: the day the catalogue gains a
  typeface, every stored look becomes a fossil of the old one and nothing on the page says so.
  That is a hand-written colour beside a seed, in a different coat.
- **`?look=roll-101` works on a browser that has never rolled.** The boot path mints it from the
  number. Without that the link falls back to the default look and reads as a working link, which
  is worse than a dead one — and every rolled card on the contact sheet would have been one.
- **A refused roll is not remembered**, so a reload cannot restore a look the contrast audit
  already turned down.

`persist.mjs` is the gate. It serves the page over **http on an ephemeral port** rather than
opening it from disk, because a `file://` document has an opaque origin: `localStorage.setItem`
throws, the engine catches it, and the gate would pass by never storing anything and never reading
anything back — grading a page whose storage the test itself had switched off.

> rolled roll-1 and roll-2 over http, reloaded, linked and forgot one.
> A45 PASS — a rolled look survives a reload, opens from a link on a browser that has never
> rolled, and can be forgotten.

**Mutation-proved, and the proof found a defect in the gate.** With `writeRolls` made a no-op, the
gate exited 1 — by throwing a stack trace at step 3, having silently discarded the four failures it
had already collected. A gate that crashes tells the next agent nothing. It collects into one list
now and prints it whatever happens; the same mutant reports seven named failures, the first being
`localStorage.rolled is null, expected two numbers`.

## A third instance of the class, and the guard that closes it

The rolled-look gate was written as **A46**, which the doc had already given to the cold-open
test. A gate number is a POINTER to a criterion; nothing was checking that it still pointed at the
one the tool means, so a green "A46 PASS" in a log would have read as evidence for a criterion
nobody has started. Same class as the rest of Part 10: **the gate graded a proxy** — the number —
rather than the thing.

`check.mjs` now audits it. Every `GATE A<n>` in the tools must appear in a `CLAIMED` map whose
values are copied from this document's own titles, and every claimed number must still carry that
exact title here. It is an exact string compare on purpose: a tool cannot take a number without
someone reading the line the doc already has there, and this document cannot renumber underneath
the tools silently. Mutation-proved — with A54 undefined here, the audit printed
`GATE AUDIT FAIL — A54 is claimed by a tool but the program doc defines no such gate` and exited 1.

## Part 15 — the first screen, measured. 2026-08-20

C36's claim is that nobody here can experience the first five seconds any more, so they have to
be graded by a procedure. `coldopen.mjs` is that procedure for the three questions a machine can
answer: A46, A48 and A49. It grades 40 first screens — ten looks at 320, 390, 834 and 1440 —
and it grades them cold, with no scroll, no hover and no click.

**320px is in this matrix and is not in verify.mjs's.** The doc pins Q1 to "above the fold,
without scrolling, at 320px". 390 is the narrowest phone anyone here owns, which is exactly the
reason it is the wrong floor to design against.

**The vocabulary is written down, not felt.** Four short lists — product nouns, buyer nouns,
forms of direct address, outcome verbs — plus a fifth list of OUR words, which may appear above
the fold only if the same screen defines them. A generous list would pass any page with words on
it. The interlock that makes A46 and A48 one gate rather than two: a product noun that is our own
jargon only counts as an answer to "what is this" if the same screen defines it. A stranger
cannot be told what a thing is in a word they have never met.

### What the first run found, and what it cost to fix

The first run failed 130 of 200 checks. Every failure was real.

| Finding | Fix |
|---|---|
| No buyer noun and no direct address, 40/40 | The deck now opens "You are deciding what to build next" |
| No outcome verb at three of four widths | The deck ends "Read those, or read why the rest died" |
| The headline ran past the fold at 320px in all ten looks, by 150px | See below — it was not the headline |
| "pack" and "kill log" used above the fold with no definition | Nav reads "What we killed" and "What you get" |

**The headline was never the problem.** `--f-hero` had a floor of `2.5rem` — a fixed 40px, which
at 320px is a minimum the narrowest screen pays for. Fixing the floor helped, and the gate still
failed 10/10 at 320px. The number that ended the guessing was one line of new diagnostic: the
headline's TOP. **323px of chrome sat above the headline on a 568px screen** — a five-line
dateline (118px), a four-row nav (184px) and the prototype's own look switcher (166px). The
headline itself was 69–113px and always had been.

Three consequences, each a rule rather than a tweak:

1. **The look switcher is now hidden for the measurement**, for the same reason its words were
   already excluded from the reading: it is this prototype's scaffolding and it is not on the
   storefront. Leaving it in the layout graded the storefront on the height of our own tooling.
   The two exclusions are one rule now, not two.
2. **Tap targets are 44px and that is not negotiable** — it is another gate. So the only lever on
   a narrow nav is FEWER things, not smaller things: the narrow nav keeps the four sections a
   stranger came for, and FAQ and Account are in the footer. Nothing is clipped; hidden is
   `display: none`, and everything is back at 40rem.
3. **On a phone the deck is 150px of prose between the headline and the only two things to do.**
   Source order stays headline, deck, actions — that is the order a screen reader and a wide
   screen both want. The narrow screen re-orders the PAINT, and only the paint.

### The gate graded a proxy, and the gate is the thing that caught it

A46 as first written asserted that the HEADLINE fitted above the fold. It passed a page whose two
buttons sat 191px below it at 320px. A first screen a stranger cannot act on has failed, whatever
it says. `a46_act` — "the first thing to do is on the first screen" — was added, and it failed
immediately on 4 of 40. That is the same defect class as A54's number collision and as the peer's
deadlocked push fence: a mechanism that is correct about the thing it measures and silent about
the thing it was built to protect.

### Two receipts worth keeping

**A media query adds no specificity.** The first narrow-screen fix sat above `.hero {…}` in the
file, lost the cascade to it, and changed nothing. The re-run printed byte-identical numbers,
which is the only reason it was caught — a fix that changes nothing looks exactly like a fix that
was not needed.

**The last cell passes by 3px.** `signal` runs `--sp: 1.2`, so every gap it meets scales, and at
320px the sum of those gaps was 3px more screen than exists. It now clears the fold by 3px. That
is the tightest cell in the matrix, and the reason the gate prints the distance rather than a
verdict: the next look that fails will say by how much, and where.

```
40 first screens graded (10 looks x 4 widths, 320px included)
A46 — the cold-open test
  a product noun a stranger knows: PASS
  a buyer noun or a direct address: PASS
  an outcome verb: PASS
  the headline fits above the fold: PASS
  the first thing to do is on the first screen: PASS
A48 — no unexplained jargon above the fold: PASS
A49 — the entry costs nothing: PASS
ALL PASS — the first screen answers Q1 and Q2 in words a stranger knows, at every width.
```

A47 stays a written procedure. It needs a person who has never seen the site, and there is no
machine form of that.
