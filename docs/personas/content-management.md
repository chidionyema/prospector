# Content management

**What this is.** Every word that reaches a buyer, who or what produced it, and the machine that
refuses to publish the bad ones.

**Read this if** you are changing a word in a pack, in the storefront, or in an operator surface,
and you need to know which of four production systems owns it and which gate will stop you.

**The one-sentence answer.** Almost none of the words are hand-written: a model writes the pack
text, sixteen deterministic Python renderers arrange it, one 2147-line linter grades the result
and blocks the listing on an error, and only the storefront chrome is copy a person types.

---

## 1. The four kinds of words

| # | Kind | Who writes it | Where it lives | What gates it |
|---|------|---------------|----------------|---------------|
| 1 | Pack body text | A model, via `prospector/prompts.py` | `store/dossiers/*.json`, candidate fields | `verify.py` grounding + `pack_linter.py` |
| 2 | Pack structure and headings | Deterministic Python, no model | `prospector/pack_*.py` (16 files, 7439 lines) | Unit tests; the renderers cannot vary |
| 3 | Storefront copy | A person, in TSX | `store_platform/src/Store.Web/src/` | Code review; `npm run build`; Playwright |
| 4 | Operator copy | A person, in Python/TSX | `prospector/ops/`, `store_platform/src/Ops.Console/` | Code review |

Kinds 1 and 2 are the product. Kinds 3 and 4 are the shop and the back office.

### 1.1 Proof that the renderers are model-free

This is the load-bearing claim of the whole document, so it is proven by exhaustion rather than
asserted. Every reference to a model, an operator object, a completion call or a prompt module
across all sixteen renderers:

```
$ rg -n "operator|\.complete\(|llm|prompts\." prospector/pack_*.py
prospector/pack_pdf.py:226:    # Without this fpdf2 drops the character silently and the sentence loses its operator.
prospector/pack_pdf.py:234:    # sentence that loses its operator.
prospector/pack_linter.py:751:    `ops/console_api.py::_read_shelf` decides whether to tell the operator "blocked by X" or
prospector/pack_linter.py:1030:#: on `19aaf66a4e9f7778` told the operator to spell out "PL" in the line "Savannah port
prospector/pack_linter.py:1033:#: keyed on the reported term, so the operator's own expansion could never match it either.
prospector/pack_linter.py:1607:    # operator that "Savannah port container dwell forecasts for 3PLs" states a figure its
prospector/pack_linter.py:1655:            # told the operator that "PLs" appears nowhere in the pack's copy. It appears
prospector/pack_floors.py:277:            "effort_tag": "solo_operator",
prospector/pack_data.py:727:            # operator's live Chrome profile, which is also how this stays runnable headless
prospector/pack_card.py:6:AI output dump, and the buyer is a would-be solo operator with an evening free. Nobody reads
```

Eight of the ten hits are comment prose about the human operator. One is a Chrome profile comment.
One, `pack_floors.py:277`, is the string literal `"solo_operator"` written into an effort tag. No
renderer imports an operator, calls `.complete()`, or reads `prompts.py`.

**Why this matters.** A renderer that called a model would make the same pack render differently on
two runs. The pack linter grades the rendered output. A non-deterministic renderer would make the
linter's verdict non-reproducible, and a pack that passed on Tuesday could fail on Wednesday with no
input change.

---

## 2. Complete inventory: the sixteen renderers

Measured with `wc -l prospector/pack_*.py` (7439 lines total).

