# Pack Quality Programme

> Opened 2026-08-14 after the founder read a live pack end to end — the first time anyone had,
> because until `tools/preview_packs.py` landed there was no route to a pack's contents without
> buying it. Read this before touching pack generation, the dossier renderer, or the listing gate.
> Append findings here; do not put them in CLAUDE.md.
>
> Source of the review: pack `8d5e24fbe6c1f5d3` ("StorySprout"), £49.99, `side_hustle` lane,
> `us` market, verified 2026-08-01, on sale as of 2026-08-14.
> Founder's verdict: **"nowhere near ready, needs 50x improvement, and markdown files is not the one."**

---

## P0 — The pack fails its own test and ships anyway

**The defect, in the buyer's words:** the QA report opens
`✅ PASS — This cleared every check we hold it to.` Three screens later:
`❌ Is the problem real? No — the sources contradict this.` Then composite 2.65/5, with
`money_provability 1/5 — the sources show nobody pays for social stories today`,
`pain_acuity 2/5`, `defensibility 2/5`.

**One buyer screenshots the PASS banner next to the ❌ and the kill log — the best asset we
have — becomes a joke.** The entire store rests on *checkable*. We put the check inside the
product and it came back negative.

### Mechanism — verified on disk, not inferred

| # | Fact | Receipt |
|---|---|---|
| 1 | The dossier really does record a grounded refutation | `store/dossiers/8d5e24fbe6c1f5d3.pass.json` → `pain_reality: verdict=refuted, confidence=0.64, retrieval_failed=False, 7 citations` |
| 2 | …in a record whose decision is PASS | same file: `decision=pass`, `gate_fired=None`, `reason="Survived all gates; composite 2.6500; 6 grounded-supported check(s) (moat grounded: 1)."` |
| 3 | The *default* gate set would have killed it | `config.yaml:374` `- pain_reality: [refuted]`; floor `config.yaml:334` `confidence_floor: 0.4`; 0.64 ≥ 0.4 → `kill_filter.is_hard_fail` (`prospector/kill_filter.py:51`) returns True |
| 4 | **But the `side_hustle` lane replaces `hard_gates` entirely** | `config.yaml:447-451` — the lane's gates are `buyer_intent, currency, route_to_market, legality`. `pain_reality` is absent. |
| 5 | …and demotes `pain_reality` to score-only | `config.yaml:538-541` under `score_checks: # run + score, never kill` |
| 6 | So the composite alone decides | `config.yaml:437` (lane) `min_composite_to_pass: 2.5`; 2.65 ≥ 2.5 → PASS via `prospector/score.py:59` |
| 7 | And the banner copy is emitted unconditionally on `Decision.PASS` | `prospector/dossier.py:299-300` `_DECISION_GLOSS[Decision.PASS] = "This cleared every check we hold it to…"`, rendered at `:332` with no reference to the individual verdicts |

**Read (4)+(5) together and the design is defensible: the £30/£49 pack lane judges DEMAND, not
moat — the lane's own `adversarial_directive` (`config.yaml:~462`) says commoditisation and
"anyone could assemble this themselves" are explicitly NOT kill reasons.** That argument is
sound. What is not defensible is (7): **the sentence "This cleared every check we hold it to"
is factually false** in every lane that runs more checks than it gates on. The lane held it to
four. It printed a claim about eight.

### The two ways out (founder's framing, unchanged)

- **(A) Kill it.** Add `pain_reality: [refuted]` back to the `side_hustle` hard gates, or gate on
  `money_provability <= 1`. Cheap to do, but it re-opens the wall the lane was built to fix
  (memory: `war-room-value-durability-wall.md`) and will cull an unknown slice of the catalogue.
  **Measure the cull before flipping** — the actuator pattern (`title_block_on_breach`,
  `shelf_copy_block_on_breach`) exists for exactly this.
