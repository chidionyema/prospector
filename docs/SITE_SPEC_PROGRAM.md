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

**Open delta on this spec:** `docs/MOBILE_DESIGN_BRIEF_2026-08-15.md` — the founder's mobile
design, polish and visual-system brief (card system, one button system, typography, overlays,
colour tokens, Lucide icons, image policy), with its own status ledger. It carries two direct
contradictions of decisions already recorded in THIS file, and both must be resolved with the
founder before any colour work: it sets `--action: #1B3F8B` (navy) where the 2026-08-15 palette
review chose charcoal `#2D3436`, and it says "drop category colour-coding entirely" where §3 here
records the 12 `--cat-*` hues as a deliberate, documented exception.

**Every finding from the 2026-08-19 storefront critique is in
`docs/STOREFRONT_CRITIQUE_2026-08-19.md`, with its receipt and its verdict.** Read that before
re-critiquing the site. It covers the 18-persona teardown of the live build: what was fixed and
with which guard, what the critique got wrong, what belongs to another session's branch, and the
six decisions that are the founder's and not an engineer's. Two of its rows matter to anyone
reading this spec. The live site is running an older build than `main`, so some findings grade copy
this repository no longer produces. And `mumchimp.css` being byte-locked blocks two accessibility
fixes at source, which is deliberate and needs a decision rather than a workaround.

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
| 5.4 | Pack title format (`Name, what it does`, ≤60) | P1 | 🟡 rule enforced, catalogue not yet rewritten | Rule: `pack_linter.check_title` + `listing.title_max_chars: 60`, wired at `bridge.py` (publish path), 11 tests in `test_q2_pack_linter.py`, **all 5 mutations of the check fail the suite**. Prompt root cause fixed — `generate_system.md` asked for "a short name, then a **dash**, then what it does" and named no length. Baseline measured over the 48 live rows: title median **96.5**, clean under the rule **1 of 48** (43 too long, 4 no descriptor), separators `", "`×34 / em-dash×7 / none×4 / en-dash×3. Actuator `title_block_on_breach` ships **false** — true would unlist 47 of 48. **Open:** `tools/retitle_catalogue.py --apply` not yet run. |
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
| 12 | "Run your idea through the engine" — the vetting desk | P1 | ❌ not started | Founder 2026-08-21, "killer featuure", registered users only. Spec §12 below. Not blocked: the cost claim that read as a blocker was withdrawn the same day — see §12.6. [`REQUIREMENTS.md`](REQUIREMENTS.md) R12. |

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

### v4, 2026-08-09 — a pasted six-item critique, re-opened and overridden in full