| File | Lines | Renders | Output filename | Model-free |
|------|-------|---------|-----------------|-----------|
| `pack_bear_case.py` | 271 | The case against the idea | `What_Would_Sink_This.md` (`:34`) | yes |
| `pack_card.py` | 360 | The two-week starter card, as HTML | `First_Fortnight.html` (`:38`) | yes |
| `pack_checklist.py` | 265 | Week-one actions | `05_First_Week_Checklist.md` (`:37`) | yes |
| `pack_data.py` | 915 | Scorecard, financial model, comparables; JSON, CSV, SVG, XLSX | several | yes |
| `pack_field.py` | 415 | Who is already in this market | `The_Field.md` (`:41`) | yes |
| `pack_floors.py` | 606 | Minimum-content floors for every section | n/a (a floor, not a file) | yes |
| `pack_html.py` | 320 | The whole pack as one browsable HTML file | `index.html` | yes |
| `pack_kicker.py` | 221 | The 30-day disproof test | `How_To_Know_In_30_Days.md` (`:26`) | yes |
| `pack_linter.py` | 2147 | Nothing. It grades. | `*.lint.json` | yes |
| `pack_manifest.py` | 419 | Machine-readable pack description | `manifest.jsonld` (`:64`) | yes |
| `pack_offer.py` | 160 | What the business sells | `The_Offer.md` (`:21`) | yes |
| `pack_pdf.py` | 706 | The printable pack | `Complete_Pack.pdf` (`:48`) | yes |
| `pack_reference.py` | 179 | Every source, every constraint | `Evidence_and_Constraints.md` (`:60`) | yes |
| `pack_table.py` | 114 | The assumptions the model rests on | `Assumptions.csv` (`:29`) | yes |
| `pack_toolkit.py` | 246 | Tools and suppliers named in the pack | `The_Toolkit.md` (`:37`) | yes |
| `pack_validation.py` | 95 | Structural validation of an assembled pack | n/a (`validate_pack` `:50`) | yes |

Two of the sixteen produce no buyer-facing file. `pack_floors.py` enforces a minimum
(`exec_summary_md` `:283`, `first_week_checklist_md` `:495`, `claim_safe_marketing` `:198`,
`ensure_marketing_floor` `:591`). `pack_validation.py` checks the assembly.

### 2.1 The reading order the buyer actually gets

`prospector/bridge.py:378-399`, `BUNDLE_READING_ORDER`, fourteen sections in this order:

1. `00_Executive_Summary.md`
2. `The_Offer.md`
3. `The_Field.md`
4. `04_Financial_Model.md`
5. `What_Would_Sink_This.md`
6. `01_Blueprint_BuildSpec.md`
7. `02_Marketing_Plan_GTM.md`
8. `03_Operations_Plan.md`
9. `05_First_Week_Checklist.md`
10. `The_Toolkit.md`
11. `Marketing_Assets.md`
12. `How_To_Know_In_30_Days.md`
13. `Evidence_and_Constraints.md`
14. `QA_Report.md`

`_SECTION_TITLES`, immediately below in the same file, maps each filename to the buyer-facing
heading: "Where this starts", "What you would be selling", "The field: who is already there",
"The numbers", "What would sink this", "What you build", and so on. **The filenames are internal.
The reader never sees them.** If you rename a section heading, edit `_SECTION_TITLES`, not the
filename, or the reading order breaks.

### 2.2 The five files that ship

`prospector/bridge.py:329-335`, `BUNDLE_FILES`:

- `index.html`
- `Complete_Pack.pdf`
- `First_Fortnight.html`
- `Assumptions.csv`
- `Marketing_Assets.txt`

The comment on that constant is a hard rule: *"if the PDF fails to render, the pack does not
list."* `BUNDLE_BONUS_FILES` (`:354-356`) adds `manifest.jsonld`, which is optional.

Verified against a real bundle on disk:

```
$ unzip -l publish/bundles/142717e797740247/prospector_pack_142717e7.zip
  Marketing_Assets.txt      593
  First_Fortnight.html     5896
  Assumptions.csv          9362
  index.html             113458
  Complete_Pack.pdf      244749
  manifest.jsonld         58557
                        -------
                         432615 (6 entries)
```

All five required files present, plus the bonus manifest. `index.html` is 113 KB — that is the
whole pack, self-contained, no external assets.

---

## 3. The three linters

### 3.1 `prospector/pack_linter.py` — the publish gate

2147 lines. It is the only linter that can stop a sale.

**The severity contract**, from the module docstring: *"an 'error' blocks listing (the pack
registers UNLISTED for repair); a 'warning' is recorded but does not block"*.

`lint_pack` (`:1902`) docstring: *"`report["ok"]` is False iff any problem has severity 'error' —
that is the half the publish gate ANDs into `is_listed`."*

**Every check, with its line:**