- **(B) Make the gate visible and defend it on the page.** Replace the blanket banner with the
  truth: *"Passed 6 of 8 checks. Two came back against it — here they are, and here is why we
  still list it."* The lane's rationale is already written in `adversarial_directive`; it just
  never reaches the buyer. This is the cheaper fix and it is the one that makes the kill log
  stronger rather than weaker.

**Not yet decided. This is the founder's call and it blocks everything below.**

---

## P1 — The Financial Model is a refund waiting to happen

Verbatim from the shipped `04_Financial_Model.md`:

```
Month 1: (price or customer target not specified)
Gross Margin: (COGS not specified)
Payback Period: (not specified)
LTV:CAC: (cannot compute without CLV and CAC)
Month 1 P&L: (not specified)
```

…under the boast *"All figures below are computed by Python from verified inputs. No language
model performed any calculation, so the arithmetic is exact."* **Exact arithmetic on nothing.**

Then `ARPU: $35/month` on a product the same document states is a one-off physical purchase with
an assumed zero repeat rate. The one number it emits is wrong in kind.

- Placeholder strings: `prospector/artifacts.py:192, 216, 234, 246, 248, 271, 291, 295`
- ARPU is computed from a field named `monthly_price` regardless of purchase model:
  `prospector/artifacts.py:171, 246`; the prompt demands `monthly_price` unconditionally at
  `prospector/prompts/artifacts.md:37`
- Nothing gates the document on being computable: `prospector/pack_validation.py:24-25` only
  checks length > 200 chars
- (Above four: reported by subagent, **spot-check the line numbers before editing** — not
  personally verified.)

**Fix:** for a one-off physical product the model should be unit cost band, gross margin per unit
at three price points, break-even order count, fixed-cost floor. That is arithmetic we can
actually do, and the inputs are already scattered through the ops plan.
**And: if a document cannot produce content, it must not be one of the eight.** "8 documents" is
a marketing number now forcing us to ship empty ones.

---

## P2 — Shipped-broken rendering (cheapest, most visible, fix first)

Visible in the first 30 seconds, in the highest-trust artefact.

**(a) Truncation mid-word.** Exec summary page one:
`currency: A 2025 report puts autism at 1 in 31 U.S.` / `legality: The passages describe U.S.`
— both cut at `U.S.` Five more mid-word cuts in the QA report: *"which still counts as demon"*,
*"which neither confi"*, *"this group is broke"*, *"parents of autistic children spe"*,
*"and no evidence indicates"*.
Two distinct causes: a hard character clip (`prospector/trimming.py:45 RATIONALE_MAX = 600`,
applied `prospector/verify.py:528`) and a sentence splitter that treats `U.S.` as a sentence end
(`prospector/plain_text.py:262 _SENTENCE_END`, which guards `e.g`/`i.e` but not `U.S`).
*(subagent-reported; verify lines.)*

**(b) `Sources used: , , , , , , ,` — bare commas, on every check, in the document whose entire
purpose is showing receipts.** Root cause is NOT missing data: the dossier JSON carries seven
real citation ids (`1e62e0c381e1c8d3`, `8299842c5162c176`, …) — **verified on disk**. The
renderer drops them. `prospector/dossier.py:413` (and `:440`) emit them wrapped in backticks:
`", ".join(f"`{c}`" for c in chk.citations)` → the HTML layer strips inline code spans, leaving
the separators.

**(c) `Candidate ID:` blank — same root cause.** `prospector/dossier.py:507` writes
`` `{cand.candidate_id}` `` in backticks; the JSON on disk has `candidate_id='8d5e24fbe6c1f5d3'`
(**verified**). `Judged by:` is NOT backticked and survives — which is the proof that the
backtick span is what gets dropped. **One bug explains (b) and (c).** Determine which renderer
drops it: the zip's `prospector/pack_html.py` styles `.section-body code` (`:256`), so suspect the
storefront path first (memory: `storefront-renders-no-markdown-2026-07-31`).