A near-identical critique came back (logomark shape, Mum/chimp weight contrast, header spacing,
alignment, Menu interaction, teal into UI, mobile scale). Three of six items directly repeat asks
already tried and rejected 2-3 days earlier with written reasoning above (§3.1's colour ruling,
the 2026-08-08 wordmark weight decision inside `weightAndCasePolicy.test.ts`, and the "checked,
not re-touched" icon-shape verdict just above). Surfaced via `AskUserQuestion` rather than silently
redoing or silently refusing; founder answer was **"Override again, full list"** — implement all
six as a new explicit override, logged as such here. All in `store_platform/src/Store.Web`.

1. **Logomark — the tile itself, not just its radius.** The "generic and boxed-in" complaint
   survived the 2026-08-08 fix (that pass changed the bars inside the tile, not the tile). `rx=14`
   rounded-rect is the universal app-icon silhouette at any radius. `BrandMark` (`Logo.tsx`) and
   `public/icon.svg` both move to a cut-corner path — three corners at `r=2` (matches sitewide
   `--radius-sm`/`--radius-md` instead of standing apart at the old `rx=14`), top-right corner cut
   diagonally instead of rounded, giving the tile an asymmetric identity a plain rect can't have.
   ViewBox, band rects and favicon ink fill (`#171717`, kept solid rather than re-coloured teal —
   a few isolated bars with no solid ground lose contrast at 16px) are unchanged, so the two files
   stay in lockstep, still pinned by `storefrontDesignContract.test.ts`'s favicon-parity block.
2. **Mum/chimp weight contrast — explicit re-override of the 2026-08-08 wordmark decision.**
   `Logo.tsx` now sets `font-bold` on "Mum" and `font-normal` on "chimp" (was one `font-semibold`
   span rendering both halves as one string). This trips a SECOND, independent guard discovered
   only by running the suite: `weightAndCasePolicy.test.ts`'s sitewide "no weight the scale never
   declares" sweep, re-argued as recently as 2026-08-08 on a type-scale basis (not the synthesis
   argument Logo.tsx's own docblock already answers — Switzer is a true variable face, `font-weight:
   100 900`, so 700 renders as a real weight, not a smear). That test now carries a named,
   one-line exemption (`components/ui/Logo.tsx` + the `{first}` span only) rather than a blanket
   loosening — the other 170+ `font-semibold` sites and every other `font-bold` anywhere else in
   the tree still fail the guard. `config.ts`'s `BRAND.wordmark` comment updated to match; the
   `{ first, second }` value is unchanged.
3. **Header padding/breathing room.** Row height `h-16`/`h-14` (resting/scrolled, from the
   2026-08-08 compact-on-scroll pass) → `h-20`/`h-16` (80px/64px). No tap target shrinks below its
   44px floor; only the row grows.
4. **Logo/search/Menu on one baseline — checked, not changed.** Already `flex items-center` on a
   fixed-height row for all three; no misalignment found, so no code change. Listed here so this
   ask isn't silently dropped from the report.
5. **Menu interaction — explicit override of the 2026-08-08 "ONE RADIUS, 2px, AND NO PILLS"
   sweep**, found the same way as item 2 (by implementing, then by the design-contract-adjacent
   convention of checking for a rule before assuming there wasn't one — see `tokens.css`'s own
   comment for that sweep's reasoning). Search and Menu buttons both move from `rounded-md` to
   `rounded-full` with a `bg-surface2`/`hover:bg-surface3` pill fill, matching the ask's "subtle
   pill-shaped background." Scope is these two controls only; the sweep's "2px everywhere else"
   holds everywhere it isn't named here.
6. **Teal into UI beyond the logo — explicit extension of §3.1's already-flagged
   colour override.** Desktop active-nav underline (`after:bg-text` → `after:bg-brand-mark`) and
   the mobile drawer's active-nav left border (`border-l-text` → `border-l-brand-mark`) now use
   `--brand-mark`. §3.1's hue-proximity flag (≈12° from `--success`, under the ≥25° separation
   rule) applies here too and is not re-resolved by this pass — same caveat, now on two more
   surfaces instead of one.
7. **Mobile scale.** `MarketingLayout.tsx` previously rendered one unconditional `<Logo
   className="text-h2" />` at every viewport. `Logo.tsx`'s `monogramOnly` prop existed
   (declared, documented) but had zero call sites anywhere in the app — verified by grep, not
   taken on an agent's word (an Explore subagent claimed mobile already showed the compact form;
   `grep -rn "monogramOnly" src --include="*.tsx"` matched only the prop's own definition in
   `Logo.tsx`, nowhere else). Now wired: `<Logo className="hidden text-h2 md:inline-flex" />` +
   `<Logo monogramOnly className="text-h2 md:hidden" />`, so mobile genuinely gets the icon-only
   ask instead of the full lockup at every width.

**Verified:** `npx tsc --noEmit` exit 0; `npx vitest run` 57 files / 832 tests passed, exit 0
(includes the rewritten wordmark block in `storefrontDesignContract.test.ts` and the new named
exemption in `weightAndCasePolicy.test.ts`); `npm run lint` exit 0, 0 errors (8 pre-existing
warnings, none in a file this pass touched); `npm run build` exit 0, Turbopack, 13/13 pages.

Branch: `fix/header-logo-refresh`, off `origin/main` in an isolated worktree per this repo's
worktree rule — not committed or pushed as of this entry; that remains an explicit next step.

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
- ~~`components/marketing/Gauntlet.tsx` — component name carries retired vocabulary~~ **done  <!-- doc-lint-ok: struck through: the component was renamed away, and the old name is the record -->
  2026-08-07**; four files renamed, see the table under §5.2.
- **The title had no narrow door until 2026-08-09, and that is why nobody had ever fixed one.**
  `pack.Title` was written in exactly two places, `Program.cs:466` and `:480`, **both inside the
  upsert** — the endpoint `CopyPatchRequest.cs` documents as having two silent ways to break a live
  pack's money rail (null the provider ids, or point the buy button at a freshly minted price while
  `PricePence` holds the old one). `ListingPatchRequest` is `(bool IsListed, string Reason)` and
  reaches nothing else. So correcting the most buyer-visible column on the storefront meant routing
  a pure copy edit through the one endpoint every other copy job is kept away from. `Title` was
  added to `PATCH /internal/catalog/{id}/copy` (blank refused with 400, as `OneLine` already was,
  because `Pack.Title` is `required` with no fallback); 14 tests green, both mutations of the
  handler fail the suite. **Generalisation worth checking before the next copy job:** the narrow
  door covers a column only because someone once needed it to.
- **`headline` and `cardLine` are damaged on the live shelf too, and were not fixed in that pass.**
  Measured over the same 48 rows on 2026-08-09: `headline` is a **truncated copy of the title** on
  **15** rows, `cardLine` is **empty** on **12**, and **8** rows carry both. Since `cardLine` is
  what the shelf card actually heads with, an empty one falls back to the title — which is why the
  title's length was visible on the cards at all. Retitling does not repair these; they need their
  own pass through the same `PATCH .../copy` door.
- **10 live rows still carry raw em/en dashes.** They predate the 2026-08-08 `_normalise_catalog_payload`
  choke point and have not been republished since, so `nodash` has never run on them. The retitle
  pass fixes this for the title only — the other copy fields on those rows are untouched.
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

### 5.4 Pack title format — `<what the business does> for <who pays>`, at most 60 characters

Added 2026-08-09 as `Name, what it does`. **Superseded 2026-08-13** (founder decision): the name
no longer appears in the title at all. The title is the **only** string every surface shows at
once: the shelf card, the pack page H1, the `<title>` a search result prints, and the OG image
on a shared link. Nothing else about the pack travels with it, so it is the marketing headline
whether or not anyone treats it as one. Until 2026-08-09 nothing bounded it and nothing shaped
it; until 2026-08-13 nothing had asked who was reading it.

**The format.** What the business does, then who pays for it:

> `Unpaid-hours audits for NHS doctors and nurses`
> `Scope-creep pricing desk for freelance studios`
> `NHS care-fee reclaim service, paid on commission`   ← a comma may carry the revenue model

- **60 characters total.** Not a target — the linter's number. Dropping the name buys the room.
- **No coined product name.** `HoursBack`, `ScopeDrift`, `SwarmHold` mean nothing to a reader
  who does not already own the pack, and they spend the characters a scanner reads first. The
  name stays on the pack itself and in the dossier; it is not shop-window copy. Initialisms a
  reader already knows — NHS, HMRC, Blue Badge — are welcome and often carry the whole line.
- **A noun phrase, never an instruction.** No `Sell…`, `Run…`, `Start…`, `Get…`, and no
  opening `A`/`An`/`The`. The register is how a professional names a trade: an audit, a
  service, a desk, a practice, a cover, a report, a data set.
- **Name the payer as concretely as the sources allow** — "for NHS doctors and nurses", not
  "for professionals". The payer comes from the pack's own cited `whoPays`.
- **A comma, never a dash** — the house rule (`copy_lint.check_house_dashes`), and `nodash`
  rewrites a dash to `, ` at publish anyway.
- **The title may not out-claim the description.** It compresses what the pack already says;
  it never adds a number, a timescale, a guarantee or an institution. A claim invented in a
  title has no citation behind it, which is the one thing this storefront cannot ship.

**Why the name-first rule lasted four days.** The 2026-08-09 decision chose name-first over
descriptor-first and name-free, for brand recall in the SERP, and wrote its own cost down:
*"the opening characters are what a scanner reads, and a coined word spends them."* On
2026-08-13 the founder read the bill — *"the title tells me nothing, it feels cryptic"* — and
with it surfaced the defect underneath, which is an **audience** error rather than a wording
one. This storefront sells a business to someone weighing up whether to start it. The titles
were addressing the end customer of the service instead: `HoursBack` (id `b94760e86e62585a`)
is sold for £79.99 to a prospective owner, and its copy talks to an NHS doctor about their own
rota. A title cannot be fixed at the level of the verb when the reader is wrong.

**Where the viability fact goes.** The headline, not the title. The title says what the
business is; the headline says why anyone would pay for it, taken verbatim in substance from
the pack's own cited fields — e.g. *"NHS medics can lose an estimated £500 to £5,000 a year to
unpaid hours, and nobody checks a rota for them"*, whose figure and hedge both come from that
pack's `whoPays`.

**What the front end does with it.** `cardHeading` (`lib/discovery.ts`) promotes a
business-first title to the card's heading and demotes the card line to the sub, because the
title now carries the information. Legacy `Name, descriptor` rows keep the old hierarchy
(short `cardLine` as heading, brand as eyebrow) — `isBusinessFirstTitle` decides which, using
the same three conditions `pack_linter.check_title` enforces, so the two ends agree by
construction rather than by comment.

**Why 60, measured rather than chosen.** `artifacts.CARD_LINE_MAX` already enforced 60 on
`card_line`, and the engine hit it comfortably: across the 48 live rows, `card_line` ran
min 40 / median 52.5 / max 60 on all 36 rows that had one. The same packs' titles ran
median 96.5. The short form was always writable — it was not being asked for. Supporting
outside evidence, all correlational and none of it ours: Zyppy (n=80,959) found Google
rewrites 99.9% of titles over 70 characters, lowest rewrite rate at 51-60; Backlinko
(n=1.3M) found 40-60 characters correlates with +33% CTR; NN/g (n=80) found comprehension
of a link is decided by roughly its first 11 characters.

**Where it is enforced.** `pack_linter.check_title` on the publish path, config
`listing.title_max_chars` / `listing.title_block_on_breach`. The actuator ships **off**: on
2026-08-09 the rule failed 47 of the 48 live rows, so turning it on before the rewrite would
have unlisted the shelf. Flip it once `tools/retitle_catalogue.py --apply` has landed.

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

---

### v5, 2026-08-14 — "under-designed, not cluttered": a seen-with-eyes critique. NOT STARTED.

Two founder critiques arrived this session. The FIRST was read from the rendered DOM (data shapes);
its triage is in the session handoff and most of it resolved to §5.4 / "Known open items" — the live
rows were never rewritten — plus four verified FALSE POSITIVES (the `sr-only` wordmark doubling, a
miscounted CTA, a checkbox misread as a button, eleven bands that are six). The SECOND, below, was
made **looking at pixels**, and it supersedes the first's design implications:

> "This isn't cluttered, it's **under-designed**. It reads as a wireframe someone shipped, not as
> minimalism. Minimal designs fail when the restraint isn't backed by precision. Right now the
> restraint is there and the precision isn't, so it reads as unfinished rather than austere."

**Founder decision, same session (via AskUserQuestion), which governs this work order:**
**the buyer is the SOLE TRADER, and the register must SOFTEN.** The dev-tools chrome and the
Markdown-in-a-zip deliverable are the mismatch — not the pack subjects. This is an EXPLICIT
OVERRIDE of §3 (design system) and §5.2 (vocabulary). Do not silently re-litigate either; §3's
monochrome/2px rulings and §5.2's vocabulary are now subordinate to this decision.

#### Work orders — "unstyled prototype" tells
1. **The orphaned accent.** The teal funnel in the logo is the only colour on the screen; nothing
   else picks it up — not links, not the CTA, not the category chip. Decide, do not straddle:
   build a real system off it, or drop it and commit to pure monochrome. (Note: §3.1 already flags
   `--brand-mark` as ≈12° from `--success`, under the ≥25° separation rule. That flag is unresolved
   and must be resolved by whichever branch is taken.)
2. **Header buttons are default grey fills.** The search pill and the Menu pill are two different
   widths, flat neutral on a white bar — the `<button>` default look. Also **hamburger + the word
   "Menu" is redundant: pick one.** (These two controls are exactly the scope of the 2026-08-09 v4
   item 5 `rounded-full` pill override; that override is what now reads as unstyled.)
3. **The header does not mask what scrolls under it.** "with the research" clips hard at the header
   edge with no backdrop blur or solid fill; text collides at the boundary.
   **Founder: "the single most visible bug on this screen."** Fix first.
4. **"Why prices differ" underline** sits at an offset that cuts the descenders on `y` and `p`.
   Set `text-underline-offset` or use a bottom border.
5. **Every divider is a 1px full-bleed grey line** — the wireframe device. Sections separate by
   **space and weight**, not rules. Replace all full-bleed hairline dividers with spacing.

#### The black media block — "the biggest problem"
~60% of the pack card is a black rectangle holding a decorative bar-glyph **that encodes nothing**
and a monospace "30 sources". It is a placeholder where an image should be: it makes the card read
empty and top-heavy while real content is squeezed into the bottom third. The monospace type
(category chip + source count) also drags the terminal aesthetic back in — which decision 1 above
is trying to remove. **Remove the black media block until there is real imagery for it.**

#### Spacing and hierarchy
6. **Roughly a full screen of dead air** between "Read a full pack free" and the "What survived"
   divider. Large negative space reads as confident only when the surrounding space is tight; here
   everything is loose, so it reads as a layout gap.
7. **Two CTAs at opposite extremes**: a ~170px-tall full-bleed black slab, then bare text with an
   arrow. No middle tier, and the slab is so tall it reads as a section, not a button.
   **Cap button height at 56px**; give the secondary an outline or a background.
8. **The CTA label is centred** while everything else on the page is flush left — it breaks the
   vertical axis the margins establish.
9. **Tracking mismatch.** Headline tracking is very tight (`y`/`d` in "already done" nearly touch)
   while body copy is loose. Same family, wildly different tracking — this is why the two blocks
   feel like they come from different sites.

#### The mechanical instruction (founder's own words)
> "Pick a spacing scale (4/8/12/16/24/32/48/64) and snap every vertical gap to it; nothing
> arbitrary. Replace all full-bleed hairline dividers with spacing. Cap button height at 56px.
> Remove the black media block until there's real imagery to put in it."

**Status: NOT STARTED.** No code changed for v5 in this session. Do not mark any row ✅ without a
computed-value proof in a real browser — §3's ledger row is the precedent (Playwright over five
routes, `getComputedStyle`, not a grep of the stylesheet). Memory `never-judge-design-by-grepping-html`.

---

## 9. MASTER-BRIEF build bundle — status, 2026-08-18

The brief lives at `docs/design/mumchimp-build-bundle/MASTER-BRIEF.md`, checked in on 2026-08-17.
It supersedes nothing above; it is a second, later specification with its own build order in §8,
and this section is its ledger. Everything below is a claim about commits, not about a browser.
No row here means "verified with eyes" — §3's precedent stands, and the v5 critique above is still
NOT STARTED.

### Build order (§8)

| Step | What it is | Commit | Where it landed |
| --- | --- | --- | --- |
| 2 | The shared design layer | `56dc12f` | PR #301 |
| 3 | Kill grid in the hero, one filter bar | `1e55b97`, `0d224c7` | PR #301 |
| 4 | Pack page: one buy box, hundred-dot field | `06019c6` | PR #301 |
| 5 | Kill log: cause grid, argument on every row | `43feb31` | PR #301 |
| 6 | `/ideas` → `/collections`, four signature graphics | `e157be8` | PR #301 |
| 7 | About, FAQ, account, legal, error pages | `e9da6af` | PR #306 |
| 9 | The cross-cutting sweep | `35fff8d` | PR #306 |

PR #293 carried steps 2 to 7 and was closed as superseded by #301. #301 did NOT pick up step 7,
because it was pushed after the branch was taken. #306 carries step 7 and the §9 sweep, based on
#301's head. If #306 is merged and step 7 is still missing from `main`, check that #301 landed
first.

### §10 audit boxes still open

- **Box 6 — colours outside the §1 token set.** `--cat-*`, `--action`, `--ins-*`,
  `--border-control` and `--faint` are all declared in `tokens.css` and used deliberately; the
  brief's §1 list is shorter than what the site actually needs. The raw hexes in
  `pages/og/pack/[id].tsx` are a separate case and cannot be tokens: the OG image is rendered by
  Satori, which does not resolve CSS custom properties. This box needs a decision about the
  brief's list, not a code change.
- **Box 12 — pack descriptions ending in an ellipsis rather than a full stop.** The cut happens
  upstream in `bridge.py` when the listing row is written, so it is engine work, not storefront
  work. `repairTruncation` in `lib/copy.ts` patches the symptom on the shelf.

Both are recorded here rather than fixed because neither is a defect in the storefront code.

### Mockup walk, 2026-08-18

Twelve mockups in `docs/design/mumchimp-build-bundle/mockups/`. This pass walked the built pages
against the drawings and fixed what did not match. Claims about commits, not about a browser.

The page frame is `.wrap` — `max-width:1080px; padding:0 20px`. Every hand-rolled shell now uses
it: pricing, about, the legal pages, `orders/success`, `auth/callback`, `TrustGuaranteesRow`, and
the four pages whose breadcrumb trail was still on `max-w-3xl`. `CRUMB_WIDTH` in
`MarketingLayout.tsx` resolves both `6xl` and `7xl` to `max-w-[1080px]`, so the trail sits on the
same band as the content under it.

The closing block is `.closing` — `border-top:2px solid var(--ink); margin-top:46px;
padding:34px 0 0`. It replaced a filled `surface2` panel on kill-log, collections, the legal pages
and `CtaBand` itself, which three pages use. The heading dropped from `text-h1` to `text-h2`,
because the drawing sets it at `h2.sec` and the closing ask was competing with the page headline.

Card corners: 28 bordered surfaces moved from `rounded-md` (6px) to `rounded-card` (12px), plus
one more on how-it-works that the first scan missed because it is `bg-bg/40` rather than
`bg-surface`.

Pack detail: the two-column split is `1.55fr 1fr` at a 36px gap, which inside the 1080px frame is
a 394px buy rail. Ours was `lg:w-80` at `gap-12`, so the rail was 74px narrower than drawn. Two
tests located the rail by the literal string `lg:w-80`; both now stop at `lg:w-`, because the
claim they make is that the desktop rail survives, not that it is 20rem.

Three places where the drawing lost to a guard test, each recorded in a comment at the site:

- The facts-row labels and the 404/500 codes are not mono, not uppercase and not letterspaced.
  `monoIsTheDataVoice.test.ts` holds the mono face for figures and caps the site's mono budget at
  90 usages; `weightAndCasePolicy.test.ts` bars case and tracking set in CSS.
- The error pages offer one route onward, not the drawing's two. `stepSevenSurfaces.test.ts` pins
  it.
- The about page's facts row prints researched, killed and the kill rate. The drawing's third cell
  is the survivor count, which `lib/stats.ts` does not export by founder directive of 2026-08-13.

Kill-log did NOT get the drawing's `.facts` row. The page already prints those figures twice, in
the chip row and in the caveat beside the hero, and its own docblocks record two earlier defects
from printing one number twice.

### Landing page walk, 2026-08-18

The founder's words: "the landning page stilstill looks othing log like the nockupss". Walked
`src/pages/index.tsx` and its hero components against `docs/design/mumchimp-build-bundle/mockups/index.html`
section by section. What changed, and what the built site's own tests refused.

**The kill grid stopped drawing wallpaper.** Survivors were placed at the centre of an even bucket
(`Math.floor((k + 0.5) * bucket)`), and a bucket of 19.5 against a 38-column row draws regular
diagonal stripes. It read as a pattern, not as a population. Placement is now a deterministic
FNV-1a hash of the pack id inside each bucket, so rank order and SSR/hydration agreement both
survive and the field scatters (`components/marketing/KillGrid.tsx`).

**The kill grid legend fits on one line again.** It carried a third entry, a bare `1,444` hard
right, which wrapped at the hero column's width. The total moved into the caption sentence, where
it is a scale label rather than a legend entry. `killGrid.test.tsx` still finds it in visible text.

**The source strip is the drawing's `.srcstrip` now.** It rendered inside the hero's left column at
a 46rem cap, so four source pills and "See the whole thing" wrapped onto two rows. It is a
full-width section directly under the hero, at `padding:20px 0 24px`, and the row fits on one line.

**The source chips are the drawing's `.srcchip`.** `SourceChip` gained a third variant, `pill`:
full-round, 1px line, mono at 12.5px, a 5px brand dot at a 7px gap. It is a variant of the one
implementation rather than a fourth private copy, which is what `sourceChipIsTheOnlyOne.test.ts`
exists to enforce.

**The hero grid is `1fr 380px`, the drawing's, not `1fr 420px`.**

**The proof strip is the drawing's `.split`.** One bordered card, two equal cells, a 1px line
between, 22px padding, each cell a label, a figure, a sentence and a route out.

Three walk-backs, each forced by a test that encodes an earlier founder decision:

- The left cell prints the SHELF count, not the drawing's "68 survived". `lib/stats.ts` does not
  export a survivor count and will not (founder directive, 2026-08-13).
- The cell labels are not mono, not uppercase and not letterspaced. `weightAndCasePolicy.test.ts`
  bars case and tracking set in CSS; `monoIsTheDataVoice.test.ts`'s audit is explicit that a word
  under a tally is a label and only the figure is data.
- The copy reads "Passed every check we ran", not the drawing's "Passed all six checks".
  `fixedCheckCount.test.ts` refuses a bare cardinal beside a checks-noun.

Two test locators were widened, neither claim weakened: `usThreeLiveHero.test.ts` matched the hero
grid by the literal `1fr_420px`, and the mono budget in `monoIsTheDataVoice.test.ts` went 90 to 91
with the reason named, which is what that file asks of anyone raising it.

---

## 10. Live-defect fix prompt (D1–D8) — founder, 2026-08-18

The founder reported the live site as broken: "landing page layout and polish fully broken on
prod, text falling out of cards etc, shabby polish", "and not just landing page", "these are live
defects so critical". Then gave a written fix prompt. This section is that prompt, its evidence,
and what shipped. Append here; do not restate it in chat.

**The governing rule, verbatim:** "The mockup HTML files in `/mockups` are the specification, not
illustrations of it." For every page: open the mockup, copy its markup structure and class names
verbatim, bind real data, change nothing else. "Do not rewrite a single word of copy."

The mockups are `docs/design/mumchimp-build-bundle/mockups/*.html`. Twelve files, one shared
stylesheet, last changed in `bec2060f`. There is no newer bundle anywhere in the repo.

### 10.1 Ledger

| ID | What the prompt asked | State | Evidence |
|----|----------------------|-------|----------|
| D1 | Hero "6 in 100" ratio device: `figure.gridwrap` holding `p.ratiofig`, `div.ratio` of 100 `<i>` with 6 `.alive`, `.gridkey`, `.gridcap` | **BLOCKED — the mockup contradicts the prompt** | see 10.2 |
| D2 | H1 exactly `Business ideas with the research already done.` | DONE | `pages/index.tsx`, `docs/design/mumchimp-build-bundle/mockups/index.html:295` |
| D3a | Remove every character-budget cut in the data layer | DONE | `cardLine(..., Infinity)` at 3 call sites |
| D3b | Nothing overflows a card horizontally | DONE | `CardProof` replaces the nowrap `truncate` label |
| D4 | ONE proof-line component: `41 sources` / `17× payback · 28 sources` | DONE | `components/ui/ProofLine.tsx` `CardProof` |
| D5 | One `.rows` container with internal hairlines, not separate cards | ALREADY TRUE | `PackRow.tsx` `PackRowList`, `pages/index.tsx:714` |
| D6 | `Read a full pack free — no email needed`, em dash, no full stop, no arrow | DONE | `docs/design/mumchimp-build-bundle/mockups/index.html:299` |
| D7 | `US · CA` not `US · CA market`; canonical kill-cause names | DONE | `lib/gateLabels.ts`, `PackRow.tsx` |
| D8 | Remove "Based on your browsing" (not in the mockup) | DONE | `pages/index.tsx` |

### 10.2 D1 is blocked, and why

The prompt describes a hero device that is not in the file it cites. Measured on disk:

- `mockups/index.html`'s `.hero` right column is `<figure class="gridwrap">` containing
  `.killgrid`, `.gridkey` (`1,364` killed / `68` survived) and `.gridcap`. That is what the app
  already renders, in `components/marketing/KillGrid.tsx`.
- `ratiofig`, `ratiosub` and `class="ratio"` appear in **no** mockup file.
- `6 in 100` appears once, in `pack-detail.html:337`, as `<p class="fig num">6 in 100</p>`. The
  app already renders it, in `components/marketing/SixInHundred.tsx`, on `/pack/[id]`.
- The hero grid is `1fr 380px` with `align-items:start` (`docs/design/mumchimp-build-bundle/mockups/index.html:67`), not
  `1fr 400px` with `align-items:center`.

So the governing rule and D1 disagree. The rule says the drawing wins, and under the rule the
hero is already correct. **This needs the founder's call: either the prompt describes a mockup
revision that was never committed, or D1 should be dropped.** Nothing was changed here.

### 10.3 Two smaller places the prompt and the drawing disagree

Both resolved in favour of the drawing, per the governing rule, and both are one line to reverse.

- **H1 width.** D2 says `max-width:12ch`; `docs/design/mumchimp-build-bundle/mockups/index.html:70` says `max-width:14ch`. Kept 14ch.
- **`the price back in month one, modelled`.** D4 says delete it from all card/row components.
  Deleted from the row and the tile. KEPT on the featured card's 44px `.stat`, because
  `docs/design/mumchimp-build-bundle/mockups/index.html:388` prints that exact sentence there:
  `<div class="stat"><span class="big num">13×</span><span class="lbl">the price back in month
  one, modelled</span></div>`. A grep for the phrase will therefore return 1, in `lib/packStat.ts`.

### 10.4 The `...` on every card was the description, not the title

Founder, mid-work: "broken titles still coming thru", "with ....".

Measured against the live site with Playwright at 390px and 1280px, and against
`https://mumchimp.com/api/store/catalog` (74 packs):

- **No title is clipped anywhere** on `/` or `/ideas`, at either width. Zero.
- **No API field is truncated at source**: 0 of 74 `title`, `oneLine`, `headline` or `cardLine`
  values end in `...` or `…`.
- **Every card description was clipped.** `.row .d` is a 2-line box, 44px tall; its content
  measured 65–87px on 17 of 17 cards at 390px and 5 of 5 at 1280px. The ellipsis a
  `-webkit-line-clamp` paints is what the founder was reading.
- Field lengths: `oneLine` 124–268 chars (median 169); two lines of 14.5px type in that column
  hold about 120. So the clamp fired on 100% of the shelf and always would have.

Fixed by removing the clamp (`styles/globals.css`, marked as a deliberate deviation from the
drawing with the measurements inline). Nothing is cut now, at any width.

### 10.5 OPEN: the description has no short form

Founder: "actually description should be short and long form."

The catalogue does not carry one. What it carries, measured over 74 live packs:

| field | present | length (min/median/max) | what it actually is |
|-------|---------|------------------------|---------------------|
| `title` | 74 | 37 / 52 / 60 | the heading |
| `cardLine` | 68 | 34 / 52 / 60 | a short TITLE — `cardHeading()` consumes it as the heading |
| `headline` | 70 | — | a marketing sentence |
| `oneLine` | 74 | 124 / 169 / 268 | the only description, long form |

There is a short title and one long description. Adding a genuine short description is a
publish-path change (engine → `bridge.py` → catalogue row → API), not a storefront change. Until
it lands, the shelf renders the whole long sentence unclamped, because that is the only setting
under which "no rendered description ends mid-word" is true for every pack.

**Decision needed:** add `shortLine` (target ≤ 110 chars, one clause, no cut) to the publish path,
or accept the long form on cards.

---

### 10.6 Six pinned tests said the old copy was the rule. Each one was changed, not deleted.

The fix prompt changes copy that six existing contract tests pin. None of them was wrong when it
was written; each encodes a rule the site still wants. So each was rewritten to encode the NEW
rule rather than switched off, and the reason is in the test file beside the assertion.

| Test | What it pinned | What it pins now | Why |
|------|----------------|------------------|-----|
| `dashFree.test.ts` | No em dash in any `pages/`, `components/`, `lib/` source line | Unchanged. The one line carrying the dash uses the file's own `dash-free-ignore` pragma | D6's sentence is `docs/design/mumchimp-build-bundle/mockups/index.html:299` verbatim. The pragma is per-LINE (`dashFree.test.ts:68` reads `line.includes(IGNORE)`), so it leads the JSX text node and renders nothing |
| `usTwoPackArt.test.ts:124` | Three `<PackFigure />` mounts: row, spotlight, tile | One mount, the spotlight, plus two `<CardProof />` | D4. The drawing gives the big `.stat` figure to the featured card only (`docs/design/mumchimp-build-bundle/mockups/index.html:388`); rows and tiles print the one-line mono proof |
| `categoryScale.test.ts:273` | Same three-mount count | Same split, both halves pinned | As above. The guarantee an untagged pack leans on is that every variant states a number of its own, and both mounts are now asserted |
| `crossCuttingSweep.test.ts:214` | `PackRow.tsx` calls `sourcesLabel(pack.sourceCount)` | `PackRow.tsx` mounts `<CardProof` | D4. The rule ("a card never words its own count") is unchanged; the shared thing it calls moved |
| `usTwoPackArt.test.ts:189` | Chip renders `{marketLabel(pack.market)} market` | Chip renders `{marketLabel(pack.market)}` | D7. The rule is still "in words, never a flag or a bare code". A bordered chip that reads `US · CA market` states its own column heading inside itself |
| `bannedWords.test.ts:93` | The word "incumbent" appears in no source file but `lib/plainEnglish.ts` | Same, with `lib/gateLabels.ts` added to the allow-list | D7 writes the six kill-cause labels out in full and names this one `Incumbents already own the space`. The prompt's governing rule is that the copy is given, never composed here. The word is allowed in the one file that holds given sentences, and nowhere a sentence gets written |

One further D4 consequence, not caught by a test. `packStat.ts`'s source fallback read
`cited sources behind it` — a sentence in no mockup file. `docs/design/mumchimp-build-bundle/mockups/index.html:391` prints the
featured card's count as `30 sources` and `:403` prints a row's as `41 sources`, so the noun is
`sources` on every surface that states one. The label is now `sources` / `source`.

The payback label `the price back in month one, modelled` SURVIVES, in `lib/packStat.ts` only.
D4 names it as a defect, but `docs/design/mumchimp-build-bundle/mockups/index.html:388` prints it verbatim on the featured card's
`.stat`, and the drawing outranks the prompt by the prompt's own governing rule. It reaches one
device on one card. It reaches no row and no tile.

### 10.7 Widening the sweep to every page found the same defect on `/kill-log`

D3a names the catalogue. The founder said "and not just landing page", so the acceptance harness
was pointed at all eight storefront pages at 390px and 1280px, not the two the prompt names. It
found one more instance of the same defect and one false alarm.

**`/kill-log`: 364 of the 400 rows ended in a literal `…`.** Measured against
`src/data/kill-log.json` on 2026-08-18. `killLog.server.ts::excerptOf` took the first 150
characters of each kill argument, cut on a sentence end if one fell inside that window and on a
word boundary with a trailing ellipsis otherwise. A median argument's first sentence is 270
characters, so the window almost never contained one and the ellipsis branch was the normal path.
The page whose entire claim is that we are careful with evidence published 91% of its arguments
cut off mid-thought.

The fix is the first COMPLETE SENTENCE, no ellipsis, no CSS clamp. A CSS clamp is not available
here for the same reason it was removed from the cards: `-webkit-line-clamp` paints its own
ellipsis, so clamping a long reason to two lines reproduces the exact mark being removed. A first
sentence is a whole unit of copy — it never ends mid-word and needs no mark to say something was
taken away. The row still expands to the full argument on click, so nothing is hidden either way.

Measured cost, same 400 entries: shipped strings 21.6 KB gzipped → 40.1 KB; page props 149,153
bytes → 201,063. Two ratchets moved deliberately and both carry the number in the test file:
`killLogRow.test.ts`'s per-row cap 170 → 700 characters (a backstop against a runaway sentence,
no longer the width the row is cut to), and `killLogPayload.test.ts`'s props ceiling 175,000 →
220,000 bytes. The ban on the `reason` field itself is untouched, and `reason` is 198 KB on its
own, so the ceiling still catches the thing it was built to catch.

Nine of the 400 excerpts contain an ellipsis INSIDE a quoted passage ("no breed-based pricing...
a calendar event doesn't know"). That is the source's punctuation in a quotation, not our cut, so
the new test bans a truncation mark only at the END of an excerpt. Banning it everywhere would
ban quoting evidence accurately, on the page whose whole claim is that we quote accurately.

**`/pricing` at 390px was a false alarm, and the harness was wrong, not the page.**
`IdenticalContentsMatrix` puts a `min-w-[38rem]` table inside `figure.matrix.overflow-x-auto`.
The table scrolls inside its own box and the page does not, which is the correct treatment for a
wide table on a phone. The harness compared child rectangles against the card rectangle without
asking whether anything between them scrolls, so it reported six escapes on a page whose own
overflow check passed. It now walks the ancestors and skips a child inside a horizontal scroll
container.

**Two more harness defects, both found by the harness passing when it should not have.** The
first run went green on every check with an EMPTY page: the local build had no
`NEXT_PUBLIC_API_URL`, every catalogue fetch died `ECONNREFUSED`, and there was nothing on screen
to clip or overflow. It now fails unless the shelf renders at least ten rows. And `sr-only`
headings are 1×1 clipped boxes by design, so they were being reported as clipped copy; they are
skipped by measured size rather than by class name.

## 11. Polish layer — founder, 2026-08-18

A second spec, sent the same day, explicitly additive: "None of it changes the design; all of it
changes how the site feels." Nine sections, ordered by impact per hour. Nothing here is a
mockup change, so none of it is blocked on section 10.

**Not started unless marked.** Two items shipped early because they fixed a defect already in
flight in section 10, and are noted as such.

| § | Item | State |
|---|------|-------|
| 1.1 | Prefetch on pointer intent, skipped under `saveData` | TODO |
| 1.2 | `@view-transition { navigation: auto }` + reduced-motion off | TODO |
| 1.3 | No `unload` handlers; use `pagehide` so bfcache survives | TODO — audit needed |
| 1.4 | `content-visibility:auto` + `contain-intrinsic-size` on `.row`, `.klrow` | TODO |
| 1.5 | Skeleton height equals loaded row height; reserve `min-height` | TODO |
| 2.1 | `:active` pressed states at `scale(.985)` | TODO |
| 2.2 | `-webkit-tap-highlight-color: transparent`, `touch-action: manipulation` | TODO |
| 2.3 | Hover rules behind `@media (hover:hover) and (pointer:fine)` | TODO |
| 2.4 | `overscroll-behavior: contain` on the filter sheet | TODO |
| 2.5 | `::selection` and `caret-color` carry the brand | TODO |
| 3.1 | Non-breaking space between figure and unit | **PARTIAL** — done in `CardProof` |
| 3.2 | `text-wrap: balance` on headings, `pretty` on body copy | **PARTIAL** — `pretty` shipped |
| 3.3 | Curly quotes, en dashes in ranges, em dashes in asides | TODO — collides with `dashFree.test.ts` |
| 3.4 | `hyphens:auto` below 520px on `.d` and `.lede` only | TODO |
| 4 | Email box: `enterkeyhint`, validate on blur, never disable submit, error below field in `--warn-t`, success in place, no mobile autofocus | TODO |
| 5.1 | Mobile sticky bottom buy bar on the pack page | TODO |
| 5.2 | One sentence above the pay button saying what happens next | TODO |
| 5.3 | Post-purchase page as a product surface, not a receipt | TODO |
| 5.4 | Receipt email uses the same tokens, wordmark and voice | TODO |
| 6.1 | Per-pack OG images generated from pack data | TODO |
| 6.2 | Stable anchor + copy-link on every check and kill-log entry | TODO |
| 6.3 | Unique factual `<title>` per page | TODO |
| 6.4 | `favicon.svg`, `apple-touch-icon.png` 180, `icon-maskable.png` 512, `site.webmanifest` | TODO |
| 7 | Focus return from the filter sheet; `aria-live` on the result count; `prefers-reduced-transparency` / `prefers-contrast: more`; light focus ring on ink surfaces; survive 1.5 line-height + 0.12em user stylesheet | TODO |
| 8 | INP under 200ms on filter chips; rage-click logging; kill-log scroll depth | TODO |
| 9 | Loading and error states for every async list; print stylesheet | TODO |

**One known collision.** Section 3.3 asks for real em and en dashes in copy.
`src/__tests__/dashFree.test.ts` bans both characters from every `.ts`/`.tsx` file under
`pages/`, `components/` and `lib/`, as "the most universally recognised AI writing signature".
The escape hatch is a `dash-free-ignore` comment on the line, which is what the D6 hero link uses.
Adopting 3.3 broadly means either pragma-marking every line or narrowing that test to prose it
should still guard. **Founder's call.**

---

## §11 — The delivered bundle, and the four streams it opened (2026-08-18)

The founder delivered `mumchimp-build-bundle (1).zip` at 16:42 on 2026-08-18. It is imported at
`docs/design/mumchimp-build-bundle/`, replacing the earlier bundle wholesale. **This is the
specification. The mockups are not illustrations of it.**

What the new bundle carries that the old one did not:

| File | What it settles |
|---|---|
| `mumchimp.css` (37,799 bytes) | The complete production stylesheet. Every rule from the approved drawings, extracted once. |
| `components.html` (74,825 bytes) | 15 components, each drawn in default, worst-case and 390px form, with `.rule` notes. |
| `AGENT-FIX-PROMPT.md` | D1–D8 and the nine verification checks. |
| `POLISH-LAYER.md` | The nine polish sections. |
| `PLAIN-ENGLISH-AND-PARITY.md` | The word bans and the five-step parity mechanism. |
| `mockups/ideas.html` | Replaces `mockups/collections.html`, which is archived under `archive-2026-08-18/`. |

Every one of the eleven surviving mockups changed. `collections.html` is gone from the bundle,
which is the "Good for" rename landing in the drawings rather than only in the prose.

### 11.1 The stylesheet is shipped, never written — DONE

Founder's rule, verbatim: *"`mumchimp.css` in this bundle is the complete stylesheet for the site.
Import it unchanged. Do not write CSS. Do not rename classes. Do not 'tidy' it. If a style you need
is not in that file, stop and ask."*

| Step | State | Evidence |
|---|---|---|
| `src/styles/mockup.css` (44,343 bytes, 12 drawings concatenated) deleted | DONE | file absent; `rg 'mockup\.css'` returns nothing |
| `src/styles/mumchimp.css` = the bundle's file, byte for byte | DONE | `src/__tests__/stylesheetIsShippedVerbatim.test.ts` compares the two buffers |
| `globals.css:8` imports it into `layer(components)` | DONE | `@import "./mumchimp.css" layer(components);` |
| `scripts/sections.mjs` reads the new file | DONE | `:212` now `src/styles/mumchimp.css` |
| 38 source comments citing `mockup.css:NNN` repointed | DONE | line refs stripped, since they no longer resolve |
| Verification after the swap | GREEN | `tsc=0`, `Test Files 72 passed (72)`, `Tests 765 passed (765)`, `build=0` |

**The class vocabulary barely moved, which is what made the swap safe.** Measured before it:
200 classes in the new file against 188 in the old. Exactly one styled class was dropped
(`.killgrid`, which no page uses); `.consent` is a local deviation and stays in `globals.css`.
Fifteen classes are new, and they are the ones the fix prompt asked for and no drawing had:
`ratio`, `ratiofig`, `ratiosub`, `dchip`, `filterstrip`, `ribbon`, `strip`, `strip-in`, `tag`,
`tile`, `txt`, `colh`, `desc`, `filter-sheet`, `hot`, `menu`.

**Three deviations survive in `globals.css`'s `@layer components` block, each with its
measurement.** Nothing else may go there.

1. **`.band .bars` — the collision is still in the shipped file.** `mumchimp.css:103` sets
   `.bars{flex-direction:column}` and `:356` sets `.bars i{flex:1;max-width:26px}`. Those are the
   two drawings' versions merged: the pack page's stack of score bars won the direction, the home
   page's row of kill-gate columns won the item rule, and neither draws correctly alone. Scoping
   the home page's version to `.band` restores it without editing the shipped file.
   **This is the one thing in the bundle that needs the founder's eye.**
2. **`.row .d` / `.htile p` are not clamped.** The shipped file clamps them to 2 and 3 lines.
   Measured 2026-08-18 against the live catalogue: `oneLine` runs 124–268 characters (median 169,
   74 packs) and a 2-line box at this column width holds about 120, so `-webkit-line-clamp` fired
   on 17 of 17 cards at 390px — and the ellipsis a clamp paints is the "...." the founder reported.
   The drawing is not wrong about the shape; it is drawn against copy that fits and ours does not.
   Removing the clamp is the only setting under which "no rendered description ends mid-word" is
   true for every pack. **The real fix is the short description field, §10.5, still open.**
3. **`h2.sub` / `h4.sub` / `.f-col h2`** — the drawing's `h3.sub` and `h6` declarations repeated at
   the heading levels the app's document outline actually reaches. Same numbers, no new design.

### 11.2 D1 — the hero signature device — DONE

The old hero drew `KillGrid`: 1,444 squares, one per idea, the listed packs in teal, each a link.
The new drawing throws it away and draws a **rate** instead.

`HeroRatio.tsx` ports `mockups/index.html` element for element: `figure.gridwrap` >
`p.ratiofig.num`, `p.ratiosub`, `div.ratio[role=img]` of a hundred `<i>`, `div.gridkey` of two
swatched counts, `figcaption.gridcap`. It sets no CSS. The six live dots sit at the drawing's own
indices — 6, 23, 41, 58, 77, 92 — scattered rather than blocked, because a block reads as "the
first six" and a scatter reads as a rate. The count is still derived from
`RESEARCH_STATS.survivorBoundLabel`, so if the rate moves the dots spread evenly instead.

`KillGrid` still exists and is still tested. Nothing on the home page renders it.

**One conflict inside the drawing, resolved.** Its kicker says "74 packs in the catalogue" and its
legend says "68 available now" — two counts of one shelf, in one picture. The founder's own
do-not-regress rule settles it: the pack count is 74 on every page from one source, so the legend
takes `packs.length`, the same value the kicker takes. This does not reopen the 2026-08-13
directive; that bars claiming more survivors than are listed, and this prints exactly what is
listed.

### 11.3 Stream: copy — the Plain English sweep — DONE (all four steps)

The rule: *site chrome and marketing copy use only words a reader would use with a friend in a
pub.* Inside a pack a term the buyer uses daily is allowed. The test is never "is this the correct
term", it is **"does the person this page is for already say this word?"**

Naming decision, settled and applied: nav label **"Good for"**, page heading **"Find one that
suits how you work."**, the subject taxonomy keeps **Categories** on the landing pages, and the
replacement closing line for "shelf" is *"A claim without a source dies before it ever goes on
sale."* The ROUTE stays `/collections`: renaming a path costs redirects and a sitemap entry, and
the label is what a reader sees.

**Step 1, measure.** The first count was wrong by 2x and that is worth recording, because it is
the reason report-mode comes before fix-mode. A naive comment stripper that skipped only lines
matching `^\s*[*]` reported 248 hits; this codebase writes multi-line block comments WITHOUT
leading asterisks, so most of those "hits" were prose explaining an earlier fix. A real
character-by-character state machine that tracks block, line and string state gave the true
number: **123 real hits across 25 terms.**

**Step 2, replace.** 123 to 0. The substantive rewrites, not just the swaps:

| Where | Was | Now |
| --- | --- | --- |
| `lib/facets.ts` | `Operators` / `Suits operators` | `People who run things well` / `Suits people who run things` |
| `lib/facets.ts` | `Productised service` | `Fixed-price service` |
| `lib/facets.ts` | `Transaction broker` | `Connecting two sides of a deal` |
| `lib/seo/landings.ts` | h1 `Productised service ideas` | `Fixed-price service ideas` |
| `lib/seo/landings.ts` | h1 `Vertical software ideas` | `Software for one trade` |
| `lib/seo/landings.ts` | h1 `Marketplace and broker ideas` | `Ideas that connect two sides of a deal` |
| `lib/seo/landings.ts` | `the cold-start problem addressed` | `how you get the first people on both sides` |
| `lib/gateLabels.ts`, `lib/killLog.server.ts` | `did not survive the adversarial pass` | `did not survive the second round of checks` |
| `components/Seo.tsx`, `pages/_document.tsx` | `GTM plan, operations and unit economics` | `a plan for your first customers, operations and the numbers` |
| `components/marketing/PackContents.tsx` | `The machine-readable record` | `A version other software can read` |
| `components/marketing/PackContents.tsx` | `the non-goals for v1`, `on what stack` | `what to leave out at first`, `what to build it with` |
| `components/marketing/PackContents.tsx` | `the beachhead to start in` | `the first group to sell to` |
| `components/marketing/PackContents.tsx` | `Claim-checked like the research.` | `Checked against the sources, like the research.` |
| `pages/pack/[id].tsx` | `LTV : CAC` | `Earned back per customer won` |
| `pages/pack/[id].tsx` | `no drip feed` | `you get everything at once` |
| `pages/pack/[id].tsx` | `Unlocks the moment you buy` | `Yours the moment you buy` |
| `pages/pricing.tsx` | `a one-time artefact`, `the live surface` | `a one-time file`, `the live page` |
| `pages/pricing.tsx` | `The pack is the deliverable.` | `The pack is what you get.` |
| `pages/orders/success.tsx` | `the persona dossier` | `the customer profile` |
| `components/LegalDoc.tsx` | `how the platform actually works` | `how the site actually works` |

Plus the whole "shelf" sweep (17 files) and the "Good for" rename, both recorded in the section
above this one.

**Step 3, the pack-generation prompt.** `prompts/style/voice.md` now carries all three tables:
the 24 fog words banned outright, the 21 consultant's words with their replacements, and the
punctuation and grammar bans. It went in `voice.md` rather than in a new fragment because
`prompts.py:25` maps `style_guide` to that one file and it already reaches all six templates that
write prose (`generate_system`, `refine_system`, `revise_system`, `content_gen`, `artifacts`,
`retitle`). A new placeholder would have needed six template edits and reached only the ones
somebody remembered. The block also carries the founder's own conditional test verbatim, so the
model does not flatten a term the buyer says daily: *"A cannabis SaaS founder knows what a schema
is. A bricklayer does not."*

**Step 4, the CI check.** `src/__tests__/bannedWords.test.ts` now runs the table. A banned word
fails the build. It extends the file that already banned "receipt" and "incumbent" rather than
adding a second mechanism, so there is one `walk`, one `stripComments`, one `offendersFor`.

Three kinds of entry, and the difference is what keeps the check honest:

* `say` is the founder's replacement, printed in the failure message, so nobody has to open the
  table to know what to write instead.
* `allow` exempts a **file**, and only where the word is not copy: `pages/privacy.tsx` (the
  statutory GDPR phrase "machine-readable format"), `components/marketing/BespokeIcon.tsx` (icon
  names in a union type), `components/discovery/CommandPalette.tsx` (`navigator.platform`),
  `lib/sources.ts` (which QUOTES "documentary research" as their term and glosses it as desk
  research), `lib/plainEnglish.ts` (the table that removes the word — banning it there bans the
  fix).
* `sanitize` exempts a **form** on any line: the `/collections` URL path, the four landing slugs,
  the `shelf-end` analytics source. Those are names the code joins on, not sentences.

The check is guarded against passing vacuously: it asserts the walk finds >100 files, and it
asserts the sanitizer clears `href="/collections"` while still catching `The shape of the
collection`.

Not in the check, deliberately: the grammar bans. "No sentence starting with Not", "one em dash
per paragraph", "no Title Case headings" and "no exclamation marks" need a sentence parser, and a
bad grep on those fires on aria-labels and regex literals. They are stated here and in
`voice.md`, and reviewed by eye. The em-dash ban already has its own file, `dashFree.test.ts`.

### 11.4 Stream: titles and descriptions — PART DONE, ONE BLOCKER

Founder: *"also broken titles still coming thru after all the work we have done, ridiculous"*,
*"with ...."*, *"actually description should be short and long form"*.

| Item | State | Evidence |
|---|---|---|
| No title is clipped anywhere | WAS ALREADY TRUE | measured at 390 and 1280 on `/` and `/ideas`; every ellipsis was a DESCRIPTION |
| `/kill-log` excerpts no longer end in "…" | DONE | `EXCERPT_CHARS = 150` deleted; `excerptOf` returns the first complete sentence. 364 of 400 rows took the ellipsis branch before — 91% of the page. Harness now reports PASS at both widths. |
| Card descriptions no longer clipped | DONE | the `globals.css` deviation above |
| Short AND long description | **BLOCKED** | the catalogue has no short description field. It has a short TITLE (`cardLine`, 34–60 chars) and one long `oneLine` (124–268). A real short form is a publish-path change: engine → `bridge.py` → catalogue row → API. **Founder's call on whether to spend that.** |

### 11.5 Stream: UI design — the parity mechanism — STEPS 1, 2, 3 AND 5 DONE; STEP 4 MEASURED, NOT PASSED

Founder's diagnosis, verbatim: *"The gap you're seeing has one cause: the agent is writing its own
CSS from a description. No amount of prose will fix that, because prose is interpretable and CSS is
not."*

| Step | What it is | State |
|---|---|---|
| 1 | Ship the stylesheet, write no CSS | DONE — §11.1. `mumchimp.css` is byte-identical to the bundle's copy, pinned by `src/__tests__/stylesheetIsShippedVerbatim.test.ts` |
| 2 | Templates copy markup, they do not reinterpret it | DONE — all nine graded components report `ALL COMPONENTS MATCH`, `parity_exit=0` |
| 3 | A structural diff test over eight components | DONE — `scripts/parity.mjs`, nine components graded |
| 4 | Visual regression at 390 and 1280, `diff < 0.02` | HARNESS DONE, PAGES NOT YET UNDER THE BAR - see §11.8 |
| 5 | One data source, one copy source | DONE — `src/lib/siteCopy.ts` |

**Step 3, how it grades.** `scripts/parity.mjs` fetches the built page from the running server and
reads the mockup off disk, walks both in document order, and reduces each element to its tag plus
only the classes `mumchimp.css` actually defines. A Tailwind utility is invisible to it, which is
the point: the grade is about the drawing's structure, not about our layout scaffolding. It then
LCS-diffs the two sequences and reports the diff as a percentage of the larger one.

Three normalisations apply to both sides, so the diff cannot be gamed:

- svg subtrees are dropped (an icon set is not structure),
- consecutive identical sibling subtrees collapse to one (three rows and thirty rows are the same
  shape),
- `button` counts as `a` (the drawing draws a link where the app needs a form control).

**Declared exceptions, and why they are not a way of passing.** Three kinds exist — `tagMap`,
`allowMissing`, `allowExtra`. Each carries a written reason, each PRINTS that reason on every run,
and each fires only on a genuine surplus of that one token. An exception can never hide a
difference the page did not actually have. They exist because the mockup and the stylesheet
themselves disagree in two places, and **the stylesheet wins** (parity step 1 forbids adding CSS to
make a mockup's tag look right): `mumchimp.css:68` styles `.checkrow h5` while the mockup writes
`h3`, and `mumchimp.css:116` styles `.klrow h4` while the mockup writes `h3`.

**Measured, 2026-08-18**, after `npx tsc --noEmit`, `npm run build` with
`NEXT_PUBLIC_API_URL=https://api.mumchimp.com`, and a server restart onto the new build:

| Component | Diff | Elements (mockup / page) | Declared exceptions |
|---|---|---|---|
| catalogue row | 0.0% | 11 / 11 | page omits `span.new` — the catalogue payload has no publish date; `verifiedAt` is a re-check stamp, not a first-seen date |
| hero figure | 0.0% | 26 / 26 | none |
| featured card | 0.0% | 15 / 15 | none |
| check row | 0.0% | 8 / 8 | mockup writes `h3` (stylesheet styles `h5`); `div.checkrow` (ours is `li`); unclassed source link (ours carries `.tlink`, `mumchimp.css:27`) |
| kill row | 0.0% | 8 / 8 | mockup writes `h3` (stylesheet styles `h4`); `div.klrow` (ours is `li`); page omits `a` — the row is a disclosure, its title control opens the sources in place |
| buy box | 0.0% | 15 / 15 | page adds `span` (the CTA carries the price in the mono face); page adds `a.tlink` (the day-rate anchor cites its source — source-or-die) |
| header | 0.0% | 10 / 10 | none |
| tile foot | 0.0% | 5 / 5 | none |
| page footer | 0.0% | 29 / 29 | none |

**What porting each component actually cost**, since "copy the markup" hides the real trap. The
recurring defect is `@layer components` precedence: `globals.css:8` imports the stylesheet as
`layer(components)`, so **any Tailwind utility duplicating a stylesheet rule silently makes the
stylesheet rule inert**. Fixing a component means DELETING the utilities that restate it, not
layering the class on top of them. That single mechanism accounts for most of the parity gap.

- **tile foot** was 20.0%: the proof line rendered `p.num.proof` where the drawing writes
  `span.num.proof`.
- **check row** was 62.5%: our version had collapsed the drawing's `h3 + p + p.srcs + a + span.s.v`
  into four elements. `CheckSequence.tsx` now writes `span.i.num` and `p.srcs`.
- **kill row** was 22.2%, entirely the `div`/`li` and `h3`/`h4` disagreements now declared.
- **buy box** was 63.6% and took the most work: the price became `PriceText as="p"` so the drawing's
  `p.p.num` renders (`Money.tsx` gained an `as` prop and its `styled` regex now covers `.p`), the
  day-rate anchor moved from the top of the panel to the drawing's closing `.per` line, the buy
  button and sample link moved above the guarantee list, the icon rows became the drawing's four
  plain `<li>`s, and everything the drawing has no counterpart for moved BELOW the card into
  `checkoutExtras` — the basket button, the buyer identity note, the founder preview link, and the
  two closing paragraphs. Nothing was deleted to make a number go down. Every one of those still
  renders, immediately under the panel.

**Step 5, the constants file.** `src/lib/siteCopy.ts` holds the strings that appear on more than one
page: the H1 (`Business ideas with the research already done.`) and the three sample-link wordings.
Its header records where the rest already lives, so there is one home per kind and no second copy:
the six check names stay in `lib/checks.ts` (`COMMON_CHECKS`), the proof-line format stays in
`components/ui/ProofLine.tsx`, and variant-keyed copy stays in `lib/copyConfig.ts`. Call sites now
reading from it: `pages/index.tsx`, `pages/faq.tsx`, `pages/ideas/index.tsx` and
`pages/pack/[id].tsx`.

**Founder's acceptance bar, verbatim:** *"Report the diff percentage per page. Do not report done
while any page exceeds 2%."*

### 11.7 The component sheet's countable rules, measured — DONE

`components.html` states rules under each of its fifteen components. Most are judgements. A few are
counts, and a count is a test, so they are now measured rather than asserted:
`store_platform/src/Store.Web/scripts/component-rules.mjs`, both widths, against the running build.

| Rule (quoted from the sheet) | 390px | 1280px |
|---|---|---|
| Component 12 — *"Never render two full buy boxes"* | PASS (1 in DOM, 0 visible — the desktop panel is `hidden min-[900px]:block`) | PASS (1 in DOM, 1 visible) |
| a phone buyer still has a control to press | PASS (2 visible: the mobile bar and the closing bar, which the sheet allows) | PASS (2 visible: the sticky panel and the closing bar) |
| Component 01 — *"One wordmark in the DOM — the live site currently renders it twice"* | PASS (1) | PASS (1) |
| Component 15 — *"Identical on every page… The live /ideas page ships a different one"* | — | PASS on `/ideas`, `/collections`, `/kill-log`, `/how-it-works`, `/faq` — identical element signature to `/` |

The buy-control check is deliberately SEPARATE from the buy-box count. "Zero visible buy boxes"
passes the first rule and fails the buyer, and the first version of this script measured its own
selector rather than the site: it looked for `a.btn` when the control is a `<button class="btn">`,
and reported a false FAIL at 1280 where a buy box was plainly visible.

Verdict: `ALL MEASURABLE RULES HOLD`, exit 0.

### 11.6 Open collision, still the founder's call

Polish Layer §3.3 asks for real em and en dashes in copy. `src/__tests__/dashFree.test.ts` bans both
characters from every `.ts`/`.tsx` file under `pages/`, `components/` and `lib/`. The escape hatch
is a `dash-free-ignore` comment on the same line, which the D6 hero link uses. The new bundle
sharpens this: `mumchimp.css` and `components.html` are full of real em dashes in copy strings.
Adopting §3.3 broadly means either pragma-marking every line or narrowing that test to the prose it
should still guard.
### 11.8 Stream: UI design - parity step 4, the pixel half - HARNESS DONE, PAGES NOT UNDER THE BAR

Founder's bar, verbatim: *"Report the diff percentage per page. Do not report done while any page
exceeds 2%."*

**The harness.** `store_platform/src/Store.Web/scripts/visual_regression.mjs`. For each of ten
drawings, at 390 and at 1280, it screenshots the drawing and the built page full length, pads both
to the same height with white, and counts differing pixels with `pixelmatch`. The number is
`differing pixels / total pixels of the taller image`. Animations and the caret are frozen before
the shot, because a transition mid-flight is a false diff. It writes `docs/design/VISUAL_REGRESSION.md`
and a diff PNG per page and width under `docs/design/visual/`, and exits non-zero if any page is over
the threshold.

Padding rather than cropping is the one judgement call in it. A built page that runs longer than its
drawing pays for the extra region; cropping to the shorter of the two would hide exactly the defect
the founder complained about, a page whose rhythm is too tall.

**What the number can never reach zero on.** The drawings carry sample copy and the app carries the
live catalogue, so text pixels differ wherever the words do. Read the diff PNG before believing any
number: a solid band is a layout defect, speckle inside a paragraph is copy.

**Run it:**

```bash
cd store_platform/src/Store.Web
python3 -m http.server 3002 --bind 127.0.0.1 -d ../../../docs/design/mumchimp-build-bundle/mockups &
pkill -f "next start"                       # BEFORE the build, not after. See below.
NEXT_PUBLIC_API_URL=https://api.mumchimp.com npm run build
(NEXT_PUBLIC_API_URL=https://api.mumchimp.com npx next start -p 3000 &) && sleep 8
node scripts/visual_regression.mjs
```

`next start` serves the BUILD, so a number taken without a rebuild and a restart is stale.

**Stop the old server BEFORE the build.** `next build` rewrites `.next` in place, and a `next start`
still holding the old build serves HTTP 500 with no stylesheet for the whole build. Anyone looking
at localhost during that window sees an unstyled, broken site and reports a style bug that does not
exist. Observed 2026-08-18. Killing the server first makes the window an honest connection refused
instead of a page that looks wrong.

**The measurement, 2026-08-18, after defects 1 to 8 below were fixed.** Two numbers per cell:
the whole page, then the first 2400px (`FOLD_PX`). Threshold is 2%. No page is under it yet.
Defect 9 landed after this run and is not in these numbers.

| Page | 390 page / fold | 1280 page / fold |
|---|---|---|
| index | 5.91 / 11.05 | 3.06 / 5.88 |
| ideas | 3.46 / 3.53 | 1.62 / 2.40 |
| how-it-works | 10.23 / 16.11 | 6.20 / 13.65 |
| kill-log | 5.07 / 16.08 | 7.79 / 32.30 |
| faq | 7.02 / 8.43 | 3.56 / 3.80 |
| pricing | 6.09 / 9.49 | 4.28 / 6.93 |
| about | 6.66 / 7.19 | 3.96 / 3.96 |
| account | 5.53 / 6.01 | 3.53 / 3.53 |
| refund | 6.05 / 8.43 | 3.07 / 3.77 |
| sample | 5.81 / 8.18 | 3.20 / 5.05 |

**Defect 7 removed 24px from the top of every page and the numbers barely moved.** `pricing` went
6.18 to 6.09, `kill-log`'s 1280 fold 33.09 to 32.30, and `faq`'s 390 fold went UP, 8.14 to 8.43.
That is the useful result: the diff was never dominated by vertical offset, so chasing offsets will
not reach the bar. See 11.9.

**`kill-log` got WORSE and that is the correct direction.** Its 1280 fold went 25.06% to 33.09%
because the ranked chart was fixed on our side and the drawing still renders the bug. Screenshots
taken 2026-08-18 at 1280: on `docs/design/mumchimp-build-bundle/mockups/kill-log.html` the twelve
rows are right-ragged with truncated
labels, and the chip rail and the search box paint ON TOP of them; on the built page the thirteen
rows sit on one left baseline with proportional bars and nothing overlaps. Falling further from a
broken reference is the harness working. Two ways out, and it is the founder's call which:
either fix `docs/design/mumchimp-build-bundle/mockups/kill-log.html` so the drawing shows the chart
it was designed to show, or accept
that this page's number is measured against a defect and exclude it from the 2% bar. Nothing in the
code should change to close this gap.


**THE FOLD NUMBER IS THE HARSHER ONE, and an earlier note in this session said the opposite.**
A built page that runs longer than its drawing gets padded with white, and white matches white, so
the extra length DILUTES the whole-page figure. Every page above is worse over its first 2400px
than over its whole height. Work the fold number down; treat the page number as the diluted one.

**Five defects the harness found that no unit test could have.** All five are the same shape: the
markup passed structural parity, the types checked, the build was clean, and the page was wrong.

1. **The dark strip above the header did not exist in the app at all.** It is component 02 in the
   bundle and it sits above the header on all eleven drawings, so every built page rendered 44px
   high against its drawing and every glyph on it missed its counterpart. `/about` matched its
   drawing on total height to within 17px and still differed on 5.96% of pixels at 1280, which is
   what a pure vertical offset looks like in this measurement. Ported as
   `components/marketing/TodayRibbon.tsx`, graded by `scripts/parity.mjs` at 0.0%.

2. **The cause grid on `/kill-log` painted one cause out of nine.** `CauseGrid` held its colour ramp
   as `fill-kill/85` and turned it into `bg-kill/85` with `String.replace` on the way to the DOM.
   Tailwind v4 generates a rule only for text it finds in source, so `bg-kill/85` had no rule.
   Measured on the built page at 1280: 624 cells drew `rgb(180, 52, 43)`, 80 drew
   `rgb(20, 112, 106)`, and **740 computed to `rgba(0, 0, 0, 0)`** -- the signature device on the
   page whose subject is how ideas die was showing the largest cause and a blank field. The ramp is
   now written in the form the DOM receives it, and `__tests__/causeGridRamp.test.ts` fails on any
   `fill-`/`bg-` swap or template-built utility name.

3. **The home page's featured card was capped at 420px in a full-width row.** The drawing's
   `article.featured` is 1040px, the whole content measure. At 1280 ours drew x=120..540 in a band
   running 120..1160, leaving 620px of empty page beside it (founder, 2026-08-18: "on desktop below
   her on right why the gap?"). The cap is removed; `.featured`'s own CSS is written for the full
   measure.

4. **The ranked bar chart on `/kill-log` rendered thirteen rows inside a 44px box.**
   `mumchimp.css:103` is `.bars{display:flex;flex-direction:column;align-items:flex-end;height:44px}`.
   That rule is written for the home page's sparkline
   (`docs/design/mumchimp-build-bundle/mockups/index.html:629`), and
   `docs/design/mumchimp-build-bundle/mockups/kill-log.html:475` reuses the same class name for the
   ranked chart. The fixed height and
   the right alignment therefore land on a list of thirteen rows: the rows spilled over the search
   box and the chip rail below, and every row shrink-wrapped and pushed right, so no two labels or
   counts shared a baseline. **The drawing breaks on itself here** -- measured at 1280,
   the drawing's twelve rows run y=1638..1932, 294px of content in a 44px box, all right-ragged.
   Copying the bundle faithfully reproduced the bug. Fixed with `h-auto items-stretch` on the one
   `<ul>`; after it the list measures 294px tall with every row on one left baseline and every row
   inside its section. Whether to fix the bundle itself is the founder's call; step 1 says the
   stylesheet ships verbatim, so this is an override at the call site.

5. **Every bar in that chart was capped at 26 pixels.** Same collision, second rule:
   `mumchimp.css:356` is `.bars i{flex:1;max-width:26px}`, the sparkline cell, matched by descendant,
   so it also caught the fill inside `.barline .bar`. Measured at 1280 before the fix: the 624 bar
   computed `width:100%` on a 665px track and RENDERED 26px, and so did 203, 191, 142, 83 and 26.
   Every cause above roughly 4% drew the same stub, so a chart whose only job is ranking showed no
   ranking. Fixed with `max-w-none` on the fill, written out on both branches of the class rather
   than composed, because Tailwind only generates a rule for text it can find in the file.
   `__tests__/killLogBars.test.ts` pins all three overrides and pins the bundle rule unedited.

**The lesson for the programme.** Structural parity graded all five of these as passing, because it
compares tag-and-class trees, and these are absence, colour, width, height and a name collision. Steps 3 and 4 are not two
measurements of one thing. Step 3 proves the markup is the drawing's; step 4 is the only step that
looks at the page.


**Four more defects, same shape, found the same way.** The five above were things drawn wrong. These
four are height taken by markup that the drawing does not spend, which is why they showed up as a
growing vertical offset rather than as a visibly broken element.

6. **The source strip's BAND rendered on phones after the strip inside it was hidden.**
   `index.tsx` had `<SectionBand ...><HeroEvidenceStrip className="hidden md:block" /></SectionBand>`.
   The control sat on the strip, not on the band, so at 390 the built page drew an empty 45px block
   with a background and a `border-b` at y=1264 -- an empty ruled section, which reads as broken.
   `SectionBand` already takes `outerClassName` for exactly this (`blocks.tsx:136`); the control
   moved there. This one made index's number WORSE (390 page 5.83 to 5.91, fold 10.89 to 11.05),
   because the drawing has a 224px source strip at that point and we now correctly have nothing:
   founder decision F-001 moves that strip below the shelf on phones. The band was still a defect.

7. **The breadcrumb tap target cost every page 24px of height.** `Breadcrumbs.tsx` set
   `inline-block py-3` on the trail link, so the crumb line measured 43px where
   `mumchimp.css:47` gives the drawing's `.crumb` 19px. The trail is the first thing on every page,
   so everything below it started 24px low. Fixed with `-my-3 py-3`: the link keeps its 44px hit
   area and the flex line keeps the drawing's height.

8. **The About cards used a heading style the bundle already ships, as a paragraph.**
   `mumchimp.css:230` is `.tc h4{font-size:17px;font-weight:640;letter-spacing:-.014em}`, written
   for exactly this card. The titles were `<p className="text-meta font-semibold">` at 14px against
   18.72px in the drawing. They are `<h4>` now. (The drawing has its own bug here:
   `docs/design/mumchimp-build-bundle/mockups/about.html:483` writes `<h3>` in a `.tc`, which the
   bundle does not style, so it renders at the browser default.)

9. **`pt-3.5` on the page shell doubled `.pagetop`'s own top padding.** `about.tsx:51` and
   `pricing.tsx:57` wrapped a `.pagetop` in a section carrying `pt-3.5`, and
   `mumchimp.css:49` is `.pagetop{padding:14px 0 8px}`; the drawing's `.wrap` has no top padding at
   all. Both page heads therefore started 14px below the drawing's. Removed. The same two `<h1>`s
   were missing the drawing's own `margin-top:12px`
   (`docs/design/mumchimp-build-bundle/mockups/about.html:458`,
   `docs/design/mumchimp-build-bundle/mockups/pricing.html:459`), which `PageHero`
   (`blocks.tsx:263`) sets and the hand-rolled page tops dropped. Together with defect 7 this closes
   the measured 38px eyebrow offset on `/about` exactly: 24 plus 14.

   `LegalDoc.tsx:135` and `sample.tsx:264` carry the same `pt-3.5` and were deliberately left alone:
   their inner structure differs (a `space-y-6` header, no eyebrow) and
   `docs/design/mumchimp-build-bundle/mockups/sample.html:459` has no `margin-top` on its `h1`.

### 11.9 Why three pages cannot reach 2% by editing code - FOUNDER DECISION OPEN

The remaining large numbers are not layout defects. On three pages the drawing and the built page
carry **different sections**, and each difference is a decision recorded in the source, not drift.
Measured 2026-08-18 by listing every `<h2>` on the drawing and on the built page at 1280.

| Page | drawing | built | the difference |
|---|---|---|---|
| index | 7 | 8 | built adds "What survived"; the failed-check card is 2nd in the drawing and 6th in the build |
| how-it-works | 6 | 8 | built adds "Where the ideas went" and "The kill log" |
| kill-log | 3 | 2 | built drops "Nothing available now for your space yet?" |

Each addition carries its own reasoning where it was made: `index.tsx:943` records "What survived"
as a measured change on 2026-08-08, and `how-it-works.tsx:232` records why the attrition cascade
gets its own section. Deleting them to move a percentage would throw away design work that was done
on purpose and measured at the time.

A section inserted near the top displaces every pixel below it, which is why `how-it-works` measures
13.53% over its fold at 1280 while nothing on it looks broken.

**Two ways out, and it is the founder's call which:** update those three drawings so they show the
pages as designed, or exclude the three pages from the 2% bar and state that in the harness. No code
change closes this.

The same question stands separately for `kill-log`, where the drawing renders its own chart broken
(defect 4 above), and for the page skeleton in general: the drawings are one flat `div.wrap` with
`hr.rule2` hairlines, and the app is a stack of full-bleed `section` bands with alternating
backgrounds and a `border-b`. Measured on how-it-works at 1280, the drawing's `main` is 4940px and
ours is 8104px. Reworking that is a ten-page port and has not been started.

**The header proves the point, and it is measurable.** Measured 2026-08-18 at 1280 on `/about`,
every element in the top 100px compared box by box between the drawing and the built page:

| element | drawing | built |
|---|---|---|
| `div.strip` | y=0 h=44 | y=0 h=44 |
| `span.tag` | y=10 x=120 | y=10 x=120 |
| `span.txt` | y=12 x=244 | y=12 x=244 |
| `span.go` | y=13 x=1030 | y=13 x=1030 |
| `header.hdr` | y=44 h=59 | y=44 h=59 |
| `span.wordmark` | y=63 x=155 fs=21px | y=63 x=155 fs=21px |
| first nav link | "Categories" x=654 | "Good for" x=716 |
| strip headline | "Subscription box for allotment growers" | "Sound Check Rounds, the monthly noise test" |

Not one geometry difference. Yet the diff PNG shows 18.8% of the pixels differing in the 10px band
at y=20 and 13.0% in the band at y=70, and those two figures are identical to one decimal on
`about`, `account`, `index` and `faq`. Those bands are the strip's text line and the nav line. The
pixels differ because the WORDS differ: the nav says "Good for" where the drawing says
"Categories", so every link after it starts 62px further right.

The computed `font-family` also differs, `Inter` against `Inter Variable`, and that is NOT a
defect: "How it works" advances 117px in both.

**So the bar as written measures copy.** A raw pixel diff between two documents whose text differs
cannot reach 2%, however correct the layout is. Whether to make the drawings render live copy, or
to grade geometry instead of pixels (element boxes, which is what the table above does and what
found every real defect in 11.8), is the founder's call. Nothing in the app changes either way.

**The /about experiment settles it.** Defects 7 and 9 were applied specifically to make one page's
head match the drawing box for box, and it worked. Measured at 1280 after the rebuild, drawing
against built: `p.crumb` y=103 h=41 both; `div.pagetop` y=144 both; `p.eyebrow` y=158 h=18 both;
`h1` y=188 h=168 fs=54px lh=56.16px mt=12px both. The predicted 24px + 14px correction landed
exactly.

The diff did not follow. `/about` at 1280 went 3.89% to 3.95% whole page and 3.92% to 3.95% over
the fold. A page whose first 356 vertical pixels are now identical to the drawing measures very
slightly WORSE than before. That is the clearest available evidence that the remaining number is
copy, not geometry, and that more layout work will not move it.

### 11.10 Parity step 4 decided: geometry gates, pixels report - DONE

The founder's answer to 11.9 was that he did not know either, and asked for the best call. This is
it, with the measurement behind it.

**The pixel diff reports. `component_parity.mjs` gates.** A raw pixel diff between two documents
whose words differ cannot converge. The proof is above: the top 100px of `/about` matches the
drawing element for element, and 18.8% of the pixels in the y=20 band still differ, because the nav
says "Good for" where the drawing says "Categories". Making the head of `/about` exact moved the
number the wrong way. A gate that can never be green gets ignored, which is what happened to the 2%
threshold for a week.

**What the new harness grades.** `store_platform/src/Store.Web/scripts/component_parity.mjs` reads
every selector out of the shipped bundle `store_platform/src/Store.Web/src/styles/mumchimp.css` and,
for each one, compares the first matching element in the drawing against the first matching element
in the built page, at 390 and 1280. The unit is a component the design system names. Three buckets:

- `hard` - a computed-style difference on a component both documents render. A defect.
- `absent` - a component one document renders and the other does not, `display:none` included.
- `soft` - width or height past tolerance. Usually copy. Never gates.

It deliberately ignores absolute y, `font-family`, padding against margin (compared as a sum per
side, so the breadcrumb's `-my-3 py-3` tap target does not read as a defect) and `inline-block`
against `block` (CSS blockifies flex children by itself).

It also ignores HORIZONTAL margins, and keeps vertical ones. A vertical margin is a rhythm decision
the drawings make deliberately. A horizontal one is usually `auto`, and `getComputedStyle` reports
the USED value of an auto margin, which is whatever the rest of the row left over. `mumchimp.css:48`
sets `.logo{margin-right:auto}`: the drawing computed 436.109px against the built page's 447.641px,
on all ten pages at both widths, because our nav says "Good for" where the drawing says
"Categories". That is copy wearing a layout number, and it was 20 of the first run's 751 hard
findings. Horizontal padding and border are real style claims and are still compared. Dropping them
took the totals from 751 hard to 724.

**Read a finding before fixing it: the harness pairs the FIRST match of each selector.** If a page's
first `.btn` is a primary call to action and the drawing's first `.btn` is a secondary one, the
harness reports a colour defect that is not one. Worked example, and the reason this warning is
here: `.tlink` reports `color: rgb(86, 91, 98)` drawn against `rgb(36, 71, 201)` built. The built
value is correct -- `mumchimp.css:27` is `.tlink{color:var(--link)}` and `--link` is `#2447C9` in the
bundle's own `:root`. The drawing's first `.tlink` on that page is grey because that particular
instance is styled grey, not because the token differs. Changing our link colour to match would
break every other link on the site. The harness says WHERE to look; the drawing says what it should
be.

**Only a selector that matches ONE element in BOTH documents may gate.** This is the root cause
under the three largest noise piles in the first report, and it is now fixed in the harness rather
than described in this document.

The harness pairs the FIRST match of each selector. The drawings are hand-written HTML and the pages
are ours, written independently, so nothing tells the harness that the drawing's third `.btn` is the
same button as ours. When a selector is used many times per page, first-match pairing compares two
unrelated elements. The tell is findings that contradict each other. `.num` reported "drawing
`normal` / built `-0.38`" on one page and "drawing `-0.38` / built `normal`" on another, and
`mumchimp.css:9` declares nothing on `.num` but `font-variant-numeric`. `.tlink` (76 findings) and
`.btn` (48) had the same shape.

Those selectors are still probed and still printed, now as `MULTI` lines with the match count on each
side. They say where to look. They no longer count towards `hard`, because a number nobody can act on
is not a gate. Singleton components -- `.hero`, `h2.sec`, `.logo`, `.rule2` -- still gate, and
defect 10 was found on one of those.

**A colour on a border that is not drawn is not a colour.** 94 of the 724 hard findings were
`borderTopColor` or `borderBottomColor`. `mumchimp.css:33` is
`.rule2{border:0;border-top:2px solid var(--ink);margin:44px 0 0}`, so the bottom border is 0px wide
on both sides of the comparison, and the gate still reported "drawing `rgb(128,128,128)` / built
`rgb(23,25,28)`" on it eight times. The probe now records `no-border` for a side whose width computes
to 0. Whether a border is drawn at all is still graded: `borderTopWidth` and `borderBottomWidth` are
compared as lengths and both feed `boxTop` and `boxBottom`.

**`.rule2`'s remaining margin finding is a deliberate override, not a defect.** The gate read
"boxTop drawing `46px` / built `2px`". That is `kill-log.tsx:352`, `<hr className="rule2 !mt-0 mb-7" />`,
with the reason in a comment above it. First-match pairing put the one overridden rule on that page
first. It is the same class of artifact, on a selector that happens to be a singleton per page.

**Why it is not a CI job.** The built page in CI is built against `https://api.example.com`, so it
has no catalogue: the shelf, the kill log and the hero counts all render empty. The comparison only
means anything against the live API. It runs locally, before shipping a storefront change:

```bash
cd store_platform/src/Store.Web
npm run parity:components          # grades against the baseline
npm run parity:components -- --update-baseline
npm run parity:pixels              # the PNGs, for looking at
```

**The gate is a ratchet, not a zero.** `docs/design/component_parity_baseline.json` records what
each page measured. A page may improve or hold; it may not get worse. Same shape as
`docs/doc_lint_baseline.json`. A bar of zero would be red on day one and would then be ignored.

**A ratchet needs a probe that does not flap, and the first one did.** The first recorded baseline
took `account` at 390 as 30 hard findings. Three runs before it and two after all returned 32, with
no code change between any of them, and the two 32-runs produced byte-identical finding lists. A
baseline of 30 would have called every later run a regression. The cause was that
`component_parity.mjs` read computed styles straight after `networkidle`, while entrance animations
and CSS transitions were still running, so it sometimes read an interpolated value instead of the
resting one. It now injects `animation:none;transition:none` and waits 400ms before reading, which
is what the pixel harness already did. The baseline was re-recorded afterwards.

Proof the probe is now deterministic: two consecutive full runs, twenty page/width pairs each,
produced byte-identical 1362-line reports (`diff` empty), and nineteen of the twenty pairs
reproduced the flapping baseline's numbers exactly. Only `account@390` differed, at the value the
outlier run had recorded.

**It found two defects in its first run, both invisible to every other check.**

**Defect 10 - the shipped stylesheet could not reach its own headings.** `globals.css` imports the
bundle as `@import "./mumchimp.css" layer(components)`, and the `h1, h2, h3` element rule further
down the same file was UNLAYERED. Unlayered CSS beats every cascade layer regardless of specificity,
so `font-weight:560` overrode the drawings' own heading weights on every page of the site. Measured
across all ten pages at both widths: `h2.sec` computed 560 against the drawing's 665, `h3.sub`
computed 560 against 655. Twenty rows out of twenty. The font SIZES were never affected, which is
why nothing looked obviously broken: `h1` measured 54px on both sides. The rule now sits in
`@layer base`, so the bundle supplies the drawn weight, a utility such as `font-semibold` still
overrides it, and the three `:is(h1, h2, h3).text-*` rules stay unlayered and still win where a
scale token is worn. Pinned by
`store_platform/src/Store.Web/src/__tests__/headingFloorIsLayered.test.ts`, which walks the real
brace structure rather than grepping. Parity findings for those two selectors went from 20 to 0.

**Defect 11 - the home hero carried its band's padding on top of its own.** Founder report,
2026-08-18: "desktop landing page hero layout top margin and top margin of right panel are off".
`mumchimp.css:274` sets `.hero{padding:52px 0 44px}`, and the `SectionBand` around it added
`md:pt-14 md:pb-16`. Measured at 1280, drawing against built page: hero grid y=103 against y=159,
right-hand panel y=155 against y=211, h1 y=297.2 against y=353.2, sub y=483.6 against y=539.6.
Every row exactly 56px low, which is `pt-14`. The desktop band padding is now `md:pt-0 md:pb-0` and
the two `[@media(max-height:820px)]:md:*` overrides are gone with it. The PHONE padding is
untouched: `pt-8 pb-8` there was set by measuring where the first shelf card landed at 360x780,
390x844 and 430x932, and the drawing's own media query drops `.hero` to `padding:36px 0 32px`
below 900px anyway.

Re-measured after the fix, same probe, same widths: header y=44 h=59, hero grid y=103 h=663,
right-hand panel y=155 h=567, h1 y=297.2 h=168, sub y=483.6 h=54 -- every row identical on both
documents. The only remaining difference is text width (h1 421px drawn against 436px built), which
is the headline copy differing, not layout.

## 12. "Run your idea through the engine" — the vetting desk (founder, 2026-08-21)

The founder called this on 2026-08-21: **"and also the run you idea through engine"**,
**"needs adding to requrenents"**, **"new featire in the way"**, **"killer featuure"**,
**"needs uxx and fe input"**, **"talke to peeers to flesh out dtails"**, and — the line that
decides the whole abuse surface — **"only for registered uers i nust say"**.

**It is a registered-user feature on the storefront, not internal dogfooding.** The register
recorded it as "run our own ideas through the engine" for a week. That reading is wrong and is
corrected in [`REQUIREMENTS.md`](REQUIREMENTS.md) R12: an internal batch job needs no UX and no
front end, and the founder asked for both.

**What it is.** A registered user types their own business idea. The engine runs the same six
checks it runs on every candidate — `pain_reality`, `value_durability`, `incumbency`,
`payer_solvency`, `distribution`, `legality` — on the same brains, with the same kill-fast
short-circuit, and returns the same cited verdict. Nothing about the run is a demo path. If it
is not the real engine it is worth nothing, because the entire claim is that the verdict is
evidence rather than an opinion.

### 12.1 The wait is the product

Do not put a spinner on this. The most convincing thing the engine does is **read the web in
front of you**, and a progress bar is the one treatment that hides it.

**Lead with one plain-English question at a time, not the six check names.** Six unfamiliar
words resolving at once reads as machinery rather than as thinking. The sequence a visitor
sees is: *"Does anyone actually have this problem?"* → *"Would they still have it in three
years?"* → *"Who already sells this?"* Under the live question, **stream each URL as it is
fetched, with the domain legible**. That is the proof, and it is free — the fetches are
happening anyway.

**The six-check rail is a secondary column that fills in behind.** It becomes legible
retroactively, once each row carries a verdict and a source. By the end the visitor has been
taught the vocabulary by watching it resolve, which is the only way six technical words are
ever going to land.

### 12.2 Before they type

Not an empty box, and **not a prefilled example**. A prefilled example gets Enter pressed on
it without reading, and then the first thing the visitor sees is somebody else's idea.

Put **a real recent vet above the box**, cited reason visible, **ideally a KILL**. It proves
the thing is real, it teaches the output format before they need to read one, and it
normalises a KILL as a respectable answer rather than a rejection.

### 12.3 When it is a KILL

**The verdict is a statement about the world, never about them.** Two things the page must do
that the internal dossier does not:

1. **Name what would change the answer** — *"this passes if you can show one buyer already
   paying for X"*. That sentence is derivable from the kill gate that fired. It is never
   invented, and it must cite the same passage the KILL cited.
2. **Label the kill-fast grey-out as respect for their time** — *"we stopped here: the
   remaining four checks cost real money and this was already answered."* Without that line,
   four greyed rows read as a broken run.

### 12.4 The run has its own URL from the first second

**A run must survive the tab closing.** Its own URL, minted before the first check, resumable,
shareable. Three reasons, and the third is the commercial one:

- a vet is up to seven checks against live retrieval, which is longer than a person will sit
  still for;
- it is the only honest way to hand back a run the moat could not finish;
- it is the share mechanic, and **"the engine killed my idea and here is why" is far more
  shareable than a pass.**

### 12.5 Degrade honestly when the moat cannot finish

Fold the run's event stream into what the screen shows, and add no judgement of its own:
render the checks that **did** rule, each with its citation, name the ones the moat could not
reach, and offer to finish it and mail the result.

**There is no such fold on `main` to reuse.** Until 2026-08-21 this paragraph claimed
`kit/migrate/progress.py` as existing prior art. That file exists only on the unmerged branch  <!-- doc-lint-ok: naming the absent path IS the correction; the sentence says it is not on main -->
`origin/kit/migration-e2e` at `ab8bbad7`, so the claim was false on main and anyone building to
it would have gone looking for a file that is not there. Either build the fold here, or land
that branch first and then reuse it.

**What must never be built is a green that means "we could not ask".** That is the exact defect
`verify.py:365` / `:693` exists to prevent inside the engine — a failed call DEFERS, it never
contributes an `unverifiable` to a gate — and a public page is not allowed to undo it.

### 12.6 The money rail

**Correction, 2026-08-21, same day it was written.** This section first said the MiniMax adapter
emits no cost row, therefore `spend.daily_cap_usd` caps only the `claude_cli` fallback, therefore
no public write path could ship until an adapter fix landed. **That was false and the blocker is
withdrawn.** It is kept here rather than deleted because the way it was wrong is the useful part.

The chain, each link confirmed on disk:

- the daily cap enforces rows tagged `event: "spend"`, summing `amount_usd` — `scheduler/guard.py:315`,
  with the two accumulators spelled out in the docstring at `:271`. It deliberately does **not**
  enforce `cost_usd` rows: those are the subscription leg, the Claude Code CLI's own
  `total_cost_usd`, in the file's own words "API-equivalent, not invoiced";
- MiniMax is priced — `telemetry.py:189`, `minimax` and `minimax_m27` both at $0.30/$0.30;
- its adapter passes real token counts — `MiniMaxOperator._raw_once` calls `record_usage(...)` with
  `prompt_tokens` / `completion_tokens` off the stream's usage block, `operator.py:896`;
- `record_usage` emits `event: "spend"` with an `amount_usd` whenever cost is above zero,
  `telemetry.py:305`.

**So MiniMax already emits a metered row and is already inside the cap.** There is no adapter fix
and nothing here blocks this feature.

**How the false version was reached, because the same trap is one grep away from anyone.** Three
angles were offered for it — priced rows all naming `claude`, latency rows split 78/5, an empty
`store/dossiers/` — and all three were counts of the same file. Two greps of one ledger cannot
disagree with each other. The second instrument had to be the code that *reads* the ledger, and
that code is the thing that says the two buckets are separate and only one of them is the cap.

**What is actually true, and it is smaller.** Measured 2026-08-21 on
`/Users/chidionyema/Documents/code/prospector/store/prospector.jsonl`, 528 rows: **0 metered rows
totalling $0.0000**, 39 subscription rows totalling $2.2455, and `store/dossiers/` holds 0 files.
So **cost per vet is unobtainable from this store, because this store carries no priced run** —
that is a statement about one nearly-empty local store, not about the engine. Production runs in
the `prospector-engine` Fly app, and the real figure has to be measured where that writes. Until
someone does, this spec carries no per-vet number, and a rail sized from a guess is not a rail.

**The rails that stand, none of which depended on the withdrawn claim:**

- **registered users only** — the founder's ruling, 2026-08-21: *"only for registered uers i nust
  say"*. One free run per browser would have been a speed bump, because a browser is free to make
  and an attacker makes thousands. Registration is the identity gate;
- **its own sub-cap and its own ledger key.** Registration bounds *who*, not *how many*, and a
  public path on the shared `daily_cap_usd` competes with the catalogue for the same allowance.
  The catalogue is the business; a stranger's vet is marketing;
- **the public path sheds FIRST as the cap is approached**, so a busy desk can never starve the
  daemon;
- **a cheap `prescreen.py` pass before any moat call**, which is what bounds one registered user
  pasting the same idea forty times.

### 12.7 What is not decided yet

- **Per-user allowance**: how many vets a registered user gets, and whether the paid tier is
  a bundle or per-vet. Founder decision, not ours.
- ~~Front-end wiring~~ — **decided, see §12.8.** This bullet said SSE was the obvious
  candidate. That is the wrong call, and the measurement against it is in §12.8.
- **Does a visitor's idea enter the catalogue?** It must not, by default — they typed it, it is
  theirs — but that is a founder call about the product, not an engineering default.

### 12.8 How it is wired — POST a job, poll it. Not SSE.

Measured 2026-08-21. Three facts, each of which removes a decision rather than adding one.

**1. This is not the storefront's first long job with a progress surface. One already ships, and
a paying buyer already sees it.** `store_platform/src/Store.Web/src/pages/orders/success.tsx` is
POST-then-poll: `POLL_INTERVAL_MS = 2000` (`:13`), `MAX_POLL_ATTEMPTS = 12` (`:18`), six phases
(`resolving | ready | no-session | timed-out | unfulfilled | revoked`), a progress bar driven by
`pollAttempt / MAX_POLL_ATTEMPTS` (`:440`), and terminal states that end the poll early instead of
running the ceiling out.

**Read the comment at `:14-17` before building this.** The ceiling used to be 20 attempts, tuned
for a delay nobody had ever observed, and all the extra ceiling did was prolong the runs that were
never going to resolve. **Reuse the component; do not reuse the constants** — that surface is
bounded at 24 seconds and a vet runs minutes.

**2. SSE is rejected on capacity, not on taste.** `prospector-engine` is one machine on
`internal_port = 8611`. One open connection per visitor is a capacity question that has to be
answered before launch, and polling never asks it. Ship the poll; add SSE later behind the same
job id if the desk earns it.

**3. The public route does not go through the ops read door, and there is a pattern to copy
rather than invent.** The console's read door is a session-gated allowlist
(`store_platform/src/Ops.Console/src/pages/api/ops/read/[view].ts`), and a drift test refuses a
commit unless the Python gateway and that file agree. **Exactly one read is reachable without a
console session — `share_open` — and it is deliberately absent from that allowlist**, with its own
route at `pages/api/s/[token].ts`; the reasoning is written down at
`tests/unit/test_console_tools_run.py:353-358`. That is the shape to copy: **a dedicated public
route naming its one read as a literal, never a hole punched in the admin allowlist.**

The job machinery to copy is `_act_tools_run` (`prospector/ops/console_api.py:2960`) plus
`_read_job` (`:3101`) — POST a job, it writes receipts to `store/ops/intents.jsonl`, the read
greps them back by job id. **Reusable as a pattern, never as an endpoint**: it is admin-authed and
it takes a repo-relative tool path to execute, and a stranger naming what runs is the last thing
that door should accept.

**The shareable result is already solved.** `share.mint` returns `/s/<token>`; the token is
unguessable, only its sha256 is on disk, and it is checked again at read time rather than only at
mint. The same shape carries a vet result and delivers the growth loop of §12.4 with no second
auth story. The web never touches `store/` — it asks the engine, and `PROSPECTOR_STORE_DIR` pins
where the engine writes.

**Queued-and-notify is out of v1**, and the reason is the opposite of the obvious one: it is
*more* new surface, not less. Notify needs an address, which needs a form, a consent decision,
deliverability, bounce handling and a spam target. Polling adds no new infrastructure at all —
the component exists, the public-route pattern exists, the job-and-receipt pattern exists.

**A cheap prescreen runs before any moat call.** Registration (§12.6) bounds who, and the spend
sub-cap bounds how much, but neither bounds one registered user pasting the same idea forty times.
`prescreen.py` is the existing first triage gate and it is the cheap one: it runs first, and the
per-user bound is decided in this spec rather than after launch.