| Check | Line | What it refuses |
|-------|------|-----------------|
| `check_repetition` | `:198` | The same sentence or claim said twice |
| `check_currency` | `:382` | A figure with no currency, or two currencies mixed |
| `check_arithmetic` | `:468` | Numbers in a table that do not add up |
| `check_placeholders` | `:575` | `TBD`, `[insert]`, an unfilled template slot |
| `check_marketing` | `:586` | Marketing copy that names no audience |
| `check_sections` | `:627` | A missing or empty section from the reading order |
| `check_truncation` | `:645` | A line cut mid-word |
| `check_title` | `:831` | A title breaking the declared format |
| `check_engine_leak` | `:1264` | Our internal vocabulary appearing in buyer copy |
| `check_shelf_copy` | `:1319` | Shelf lines that trail off, repeat, or point at nothing |
| `check_claims` | `:1570` | A figure with no source behind it |
| `check_title_claims` | `:1675` | A claim in the title the pack does not support |
| `check_urls` | `:1821` | A citation URL that does not resolve |
| `readability_grades` | `:148` | (measures, does not block) |

**`check_truncation` (`:645`) is the interesting one**, because it is decidable only against the
pre-truncation source. Its docstring:

> `fields` maps field name → (final rendered value, full pre-truncation source). Two cut styles
> exist in the publish path and both are checked against the source: an ellipsis suffix whose
> pre-ellipsis text stops inside a word of the source, and a bare hard slice (`headline[:140]`,
> `subhead[:280]`) that ends exactly at its cap in the middle of a source word. The source is what
> makes this decidable — "…applicat…" is only provably mid-word because the source continues with
> a letter.

**`check_shelf_copy` (`:1319`) applies a stricter rule than `check_truncation`.** Its first
sub-check (`:1349-1354`) refuses any ellipsis at all on a shelf line, proven or not, with this
reason: *"on the shelf the line IS the whole of the copy, so an ellipsis is a defect whether or not
the cut was clean. 29 of the 50 live one-liners ended this way on 2026-08-13."*

**`check_title` fixes the title format.** `TITLE_MAX_CHARS = 60` (`prospector/pack_linter.py:1234`
region), declared shape `<what the business does> for <who pays>`, founder decision 2026-08-13,
superseding "the name leads" of 2026-08-09. The comment explains the cap: *"`TITLE_MAX_CHARS`
mirrors `CARD_LINE_MAX` (artifacts.py) deliberately — the storefront already produces a 40-60 char
line for the same pack and renders it well, so the title has no claim to be 90+."*

**Bare pronoun openers.** `_BARE_PRONOUN_OPENERS = frozenset({"it", "they", "this", "that",
"these", "those"})`. It fires only when the pronoun is followed immediately by a finite verb. The
comment records the calibration: *"measured over the 75 live one-liners on 2026-08-16 it named
exactly one, the founder's."* One false-positive rate of 1 in 75 is why the check needs no
exception list.

**Run it:** the report is written to `store/dossiers/<id>.lint.json`. Read the persisted receipt
rather than re-linting — the answer is already on disk.

### 3.2 `scripts/doc_lint.py` — the documentation linter

Three checks: a `path/file:line` reference that does not exist, an empty referenced path, and a
retired provider name.

- `SCAN_GLOBS = ("RUN.md", "README.md", "docs/*.md")`
- `HISTORICAL_FILES = frozenset({"CLAUDE.md", "docs/COST_PROGRAM.md", "docs/attic"})` — exempt,
  because they are records of what was true.
- `CROSS_REPO_FILES = frozenset({"docs/TELEGRAM_OPERATOR_PROGRAM.md"})`
- A trailing `doc-lint-ok` comment exempts a single line.
- Functions: `selected_providers` `:108`, `lint` `:182`, `check_ratchet` `:235`, `main` `:254`.
- **It never edits.** Report only.

Measured this session:

```
$ python3 scripts/doc_lint.py; echo "EXIT=$?"
docs/SUBSCRIPTION_PROGRAM.md:1251: missing_path: Services/FulfilmentService.cs:115-133 — the doc points at a path that is not there
doc_lint: 184 problem(s)
EXIT=1
```

**184 problems, exit 1.** The docs currently fail their own linter.

**Trap, and it cost time this session.** `python3 scripts/doc_lint.py | tail` reports `EXIT=0`.
That is `tail`'s exit status, not the script's. Capture the real status before any pipe.

### 3.3 `ops/config/retired_terms.yaml` — the retired vocabulary

85 lines. One term is currently live: `paddle`, removed 2026-08-16. Every `allow:` prefix carries a
written reason, so an exemption cannot be added silently.

```
$ python3 ops/automations/retired_terms.py
OK: 1386 files, no retired term found (paddle).
```