**(d) `Judged by: fallback(cursor_cli+claude_cli+minimax)` shown to the buyer.**
`prospector/dossier.py:504`. Two problems: we are telling a customer the judge was a fallback
chain, and `cursor_cli` was deleted from this repo on 2026-08-06 — so this string also dates the
pack. Buyer-facing copy should not name the operator chain at all; keep it in the audit record.

---

## P3 — The sourcing will not survive the scrutiny we invite

The pack opens with the best paragraph in it: *"pick any claim marked SUPPORTED, click its
source, and if it doesn't say what we say it says, claim the refund."* That is a loaded gun:

- **`jeffreydachmd.com` — "Increasing Autism Rate is Caused by Environmental Toxin Says RFK Jr"
  — and `playproject.org` ("a 3000% increase!") cited to support the prevalence figure, in a pack
  sold to people who will market to autism parents. The CDC pages were already retrieved and are
  in the same source list.** This is the one that can end the brand's credibility in a vertical.
  → **Needs a source-quality gate, not a source-count one.** A retrieved primary source must
  outrank a blog restating it; health/medical claims should refuse non-primary domains outright.
- Two Pinterest boards cited as evidence of a *purchasing* market (a board is evidence someone
  made a mood board). A Scribd upload of someone else's collection. A YouTube video under
  "currency". `101autism.com`'s own storefront used as proof parents *spend* — it proves someone
  is selling, not that anyone bought.
- *"Grounded in 51 sources"* with `lulu.com/create/print-books` listed **twice** and a dozen
  sources carrying nothing load-bearing. **Source count as a headline metric incentivises
  padding.** Nobody buys on 51 vs 30. Replace with *"4 load-bearing claims, each with a primary
  source."*

---

## P4 — We sell the same 2,500 words three times

Build spec, GTM and Ops each independently explain: what a social story is (same `otb.ie` cite),
the free-alternative risk (same two cites), COPPA (same three FTC cites), Lulu (same five cites),
the Meta/ASA advertising risk (same cites), and the 1-in-31 correction. **Six themes, three times
each — roughly 40% of the reading is re-reading.** The pack advertises "5,000+ words"; this is
~12,000 with maybe a third of that as payload. Length is being used as a value proxy and it is
hurting the read.

**Fix:** one `Constraints & Evidence` document the three plans reference; each plan then handles
its own *application* — the build spec gets the file-retention implementation of COPPA, not the
COPPA explainer.

Related: `assumption — unverified` appears dozens of times. The honesty is the differentiator,
but past the fifteenth instance it reads as a hedge template. Consolidate into one assumptions
register with a **cost to test** column — which Ops §14 already half-does, and does well.

---

## P5 — Format: "eight markdown files in a zip" is the problem, not the packaging

Founder, verbatim: **"markdown files is not the one."** Eight `.md` files in a zip is the single
strongest signal that this is an AI output dump rather than a £49.99 product. The site frames it
as a feature ("yours to keep, edit, paste anywhere"); it reads as *we didn't design anything*.
Nobody reads 12,000 words of raw markdown, and the buyer is a would-be solo operator with an
evening free.

**Ship instead:** one typeset PDF; a single-page "first fortnight" card; one machine-readable
table (assumption, cost to confirm, test, cost of test). Keep the markdown as a secondary
download for those who want it. Note `prospector/pack_html.py` already produces a styled
`index.html` — that is the seed of the typeset artefact, not the finished answer.

---

## P6 — Marketing Assets is doing the wrong job

The section headed **Launch Email** contains a product description. The section headed
**Listing Page** opens with `Subject:`. The labels are swapped.

Worse: the "Listing Page" copy is selling **our pack** — *"Here is a new opportunity pack… Open
the pack."* — complete with our sourcing caveats. The buyer wanted launch copy for *StorySprout*,
aimed at *parents*. One of eight documents is not doing its job at all.

