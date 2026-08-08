# Mumchimp Site Spec — tracked programme

> **Why this file exists.** On 2026-08-07 this spec lived only in a chat transcript.
> `checkpoints/LATEST.md` literally said: *"it is NOT in the repo — if it is needed verbatim, read
> it from the transcript `611968c4-3e56-435d-b4aa-37553991ccb6.jsonl`."* Every fresh session had to
> re-derive the work from a transcript it could not read, so the same audit was paid for repeatedly
> and status was carried in prose that drifted. The spec now lives here, versioned with the code it
> describes.
>
> **The rule (same as `COST_PROGRAM.md` and `GRAPHIFY_ENFORCEMENT_SPEC.md`): read this before
> touching the storefront, and append results HERE — never into `CLAUDE.md`, never only into a
> checkpoint.** A checkpoint is a session's narrative; this is the programme's state.
>
> **Status is a probe, not a paragraph.** Every ✅ below carries the command that proves it. If you
> cannot re-run the command and see the receipt, the item is not done — downgrade it.
>
> **The proof command is `python3 scripts/site_spec_probe.py`** (add `--section 5.2 --verbose` for
> one item's offenders). It parses the glyph out of the ledger table below, runs a live probe for
> that row, and exits 1 when the two disagree. Read-only, no dependencies. It fails in **both**
> directions on purpose — a ✅ that stopped being true and a ❌ that is secretly done are the same
> defect, and the second is the one that had gone unnoticed here (§6.6, below). Do not update a
> status line in this table without a probe run in the same session; if a row has no probe, add one
> rather than asserting the status in prose.

Audience: a developer or AI agent implementing changes to mumchimp.com.

**Design thesis:** the site is the visible console of the vetting engine, not a brochure about it.
Restraint + real data + zero latency. No stock imagery, no decorative icons — every visual is
generated from real engine data (verdicts, source counts, kill ratios). Reject glassmorphism, neon
gradients, 3D blobs, mascots, AI-slop gradients.

**Copy thesis:** Monzo-register — plain, precise, warm, jargon-free. Rewrites are
information-preserving: every decision, fact, and promise in the original survives the edit. Word
counts are defaults, not gates. The one absolute rule: **say each thing once, sitewide** — one page
owns each fact; every other page links to it.

---

## Status ledger — last verified 2026-08-08

| § | Work | Priority | Status | Proof |
|---|---|---|---|---|
| 1 | Data integrity (one source of truth per number) | P0 | ✅ done | `kill-log-totals.json` + `lib/stats.ts` (`RESEARCH_STATS`); pack counts fetched live from `/catalog`. Grep for `1285\|1331\|1412\|1168\|78\|81\|145\|56\|57` in `*.tsx`/`*.ts` returns only code comments and unrelated pixel values (`Logo.tsx:78` `w: 56`, `CategoryGraph.tsx:96` radius). |
| 2 | Engine-output publish pass | P0 | ✅ done | `prospector/plain_text.py` (`publish_pass`, `publish_pass_document`). Scan of all 400 `kill-log.json` entries across `title`/`oneLiner`/`gateLabel`/`reason`: hex ids 0, empty citations 0, truncation 0, **confidence floats 0**, denylist 0; 0 reasons ending without terminal punctuation. `pytest tests/unit/test_publish_pass.py tests/unit/test_bundle_index_html.py` → **86 passed**. |
| 3 | Design system (`tokens.css`) | P2 | ✅ done, **bar the dark palette** | Founder scoped it 2026-08-08: "apart from the dark we need all the other design requirement fulfilled." `src/styles/tokens.css` now exists (the token layer split out of `globals.css`, which drops 775 → 363 lines) and is the single declaration site for every token. Proved at the **computed value** in a real browser, not by grepping the sheet — Playwright over `/`, `/sample`, `/kill-log`, `/pricing`, `/how-it-works`: `getComputedStyle(body).fontFamily[0]` = **Switzer**; `--shadow-1` = **none** and elements with a non-`none` `boxShadow` = **0** on all five; the only non-zero `borderRadius` anywhere = **2px**; `--accent` = **#171717** (ink, not blue). Built sheet: `2563EB` × 0, `Geist` × 0, `text-mega` × 0, `--text-display: clamp(2.25rem, 1.5rem + 2.4vw, 3rem)`. `npx tsc --noEmit` **exit 0**; `npm run build` **exit 0** ("Compiled successfully in 5.7s"). Two documented exceptions, both deliberate — the 12 `--cat-*` category hues (they carry discovery meaning) and `lucide-react` for UI **chrome** only. See "§3 landed — what was implemented and what was knowingly not" below. |
| 3.5 | Motion — easing + reduced-motion floor | P2 | 🟡 partial | `site_spec_probe.py --section 3.5`. §3.5's easing curve already ships **verbatim** — `cubic-bezier(0.2, 0, 0, 1)` (`globals.css:52-54`) — and `--transition-fast: all 0.12s` is §3.5's `--t-micro` under another name. The floor §3.5 calls non-negotiable is enforced by a catch-all (`globals.css:730`, `*, *::before, *::after`) plus a separate rule reaching the view-transition pseudo-tree (`:596`), which the catch-all cannot (those elements are not DOM descendants). **Not built:** the signature resolve sequence, and therefore no `--t-state`/`--t-resolve`. Those tokens are deliberately NOT added ahead of the animation — a token with nothing behind it is dead weight that reads as done. |
| 4a | Core components — **source chip** | P2 | ✅ done | `components/ui/SourceChip.tsx` is the sitewide primitive; `sourceChipIsTheOnlyOne.test.ts` (6 tests) forbids a seventh. It replaced **six** private copies in two visual languages — `Citation.tsx`, `sample.tsx:112`, `HeroDossier.tsx:104`, `Gauntlet.tsx:123`, `DossierPreview.tsx:96`, `kill-log.tsx:477` — plus three separate `domainOf` helpers. Two of the six omitted `rel="nofollow"`. `site_spec_probe.py --section 4a`. |
| 4b | Core components — QA row, glyph strip | P2 | ❌ not started | Five QA-row shapes (`CheckSequence.tsx:81`, `EvidenceRecordPanel.tsx:49`, `sample.tsx:310`, `pack/[id].tsx:712`, `how-it-works.tsx:179`) and two glyph strips (`HeroEvidenceStrip.tsx:65`, `EvidenceBar.tsx:24`). Unlike the chip these differ **by design** (confidence score, rationale, methodology-only). §4 wants one; that is a visual decision, not a refactor — see the note below. |
| 5.2 | Vocabulary — one name per thing | P1 | ✅ done | `site_spec_probe.py --section 5.2` → **0 reader-facing instances** of catalog/shot/grounded/gauntlet/dossier. The **previous** ✅ was false: the probe found 12, in `how-it-works.tsx:147,262,270`, `DossierPreview.tsx:40,128`, `DossierExcerptPlate.tsx:57`, `Gauntlet.tsx:163`, `sample.tsx:373`, `pack/[id].tsx:897`, `faqContent.ts:124`, `terms.tsx:36` (×2). It came from a raw grep that could not tell an identifier from a sentence; the probe extracts JSX text nodes + sentence-shaped string literals, so it counts what a **reader** sees, not what the compiler does. All 12 fixed 2026-08-07 — see "the survivor is *evidence record*" below. |
| 5.3 | Ownership map (say it once) | P1 | ✅ done | /about, /how-it-works, /faq de-duplicated. Home owns the pack manifest (`index.tsx:1693`), /pricing keeps bare filenames only (`pricing.tsx:123`), a pack page lists its own (`pack/[id].tsx:669`). "What you get, at every price" deleted from home.
`factOwnership.test.ts` (14 tests) pins six facts, the sixth added 2026-08-07 — see "the founder was
introduced twice" below. |
| 6.1 | Home | P1 | ✅ done | All nine work orders landed; interface copy 764 → 452 words (−41%) by de-duplication. `npx tsc --noEmit` → **0**; `priceRange.test.ts` 6/6. Checks strip now renders `checkVerdicts()` (six verdict-form phrases read off `lib/checks.ts`, cross-checked against `kill-log.json` `gateLabel`), not `engineGateIds()`. |
| 6.2 | /how-it-works — prune | P1 | ✅ done | AI disclosure added above check 1; duplicate "auditable, not a black box" cut; "honest limits" → one line + link to `/pricing#what-you-do-not-get`; `truncateReason` → `firstSentences`. |
| 6.3 | /about — rebuild | P1 | ✅ done | Founder story present; checks list / kill-log explanation / "what a pack is" deleted; style-guide leak ("source-or-die… Refutational, not promotional") removed. |
| 6.4 | /pricing | P1 | ✅ done | "no seat fees / no drip-feed / no upsell" cut (incl. `priceRange.ts:140,150`, 2026-08-07); "earns one rung" rewritten; `id="what-you-do-not-get"` anchor added; `itsorigin` fixed. |
| 6.5 | /faq | P1 | ✅ done | Q1 answer-first, 8 documents interpolated from `PACK_CONTENTS.length`; Q11 rewritten complete; Q12 comma splice fixed. |
| 6.6 | /kill-log | P1 | ✅ done | Entries publish-passed; hero live counts; closing comma splice fixed. Cause-of-death taxonomy **is built** — `kill-log.tsx:294-341`, `<section aria-labelledby="distribution-heading">` "How ideas die": one bar per gate off live `byGate` data, scaled to the largest cause (not the total, or every bar but one is a sliver), with a published/unpublished legend. `site_spec_probe.py --section 6.6` asserts all four markers. The previous "not built" was **stale for at least a session** — nothing re-read the tree after it shipped. |
| 6.7 | Catalogue & intent search | P1 | ❌ not started | Skills-picker not yet merged into a single intent input. |
| 6.8 | Pack pages & /sample | P2 | ❌ not started | Standard defined, next pass. |
| 7 | Performance & transitions | P2 | 🟡 partial | **View transitions are shipped**, not "not started": `@view-transition { navigation: auto }` (`globals.css:575`), a 0.16s root cross-fade (`:584`), per-card shared elements via `viewTransitionName` (`PackMark.tsx:65`, name minted by `lib/packMark.ts:132` with a `pm-` prefix because the value is a CSS custom-ident), and reduced-motion coverage for the pseudo-tree (`:596`). `site_spec_probe.py --section 7`. **Unmeasured:** LCP <1.2s — no number has been taken, so that half is neither done nor failing, it is unknown, and the row stays 🟡 until someone measures it. |

### The spec contradicted itself once — resolved

§5.3's ownership table named **Home** the owner of "what's in a pack (8 documents)"; §6.1 said
delete Home's "What you get, at every price" section. Home had **two** sections stating pack
contents, and on 2026-08-07 two concurrent agents each deleted one of them, neither aware of the
other — so a fact with a named owner ended up stated on no page at all. Founder resolved it:
**Home owns the manifest.** The section to delete was always the pricing essay.

The generalisable bit: an ownership table and a page-level delete order can be individually correct
and jointly wrong. When a page states one fact twice, "delete the duplicate" is ambiguous until you
name *which* instance survives.

**That resolution is now enforced, not remembered.** `src/__tests__/factOwnership.test.ts` asserts
every §5.3 fact renders on **exactly one** page — anchored on structural markers
(`<PackContentsSection`, `id="distribution-heading"`), not on copy, because §6 rewrites copy every
session and a prose grep would fail on every legitimate edit and be deleted within a week. The
load-bearing half is `>= 1`: the natural way to write a de-duplication guard is *at most once*, and
at-most-once **passes at zero** — it would have been green on 2026-08-07. Four synthetic cases in
the same file replay the incident (orphaned / restated / moved / correct-and-silent) so the failure
path is proven to execute rather than trusted on its shape.

### §5.2: the survivor is "evidence record"

§5.2's table retires **dossier** and canonicalises **pack**. Applied literally that is wrong here,
and the wrongness is instructive: on 2026-08-07 the tree used "dossier" for the *verification record
inside* a pack, not for the pack. Substituting the table's canonical term produces "every pack on
the shelf carries a pack like this." A retire-list names what dies; it does not name what survives,
and the survivor is the half you actually need.

The tree had **three** names for that one thing — "verification dossier" ×5, "evidence record" ×1,
"verification record" ×1 — which is the §5.2 defect itself, not a wording preference. Chosen
survivor: **evidence record**. It was already in the tree (`how-it-works.tsx:267`), it uses the
vocabulary §5.2 already approves ("evidence-backed / sourced"), and it avoids both retired words.
All 12 sites now read it. `terms.tsx` additionally lost "source-grounded" → "evidence-backed".

Component *filenames* were carved out of §5.2 on purpose — the probe scopes the rule to what a
**reader** sees, because renaming an identifier is churn a buyer never experiences, and treating the
two as one item is what produced the false ✅ in the first place. They were then renamed anyway, as a
separate item, once the reader-facing pass was green (2026-08-07):

| was | is | why that name |
|---|---|---|
| `HeroDossier.tsx` | `HeroEvidenceStrip.tsx` | renders the **shape** of a record — eight glyphs, at a glance |
| `DossierPreview.tsx` | `EvidenceRecordPanel.tsx` | renders the **answers** — check name, verdict, source |
| `Gauntlet.tsx` | `CheckSequence.tsx` | renders the **sequence** — order, confidence, the reversal at check eight |
| `DossierExcerptPlate.tsx` | `EvidenceExcerptPlate.tsx` | a real line from the pack's own record |

The three-way split is not invented for the rename; each file's own docblock already argued it was
not a copy of the other two on exactly those grounds. `git mv` + a word-boundary rewrite of all 63
references, then the docblock prose in the four files (a file called `CheckSequence.tsx` whose header
read "ONE REAL IDEA, RUNNING THE GAUNTLET" is the drift this programme exists to remove).
`pack.dossierRef` is untouched: it is the API's own field name, and renaming a wire field is a
different, breaking change.

One trap worth recording, because it failed **silently**: the first rewrite loop was
`for f in $FILES` in zsh, which does **not** word-split an unquoted variable. The whole list arrived
as one filename, `perl` reported `Can't open <the entire list>`, and the grep that followed still
showed every reference intact — the tell was the residual-refs check, not the loop's own output.
(Memory: `zsh-does-not-word-split-unquoted-vars`.)

### §4: the source chip had six copies, and the tree believed it had one

Worth recording because the failure mode is not "we forgot to share a component". The tree
*asserted* the sharing, in prose, and was wrong. `HeroDossier.tsx` carried a comment reading

> the -45deg arrow copy `SourceChips` on `/sample` deliberately: this site has one way of drawing
> "a source you can open"

directly above markup with no arrow, no border and a different colour. `DossierPreview.tsx` said
the same thing about the same non-existent shared markup, while rendering its source in the accent
colour — breaking a rule `Citation.tsx:22-24` had already written down ("the accent means *you can
act here*; a source is evidence"). Nothing could tell, because no test named the primitive.

Two receipts on why a mechanical guard beat a careful reading: a delegated survey of the whole tree
found five copies and reported them confidently; `sourceChipIsTheOnlyOne.test.ts` found **six** on
its first run — `kill-log.tsx:477`, a byte-for-byte paste of `CitationChip`'s markup. And the guard
matches on *behaviour* (an external anchor whose visible text is a hostname), not on class strings,
so a restyle does not fail it. That is the property that decides whether a guard is alive in six
months.

`variant="link"` survives alongside `variant="chip"` deliberately. §4 asks for a single form;
collapsing the two is a visible change to the hero and /how-it-works, which is a founder call. What
was actually broken was not that the hero draws sources compactly — it is that it drew them with a
private copy. One implementation, two declared variants, is the honest state.

### §5.3: the founder was introduced twice, and the ownership guard could not see it

`lib/config.ts` held `FOUNDER.bio`, a 417-character first-person paragraph. `pages/about.tsx` tells
the same story at length — same opening sentence ("I always wanted to run my own business"), and the
bio's fourth sentence *is* that page's `<h1>`. `FounderNote.tsx` rendered the bio whole for `/about`
and `line-clamp-2`'d for the home page, so a stranger met the same person twice in two lengths.

The decision had already been made and written down. `pages/index.tsx:1785`:

> `FounderNote` is REMOVED from the homepage (not deleted, and not from the site): the founder's
> paragraph now lives once, on /about.

That comment is correct and load-bearing and cannot fail, which is the whole pattern this programme
keeps finding: the config string outlived the decision that retired it, and the next surface wanting
a human on it would have read `FOUNDER.bio` and reintroduced the second telling.

Two things were done, and the second is the one that matters:

1. `FOUNDER.bio` **removed**, not shortened. Shortening was the option the open item offered and it
   was rejected: a one-line summary is still a second copy, of a smaller thing, and it would have
   been a compression of /about's own headline. `FounderNote` now names the person and links there;
   the block where `bio` used to be says so, so the next author does not re-add it.
2. `factOwnership.test.ts` gained the founder story as its sixth owned fact
   (`marker: /id="founder-story"/`, owner `pages/about.tsx`) **and** a guard against the way the rule
   was actually broken. The ownership walk reads `src/pages` only — which is the right scope for
   "which page renders this" and the wrong scope for prose held in a config constant. A config string
   renders wherever it is imported, so it routes around the check entirely. The new assertion fails
   any `FOUNDER` field over 200 characters.

Fired-proof, run against `HEAD` before the deletion rather than asserted:

```
OLD (HEAD):          FLAGS -> FOUNDER.bio (417 chars)
NEW (working tree):  clean
```

The threshold is length, not content, deliberately: matching the story's words would pass the moment
someone reworded it, and paragraph-length prose in a config object is the signature regardless of
what the paragraph says.

A related finding, recorded because it is not what the open item claimed: `FounderNote` is rendered
on **no page**. `grep -rn "<FounderNote"` over `src` returns nothing — /about builds its own markup.
So the duplication was latent, not live. It is still the right fix; a dormant second copy is a second
copy with a longer fuse.

### The spec contradicted the live brand — §3.1/§3.2 RESOLVED 2026-08-08

§3 was written against a **dark** palette; the site shipped **light** ("brand v3", 2026-08-06) and
is pinned there by ~30 assertions. This is not a to-do, it is a conflict, and implementing §3 as
written would turn a green suite red:

| §3 asks for | The tree has | Pinned by |
|---|---|---|
| `--ink-0: #0A0A0A`, `--paper: #E9E7E2` (dark) | `--bg: #FFFFFF` (`globals.css:33`), `--text: #171717` (`:39`) | `storefrontDesignContract.test.ts:56` (`--bg:\s*#FFFFFF`) |
| 2px radius, "no pills" | `--radius-sm: 4px` (`:378`), `--radius-md: 8px` (`:379`); the canonical chip **is** an `h-8 rounded-full` pill | `storefrontDesignContract.test.ts:191, 319, 380-410` |
| Switzer / Commit Mono | Geist | — |
| `--verdict-*` tokens | `--survive*` / `--kill*` | `globals.css:23-222` |

**Status: RESOLVED 2026-08-08 — the founder overturned the safe reading.** The ruling: *"apart from
the dark we need all the other design requirement fulfilled."* So the conflict was never §3 vs. brand
v3 wholesale — only ONE row of the table above is a real contradiction (the palette's lightness), and
it was being used to hold up the other three. **The dark palette is retired; every other §3
requirement is implemented on the light palette.** Radius went to 2px, the pills were squared, Geist
was replaced by Switzer + Commit Mono, and the verdict marks were built. What that cost, row by row,
is below.

The lesson worth keeping: "the spec contradicts the tree" was true of a single cell and stated of a
whole section, and that framing froze §3.1–§3.4 for two days. When a spec conflicts, resolve it at the
grain of the individual requirement, not the heading.

### §3 landed — what was implemented and what was knowingly not

Three decisions were the founder's, taken 2026-08-08, and each is a deliberate exception rather than
an oversight:

1. **Colour — "verdicts only, keep the category hues."** `--accent` was `#2563EB` blue; it now
   resolves to `var(--text)` (ink) and an inline link's entire affordance is a hairline underline.
   `--focus`, `--info` and `--highlight` were de-blued the same way. The **12 `--cat-*` hues stay**,
   against §3.1's letter, because on the catalogue they carry discovery meaning rather than
   decoration. `1D4ED8` still appears once in the built sheet: that is `--cat-housing-rental`.
2. **Icons — "six glyphs, keep lucide for chrome."** `components/ui/Glyph.tsx` implements all six
   marks (14×14, 1.5px, `currentColor`, the survived tick knocked out with an SVG **mask** so it is
   correct on any surface, not a `--bg`-coloured stroke). Wired into every surface that draws a
   RULING: `sample.tsx` (verdict badge, the stat strip, the pushback plate), `kill-log.tsx`,
   `pack/[id].tsx` (×5), `DossierCard.tsx`, `EvidenceExcerptPlate.tsx`. `lucide-react` still draws
   chrome (menu, search, chevrons) and a few non-rulings that were checked one by one and left
   alone on purpose — the 14-day refund shield (`pack/[id].tsx:323`) is a commercial policy we
   chose, and `FacetBar.tsx:380`'s tick counts filter matches. **§3.3's "no icon libraries" is
   therefore formally unmet, by design.** The rule actually enforced is the sharper one: a verdict
   is never drawn by a general-purpose icon set.
3. **Typefaces — Switzer + Commit Mono, self-hosted.** `public/fonts/Switzer-Variable.woff2`
   (43,220 B) + `CommitMono-400.woff2` (48,128 B) = **91,348 B** against §3.2's "≈60–90KB" budget,
   `font-display: swap`. The `next/font/google` Geist import had to be **deleted** from `_app.tsx`,
   not merely left unused: a `next/font` `variable` class sets the property on an ELEMENT, which
   beats a `:root` declaration on every descendant, so leaving it would have kept rendering Geist
   while `tokens.css` sat there declaring Switzer — two files that each look correct alone.

Two things were changed that reverse earlier deliberate decisions, recorded here because silently
reversing them is how a ledger stops being trustworthy:

- **`--text-mega` (6rem) is deleted and the homepage hero dropped 96px → 48px.** It was a seventh
  step on a six-step scale, argued for on the grounds that 48px "is a large paragraph, not a display
  cut". §3.2 answers that directly: display is 3.0rem, "Homepage hero only". The measurement that
  justified the step is not invalidated — `index.tsx` argued the 48→96 jump "costs the measured
  1280×720 fold nothing" because at `lg` the hero sits beside the product, and going back down can
  only give the fold more room. Measured after: the hero is 2 lines at 1280px, was 4.
- **`--text-h1` went 2rem → 2.25rem**, reversing a v3 drop made because the pack-detail h1 wrapped to
  four lines under Geist. Switzer's x-height differs again. The two top steps are now `clamp()`s
  carrying their own mobile size (spec: display mobile 2.25, h1 mobile 1.75), so the "caller must
  add its own mobile size" contract — a rule enforced by nobody — is gone. **Both clamps reach their
  maximum at 1000px, so every measurement previously taken at 1280 still holds.**

**Not done, and not claimed:** the dark palette (`--ink-0` / `--paper`), and the `--verdict-*` token
rename (the tree's `--survive*` / `--kill*` carry the same meanings; renaming ~200 call sites buys
nothing a reader can see). §3.5's resolve sequence is still unbuilt — its own row covers it, and the
six marks it needs now exist.

### Appearance tests are SUSPENDED while the UI moves — founder directive 2026-08-08

> "tests on a ui that is ever changing is stupid and waste of resources, suspend copy and design
> tests and basic tests until stable."

Ten files are excluded in `store_platform/src/Store.Web/vitest.config.ts` via the named constant
`SUSPENDED_UNTIL_UI_STABLE`: `brandV3`, `storefrontDesignContract`, `weightAndCasePolicy`,
`threeRadiiTwoShadows`, `monoIsTheDataVoice`, `uiPolishContract`, `noArbitraryHex`, `oneColourRule`,
`dashFree`, `categoryScale`. To lift a suspension, delete its line. There is deliberately no flag
and no env var: a suspension that can be toggled invisibly is one nobody ever ends.

**The evidence for the directive, since the suspension is itself a claim.** §3 moved the tokens out
of `globals.css` into `styles/tokens.css` and re-pointed `--accent` at ink. That one change turned
**21 assertions across 6 files red**, and not one of them had found a defect — every failure read
as a deleted token ("`--bg` must be clean white", "`--primary` must be ink") over tokens that were
present, correct and one file to the left. Cost to make them green again: a stylesheet-inlining
test helper plus a rewrite of every superseded number. That is the tax being suspended.

**What stays ON, and the line is not arbitrary.** Guards on what the site *tells a buyer* —
`fixedCheckCount`, `checkLexicon`, `packContents`, `priceRange`, `stats` — assert that a rendered
number matches its source. The copy rewrite (PR 133) shipped "This one survived all 9." onto the
pack page above the buy button, false for 60 of the 63 published packs, and that class of test is
the only thing that catches it. Appearance drifts; a false claim to a buyer does not become true
because the design changed.

Measured after suspending: `npx vitest run` **46 files / 500 tests passed, exit 0**;
`npx tsc --noEmit` **exit 0**; `npm run build` **exit 0** (exit captured before any pipe).

`src/__tests__/helpers/stylesheet.ts` is kept even though its consumers are suspended: it reads a
stylesheet with local `@import`s inlined, so when these guards come back they measure the token
wherever it lives. Without it the failure mode reverses and gets worse — a guard asserting a
property is ABSENT goes green over a violation that moved into the imported file.

### SUSPENSION LIFTED 2026-08-08 — all ten files are back on, and green

Lifted to ship §3 to production. The directive suspended these "until stable"; §3 IS the change the
suspension was protecting against, and it has landed, so the condition is met.
`SUSPENDED_UNTIL_UI_STABLE` is now an empty array rather than a deleted constant, on purpose: the
next UI push re-suspends by adding lines back, and the rationale above it stays attached to the
mechanism instead of being rediscovered.

Un-suspending turned **5 tests red across 3 files, and not one was a §3 defect.** All five were
guards still measuring the pre-§3 mechanism. That is this section's own lesson in a second and
nastier form: the first wave failed because the token MOVED, these failed because the thing they
measured no longer EXISTS, and two of them would have gone green while checking nothing.

| Guard | Asserted | Reality | Fix |
|---|---|---|---|
| `storefrontDesignContract` | `--text-h2--line-height: 1.3`, weight 600 | §3's own type table above declares **1.2 / 520** | assertion updated to the table, with a trailing `;` so `1.2` cannot also match a future `1.25` |
| `storefrontDesignContract` | `--text-body--line-height: 1.6` | table declares **1.55** | same |
| `storefrontDesignContract` | `const SHELL = …max-w-(6xl\|7xl\|\[1200px\])\b` | `MarketingLayout.tsx:104` ships `max-w-[1200px]` | **the regex was unsatisfiable**: `\b` needs a word char, and the class ends `]` before a space, so the branch written to permit the shipped value could never fire. Now a `(?![\w-])` lookahead |
| `weightAndCasePolicy` | reads `weight: [...]` arrays out of `_app.tsx` | §3 deleted next/font; Switzer is self-hosted **variable, axis 100-900** | re-argued, see below |
| `categoryScale` | `--accent` matches `#rrggbb` | §3 retuned it to `var(--text)` | `token()` now follows `var()` aliases the way the browser does |

**`weightAndCasePolicy` rule 1 was re-argued, not edited**, because its own comment said that is what
a 700 being loaded would require. The ban on `font-bold` rested on SYNTHESIS: no 700 cut was
downloaded, so the browser smeared the 600 into a fake bold. A variable face with a declared 100-900
axis renders a true 700, so that argument is dead and a guard still citing it would have been a
false comment defending a real face. The rule survives on the stronger basis it should always have
had, the type scale itself, which tops out at 560: no `--text-*--font-weight` may declare above 600.
The old test also carried a live vacuity hazard worth naming, since it is the general case — it
asserted "weights above 600 is empty" over a list built by a regex, and when next/font went away
that list became empty, at which point the ban would have passed by having nothing to check. Its
non-vacuity guard is kept and now points at a pattern that exists.

Measured after lifting, in worktree `prospector-ship` at the merge of `origin/main`:
`npx vitest run` **56 files / 820 tests passed, exit 0**; `npx tsc --noEmit` **exit 0**;
`npm run lint` **exit 0** (one pre-existing `react/no-unescaped-entities` error on `index.tsx`,
present identically on `origin/main`, fixed in the same commit); `npm run build` **exit 0**, every
exit code captured before any pipe.

### §3.1 partially re-overridden 2026-08-08 — brand colour on the logo mark, tap targets, filter jump

Three fixes, all in `store_platform/src/Store.Web`, all verified: `npx tsc --noEmit` exit 0;
`npx vitest run` 57 files / 832 tests passed; `npm run lint` 0 errors (12 pre-existing warnings,
none touched by this pass); `npm run build` exit 0, Turbopack, 13/13 pages.

1. **Logo mark gets brand colour — explicit founder override, this session, of the 2026-08-08
   "no brand colour" ruling above.** Scope is narrow and deliberate: only `BrandMark` in
   `Logo.tsx` (the header/footer tile), not CTAs, links, or any other chrome — those stay ink.
   `tokens.css` gains `--brand-mark: #0F766E` (= `--cat-care-benefits`, the existing "muted
   teal/green" already on category tags — reused rather than a 13th invented hex) plus its
   `--color-brand-mark` `@theme` mapping; `Logo.tsx`'s `BrandMark` svg takes `text-brand-mark`.
   **Flagged, not resolved:** at Lab hue ~175°, this sits only ~12° from `--success`/`--focus`
   (#047857, "survived", ~163°) — under the ≥25°-from-verdict separation this sheet's own
   category-hue methodology requires everywhere else (see the `--cat-professional-services`
   comment). Every teal/green slot on the wheel is already reserved by `--success` or a category
   hue; there was no clean unoccupied one. The header logo now sits in the same colour family as
   the "survived" verdict mark — full reasoning and hex math in the `tokens.css` comment beside
   `--brand-mark`. Revisit if that reads as false verification signal in practice.
2. **Mobile header tap targets** (`MarketingLayout.tsx`): the hamburger button was ~36px
   (`p-2` + default 20px glyph) beside a search button explicitly sized to the 44px WCAG 2.5.8
   floor two lines above it — now matches (`min-h-11 min-w-11`). Right-side action gap
   `gap-1` (4px) → `gap-2` (8px).
3. **Filter-sheet open caused an unrequested scroll jump** (`pages/index.tsx`). Root cause,
   confirmed by reading the code (not asserted): `shelfControls`' inline `StepFlow` block
   unmounts to zero height the instant `filtersOpen` flips true (by design, to reset wizard step
   — see the comment above it), and that block sits above the fold for exactly the readers who
   can trigger this, since the pinned `FilterFab` trigger only renders once they've scrolled past
   it (`FacetBar.tsx`'s `scrolledPast` gate). Collapsing 300–400px of page height above their
   current scroll position shifts everything below it up by that amount while `scrollY` stays
   fixed — reads as landing on a random section, because the shift size varies with step/answer
   state. Fix: a `ResizeObserver` tracks the block's live height into `stepFlowHeight`; while the
   sheet is open, a same-height `aria-hidden` spacer stands in for it instead of nothing, so page
   height — and therefore what's under the reader's scroll position — doesn't move. The unmount
   itself, and the "exactly one mounted wizard" invariant it exists for, are untouched.

Not investigated further, lower confidence, not fixed: the second Explore agent also flagged
`Modal.tsx:37`'s `body.style.overflow = 'hidden'` as a possible secondary few-pixel shift via
scrollbar-gutter interaction, and a `.focus()` call on the panel — no reproduction, no code
change made for either.

### Header follow-up, same session, same day — compact-on-scroll, a visible Menu label

Three more from the same critique pass, `MarketingLayout.tsx` only. Re-verified: `tsc` exit 0,
832/832 tests, lint 0 errors (same 12 pre-existing warnings), build exit 0, 13/13 pages.

1. **Compact header on scroll.** The row was a fixed `h-16` (64px) at every scroll position. Now
   steps to `h-14` (56px) past the same `scrolled` threshold (4px) that already turns the hairline
   on, on the same 200ms transition. Logo and control sizes are untouched — the row shrinks, not
   its contents — so every 44px tap target stays 44px rather than scaling toward the floor.
   Knock-on fix required: the desktop nav links' active-state underline is pinned to
   `-bottom-px` of the link's own box, which was a hardcoded `h-16` — with the row now sometimes
   56px, that overflowed and threw the underline off the header's real bottom edge. Changed to
   `h-full` so it tracks whatever the row's actual height is; this was a latent bug (a
   `h-16` inside a `h-16` parent worked by coincidence) that the compact header exposed.
2. **Visible "Menu"/"Close" label on the mobile hamburger**, replacing icon-only +
   `aria-label`. `aria-label` was removed rather than kept alongside the new visible text:
   this button only renders below `md`, so the label is always visible there (unlike the header's
   Search button, whose text hides below `lg`) — keeping both would give the control two
   different accessible names, which fails WCAG 2.5.3 Label in Name. `Icon.tsx:128` sets
   `aria-hidden="true"` unconditionally on every glyph, so the accessible name is just the word.
3. **Icon shape itself — checked, not re-touched.** The pasted critique's "reads as a generic
   document/hamburger icon" complaint describes the OLD `BrandMark` (three left-aligned bars,
   ragged widths). `git log` shows that was already fixed: commit `91c26ae`, message "...the
   brand mark read as a list icon", replaced it with the centred, descending-width funnel
   currently in `Logo.tsx`, specifically to kill that exact read (see the file's own comment on
   why left-aligned bars in a dark tile is the universal list/document glyph). That commit is
   already on `main` (`git branch --contains 91c26ae` includes `main`; `git show
   origin/main:.../Logo.tsx` has the same centred bands as this branch) — the complaint is stale
   against what's shipped, not a live defect. No redesign attempted on top of an already-settled,
   three-times-iterated (2026-08-06/07/08) shape with no new evidence of a problem.

Also asked and answered "something else — I'll describe it" via multiple-choice, but no
detail was supplied in the response — nothing to act on there; open if the user specifies later.

### Known open items

- ~~**§6.1 Home** — delete "What you get, at every price" (`index.tsx:1668`); "Newest on the shelf"
  → "New this week"; checks strip → question-form verdict phrases~~ **done; bullet was stale, retired
  2026-08-08.** It contradicted its own ledger row (§6.1 ✅) for a session. Checked rather than
  assumed, because a grep says the opposite at first glance: `"What you get, at every price"` returns
  1 hit in `index.tsx` and `engineGateIds` returns 1 — and **both are inside comments recording their
  own removal** (`:1665`, `:1737`). `"Newest on the shelf"` → 0, `"New this week"` → 1,
  `checkVerdicts` → 3. The lesson is the one §5.2 already paid for: a raw grep cannot tell code from
  prose, and here it would have kept a finished item open instead of closing a live one.
- ~~`lib/config.ts:46` — `FOUNDER.bio` duplicates the /about story~~ **done 2026-08-07**, removed
  outright rather than shortened; see "the founder was introduced twice" below.
- ~~`components/marketing/Gauntlet.tsx` — component name carries retired vocabulary~~ **done
  2026-08-07**; four files renamed, see the table under §5.2.
- **Existing packs on disk are not retroactively publish-passed.** The pass runs at generation time.
  Measured on the 40 newest bundles: 260 `.md` files would change, 4,000,997 → 3,682,764 chars
  (−7.95%). Cleaning the shelf needs a re-render; not done.

---

## 0. Priority order

| Priority | Work | Why |
|---|---|---|
| **P0** | §1 Data integrity (number consistency) | Self-refuting trust bug; visible in 30 seconds |
| **P0** | §2 Engine-output publish pass | Raw internals + one offensive phrase on public pages |
| **P1** | §6 Page-by-page copy changes | The wordiness/clarity work |
| **P1** | §5 Vocabulary normalisation | Cheap, sitewide find-and-replace class of fixes |
| **P2** | §3 Design system + §4 components | Visual rebuild |
| **P2** | §7 Performance & transitions | Ships with the design rebuild |

---

## 1. P0 — Data integrity: one source of truth for every number

**Bug as found:** counts were hand-typed and contradicted each other across pages — Home 1,285
killed / 78 survived / 56 packs; How it works 1,331 (body: "1,412 researched") / 81; About 1,168 /
145; Kill log 1,168 / 145; Pricing 1,331 / 81 / 57 packs.

**Requirements:**
1. All counts (killed, survived, listed, sources, per-category tallies, price-rung tallies) render
   from the engine's live totals via one shared data source. Zero hand-typed numbers anywhere,
   including meta descriptions and OG tags.
2. If survived ≠ listed (e.g. 78 survived, 56 packaged), render both with the distinction stated
   once: "78 survived the checks; 56 are packaged and listed so far." Never show a bare pair that
   doesn't reconcile.
3. Canonical pack-structure sentence, defined once, referenced everywhere: a pack = **8 documents**.
4. Homepage catalogue-count sentence "Showing 13 of 46 written for your market, plus 10 written for
   other markets below" → computed "46 UK packs · 10 US packs" (and it must sum to the header total).

---

## 2. P0 — Engine-output publish pass

Kill rationales, QA verdicts, and check summaries are engine-authored and were rendering raw. A
publish-pass runs in the pipeline (not hand edits) before any engine text reaches a public page or a
pack file:

1. **Strip debug artifacts:** passage/hash IDs ("Passages 9fa810377aee4d8f…", "[4f51b226e"), empty
   citation markers "(,)" "(,,,,)", dangling brackets.
2. **No truncation:** complete or trim sentences at a sentence boundary. Nothing renders ending
   mid-word ("…rather rat", "…the sol") and no card/entry ends with "…". If space is constrained,
   the pipeline shortens to a complete sentence.
3. **Register filter:** rewrite internal shorthand flagged against a denylist. Known instance: "the
   target buyer profile is a broke body" → "a buyer group under severe financial strain." (Carers
   are a major buyer segment; this class of phrase is a reputational risk.)
4. **Confidence display:** never render raw floats ("conf 0.41" reads as 41% confident and
   undermines the verdict). Default = omit on marketing pages, show with explanation inside the QA
   report.

Applies to **both** surfaces: site-rendered engine text (kill log, how-it-works dossier, pack pages)
and pack documents themselves.

**The escape a closed defect class still had (2026-08-07).** Every confidence rule demanded the
digits sit ADJACENT to the word, so a single `(` between them slipped past all five: `kill-log.json`
row 392 published *"…, with a low confidence (0.43)."* with the pass already live and the suite
green. A defect class is not closed until its *spellings* are — the parenthesised form is now
handled (qualifier consumed with it, so nothing is stranded), pinned by
`TestParenthesisedConfidenceFloat` with four non-firing guards, and the data regenerated.
**Re-run the four-field scan over all 400 entries after any pass change; the suite alone did not
catch this.**

**Implementation notes (2026-08-07).** The hex-id pattern is fenced three ways —
`\b`…`\b` so it cannot fire inside a longer token, exactly 16 chars, and a mandatory-digit lookahead
so all-letter words like `defaced`/`facade` can never match. The `(?-i:…)` scoping is load-bearing:
without it the surrounding `re.I` leaked into the character class and ate uppercase ids. The register
denylist is an extensible `(pattern, replacement)` tuple, `\b`-fenced both ends so `brokerage`,
`embody` and `skintone` cannot fire, with optional quote characters absorbed.

---

## 3. P2 — Design system (tokens)

Ship as CSS custom properties in one `tokens.css`. Components consume tokens only; no raw hex in
component styles. Dark is the only theme.

### 3.1 Colour

**The deliberate risk: no brand colour.** The only colour on the site is the verdict system; colour
therefore *means* "a verdict." CTAs work by inversion, not hue. If a screen has no verdicts, it is
monochrome — that is correct.

| Token | Value | Use |
|---|---|---|
| `--ink-0` | `#0A0A0A` | Page background (matches existing theme-color) |
| `--ink-1` | `#111214` | Cards, panels |
| `--ink-2` | `#191B1E` | Overlays, expanded source chips |
| `--hairline` | `#26292E` | 1px borders/dividers only — never thicker |
| `--paper` | `#E9E7E2` | Primary text (warm off-white; not `#FFF`) |
| `--paper-dim` | `#8B8E94` | Secondary text, labels |
| `--paper-faint` | `#54575D` | Disabled, killed-idea text |
| `--verdict-survived` | `#5FE3B3` | Check passed |
| `--verdict-pushed` | `#E3B85F` | Pushed back / caveated |
| `--verdict-killed` | `#C4574E` | Killed — always paired with strikethrough (colour never the sole carrier) |
| `--cta-bg` | `#E9E7E2` | Primary button: inverted ink, `#0A0A0A` text |
| `--cta-hover` | `#FFFFFF` | Primary hover |
| `--link` | `#E9E7E2` | Links = paper + `--hairline` underline, brightens on hover. No blue |
| `--focus` | `#5FE3B3` | 2px focus ring |

Rule: verdict colours appear **only** on engine output (glyphs, QA rows, kill log, counters). Never
on buttons, links, or decoration.

Contrast floors: `--paper` on `--ink-0` ≈ 13:1; verdict colours on `--ink-1` must clear 4.5:1 at data
size. Maintain if values change.

### 3.2 Typography

Semantic split: **grotesk = a human wrote it; monospace = the engine produced it.** Prices, counts,
verdicts, sources, filenames, dates → mono. Prose, headlines, the About voice → grotesk. This split
is a product feature, not styling.

| Role | Face | Stack |
|---|---|---|
| Display + body | Switzer (Fontshare, free, variable) | `Switzer, 'Helvetica Neue', Arial, sans-serif` |
| Engine/data | Commit Mono (free) or Berkeley Mono (paid) | `'Commit Mono', 'SF Mono', Consolas, monospace` |

Self-host, `font-display: swap`, latin subset; budget ≈ 60–90KB total. (Inter / Space Grotesk / IBM
Plex Mono deliberately avoided.)

Scale (1rem = 16px):

| Token | Size/line | Weight | Use |
|---|---|---|---|
| `--type-display` | 3.0/1.05 | 560, −2% tracking | Homepage hero only (mobile: 2.25) |
| `--type-h1` | 2.25/1.1 | 560 | Page titles (mobile: 1.75) |
| `--type-h2` | 1.5/1.2 | 520 | Section heads |
| `--type-body` | 1.0/1.55 | 400 | Prose; max measure 68ch |
| `--type-data` | 0.875/1.4 | mono 400 | Engine output |
| `--type-label` | 0.75/1.3 | mono 400, +6% tracking, caps in the VALUE | Eyebrows, counts, category tags |

`--type-label` carries NO `text-transform`. `src/__tests__/weightAndCasePolicy.test.ts:104-113`
forbids the property outright in `globals.css` and says why in its own failure message: uppercase
the value with `.toUpperCase()` if caps are the voice. The two are not in conflict once the
distinction is kept — the caps this token is for are the data's own casing (`UK`, `US`, gate tags),
which arrives already uppercase, so `text-transform` would only add the power to shout at a
sentence that was never meant to be one. The +6% tracking stays: it is what makes mono caps at 12px
legible, and it applies whether the caps came from the data or from CSS.

### 3.3 Glyph system (the entire icon set — six marks)

Custom inline SVG sprite, 14×14, 1.5px stroke, `currentColor` so parent token applies the verdict
colour. No icon libraries.

| Glyph | Construction | Meaning |
|---|---|---|
| Survived | Filled square, ink tick knocked out | Check passed |
| Pushed back | Square, left half filled | Passed with caveat |
| Killed | Outline square, ✕ through | Check failed |
| Pending | Outline square, empty | Animation start state |
| Source | Small ¶-style anchor mark | Claim carries a receipt — tappable |
| Kill cause | ✕ + two-letter mono code (IN incumbency · PS payer solvency · PA pain · DI distribution · LE legality · VA value durability) | Kill-log taxonomy |

### 3.4 Space, radius, elevation

- Base unit 4px; steps 4/8/12/16/24/32/48/64/96.
- `--radius: 2px` everywhere (glyph squares 1px). No pills.
- **No box-shadows.** Depth = surface step (ink-0 → ink-1 → ink-2) + hairline.
- 12-col grid, 1200px max, 24px gutters. Catalogue: CSS grid `minmax(300px, 1fr)`.

### 3.5 Motion — narrates state change; nothing else moves

| Token | Value | Use |
|---|---|---|
| `--ease` | `cubic-bezier(0.2, 0, 0, 1)` | Everything |
| `--t-micro` | 120ms | Hover, focus, glyph highlight, counter tick |
| `--t-state` | 240ms | Chip expand, panel open, filter apply |
| `--t-resolve` | 400ms per check | Verification sequence |

**Signature animation — the resolve sequence** (hero, how-it-works, pack QA on first view): pending
glyph → 400ms hold → snaps to verdict; killed rows strike through and dim to `--paper-faint` over
240ms. **Sequential, never parallel** — the engine checks one thing at a time. Kill counter: single
120ms mono-digit tick when in view; no slot-machine rolls. `prefers-reduced-motion`: final states
render instantly — non-negotiable. No parallax, no scroll-jacking, no decorative motion.

---

## 4. P2 — Core components

- **Primary button:** inverted ink, mono label, sentence case, 2px radius, ≥44px hit area, one per
  viewport. Label = the action's exact effect (≤4 words, verb first). **Secondary:** hairline
  outline, paper text.
- **Pack card:** `--ink-1` + hairline. Top row: category label + `£NN` (mono, right). Title grotesk
  520. **8-glyph verdict strip** (one per check — the card's signature, replacing prose
  description). Bottom: `8 docs · NN sources` in `--type-label`. Tap a glyph → expands its verdict +
  source. The pack page carries the description (see §6.8 copy rule).
- **Source chip:** inline anchor glyph after a claim; tap → `--ink-2` popover, 240ms: domain (mono) +
  one line on what it evidences + link. Sitewide primitive — any sourced claim gets one.
- **QA row:** glyph + check name (grotesk) + verdict word (mono, verdict colour) + source chip. One
  component reused identically on pack pages, /sample, /how-it-works, and the homepage receipt block
  — the receipt format must be recognisable everywhere.
- **Kill-log entry:** struck-through idea name (mono) + kill-cause glyph/code + expandable sourced
  reason (publish-passed per §2).
- **Intent search (catalogue):** single full-width input, mono placeholder `describe what you can
  run…`, answered by the engine; category filters demote to a secondary row. The existing "What
  skills do you bring?" picker merges into this.
- Adopt-time delete list: all box-shadows, all radii >2px, all colours outside §3.1, any icon not in
  §3.3, HTML `<form>` tags in any React surface (use event handlers).

---

## 5. P1 — Copy standard & vocabulary

### 5.1 Voice rules (Monzo-register, information-preserving)

1. **Say it once, sitewide.** Ownership map in §5.3. Every other page links, never restates.
2. **Kitchen-table test** for *site copy*: if you couldn't say it to a friend, rewrite it. Kills:
   parametric micro-bond, productized service, vertical tool, grounded, beachhead, payer solvency
   (as display text), solo-underwritten, IRROPS, eligibility matrices, "earns one rung."
3. **Pack copy is a different standard:** completeness and precision over brevity. Load-bearing
   domain terms (DSAR, COSHH, TPO, IHT, parametric) are **kept and defined on first use**, never
   paraphrased away.
4. **Front-load:** first five words carry the point. FAQ answers answer in sentence one.
5. **Question-form beats noun-phrases** for the checks. "Is the pain real?" not "pain reality." The
   kill-log's verdict labels ("The payer cannot actually pay") are the canonical phrasing — use them
   everywhere the checks are named, including replacing the homepage strip "pain reality · value
   durability · incumbency · payer solvency · distribution · legality."
6. **Length defaults (not gates):** pack-card/opening description — as long as needed to name buyer +
   problem + mechanism, no longer (don't strip a pack's genuine moat, e.g. FOI/tribunal-data edge, to
   hit a count); explanatory paragraphs ~40 words; buttons ≤4 words. Longer is right when every
   clause carries a decision, fact, or promise (the pricing comparison tables are the model).

### 5.2 Vocabulary — one name per thing (global find-and-fix)

| Canonical | Retire | Notes |
|---|---|---|
| Catalogue | Catalog | en_GB locale |
| pack | dossier, report, download, shelf item | |
| killed / survived | shot, rejected, died, destroyed | |
| the checks | the gates, the fronts, the filter, the panel, the gauntlet | |
| the engine | the Mumchimp engine, the filter, "a room built to destroy it" | |
| evidence-backed / sourced | grounded | |

### 5.3 Ownership map (who owns each fact)

| Fact | Owner | Remove restatements from |
|---|---|---|
| Pricing logic (same 8 docs; price = opportunity size) | /pricing | Home (×3), FAQ |
| The checks, listed | /how-it-works | /about (full duplicate), home strip |
| What's in a pack (8 documents) | Home ("What's inside") | Second home section, /pricing doc list → keep as bare filenames only, /about, FAQ ¶1 |
| Kill-log explanation | /kill-log | Home, /how-it-works (×2), /about |
| Honest limits / what you don't get | /pricing | /how-it-works "The honest limits" → link |
| Email-capture promise | The capture block itself, once | Was stated 4× within the block |

---

## 6. P1 — Page-by-page work orders

### 6.1 Home

- **Keep untouched:** hero headline + subline ("Business ideas with the research already done." /
  "The buyer, the price, the margins and the plan. Every claim links to its source."); the QA
  question block; "14-day money back · Every claim sourced · One-time payment"; footer disclaimer.
- **Hero (design):** becomes a live engine readout — ideas entering, dying, occasionally surviving,
  ticking against live counts (§1), using the resolve sequence (§3.5). Two CTAs. Target ≤ ~800 words
  of interface copy on the page (from ~1,400) achieved almost entirely by de-duplication, not
  compression.
- Sample CTA: "Read a free sample / A whole report, free. No payment, no email." → **"Read a full
  pack free — no email needed."**
- "Newest on the shelf" → **"New this week"**.
- Pricing sentence → one line: **"Same 8 documents in every pack. Bigger opportunity, higher
  price."** + link to /pricing.
- Pack cards → §4 glyph-strip card; all card copy through §2 (no "…" truncation) and §5.1 rule 6.
- US-packs note → **"US research, US law, US buyers. The method transfers; the numbers won't."**
- Email block, full replacement: header **"Get the next survivor."** / body **"Most ideas die in
  vetting. When one survives, we email you. Nothing else."** / button **"Email me survivors"** /
  microcopy **"Unsubscribe any time."**
- Checks strip → replace with the six kill-log verdict phrases (§5.1 rule 5).
- Trust section → **"Every idea is checked the way a sceptical investor would check it. No source, no
  listing. What's here is what survived."**
- **"What you get, at every price" section → delete** (owner: /pricing). Doc-list blurbs trimmed
  ~30% and de-jargoned, e.g. Executive Summary → "The opportunity on one page: what it is, what
  checked out, and what we don't claim." Financial Model → "Pricing and the numbers behind it.
  Anything we couldn't verify is marked missing — never made up." Closing line → "8 plain-text files
  in a zip. Yours to keep, edit, or paste anywhere. No login, no subscription." (drop
  Notion/Obsidian name-drops).
- Chidi paragraph → moves to /about (§6.3); homepage keeps one line + link ("Who is behind this →").
- Closing CTA sub-line → "56 packs. Research done, every claim sourced." (live count).

### 6.2 /how-it-works — best page on the site; prune, don't rewrite

- **Keep:** the full real-dossier walk-through with live sources (it *is* the pitch); "One kill, and
  it stops"; the adversarial-pass section; "Silence in the evidence record means 'unverifiable,' not
  'false'" verbatim.
- Replace static walk-through with the resolve-sequence animation over the same content (§3.5).
- Confidence floats per §2.4. Killed-example cards: complete sentences, no "…".
- Keep one "auditable, not a black box"; cut the duplicate.
- Add the one canonical AI-disclosure sentence (agents run the checks) — this page owns that fact;
  home and about stay silent on mechanism and link here.
- "The honest limits" → one line + link to /pricing's "What you do not get".
- Vocabulary sweep: panel/gauntlet/gates/fronts → the checks / the engine.

### 6.3 /about — rebuild; wrong page entirely

- Content = Chidi's story (move + slightly expand the homepage paragraph; "So I built the part I
  kept losing to doubt" is the thesis — let it breathe), one line on the engine's origin, single
  links to /how-it-works and /kill-log. Optionally one photo; otherwise monochrome per §3.1.
- Delete: the duplicated checks list, kill-log explanation, "what a pack is."
- Delete or translate the internal style-guide leak: "The voice is source-or-die. Sourced, not sold.
  Refutational, not promotional."

### 6.4 /pricing — keep; it earns its length

- **Keep:** the rung table (£149×1 / £99×1 / £79×6 / £49×40 / £29×9 — render from live data); "What
  you do not get" (now the sitewide owner of honest-limits); both sourced comparison tables (desk
  research firms €4–6k; subscription feeds $39/mo).
- Headline block: keep "One payment. No subscription." — cut "no upsell / no seat fees / no
  drip-feed".
- "aiming at the US earns one rung over" → "US-market packs sit one price step higher, because the
  market they address is bigger."
- Typo: "itsorigin" → "its origin". Counts per §1.

### 6.5 /faq

- Q1 rewrite (answer-first, aligns to 8 docs, de-dupes pricing): "A pack: one vetted business
  opportunity in 8 documents — build spec, go-to-market plan, operations plan, financial model,
  first-week checklist, marketing assets, executive summary, and a QA report with a source behind
  every claim. Delivered as a zip of plain-text files the moment payment clears. One payment, no
  subscription."
- Every answer: answer in sentence one, ≤3 sentences default (break for genuinely complex questions
  like the "500 buyers" one).
- "Catalog" → "Catalogue" in nav/footer.

### 6.6 /kill-log — the concept is the marketing centrepiece; surface it

- **Keep:** hero minus "shot": "We killed 1,168 ideas to put 145 on the shelf. Anyone can claim their
  research is rigorous. This is the receipt." (live counts).
- Entries through the §2 publish pass.
- Design: cause-of-death taxonomy visualised (counts per kill cause, from live data); entries use the
  §4 kill-log component; the six verdict-form filter labels here are canonical sitewide (§5.1.5).
- Closing note comma-splice: "…are left out. They're true, but they tell you nothing."
- Promote in IA: this page sells the survivors harder than the survivors do.

### 6.7 Catalogue & search

- Intent search per §4; skills-picker merges into it.
- Category counts, sort, filters all live-data.

### 6.8 Pack pages & /sample (Part C — next pass, standard defined now)

- Layout: split anatomy — human-readable opportunity one side (grotesk), machine receipts the other
  (mono QA rows, expandable source graph, §4 components).
- Opening description owns the full buyer + problem + mechanism statement (the card only shows the
  glyph strip).
- /sample = pure reader mode: best typography on the site, inline source chips; its job is to make
  £29 feel underpriced.
- Pack documents (8 files): pack-copy standard (§5.1.3) + publish pass (§2). A dedicated review of
  the sample's 8 documents propagates to all packs via the shared template.
- Checkout: one screen, guest by default, zero added friction.

---

## 7. P2 — Performance & transitions

- View Transitions API between catalogue and pack page; the card's glyph strip morphs into the pack
  page's QA block, 240ms.
- Targets: interaction → visual response <100ms; LCP <1.2s on 4G; zero CLS.
- Fonts per §3.2; inline SVG sprite for glyphs; no icon/webfont libraries.

---

## 8. Acceptance checklist

- [x] No hand-typed engine numbers anywhere (grep for: 1285, 1331, 1412, 1168, 78, 81, 145, 56, 57)
- [x] survived vs listed reconciled or explained in one sentence (`stats.ts` `survivorsSummary()`)
- [x] Publish pass live; kill log shows no hash IDs, no "…"/mid-word truncation, no "(,)" artifacts,
      no denylisted phrases; confidence floats resolved
- [x] "Catalog"→"Catalogue"; "shot"→"killed"; "grounded"→"evidence-backed/sourced";
      panel/gauntlet/gates/fronts→checks/engine; dossier/report→pack — zero remaining instances
- [ ] Pricing logic, checks list, pack contents, kill-log explanation, honest limits, email promise
      each stated on exactly one page *(home still restates pack contents + pricing logic)*
- [x] FAQ Q1 says 8 documents; "itsorigin" fixed
- [x] /about contains the human story and no mechanism duplication
- [ ] Only colours in production are §3.1 tokens; verdict colours appear only on engine output; no
      box-shadows; no radius >2px; no icons outside §3.3
- [ ] Resolve sequence sequential; `prefers-reduced-motion` renders final states instantly
- [ ] Focus visible on all interactives; killed state never colour-only; contrast floors hold
- [ ] LCP <1.2s / CLS 0 on the homepage and a pack page