Clean. This is the cheapest of the three linters and the one most likely to be forgotten when a
provider is swapped out.

---

## 4. Source-or-die, and where it is mechanically enforced

The rule: every factual claim and every number carries a retrievable source, or it is marked
`unverifiable`. It is enforced in four separate places, which is why it holds.

1. **At verdict time.** `prospector/verify.py` rules only on passages actually fetched. A verdict
   call that raises returns `retrieval_failed=True` (`verify.py:365`), which fires the DEFER gate
   (`verify.py:693`) rather than contributing an `unverifiable` check to the kill gates.
2. **At gate time.** `prospector/kill_filter.py:20`, `is_hard_fail`: `retrieval_failed` can never
   trip a gate, and a kill needs a cited killing verdict clearing `thresholds.confidence_floor`.
3. **At lint time.** `check_claims` (`pack_linter.py:1570`) and `check_urls` (`:1821`). A figure
   with no source is an error. A citation URL that does not resolve is an error.
4. **On the shelf.** `store_platform/src/Store.Web/src/pages/index.tsx:2150-2153`: *"A claim
   without a source dies before it reaches this shelf. Every pack here came out the other side."*

That last one is a promise printed on the home page. It is only true because of the three above it.
If you weaken any of 1-3, you have to change the home page copy, or the site is lying.

### 4.1 What the receipt looks like

`store/dossiers/142717e797740247.lint.json`, a real pack, read this session:

- `ok: true` — it listed
- ruleset `6fe7fcfd4331`
- `urls_checked: 20`
- `sections_graded: 13`
- readability grades 5.9 to 15.0 across sections
- `R5_unsourced_figures: 8`
- `Q_bad_quotes: 32` of 53 quotes
- `human_register.outside`: `punct_hyphen_per_1k` 22.558 against a p95 of 7.0547, z = 7.72

**This pack is on sale with 8 unsourced figures and 32 questionable quotes.** Those are warnings,
not errors, so they did not block the listing. That is the severity contract working exactly as
designed and it is also the largest content debt in the estate. See §8.

---

## 5. The storefront renders no markdown

**Proven, not assumed.**

```
$ rg '"(marked|react-markdown|remark|markdown-it|rehype)' store_platform/src/Store.Web/package.json
(no hits)
```

No markdown library is installed. And `dangerouslySetInnerHTML` appears in exactly two places in
the whole web app:

- `components/Seo.tsx:159` — JSON-LD structured data
- `components/marketing/PopulationField.tsx:135` — marks generated from two integers

**What this means for anyone writing copy.** If you type `**bold**` into a storefront string, the
buyer sees the asterisks. If you type a markdown link, the buyer sees the brackets. Every visual
distinction on the site is a React element and a CSS class. There is no shortcut.

**It also means pack markdown is not what the buyer reads on the site.** The `.md` sections in the
reading order are rendered to HTML inside the bundle by `pack_html.py:131` (`render_pack_html`) and
`pack_pdf.py`. The website shows the pack's metadata and the sample, not the markdown.

### 5.1 Two CSS rules that are content rules

- `components/marketing/blocks.tsx:76` mandates `overflow-clip` and **never** `overflow-hidden`.
  `overflow-hidden` on an ancestor kills every descendant `sticky`. It did:
  `pages/pack/[id].tsx:1420-1422` records *"THIS RAIL ONLY STARTED STICKING ON 2026-08-14.
  `sticky top-24` had been here for months and computed as `sticky`, but `SectionBand`'s inner div
  was `overflow-hidden`."* Same note at `components/marketing/PackSpecimen.tsx:252-254`.
- `src/styles/tokens.css:829` deletes `fade-in-up` (20px over 800ms). `:836-837`: *"hero must not
  fade. Use `animate-settle` on anything that can be a route's LCP element."* An entrance animation
  on a headline makes Largest Contentful Paint wait for the animation. Measured with
  `scripts/design-audit/measure-lcp.mjs`, recorded at `tokens.css:852-865`, including the line
  *"the metric was waiting on a fade"*.

---

## 6. Known content defects: verified, one by one

The three named defects were checked against live data and current code this session. Two are
fixed. One is fixed at the mechanism and needs a re-measure.

### 6.1 Truncated one-liners — FIXED, verified live

The defect: 29 of 50 live one-liners ended in an ellipsis on 2026-08-13
(`pack_linter.py:1352` comment).