Headings are generated from the asset `type` field (`prospector/bridge.py:1475`), types assigned
at `prospector/artifacts.py:805` `["listing_page", "teaser_social", "seo_preview", "launch_email"]`;
the generating prompt (`prospector/prompts/content_gen.md:38-66`) defines each type's *structure*
but never states **who each asset is written for**. *(subagent-reported; verify lines.)*

---

## P7 — Commercially unresolved: the pack has an unpriced shelf life

Verified `2026-08-01`, and it states *"Evidence goes stale after 2026-08-31."* Today is the 14th.
Someone buying on the 28th gets three days of validity. **Is there a refresh? A re-verification?**
Right now that line advertises a shelf life we have not priced. Either re-verification is included
(and automated), or the window must not be printed as a promise.

---

## What is genuinely good — a rewrite must not lose it

The founder singled these out. **Roughly 20% of the wordcount is the product; the other 80% is
scaffolding, repetition, and one empty document.** Cut to these and the pack is worth £49.99:

- **Ops §6, the pre-print check** — six named failure modes with the reason each one matters.
  *"Better than a consultant would write."*
- **Ops §8, refund policy in publishable words**, with the half-price reprint tied to the approval
  tick. Real operating design.
- **Ops §12** — each risk with a named early-warning signal (*"two skipped Wednesdays in a row"*).
- **Ops §14 and Build §13** — proven / not proven / never claim, and honest exit conditions.
- **"Make fifteen by hand before you write code."** That single line is worth more than the
  financial model was supposed to be.
- Threading the no-health-claims rule through as a **build constraint** rather than a footnote.

---

## Order of work

1. **P0 decision from the founder** (kill vs. defend-on-page). Blocks the rest.
2. **P2 rendering** — cheapest, most visible, and (b)+(c) are one bug.
3. **P1 financial model** — and drop the document from the eight when it cannot compute.
4. **P3 source-quality gate** — the anti-vax-adjacent citation is the highest-consequence item here.
5. **P6 marketing assets audience** — a prompt fix.
6. **P4 de-duplication** and **P5 typeset format** — the 50x, and the largest.
7. **P7 refresh policy.**

**Nothing in this list is measured across the corpus yet.** Every item above is proven on ONE
pack. Before fixing, run each defect as a census across all 62 published packs using
`tools/preview_packs.py` (read from R2 — never from `publish/bundles/`, memory:
`a-listed-pack-had-only-a-kill-dossier.md` and the 2026-08-14 disk/R2 correction). A defect on
1 of 62 is a repair; a defect on 62 of 62 is a generator change.

---

## P8 — the action document was the same six lines in every pack *(outside the census)*

Found 2026-08-13 while wiring P5, not in the founder's nine. **127 of 127 bundles on disk carried
an identical `05_First_Week_Checklist.md`**, because `pack_floors.first_week_checklist_md` was
wired unconditionally at `bridge.py`'s bundle step — a model-written checklist was never a
possibility, the floor WAS the document. It also broke the rule `prompts/artifacts.md` imposes on
every other document in the pack, telling the buyer to *"re-read the QA report kill/pass gates and
list every SUPPORTED citation URL"* and to confirm that *"the buyer (`who_pays`)"* matched reality
— our own audit trail, addressed to us, with a snake_case field name in a code span.

**Fixed** by `prospector/pack_checklist.py`: a ten-step fortnight derived from the candidate
fields, the check verdicts and the pack's own `##` headings — no model call, so the 127 packs
already sold get the identical document (`tools/backfill_bundle_html.py`). The floor stays as the
fallback for a pack that names no buyer. Tests: `tests/unit/test_pack_checklist.py`.

---

## Status ledger — what shipped, with receipts

Append here; do not restate status in prose anywhere else.

