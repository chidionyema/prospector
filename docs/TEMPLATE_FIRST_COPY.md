# Template-first listing copy

Why this document exists. The engine is moving off this laptop, so the Claude Code CLI may
not be reachable from where it runs. The founder's instruction: "sales pages should be
templates and most things should be, so we don't need Claude Code. Examine current templates
and minimise what we need intelligence for." The hard constraint on top of it: "can't risk
copy not being quality."

So the question this document answers is not "can we template the listing page". It is
"which listing fields can be built from data the engine already holds, without the copy
getting worse". Every number below is counted over the packs on disk, not estimated.

## What is already model-free

The pack BODY is already templates. The 16 `prospector/pack_*.py` renderers make no model
call. `prospector/pack_floors.py:198` (`claim_safe_marketing`) is a complete deterministic
listing page that already ships when the model path returns nothing, and
`prospector/facet_derive.py` already derives two facets from candidate fields. The
template-first mechanism exists. This work extends it rather than adding a second one.

The listing page is the remaining model-written surface, and it is not free prose.
`prompts/content_gen.md:97-117` fixes it to a JSON object of eleven fields.
`prospector/artifacts.py:1063` (`_normalize_listing`) coerces the result.

## The corpus

89 pass dossiers on disk carry a `listing_page` (of 108 pass dossiers total), read from
`store/dossiers/*.pass.json` at `candidate.tags["marketing"]`. Every count below is over
those 89.

How often the model actually fills each field:

| field | filled |
|---|---|
| `who_pays` | 89/89 |
| `effort_tag` | 89/89 |
| `copy` | 89/89 |
| `what_you_get` | 88/89 |
| `facets` | 87/89 |
| `cta_text` | 86/89 |
| `subhead` | 77/89 |
| `proof_point` | 76/89 |
| `card_line` | 74/89 |
| `headline` | 73/89 |
| `time_to_first_revenue` | 0/89 |

The empties are the salvage path (`artifacts.py:1133`, `_salvage_listing`) dropping a field
that failed claim-check on its own. That is working as designed and is not a defect.

## The buckets

### (a) Closed-vocabulary classification

The model picks one token from a fixed list. It is being used as a classifier, not a writer.

| field | vocabulary | evidence |
|---|---|---|
| `effort_tag` | `low \| medium \| high` | `prompts/content_gen.md:105`, validated `artifacts.py:1111` |
| `facets.advantages` | 0-3 of `code \| nocode \| sales \| ops \| audience` | `content_gen.md:107`, `facets.py` |
| `facets.payer` | `b2b \| b2c \| b2g` | `content_gen.md:108` |
| `facets.effort` | `automatable \| part_automatable \| hands_on` | `content_gen.md:109` |
| `facets.commitment` | `evenings \| part_time \| full_time` | `content_gen.md:110` |
| `facets.mechanism` | 8 members | `content_gen.md:111` |
| `facets.sector` | 12 members | `content_gen.md:112` |

Every one of these is validated against the closed vocabulary at `artifacts.py:1115`
(`facets.normalize`) and off-vocabulary answers are dropped rather than coerced. Measured
cost of that: 3 of 89 packs carry `effort_tag: "solo_operator"`, which is not a member, so
the field arrives empty. (Those 3 came from the deterministic floor, `pack_floors.py:277`,
not from the model.)

**These seven are classification, not writing. None of them needs a frontier model.** A
cheap local classifier, or in one case a lookup, is enough. One of them can be resolved
today without any model at all; see (b).

### (b) Extraction from data already on hand

Four fields looked extractable. Three of them are not, and the measurement is what says so.

| candidate | source field | is the data there? | verdict |
|---|---|---|---|
| `facets.mechanism` | `candidate.structural_form` | **89/89 present** | **TEMPLATE IT** |
| `facets.effort` | `candidate.automatability` | 89/89 present | **do not** (31% agreement) |
| `proof_point` | supported check rationales | 88/89 offer a numeric sentence | **do not** (wrong voice) |
| `what_you_get` | `candidate.tags["artifacts"]` | 84/89 have the 4-key manifest | **do not** (loses evidence) |
| `time_to_first_revenue` | verified claims | 1/89 | **dead field** |