Measured today against the live catalogue:

```
$ curl -s https://api.mumchimp.com/catalog | python3 -c "..."
rows 74
oneLine ending in ellipsis: 0
rows with oneLine: 74
len min/mean/max: 124 176.4 268
title len max: 60  over 60: 0
```

**Zero of 74 live one-liners trail off. Zero of 74 titles exceed the 60-char cap.** The
`check_shelf_copy` and `check_title` gates are holding.

### 6.2 Content-addressed bundle keys — WORKING AS DESIGNED

`prospector/bridge.py:1438`: *"Upload the deliverable to R2 (content-addressed by hash, so a later
republish…)"*. The key is minted at `:1446`:

```python
content_key = f"packs/{candidate_id}/{content_hash}.zip"
```

`bridge.py:1631`: *"SHA-256 of the bundle, used as the content-addressed storage key."*

**The consequence for content management.** Change one word in a pack and re-render, and the hash
changes, so the storage key changes. The old key still exists. Entitlements snapshot the key they
were sold against (`DeliveryEndpoints.cs:242-245`: *"Serve the key snapshotted on the entitlement
(what the buyer paid for)"*), so **an existing buyer keeps the version they bought**. New buyers
get the new one. This is correct and deliberate. It also means you can never "fix a typo for
everyone" — a republish creates a second artefact.

`content_key` is only written to the catalogue row when the pack is listed (`bridge.py:1523`:
`content_key=content_key if is_listed else None`).

### 6.3 The share card was another product's — FIXED, and the fix is a URL

`store_platform/src/Store.Web/src/lib/seo/ogImage.ts` records both halves.

The first defect, from `pages/og/pack/[id].tsx:10-12`: *"Every pack page previously nominated the
same generic `/og.png`, so 49 different products shared one image on X, LinkedIn, Slack, iMessage,
and in the citation cards AI assistants now render."* Fixed by the per-pack route
`/og/pack/<id>`, rendered with `next/og` from `getServerSideProps` on the Node runtime.

The second defect is the one the memory names, `ogImage.ts:37-48`:

> THE `?v=` IS LOAD-BEARING, not decoration. Until 2026-08-14 `public/og.png` was the link-preview
> card of a different product entirely ("The Intro Exchange"), shipped in `5f95ca7` and never
> regenerated; it is now the Mumchimp card (`scripts/gen-brand-assets.mjs`). Every social scraper
> caches a preview against the image URL and re-fetches on a timescale of weeks, not minutes.
> Replacing the BYTES at an unchanged URL therefore leaves the wrong brand on every link already
> scraped.

Current value: `DEFAULT_OG_IMAGE_PATH = '/og.png?v=2026-08-14'`.

**The rule this leaves you.** If you regenerate `public/og.png`, you must bump the date in that
constant in the same commit. Replacing the bytes alone changes nothing anyone sees.

**Why the route is not under `/api`.** `next.config.ts` rewrites `/api/:path*` to the backend, and
an array rewrite is evaluated after static pages but before dynamic routes, so `/api/og/pack/[id]`
would lose to the proxy and 404 from the API (`pages/og/pack/[id].tsx:16-18`). `/og` is also not in
the robots.txt disallow list, which matters: *"A blocked og:image is the same as no og:image"*
(`ogImage.ts:9-11`).

---

## 7. How to change a word safely, end to end

### 7.1 Storefront copy (kind 3)

1. Find the string. It is a literal in a `.tsx` file under `store_platform/src/Store.Web/src/`.
2. Edit it. No markdown. See §5.
3. If it is a number or a claim, it must come from `src/lib/stats.ts`, not be typed inline. That
   module exists because on 2026-08-06 `/kill-log` said *"We researched 1168 business ideas and
   rejected 89%"* while `/how-it-works` said *"Of 1,313 ideas researched, 145 survived"*.
   `researched` is now an invariant: killed + survived.
4. **Do not add a survivor count.** Founder directive 2026-08-13, recorded in `stats.ts`: *"saying
   80 when only 50 are listed should never happen regardless of the reasons why survivors are
   unlisted."* The survivor count is deliberately not exported.
5. Build, and capture the exit status **before** any pipe. `npm run build 2>&1 | tail` reports
   tail's status, so a failed build reads as exit 0.

### 7.2 A pack heading (kind 2)

1. Edit `_SECTION_TITLES` in `prospector/bridge.py` (after `:399`). Not the filename.
2. Check `pack_linter.check_sections` (`:627`) still finds the section.
3. Re-render. The bundle hash changes, so the storage key changes. See §6.2.

### 7.3 Pack body text (kind 1)

You cannot edit it directly. It is model output held in the dossier. To change what the model
produces, edit the prompt in `prospector/prompts.py`, then re-vet. Every pack rendered under the
old prompt keeps its old text.

### 7.4 The republish path

A pack that fails lint registers UNLISTED for repair. The repair path is the ops console:

```
python -m prospector.ops.console_api read shelf
python -m prospector.ops.console_api act shelf.repair_copy --preview --payload '{...}'
python -m prospector.ops.console_api act shelf.repair_copy --confirm <token> --payload '{...}'
```

`shelf.repair_copy`, `shelf.publish_pending` and `shelf.regate` are three of the thirteen write
actions in `store_platform/src/Ops.Console/src/pages/api/ops/act/[action].ts:21-34`. Every write is
two-step: preview, then confirm with the token the preview returned.

**Price is refused by name.** The console will not write a price; it points you at
`prospector/bridge.py`, because one `PriceDecision` mints the Stripe Price object and the catalogue
row together. A price written in one place and not the other charges the buyer and then fails the
fulfilment fence.

---

## 8. The numbers, measured this session

| Measurement | Value | Command |
|---|---|---|
| Renderer source | 7439 lines over 16 files | `wc -l prospector/pack_*.py` |
| Linter source | 2147 lines | same |
| Lint receipts on disk | 123 | `ls store/dossiers/*.lint.json \| wc -l` |
| Receipts with at least one error | 76 of 123 | count over the receipts |
| Passed packs that cannot be sold | 74 of 108 | `python3 ops/automations/stranded_packs.py` |
| Doc-lint problems | 184, exit 1 | `python3 scripts/doc_lint.py` |
| Retired-term scan | 1386 files, 0 hits | `python3 ops/automations/retired_terms.py` |
| Live catalogue rows | 74 | `curl -s https://api.mumchimp.com/catalog` |
| Live one-liners trailing off | 0 of 74 | same |
| Live titles over 60 chars | 0 of 74 | same |

### 8.1 What blocks the 74 stranded packs

```
$ python3 ops/automations/stranded_packs.py
FINDINGS — 74 of 108 passed packs cannot be sold (34 can).
73 lint_failed, 1 never_linted.
blocked by these checks (packs affected):
  42 shelf_copy, 21 placeholders, 20 title, 6 citation_urls,
   2 marketing_audience, 1 currency, 1 grammar
```

Across all 123 lint receipts, blocking errors by kind: placeholders 68, shelf_copy 66, title 26,
citation_urls 8, sections 6, marketing_audience 2, grammar 1, currency 1.

**Read that carefully.** The two biggest blockers, placeholders and shelf copy, are both copy
defects, not research defects. **The bottleneck is packaging, not thinking.** See
[growth-marketing.md](growth-marketing.md) for what that costs in revenue.

### 8.2 Warnings, which do not block

house_style 4633, house_quote 2803, repetition 1600.

Nine thousand warnings across 123 packs. They are recorded and ignored. That is a deliberate
choice, and it is also §9's first invariant risk: a warning class that grows without bound stops
being read, and then a real signal in it is invisible.

---

## 9. Invariants, and what breaks when they go

| Invariant | Where it lives | What breaks |
|---|---|---|
| No renderer calls a model | proven in §1.1 | The same pack renders differently twice; lint verdicts stop being reproducible |
| `report["ok"]` is False iff any error | `pack_linter.py:1902` | Either bad packs list, or good packs strand |
| If the PDF fails, the pack does not list | `bridge.py:329-335` | A buyer pays and receives an incomplete bundle |
| The storefront renders no markdown | §5, zero libraries installed | Asterisks and brackets appear in live copy |
| The bundle key is the content hash | `bridge.py:1446` | Editing a pack silently rewrites what past buyers already own |
| An entitlement serves its snapshotted key | `DeliveryEndpoints.cs:242-245` | Same as above, from the other side |
| Titles cap at 60 chars | `TITLE_MAX_CHARS`, `check_title:831` | Shelf cards truncate mid-word again |
| Shelf lines never end in an ellipsis | `check_shelf_copy:1319` | Back to 29 of 50, the 2026-08-13 state |
| Every number on the site comes from `stats.ts` | `src/lib/stats.ts` | Two pages contradict each other, as they did on 2026-08-06 |
| `?v=` bumps when `og.png` changes | `ogImage.ts:48` | Warm scraper caches keep showing the old card forever |

---

## 10. Failure modes

**Symptom: a finished pack never appears on the shelf.**
Root cause: lint error. Fix: read `store/dossiers/<id>.lint.json` — the answer is already on disk,
do not re-lint. Then `python3 ops/automations/stranded_packs.py` for the estate-wide picture.

**Symptom: a shelf line reads as nonsense, e.g. "It takes a published NHS rota…".**
Root cause: a bare pronoun opener with no antecedent. The line is shown beside the title, never
inside a paragraph, so "It" points at nothing. Caught by `check_shelf_copy`'s
`_BARE_PRONOUN_OPENERS` since 2026-08-16. Fix: `act shelf.repair_copy`.

**Symptom: the doc linter reports a path that clearly exists.**
Root cause: usually the path moved and the doc did not. Current live example:
`docs/SUBSCRIPTION_PROGRAM.md:1251` points at `Services/FulfilmentService.cs:115-133`. Fix the doc.
If the reference is deliberately historical, move the file into `HISTORICAL_FILES` or add
`doc-lint-ok` to the line, with a reason.

**Symptom: a linter "passes" in CI but the problem is still there.**
Root cause: a pipe ate the exit status. `python3 scripts/doc_lint.py | tail` prints `EXIT=0` while
the script exits 1. Fix: capture the status before the pipe.

**Symptom: a shared link shows the wrong brand.**
Root cause: `public/og.png` bytes were replaced without bumping `?v=`. Every scraper caches against
the URL. Fix: bump `DEFAULT_OG_IMAGE_PATH`. Facebook's cache also needs a manual pass through its
Sharing Debugger.

**Symptom: a sticky sidebar does not stick.**
Root cause: an ancestor has `overflow-hidden`. Fix: `overflow-clip`. See `blocks.tsx:76`.

**Symptom: LCP regressed after a copy change.**
Root cause: the new element inherited an entrance fade. Fix: `animate-settle`, never `animate-rise`
or a fade, on anything that can be the LCP element. `tokens.css:836-837`.

---

## 11. Open gaps and debt

| Gap | Evidence | Cost to close |
|---|---|---|
| 74 of 108 passed packs unsellable | `stranded_packs.py` | The largest single content debt. 42 need shelf copy, 21 need placeholder fills, 20 need titles. Mostly mechanical. `stranded_packs.py` has no `--fix` by design. |
| 8 unsourced figures in a listed pack | `142717e797740247.lint.json`, `R5_unsourced_figures: 8` | Promote R5 from warning to error and 76 more packs strand. The real fix is upstream, in the prompt. |
| 32 of 53 quotes flagged in a listed pack | same receipt, `Q_bad_quotes: 32` | Same tradeoff. |
| ~9000 warnings ignored | house_style 4633, house_quote 2803, repetition 1600 | Either act on a class or delete the check. An unread warning is a lie about coverage. |
| 184 doc-lint problems, exit 1 | measured §3.2 | Docs are not gated in CI, so this grows. Fixing needs a pass per file. |
| Register drift is measured, not gated | `human_register.outside` z = 7.72 on hyphen density | The pack reads as machine-written on a measurable axis and nothing blocks it. |

**HYPOTHESIS: the 68 placeholder errors are concentrated in a few sections.** The check that would
confirm or kill it: group `problems` by `section` across all `store/dossiers/*.lint.json` where
`check == "placeholders"`. If they cluster, one prompt edit clears most of them. I have not run
this.

---

## 12. Where to look next

- [growth-marketing.md](growth-marketing.md) — what the 74 stranded packs cost, and the facet gaps
  that limit discovery.
- [support.md](support.md) — what a buyer sees when a pack's content is wrong after purchase.
- [buyer.md](buyer.md) — the same product described without any of this vocabulary.
- [../ESTATE_MAP.md](../ESTATE_MAP.md) — where every system in this document sits.
- `docs/PACK_NARRATIVE_PROGRAM.md` — the reading order's design rationale and the implementation
  ledger. Read it before touching any `pack_*.py`.