| Item | State | Receipt |
|---|---|---|
| P2 rendering | shipped | `tests/unit/test_pack_render_defects.py` |
| P1 financial model | shipped | `pack_linter.REQUIRED_FIN_SECTIONS`, `tests/unit/test_currency_check_is_region_aware.py` |
| P3 source quality | in flight (separate branch of work) | `docs/RETRIEVAL_PROGRAM.md` |
| P6 marketing audience | shipped | `prospector/marketing_assets.py` `LABELS`, `tests/unit/test_marketing_assets_have_an_audience.py` |
| P4 de-duplication | shipped as consolidation | `prospector/pack_reference.py` → `Evidence_and_Constraints.md` |
| P5 one-page card | shipped | `prospector/pack_card.py` → `First_Fortnight.html` |
| P5 machine-readable table | shipped | `prospector/pack_table.py` → `Assumptions.csv` |
| P5 typeset PDF | **open — founder decision** | no PDF renderer is installed; see below |
| P7 shelf life | shipped | `dossier.SHELF_LIFE_POLICY`, `tests/unit/test_shelf_life_copy.py` |
| P8 action document | shipped | `prospector/pack_checklist.py` |
| Backfill onto the live shelf | shipped | `tools/backfill_bundle_html.py`, 62/62 converted |

**P4, measured rather than asserted.** The doc's *"roughly 40% of the reading is re-reading"* is
not what the corpus shows: across the packs on disk, **0.4% of paragraphs repeat verbatim and 3.5%
are near-duplicates**. The real signature of the defect is the *evidence*, not the prose — a median
of **11 cited sources appear in more than one plan document per pack**, which is what
`Evidence_and_Constraints.md` consolidates. The fix is the right one; the 40% figure is not, and it
should not be quoted again.

**P5's remaining half.** A real typeset PDF needs a decision, not more work: no PDF library is
installed (weasyprint, reportlab, fpdf, xhtml2pdf, pdfkit, markdown_pdf — all absent; only
`mistune` is), and the core PDF fonts are latin-1, so they cannot render the em-dashes and curly
quotes the house style uses. Shipping one means vendoring a Unicode-licensed TTF into the repo.
Until then the printable artefact is `First_Fortnight.html`, which prints to one sheet.

**Everything a fix adds must reach the packs already sold.** That single constraint is why
`pack_reference`, `pack_card`, `pack_table` and `pack_checklist` are all deterministic renderers
over data already on disk: a model call cannot be replayed into a zip somebody bought last month.
The backfill compares content rather than presence, so re-running it is a no-op
(`rebuild_zip_with_index` returns `None` when nothing would change).

---

## The next ship item — P0 was fixed in the generator and never reached the shelf (2026-08-14)

**One item, measured across the whole live shelf rather than one pack.** Everything else open in
this document is either shipped (status ledger above), a founder decision (P5 PDF), or a separate
branch of work (P3 → `docs/RETRIEVAL_PROGRAM.md`). This is the only open item that is a factual
falsehood inside a product on sale, and it is the item the store's whole proposition rests on.

### Two status lines above are stale, and correcting them is what exposes the gap

| Stale line | What the tree says |
|---|---|
| §P0 `**Not yet decided. This is the founder's call and it blocks everything below.**` (this doc, line 58) | **Decided and shipped.** `prospector/dossier.py:326-345` `_pass_gloss` — "Fixed 2026-08-14 … the version the founder approved on sight (2026-08-13)". Option **(B)**, defend-on-page. |
| Order of work item 1, `P0 decision from the founder … Blocks the rest` (line 232) | Unblocked; items 2–7 all carry receipts in the status ledger. |

### The gap the correction exposes, measured

The renderer stopped making the claim. **The shelf never did.**
`tools/backfill_bundle_html.py:19-30` is explicit that it rewrites only the two GENERATED files
(`index.html`, `manifest.jsonld`) and copies every `.md` deliverable **byte-identical**, with one
deliberate one-line exception (the retired staleness footer). `QA_Report.md` is a deliverable.
So the fix reaches packs generated after 2026-08-14 and no others.