#### `facets.mechanism` — template it

`facet_derive.derive_mechanism` (`facet_derive.py:159`) maps `candidate.structural_form` to
the `mechanism` facet. The module's own argument for why this is safe: `MECHANISM` mirrors
`config.yaml generation.structural_forms`, so this is a vocabulary check, not an inference
(`facet_derive.py:13-15`).

Measured against what the model wrote, over the same 89 packs:

```
both present, AGREE       : 62
both present, DISAGREE    :  3   productized_service->vertical_tool (2),
                                 productized_service->picks_and_shovels (1)
model only (form off-vocab): 20
DERIVED only (model blank) :  2   <- gaps the template FILLS
neither                    :  2
agreement rate            : 62/65 = 95%
```

`structural_form` is non-empty on 89/89 candidates. 20 of them carry a form outside the
facet vocabulary (`micro_ecommerce`, `productized_freelance`, `local_service`,
`api_product`, `vertical_saas`, ...), and `facets.clean_one` refuses to coerce those, so the
deriver returns nothing and the model's answer stands. That is the correct ordering and it
is why this is a safe change: derive first, fall back to the model, never coerce.

Net effect: 64 of 89 packs get their `mechanism` from the candidate's own declared form
instead of a model re-judgement, 2 previously-blank facets get filled, and 3 change value.

#### `facets.effort` — do NOT template

`facet_derive.derive_effort` (`facet_derive.py:127`) bands `candidate.automatability`.
The source field is present 89/89. But it disagrees with the model:

```
both present, AGREE       : 26
both present, DISAGREE    : 58   part_automatable->automatable (48),
                                 hands_on->part_automatable (6),
                                 part_automatable->hands_on (3),
                                 hands_on->automatable (1)
agreement rate            : 26/84 = 31%
```

48 of the 58 disagreements are in one direction: the deriver reads the candidate's own
`automatability` (often the literal word "high", or 0.85, written at GENERATION time, when
nothing is judged) and calls it `automatable`, while the model reading the whole verified
dossier calls it `part_automatable`. `effort` routes buyers on the storefront. Swapping a
post-verification judgement for a pre-verification self-assessment on 58 of 84 packs is not
a template win, it is a filter that lies. Leave it model-written.

#### `proof_point` — do NOT template

The data is there: 88 of 89 packs have a supported check rationale containing a numeric
sentence of 40-400 characters. So a deterministic builder is *possible*. It should not be
built, for two reasons that are both measured.

First, the model is not lifting the rationale. Only **29 of 76** proof points share 50% or
more of their content words with any supported rationale. It is compressing and re-voicing,
which is exactly bucket (c) work.

Second, the rationales are written in verdict voice, for an internal reader. Real examples
from `store/dossiers/08b22037fc2afc07.pass.json`:

> rationale: "The passages describe a live, present-tense situation: the Ombudsman has just
> published its annual review of adult social care and announced that it found fault in
> nearly two out of every three adult social care complaints it investigated over the past
> year [8fd945ede1af9b55][88727c2ce7303497], whil..."

> proof_point shipped: "The Local Government and Social Care Ombudsman announced that it has
> found fault in nearly two out of every three adult social care complaints it has
> investigated in the past year, as reported by Home Care Insight."

The template would ship the first one, brackets, passage ids, "the passages describe" and
all. That is worse copy on the single most persuasive line on the card.

#### `what_you_get` — do NOT template

The artifact manifest is present on 84/89 packs and it is always the same four keys:
`financial_model`, `gtm_plan`, `build_spec`, `ops_plan`. So a manifest-driven bullet list is
easy, and `pack_floors.py:261-269` already writes exactly that as the floor:

```
"Blueprint / build spec", "Go-to-market plan", "Operations plan",
"Financial model (arithmetic computed in Python, assumptions listed)"
```

The model's bullets are not that. Across 302 bullets on 89 packs, **171 (57%) carry a figure
or run past 120 characters**, because they name the pack's own evidence:

> "A drafting library grounded in published duties. The Care Act 2014 places a statutory duty
> on councils to assess any adult, including carers, appearing to have a need for care or
> support (PMC). Section 10 provides the framework for the assessment of a carer (SCIE and
> legislation.gov.uk)."

Replacing that with "Blueprint / build spec" is the copy regression the founder's constraint
forbids. The generic four already exist as a floor for the case where the model produced
nothing; they must not become the default.

#### `time_to_first_revenue` — a dead field

**The model has never filled it. 0 of 89.** The prompt only permits a value when a verified
claim states a time range (`content_gen.md:114`), and a time range appears anywhere in the
supported rationales on **1 of 89** packs. `pack_floors.py:278` hardcodes it to `""`.

It is read by `bridge.py:921` into `timeToFirstRevenue` on the catalogue row, so it renders,
always empty. There is nothing to template. The correct action is to delete it from the
contract; that is a prompt and payload change, recorded here rather than made in this diff.

### (b-dead) `cta_text` has no consumer

Not a bucket, a finding. `cta_text` is written by the model on 86 of 89 packs, in 79
distinct values ("Get the full opportunity pack", "Get the Georgia film filing pack", "Get
your appeal letter drafted"). It is set at `artifacts.py:1117` and **nothing reads it**:

```
$ rg -n cta_text -g '!tests/**' -g '!docs/**' .
./prompts/content_gen.md:115
./prospector/artifacts.py:1117
```

It is not in `bridge.py`'s `catalog_meta`, so it never reaches the catalogue, the storefront
or the pack. It is model attention spent on a string no buyer sees.

It is deliberately NOT templated in this diff. Building a constant for a field nothing
renders buys nothing measurable, and if the field is ever wired to a real buy button, a
single generic label would be worse copy than the 79 bespoke ones. The correct action is the
same as `time_to_first_revenue`: delete it from the contract.

### (c) Genuine writing — stays model-written

| field | why a template cannot do it |
|---|---|
| `card_line` | 60-character truthful compression. `artifacts.py:1029` DISCARDS an over-long line rather than truncating, because a mid-clause cut changes the claim. Choosing what to drop is the judgement. |
| `headline` | 10-15 words naming the concrete outcome (`content_gen.md:100`). No field on the dossier holds it. |
| `subhead` | one sentence, who it is for and what they get. Closest source is `candidate.one_liner`, but the floor's `[:280]` slice (`pack_floors.py:259`) is the same mid-clause cut `card_line` bans. |
| `who_pays` | see below |
| `proof_point` | see (b) |
| `what_you_get` | see (b) |

`who_pays` deserves its own note, because `candidate.who_pays` is non-empty on 89/89 and it
looks liftable. It is not. Only **3 of 89** listings are byte-identical to it, and the
difference is load-bearing: the listing version adds the distribution channel, which the
candidate field does not carry.

```
candidate.who_pays: Unpaid family carers in England looking after a parent, partner or adult
                    child whose council-funded care hours have just been reduced or removed.
                    Typically people in their 40s to 60s who have cut thei...
listing.who_pays  : Unpaid family carers in England whose relative's council funded hours
                    have been cut, reached through carer forums and local carer organisations
                    such as the 135 Carers Trust Network Partners.
```

```
candidate.who_pays: Owner-operators of the ~350 classified shellfish production businesses in
                    England, Wales and Scotland (rope-grown mussel, oyster and clam farms,
                    typically 1-10 staff), paying £80-£250/month per lease;...
listing.who_pays  : Owner operated UK shellfish farms, reached through the Shellfish
                    Association of Great Britain newsletter, SAGB Conference and Dinner, and
                    Local Action Groups.
```

The listing version is a compression plus a channel the candidate never stated. Lifting the
candidate field would ship an over-long, channel-less paragraph on the card.

## The honest headline

**The listing page cannot be made template-first without the copy getting worse.** Six of
its eleven fields are writing or compression judgement. Two are dead. Of the seven
classification fields, exactly one has a dossier field that means the same thing.

What this work can honestly deliver is: one facet moved from model judgement to a lookup on
a field the candidate already declares, two dead fields identified for deletion, and seven
classification fields identified as not needing a frontier model. The pack body, which is
the bulk of what is sold, is already 100% model-free.

## Implementation ledger

### 2026-08-18 — `facets.mechanism` derived from `candidate.structural_form`

**Shipped.** One field. Everything else in bucket (b) was rejected on the measurements above.

What changed:

* `artifacts._derive_mechanism` (new, beside `_derive_copy`) reads
  `candidate.structural_form` through `facet_derive.derive_mechanism`.
* `_normalize_listing` takes an optional `candidate` and, when the builder returns a value,
  that value wins over the model's tag. Derive first, model as fallback, exactly the ordering
  `copy` already uses. Absent a candidate the function is byte-for-byte what it was.
* `_gen_one_content` takes the Candidate OBJECT alongside `cand_json`, because `cand_json` is
  `_candidate_prompt_view`'s projection for a model to read and does not carry engine fields.
* `tools/backfill_listing_copy.generate_listing` passes its candidate too. Without that, a
  backfilled listing would take its mechanism from the model while a freshly generated one
  took it from the declared form, and one field would mean two things depending on which
  producer wrote the pack.

Pinned by `tests/unit/test_listing_mechanism_is_derived_not_classified.py` (8 tests),
including a test that `effort` is still NOT derived, so a later "while we are in here" change
has to argue with the 31% number instead of a hunch.

#### The quality gate

`pack_linter.lint_pack` run over the 84 real packs on disk that carry both a listing_page and
the artifact set, through the same inputs `bridge.py` builds, URL checking off. Graded by pack
id, before and after:

```
  BEFORE  ok 39/84   blocked 45
  AFTER   ok 39/84   blocked 45
  packs that passed BEFORE and fail AFTER : 0
  packs that failed BEFORE and pass AFTER : 0
  packs whose ERROR set changed           : 0
  packs whose WARNING count changed       : 0
```

The 45 blocked packs are blocked before and after, on `placeholders:financial_model` and
`identifier_leak:build_spec` — pack-body defects that predate this work and are untouched by
it.

Every buyer-facing string, across all 84 packs:

```
  card_line             changed on 0 pack(s)
  headline              changed on 0 pack(s)
  subhead               changed on 0 pack(s)
  what_you_get          changed on 0 pack(s)
  proof_point           changed on 0 pack(s)
  who_pays              changed on 0 pack(s)
  copy                  changed on 0 pack(s)
  effort_tag            changed on 0 pack(s)
  cta_text              changed on 0 pack(s)
  time_to_first_revenue changed on 0 pack(s)
```

**No copy changed.** That is the whole quality argument, and it is a count, not a claim: this
change moves one browse facet and touches no sentence a buyer reads. The five other facets
also moved on 0 packs.

#### What actually moved: 5 packs of 84

Two facets FILLED that were blank. An untagged pack is reachable only under "All", so these
two were invisible to every filter and to the Matchmaker:

```
  50075fc6e149d809   None -> productized_service
  f2ac7df9995c334e   None -> productized_service
```

Three changed value, each to the form the candidate itself declares:

```
  38029727242c23c9   productized_service -> vertical_tool
     title: CMMC Level 2 evidence packs for GA defense software vendors
     candidate.structural_form = "vertical_tool"

  e55d5ee49e76e0a9   productized_service -> vertical_tool
     title: NHS Spine conformance for UK digital health vendors
     candidate.structural_form = "vertical_tool"

  8d5a441749448b69   productized_service -> picks_and_shovels
     title: Asset cross-check service for divorcing spouses
     candidate.structural_form = "picks_and_shovels"
```

**Honest cost, stated plainly: the third one reads worse.** "Asset cross-check service for
divorcing spouses" is a productized service by any ordinary reading, and generation's
`picks_and_shovels` looks like the weaker tag. That is 1 pack in 84. It is disclosed rather
than argued away, and it is the price of the trade: the derived value is traceable to a field
on the dossier, the model's is not, and two fields that mean the same thing must not disagree.

#### Side by side, 5 real packs

The five that moved. Every buyer-facing field, old and new:

```
--- 50075fc6e149d809 ---
  headline  [SAME] "Stripe chargeback defence packs for UK Shopify agencies"
  subhead   [SAME] "Pulls order, IP, fulfilment and signature evidence from Shopify and the
                    courier and packages it into Stripe's exact dispute-evidence format ..."
  who_pays  [SAME] "Owner of a UK Shopify Plus or ecommerce agency running DTC brand clients
                    (£500k-£20m GMV per client) who currently lose 30-50% of chargebacks ..."
  copy      [SAME] 619 chars
  facets.mechanism   None -> productized_service

--- f2ac7df9995c334e ---
  headline  [SAME] "Gig Deactivation Reversal Dossier"
  subhead   [SAME] "A productized service that builds a proven appeal pack for gig workers
                    unjustly deactivated by platforms like Uber, DoorDash, or Instacart ..."
  copy      [SAME] 599 chars
  facets.mechanism   None -> productized_service

--- 38029727242c23c9 ---
  card_line [SAME] "CMMC Level 2 evidence binders for defense software firms"
  who_pays  [SAME] "The person responsible for security or compliance at a small defense
                    contractor handling Controlled Unclassified Information, reached
                    through the Cyber AB Marketplace ..."
  cta_text  [SAME] "Get the CMMC evidence pack plan"
  copy      [SAME] 1243 chars
  facets.mechanism   productized_service -> vertical_tool

--- 8d5a441749448b69 ---
  card_line   [SAME] "Check a spouse's declared assets against public records"
  proof_point [SAME] "Forensic accountants typically charge £3,000 to £5,000 for a business
                      valuation in a divorce case (forensic.legal)."
  who_pays    [SAME] "A self representing divorcing spouse, a group that has grown since 2012
                      legal aid cuts pushed more family court litigants into representing
                      themselves (Parliament research briefing)."
  copy        [SAME] 490 chars
  facets.mechanism   productized_service -> picks_and_shovels

--- e55d5ee49e76e0a9 ---
  card_line [SAME] "NHS clinical safety paperwork for health software firms"
  headline  [SAME] "Turn a health software firm's existing documents into the NHS safety
                    evidence assessors ask for"
  who_pays  [SAME] "The chief technology officer or head of regulatory at a UK digital health
                    company that needs to connect to NHS systems, reached through NHS
                    Digital's supplier webinars ..."
  cta_text  [SAME] "Get the NHS conformance pack plan"
  copy      [SAME] 1576 chars
  facets.mechanism   productized_service -> vertical_tool
```

#### Tests

`pytest tests/ -q -k "listing or artifact or copy or publish or shelf or bundle or content"`
— 651 passed, 1 skipped. `ruff check .` repo-wide clean.

One existing test needed a signature fix, not a behaviour change:
`tests/unit/test_artifact_content_phase_budget.py` monkeypatches `_gen_one_content` with a
fake whose parameter list must match what `generate_marketing_content` submits.

## What was NOT done, and why

Each of these is a deliberate refusal with the number behind it, not an omission.

| not done | why |
|---|---|
| template `facets.effort` | 31% agreement with the model over 84 packs. `candidate.automatability` is written before anything is verified. |
| template `proof_point` | only 29 of 76 are traceable to a rationale; the rationales are verdict voice with passage ids in them. |
| template `what_you_get` | 171 of 302 bullets carry a figure or run past 120 characters. The generic four already exist as a floor and must not become the default. |
| template `card_line`, `headline`, `subhead`, `who_pays` | compression and phrasing judgement. Bucket (c). No dossier field holds the answer. |
| template `cta_text` | no consumer anywhere. Delete it, do not template it. |
| template `time_to_first_revenue` | filled 0 of 89 times. Delete it. |
| move the four remaining facets to a local classifier | out of scope here, but they are classification and do not need a frontier model. `sector`, `payer`, `commitment` and `advantages` are refused by `facet_derive` on a documented incident and are resolved by hand in `store_platform/data/facets-backfill.json`. |
| delete the two dead fields from `content_gen.md` | a prompt edit changes model behaviour on every OTHER field in the same response. It needs its own diff and its own golden run. |