Census over all 74 live listings, `publish/bundles/<id>/*.zip` (BUILT, not necessarily SERVED —
`tools/preview_packs.py:23-31`), reproducible by `python3 scripts/pack_banner_probe.py`:

```
live listings                         : 74
  no bundle on this disk              : 0
  bundle unreadable                   : 0
  QA_Report carries retired banner    : 73
  …and contradicts it in the same doc : 12
```

Verbatim from `publish/bundles/08b22037fc2afc07/prospector_pack_08b22037.zip → QA_Report.md`:

> `## ✅ PASS` … `_This cleared every check we hold it to, on evidence we fetched and cited below._`

and, in the same document:

> `### ❌ Can the customer afford it?` … `**No — the sources contradict this.** Confidence 0.53.
> *(check: `payer_solvency`)*`

That is the founder's P0 defect — the one found by reading pack `8d5e24fbe6c1f5d3` — present on
**12 of the 74 packs a buyer can pay for today**, and the retired sentence alone on 73 of 74.
By the doc's own rule (*"a defect on 1 of 62 is a repair; a defect on 62 of 62 is a generator
change"*) this is neither: the generator is already fixed. It is a **backfill**.

### The re-render path exists and is currently broken — one defect, at a known line

The pack is re-renderable without a model call: the stored record is
`store/dossiers/<id>.pass.json` (**60 of the 74** live packs have one), and every pack's zip
carries `manifest.jsonld` with each check, verdict and cited passage for the other 14.
`pack_manifest.dossier_from_dict` → `dossier.render_markdown` is the whole path.

It raises today:

```
File "prospector/dossier.py", line 671, in render_markdown
    for ax, val in sc.scores.items():
AttributeError: 'types.SimpleNamespace' object has no attribute 'items'
```

Cause, not symptom: `pack_manifest._ns` (`prospector/pack_manifest.py:351-355`) recursively turns
every dict into a `SimpleNamespace` because `render_manifest` reads through `getattr` — which is
correct for the manifest and wrong for `score.scores` / `score.justification`, whose keys are
*data* (axis names), not fields. `dossier.py:308-317` `_verdict_of` already carries the same
lesson for `verdict` ("one reader, both shapes"); the score maps never got it.

### The work order

1. **Make a stored dossier renderable.** `score.scores` and `score.justification` must round-trip
   as mappings — either `_ns` stops descending into value-keyed maps, or `render_markdown` reads
   them through one `_mapping()` helper the way `_verdict_of` reads verdicts. Test: render every
   `store/dossiers/*.pass.json` and assert no exception + a banner that names the counts.
2. **Extend the backfill to regenerate `QA_Report.md`** for a pack whose banner contradicts its
   verdicts — a *narrow, second* deliberate exception to the byte-identical rule, documented in
   `tools/backfill_bundle_html.py`'s docstring next to the first. Content-compared, so re-running
   stays a no-op.
3. **Re-upload and re-verify from R2**, not from disk. `tools/preview_packs.py --from r2` is the
   only source that proves what a buyer receives.
4. **Keep it from returning.** `scripts/pack_banner_probe.py` exits 1 while any live pack carries
   the retired sentence; it belongs in the same gate as `scripts/site_spec_probe.py`.

**Why this one and not the storefront v5 pass** (`docs/SITE_SPEC_PROGRAM.md:966`, NOT STARTED):
v5's own "fix first" item — the header that did not mask what scrolled under it — is already
fixed at `store_platform/src/Store.Web/src/components/marketing/MarketingLayout.tsx:142-157`
(opaque `bg-bg`, dated 2026-08-14). v5 is a conversion improvement on a page; this is a false
claim inside the thing that was already paid for, and it is the exact claim the kill log exists
to make credible.
