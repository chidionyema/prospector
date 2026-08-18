# Product Manager

**What this is.** The whole product, end to end: what is actually in the thing we sell, how a signal
becomes a pack on the shelf, what fraction survives each gate with today's real numbers, how the
catalogue is segmented, and the five weaknesses that have evidence behind them.
**Read this if** you need to decide what to build next, explain the funnel to someone, or find out
why 96 candidates in 100 die.
**Do not read this for the money.** Prices, costs and margins are [`finance.md`](./finance.md); this
file stops at "what it is worth building" and hands off there.

Every claim carries a `file:line`, a config key with its line number, or a command with the output it
produced. **All counts were measured on 2026-08-18 on this machine** unless dated otherwise. Where a
claim could not be proved, the line begins `HYPOTHESIS:` and names the check.

Siblings, so this file does not duplicate them:

- [`../ESTATE_MAP.md`](../ESTATE_MAP.md) — what runs and where.
- [`../PACK_NARRATIVE_PROGRAM.md`](../PACK_NARRATIVE_PROGRAM.md) — the tracked programme for what the
  buyer reads. **Append pack-narrative findings there, not here.**
- [`finance.md`](./finance.md) — the price ladder, the cost per pack, the money rail.
- [`analyst.md`](./analyst.md) — whether a funnel number can be trusted.
- [`buyer.md`](./buyer.md) — the same journey from the buyer's chair.
- [`content-management.md`](./content-management.md) — the prose, the voice rules, the linter.
- [`growth-marketing.md`](./growth-marketing.md) — discovery, facets, shelf copy.
- [`ops.md`](./ops.md) — the buttons that change any of it.

---

## 0. The product in seven numbers

| Question | Number | § |
|---|---|---|
| Dossiers ever produced | **2,929** | §3.1 |
| Of those, PASS | **108 (3.69%)** | §3.1 |
| Packs on the live shelf right now | **74** | §3.6 |
| Sections in a pack, in a fixed reading order | **14** | §1.1 |
| Renderers that build them | **16 modules**, 8 of them model-free | §1.2 |
| Best-converting lane | **`side_hustle`, 8.2%** — the *smallest* funded lane | §4.2 |
| KILLs caused by our own failed calls, not by judgement | **249 of 2,698 (9.2%)** | §7.2 |

The product works. The funnel does not yet aim itself at the evidence it has already collected —
§4.2 and §7 are the same story told twice.

---

## 1. Complete inventory: what is actually for sale

### 1.1 The pack — fourteen sections, one fixed reading order

`prospector/bridge.py:378` `BUNDLE_READING_ORDER` is the order. `bridge.py:414` `_SECTION_TITLES` is
what the buyer sees. `bridge.py:295` carries the instruction: *"`BUNDLE_READING_ORDER` and
`_SECTION_TITLES` are what they read. Leave them alone."*

| # | File | Buyer-visible title | Rendered by | Model call? |
|---:|---|---|---|---|
| 1 | `00_Executive_Summary.md` | Where this starts | `pack_floors.exec_summary_md()` | no |
| 2 | `The_Offer.md` | What you would be selling | `pack_offer.render()` `:87` | **no** |
| 3 | `The_Field.md` | The field: who is already there | `pack_field.render()` `:308` | **no** |
| 4 | `04_Financial_Model.md` | The numbers | model artifact + bear-case absorb | yes |
| 5 | `What_Would_Sink_This.md` | What would sink this | `pack_bear_case.render()` `:239` | **no** |
| 6 | `01_Blueprint_BuildSpec.md` | What you build | model artifact | yes |
| 7 | `02_Marketing_Plan_GTM.md` | How the first customers find you | model artifact | yes |
| 8 | `03_Operations_Plan.md` | How it runs once it works | model artifact | yes |
| 9 | `05_First_Week_Checklist.md` | Your first fortnight | `pack_checklist.render()` `:146` | **no** |
| 10 | `The_Toolkit.md` | The toolkit | `pack_toolkit.render()` `:125` | **no** |
| 11 | `Marketing_Assets.md` | Copy you can paste | model artifact | yes |
| 12 | `How_To_Know_In_30_Days.md` | How to know in 30 days | `pack_kicker.render()` `:92` | **no** |
| 13 | `Evidence_and_Constraints.md` | Everything we read, once | `pack_reference.render()` `:87` | **no** |
| 14 | `QA_Report.md` | Every check, in full | `dossier.render_markdown()` `:738` | no |

The order is a reader's journey, not the pipeline. `docs/PACK_NARRATIVE_PROGRAM.md:475-476` records
what it replaced: *"Today's reading order is the pipeline: exec summary → build → GTM → ops →
financials → checklist → marketing → evidence → QA."* The audit was the largest thing the buyer
scrolled through; it is now section 14.

`PACK_NARRATIVE_PROGRAM.md:495-502` names the borrowed shape: §1 is the anecdotal lede, §2 the nut
graf, §5 the fallibility device, §13 the kicker circling back to the buyer named in §1.

**The titles were rewritten on 2026-08-15 and the reason is a product reason.** `bridge.py:414-421`:
they were named after the DOCUMENT ("The Financial Model", "The QA Report") rather than after what
the reader gets. Two of them printed the engine's own vocabulary at *"a buyer who has no QA
department and did not buy a blueprint."*

### 1.2 The sixteen `pack_*` modules

| Module | Entry point | Produces | Model call? |
|---|---|---|---|
| `pack_floors.py` | `exec_summary_md()` | `00_Executive_Summary.md`, plus the completeness floors | no |
| `pack_offer.py` | `render()` `:87`, `FILENAME` `:21` | `The_Offer.md` | no |
| `pack_field.py` | `render()` `:308` | `The_Field.md` | no |
| `pack_bear_case.py` | `render()` `:239` | `What_Would_Sink_This.md` | no |
| `pack_checklist.py` | `render()` `:146` | `05_First_Week_Checklist.md` | no |
| `pack_toolkit.py` | `render()` `:125`, `FILENAME` `:37` | `The_Toolkit.md` | no |
| `pack_kicker.py` | `render()` `:92`, `FILENAME` `:26` | `How_To_Know_In_30_Days.md` | no |
| `pack_reference.py` | `render()` `:87`, `FILENAME` `:60` | `Evidence_and_Constraints.md` | no |
| `pack_table.py` | `render()` `:52`, `FILENAME` `:29` | `Assumptions.csv` | no |
| `pack_card.py` | `render()` `:126` | `First_Fortnight.html` | no |
| `pack_html.py` | `render_pack_html()` `:131` | `index.html` — the in-bundle reading experience | no |
| `pack_pdf.py` | `render_pack_pdf()` `:664`, `FILENAME` `:48` | `Complete_Pack.pdf` | no |
| `pack_manifest.py` | `render_manifest()` `:210`; `dossier_from_dict`, `_ns` `:356` | `manifest.jsonld` | no |
| `pack_data.py` | `scorecard()` `:228`, `financial_model()` `:289`, `comparables()` `:399`, `render_pdf()` `:686`, `write_artifacts()` `:861`, `artifacts_for_bundle()` `:904` | JSON / CSV / SVG / XLSX / PDF bonus files | no |
| `pack_linter.py` | `audit_bundle()` | `<id>.lint.json` — the grading receipt | no |
| `pack_validation.py` | `validate_pack()` `:50` | nothing; it is the completeness gate | no |

`pack_linter.py` is **121,536 bytes**, the largest module in the engine. It grades what the other
fifteen produced.

**Eight of these are deterministic and that is load-bearing, not stylistic.**
`PACK_NARRATIVE_PROGRAM.md:606-610`: *"All eight are deterministic: they render from dossier fields
and make no model call. That is not a style preference, it is what makes them BACKFILLABLE onto the
145 bundles already in `publish/bundles/`. A renderer that called a model would produce a different
document every time it ran, so a pack bought last month and the same pack rebuilt today would
disagree."*

**The trap every new renderer hits.** Two shapes reach these modules: a live `Dossier`, and the
`SimpleNamespace` tree that `pack_manifest.dossier_from_dict` builds from stored JSON
(`pack_manifest._ns`, `pack_manifest.py:356`). `_ns` builds attributes **from dict KEYS ONLY**, and
its verdicts are plain strings, not enum members. `PACK_NARRATIVE_PROGRAM.md:612-616`: read every
field with `getattr` and a default, or the backfill path raises on a pack the generator handled fine.

### 1.3 What lands on disk

Measured:

```
listings (store/listings/*.json)   119
bundles (publish/bundles/*)        189
lint receipts (*.lint.json)        123
runs (store/runs/*)                 17
pending signals                      3
live catalogue rows                 74
```

A listing receipt is thin, and knowing that saves an hour:

```json
{"candidate_id": "08b22037fc2afc07",
 "title": "PanelPack — the fixed-fee pack that gets your relative's care package restored…",
 "market": "uk", "verified_at": "2026-08-06T07:21:05.061086+00:00",
 "published_via": "EngineBridge", "catalog": true}
```

**There is no price in it.** All 119 parse and all 119 return `price_pence: None`, because the key
does not exist. Price lives in the Store's SQLite catalogue and in Stripe. See
[`finance.md`](./finance.md) §7.4.

Written by `publish/publish.py:85` `_write_listing`. The publish entry point is `publish.py:21`
`publish()`, dry-run gate at `:58`, the PASS gate at `:82`:

```python
success = bridge.publish_pass(dossier)
```

**189 bundles against 119 listings and 74 live rows.** The three counts diverge by design — a bundle
is built, a listing is a receipt of publish, and a catalogue row is what is sellable today — but the
gap between 119 and 74 is 45 packs that were published and are not on the shelf. See §7.5.

### 1.4 The eleven checks

`prospector/models.py:68` `CHECKS: dict[str, str]` — the question each check asks:

| Check | Kind |
|---|---|
| `pain_reality` | universal hard gate |
| `value_durability` | universal hard gate |
| `incumbency` | universal hard gate |
| `payer_solvency` | universal hard gate |
| `distribution` | universal hard gate |
| `legality` | universal hard gate |
| `buyer_intent` | lane-specific (hard for `side_hustle`) |
| `route_to_market` | lane-specific |
| `currency` | lane-specific |
| `claims_verifiable` | lane-specific |
| `price_comparables` | **evidence-only, can never kill** (`models.py:107`) |

The project CLAUDE.md calls the first six "the filter is universal": the same six checks apply to any
business, any sector, any scale, by the same bar.

---

## 2. How it actually works

### 2.1 Path A — a signal becomes a pack on the shelf

| # | Hop | Where |
|---:|---|---|
| 1 | A tick starts; the guard rules on spend, PAUSE and the clock | `prospector/scheduler/guard.py:346` `evaluate()` |
| 2 | Generation preflight: is EVERY verdict brain dead? | `scheduler/run_scheduled.py:465` `_moat_blind_reason` |
| 3 | Rate gate: one bounded live search; suppress only while retrieval is actually degraded | `config.yaml:2369` `gate_generation_on_grounding: true` |
| 4 | Candidates generated per lane on the non-critical chain | `run.py:320` `_noncritical_order(cfg)`, consumed `:679`; quotas `config.yaml:610-614` |
| 5 | Near-duplicates dropped against the catalogue | `prospector/dedup.py`; threshold `config.yaml:2005` `dedup_threshold: 0.85` |
| 6 | Prescreen — fast, cheap triage that preserves novelty | `prospector/prescreen.py` |
| 7 | **The moat**: query gen → fetch → verdict, per check, kill-fast | `prospector/verify.py` |
| 8 | A failed verdict call DEFERS; it never contributes `unverifiable` | `verify.py:365` (`retrieval_failed=True`) → gate `verify.py:693` |
| 9 | A brain outside `moat_primary()` is stamped `provisional` | `operator.py:1509` `is_provisional_provider` |
| 10 | Deterministic hard gates: KILL or PASS | `prospector/kill_filter.py` |
| 11 | Survivors scored on six axes; composite = Σ(score × weight) | `prospector/score.py` |
| 12 | Dossier composed and rendered | `prospector/dossier.py:738` `render_markdown()` |
| 13 | **PASS only** → publish | `publish/publish.py:82` |
| 14 | Content gates, bundle build, lint, price, Stripe, R2, catalogue row | `bridge.py:683` `publish_pass` |

**Hop 13 is where most of the product goes missing and it is deliberate.**
`prospector/bridge.py` builds artefacts only for PASSes; a KILL gets a dossier and nothing else. That
is the CLAUDE.md rule *"A KILL with a cited reason is first-class"* meeting the rule *"Publish only on
PASS"*. At a 3.69% PASS rate it means 96% of everything the engine reasons about produces a dossier
nobody reads.

**Hop 9's asymmetry is the one people get wrong.** Generation may run into a provisional tail; the
**drain may not**. `run.py::_cmd_resume` runs the classifier at `trusted_only=True`, because re-vetting
a `provisional` row on a provisional brain re-stamps it `provisional` — the row does not move and the
money is spent. Project CLAUDE.md records the measurement: provisional −14 / defer +13 over 30
minutes, net −1.

**The bundle assembly, in order** (`bridge.py:1678` `_create_bundle`):

1. The four model-written artifacts are generated.
2. The prose pass runs on every engine-authored document.
3. The deterministic sections are rendered and appended.
4. The bear case ABSORBS the financial model's weaknesses into `04_Financial_Model.md`.
5. `sections_out` is filled with buyer-visible title → markdown, drawn from `BUNDLE_READING_ORDER`.
6. `publish_pass` passes it to `lint_pack` as `pack_sections`.

Step 5 exists because of a real defect. `PACK_NARRATIVE_PROGRAM.md:647-651`: **the pack linter was
grading 9 of 14 sections** — `lint_pack` was handed `artifacts`, the four model-written documents.
Anything that stubs `_create_bundle` in a test must now accept that keyword.

Step 2's placement caused a defect of its own, twice. `PACK_NARRATIVE_PROGRAM.md:640-645`: the prose
pass **DELETES any line ending in `…`**. `pack_floors` and `pack_field` both truncated to a character
budget and closed on an ellipsis, so the line was rendered and then silently removed. In `pack_field`
that left *"a citation with a link and no passage under it, on a source-or-die storefront."* The
pattern to copy is `pack_field._CUT_NOTE` — mark the cut, then close the sentence.

### 2.2 Path B — the buyer's journey, hop by hop

| # | Hop | Where |
|---:|---|---|
| 1 | Storefront loads catalogue and stats together | `store_platform/src/Store.Web/src/pages/index.tsx:2316` |
| 2 | API serves the catalogue | `Store.Api/Program.cs:258` `app.MapGet("/catalog", …)` |
| 3 | DTO projected — Id, Title, OneLine, Price, PricePence, PaymentProvider, ProviderPriceId, FinancialSnapshot | `Program.cs:283-326` |
| 4 | A row renders | `Store.Web/src/components/discovery/PackRow.tsx:45` |
| 5 | Product page fetches detail | `Store.Web/src/pages/pack/[id].tsx:1728` → `Program.cs:332` |
| 6 | Checkout opens a session | `Store.Api/Endpoints/CheckoutEndpoints.cs:147` `OpenSessionAsync` |
| 7 | **Sellability fence** — unlisted packs cannot be bought | `CheckoutEndpoints.cs:320` `.Where(p => ids.Contains(p.Id) && p.IsListed)` |
| 8 | Stripe session created | `Store.Api/Payments/StripeProvider.cs:317` |
| 9 | Line item uses the pack's own `ProviderPriceId` | `StripeProvider.cs:408` |
| 10 | Webhook arrives | `Store.Api/Endpoints/WebhookEndpoints.cs:13` |
| 11 | Signature verified | `WebhookEndpoints.cs:34` |
| 12 | Fulfilment | `WebhookEndpoints.cs:56` |
| 13 | **Fulfilment fence** — paid amount vs the pack's currency floor | `Store.Api/Services/FulfilmentService.cs:133`, comparison `:141` |
| 14 | Presigned download, 5-minute TTL | `Store.Api/Endpoints/DeliveryEndpoints.cs:19`, `:258` |

`FulfilmentService.cs:141`:

```csharp
return item.AmountPence < floor ? $"{item.ProductId} (paid {item.AmountPence} < floor {floor} {currency})" : null;
```

Rate limiting sits across the whole path: `Store.Api/Program.cs:228` `app.UseRateLimiter()`,
`Infrastructure/RateLimitPolicy.cs:48` `DefaultPermitPerMinute = 120`, `:51`
`DefaultWaitlistPermitPerMinute = 5`, fixed window with `QueueLimit = 0` at `:84-91`. Memory
`api-rate-limits-its-own-storefront.md` records the incident where the storefront's own server-side
render tripped it.

The price side of hops 6–13 is [`finance.md`](./finance.md) §3. The single invariant to carry across:
**one `PriceDecision` mints the Stripe Price and the catalogue row together** (`bridge.py:1284` →
`:1407` → `:2147`), so a buyer cannot be charged an amount the fence then rejects.

---

## 3. The funnel, measured

### 3.1 All-time decisions

```bash
python3 -c "
import json,glob,collections
c=collections.Counter()
for fp in glob.glob('store/dossiers/*.json'):
    try: d=json.load(open(fp))
    except: continue
    c[d.get('decision') or 'none'] += 1
print(c, sum(c.values()))"
```

| Decision | Count | Share |
|---|---:|---:|
| KILL | 2,698 | 92.11% |
| **PASS** | **108** | **3.69%** |
| no decision recorded | 123 | 4.20% |
| `provisional` on disk | **0** | 0.00% |
| **Total dossiers** | **2,929** | |

**Zero provisional rows on disk.** With `moat_primary: [minimax, claude_cli]`
(`config.yaml:81`) both configured brains are trusted, so nothing currently *can* be stamped
provisional. That is the promotion working as intended, and it also means the `provisional` → re-vet
machinery is untested by live traffic right now.

The 123 dossiers with no `decision` field are 4.2% of everything the engine has produced. **HYPOTHESIS:
these are the crashed-vet population** — memory `a-killed-vet-destroyed-the-candidate.md` records that
a SIGKILLed vet wrote no dossier and no index entry. Check: print `created_at` and the key set for a
sample of them and compare against `store/runs/`.

### 3.2 Where the kills happen

```bash
python3 -c "
import json,glob,collections
c=collections.Counter()
for fp in glob.glob('store/dossiers/*.json'):
    try: d=json.load(open(fp))
    except: continue
    if d.get('decision')=='KILL': c[d.get('gate_fired') or '<none>'] += 1
for k,v in c.most_common(): print(f'{v:6d}  {k}')"
```

| `gate_fired` | KILLs | Share of KILLs |
|---|---:|---:|
| `moat_ungrounded` | **1,042** | **38.6%** |
| `min_composite` | 744 | 27.6% |
| `source_or_die` | 256 | 9.5% |
| `incumbency` | 254 | 9.4% |
| `adversarial_decisive` | 140 | 5.2% |
| `value_durability` | 112 | 4.2% |
| `payer_solvency` | 59 | 2.2% |
| `legality` | 30 | 1.1% |
| `distribution` | 18 | 0.7% |
| `currency` | 14 | 0.5% |
| `route_to_market` | 13 | 0.5% |
| `pain_reality` | 9 | 0.3% |
| `buyer_intent` | 7 | 0.3% |

**Read the top three rows as one finding.** `moat_ungrounded` (1,042) + `source_or_die` (256) =
**1,298 KILLs, 48% of all kills, are about EVIDENCE, not about the idea.** The engine is mostly not
rejecting bad businesses; it is rejecting businesses it could not find sources for.

Memory `grounding-bottleneck-is-relevance-not-availability.md` names the cause: the passages come
back, they are just not relevant to the question asked. That makes this a **query-generation** problem
sitting in `prospector/prompts.py`'s `query_gen`, not a retrieval-provider problem.

The six universal hard gates — the actual filter — account for **482 kills, 17.9%**. Everything else
is machinery.

### 3.3 The 249 kills nobody judged

```bash
python3 -c "
import json,glob
n=0
for fp in glob.glob('store/dossiers/*.json'):
    try: d=json.load(open(fp))
    except: continue
    if d.get('decision')=='KILL' and 'Composite 0.0000' in (d.get('reason') or ''): n+=1
print(n)"
```

**249.** That is **9.2% of all KILLs**, killed on `min_composite` with a composite of exactly zero.

A zeroed composite is the signature of the fail-safe path, not of a reasoned score. Project CLAUDE.md
carries the archetype: `store/dossiers/2102bacc6dd75cf9.kill.json` is a KILL on `min_composite` whose
seven checks all read `unverifiable, conf 0.0, "Verdict call failed; fail-safe."` — a candidate killed
by our own outage, in a dossier that reads as fully reasoned.

The DEFER gate (`verify.py:365` → `:693`) was added on 2026-08-06 to stop exactly this. **249 is the
historical backlog it left behind**, and every one of those candidates is a real idea that was never
evaluated. HYPOTHESIS: most of the 249 predate 2026-08-06. Check: bucket their `created_at` by day and
look for the cliff.

### 3.4 Provider chain, in practice

Live roster (`config.yaml`):

| Role | Key | Line | Value |
|---|---|---:|---|
| Verdicts | `operator` | 58 | `[minimax, claude_cli]` |
| May rule finally | `moat_primary` | 81 | `[minimax, claude_cli]` |
| Generation / prescreen / score | `noncritical_operator` | 136 | `[minimax, minimax_m27]` |
| Pack prose | `artifact_operator` | 145 | `[claude_cli, minimax]` |
| Shelf copy | `marketing_operator` | 157 | `[minimax, claude_cli]` |

`claude_cli` is **barred** from the non-critical chain (founder, 2026-08-14: *"claude should never be
used for non-critical"*), enforced where the chain is BUILT — `_noncritical_order` strips it,
`_NONCRITICAL_FORBIDDEN` (`run.py:320`).

### 3.5 Market coverage

| `market` | Dossiers |
|---|---:|
| `uk` | **1,948** |
| `us-il` | 158 |
| *(blank)* | 143 |
| `us` | 142 |
| `us-ga` | 137 |
| `us-ca` | 98 |
| `us-oh` | 96 |
| `us-pa` | 56 |

**67% of everything ever vetted is UK.** US is split across a per-state taxonomy (`us-il`, `us-ga`,
`us-ca`, `us-oh`, `us-pa`) plus a bare `us`, which is six labels for one country. That has a direct
product consequence: `market_rung_offset` (`config.yaml:1908-1911`) declares `uk: 0` and `us: 1`, so
a pack tagged `us-il` matches neither key. See §7.3.

143 dossiers carry no market at all, and `pricing.py:300-320` says an unclassified pack ignores market
entirely — which is correct behaviour, and also 143 packs that never got the US uplift.

### 3.6 The shelf as it stands

```bash
curl -s https://api.mumchimp.com/catalog | python3 -c "..."
```

74 rows.

| Price | Rows | Mean `sourceCount` |
|---:|---:|---:|
| £19.99 | 2 | 19.5 |
| £29.99 | 17 | 36.4 |
| £49.99 | 30 | 31.1 |
| £79.99 | 16 | 39.8 |
| £99.99 | 9 | 36.6 |

`sourceCount` across the shelf: n=74, min 16, p20 26, **median 34**, p80 42, max 51, mean 34.5.

Every pack on the shelf cites at least 16 sources and the median cites 34. That is the product's real
differentiator and it is the number the price ladder is built on
([`finance.md`](./finance.md) §5.2).

---

## 4. Segmentation: the ambition lanes

### 4.1 What a lane is

`config.yaml:588`:

```yaml
active_lanes: [side_hustle, smb, growth, venture]
```

`config.yaml:587` `active_lane: ""` — the singular key pins a single lane and **overrides**
`active_lanes`; empty `active_lanes` means a single-default (venture) run.

Each lane declares its own hard gates, score-only checks and thresholds under `config.yaml:615`
`lanes:`. `venture` is first and is the current default: `confidence_floor: 0.4`,
`min_composite_to_pass: 2.5`, `min_supported_to_pass: 2`, with `value_durability`, `incumbency` and
`payer_solvency` as hard gates on `[refuted]`. `side_hustle` adds
`moat_critical_checks: [buyer_intent]` and its own `adversarial_directive`.

| Lane | Reads as | `lane_quota` | Line |
|---|---|---:|---:|
| `side_hustle` | solo operator | **3** — the smallest | `config.yaml:611` |
| `smb` | small team | **5** — the largest | `:612` |
| `growth` | startup | 4 | `:613` |
| `venture` | unicorn ambition | 3 | `:614` |

Quotas are **weights, not counts**, whenever a total is passed — and the daemon always passes one
(`run_scheduled.py:932` calls `run_signal(..., k=batch_size, ...)`). `run.py::_lane_counts` returns the
block verbatim only when `k is None`; with a `k` it scales by `k * quota[t] / sum(quota)`. At
`batch_size: 50` (`config.yaml:2353`) the 3/5/4/3 ratio scales to **side_hustle 10, smb 17, growth 13,
venture 10**.

`config.yaml:605-608` flags the side effect honestly: proportional scaling carried venture from 3 to
10 despite the "do not over-buy" reasoning, because scaling has no opinion about a lane's PASS rate.
**To hold a lane down, change the WEIGHT, not `batch_size`.**

### 4.2 The quotas are weighted on evidence that has since been refuted

`config.yaml:589-591` states the basis verbatim:

> Weights are EVIDENCE-LED, from historical per-lane PASS rate across the 221 tier-tagged dossiers —
> NOT a guess at which tier sounds most ambitious:
> `smb 6/51 = 11.8%   growth 2/41 = 4.9%   side_hustle 4/94 = 4.3%   venture 0/35 = 0.0%`

Measured today across all 2,929 dossiers:

```bash
python3 -c "
import json,glob,collections
tot=collections.Counter(); ps=collections.Counter()
for fp in glob.glob('store/dossiers/*.json'):
    try: d=json.load(open(fp))
    except: continue
    t=d.get('ambition_tier') or '<untagged>'
    tot[t]+=1
    if d.get('decision')=='PASS': ps[t]+=1
for t,n in tot.most_common(): print(f'{t:12s} {ps[t]:3d}/{n:5d} = {100*ps[t]/n:5.1f}%')"
```

| Lane | PASS / vetted | Rate | Quota funded | Rank then | Rank now |
|---|---:|---:|---:|---|---|
| `side_hustle` | **35 / 425** | **8.2%** | **3 (smallest)** | 3rd | **1st** |
| `venture` | 13 / 329 | 4.0% | 3 | 4th (0.0%) | 2nd |
| `growth` | 15 / 434 | 3.5% | 4 | 2nd | 3rd |
| `smb` | **19 / 595** | **3.2%** | **5 (largest)** | **1st** | **4th** |
| *(untagged)* | 26 / 1,146 | 2.3% | — | — | — |

**The ranking has completely inverted.** The lane funded most is now the worst converter. The lane
funded least is now the best, at 2.6x the smb rate.

Two of the config's own predictions are also dead:

- `config.yaml:614` says venture has *"0 PASS in 35, do not over-buy."* Venture has **13 PASSes in
  329**, and `config.yaml:596` says *"Revisit when venture records its first PASS."* **It has.**
- The sample the weights rest on has grown from 221 tier-tagged dossiers to **1,783**, an 8x increase.

**Cost of leaving it.** At `batch_size: 50`, side_hustle gets 10 slots and smb 17. Moving to the
measured rates would produce roughly 0.8 more PASSes per tick from the same spend. At
[`finance.md`](./finance.md) §7.2's $46.10 per sellable pack, that is the cheapest yield improvement
available anywhere in this document, and it is a four-line config edit.

**Do not make it blind.** `config.yaml:597-599` warns that these are WEIGHTS, and dropping smb to zero
would stop measuring it. The right move is to re-rank, not to defund.

---

## 5. Which switches are deliberately OFF, and why

The repo's pattern is **baseline first**: a check RUNS and writes its receipt long before an actuator
turns on against numbers measured across live packs. `PACK_NARRATIVE_PROGRAM.md:661` states it
explicitly.

| Switch | Line | State | Why |
|---|---|---|---|
| `listing.lint_repetition_block` | `PACK_NARRATIVE_PROGRAM.md:661` | **off** | Grades STYLE. `repetition_findings` accrues in `<id>.lint.json`; the actuator waits for live-pack baselines. |
| `pack_linter.readability_grades` | `PACK_NARRATIVE_PROGRAM.md:662`, `:665-670` | recorded, **no actuator at all** | The grade measures WHO WROTE a section, not quality. See below. |
| `listing.claim_check_block` | `PACK_NARRATIVE_PROGRAM.md:663` | **ON** | Grades TRUTH. "No unsourced numbers ship, ever" has no exception for the document the buyer pays for. |
| `listing.require_figure_verification` | `config.yaml:1513` | **false** | See §7.4 — turning it on delists ~30% of the shelf. |
| `comparables.rung_adjust_enabled` | `config.yaml:1927` | **false** | Retrieving pricing evidence and acting on it are two decisions. |
| `generation.critique_revise.enabled` | `config.yaml:1256` | **false** | — |
| `prescreen_prefilter.shadow_mode` | `config.yaml:2026` | **true (shadow)** | The embedding prefilter runs and writes its verdict; it does not drop anything. |
| `numeric_citation` | `config.yaml:2065` enabled, `:2066` `shadow_mode: true` | **shadow** | Same pattern. |
| `coverage_sampler.enabled` | `config.yaml:2078` | **false** | — |
| `meta_shape_monitor.enabled` | `config.yaml:2111` | **false** | — |
| `schedule.backlog_cap` | `config.yaml:2354` | **0 = off** | Superseded by the rate gate (`:2369`). A stock brake has unbounded memory: one outage suppresses generation indefinitely. |
| `spend.daily_subscription_cap_usd` | `config.yaml:2528` | **0 = off** | Freezes the backlog. See [`finance.md`](./finance.md) §1.1. |

Switches that are ON and worth knowing:

| Switch | Line | State |
|---|---|---|
| `generation.denylist.enabled` | `config.yaml:1194` | true |
| `generation.incumbent_seed.enabled` | `config.yaml:1205` | true |
| `generation.verbalized_sampling.enabled` | `config.yaml:1219` | true |
| `claim_lock.enabled` | `config.yaml:2125` | true |
| `pack_data.enabled` | `config.yaml:2169` | true |
| `comparables.enabled` | `config.yaml:1922` | true |
| `schedule.gate_generation_on_grounding` | `config.yaml:2369` | true |
| `schedule.revet_provisional_kills` | `config.yaml:2368` | true |

**Readability deserves its own paragraph because it is a real product finding, not a deferred
feature.** `PACK_NARRATIVE_PROGRAM.md:665-670`, measured on pack `e698149e137fc164`: the fourteen
sections spread from **grade 5.9 to 17.3** — deterministic sections at 5.9–7.3, model-written ones at
12.6–13.8, and *"the worst was 'Copy you can paste' at 17.3, the section whose entire job is to hand
the buyer sentences for a landing page."*

The section a buyer is meant to copy verbatim onto a landing page is the hardest section in the pack
to read. That is a writing brief, not a threshold — a grade ceiling would block a pack for quoting a
statute. It belongs to [`content-management.md`](./content-management.md).

---

## 6. The numbers, assembled

| Metric | Value | Command / source |
|---|---:|---|
| Dossiers all time | 2,929 | §3.1 |
| PASS all time | 108 (3.69%) | §3.1 |
| PASS in the last 14 days | 75 / 1,823 (**4.11%**) | [`finance.md`](./finance.md) §7.2 |
| KILLs from evidence failure | 1,298 (48% of kills) | §3.2 |
| KILLs from the six universal gates | 482 (17.9%) | §3.2 |
| KILLs on a zeroed fail-safe composite | 249 (9.2%) | §3.3 |
| Bundles built | 189 | §1.3 |
| Listings published | 119 | §1.3 |
| Lint receipts | 123 | §1.3 |
| Live catalogue rows | 74 | §3.6 |
| Median sources per live pack | 34 | §3.6 |
| Mean shelf price | £57.15 | [`finance.md`](./finance.md) §5.6 |
| Sections per pack | 14 | §1.1 |
| Sections rendered without a model | 8 | §1.2 |
| Best lane PASS rate | side_hustle 8.2% | §4.2 |
| Worst funded-most lane | smb 3.2% on the largest quota | §4.2 |

**The PASS rate is rising**: 3.69% all time against 4.11% over the last fourteen days.

---

## 7. Five product weaknesses, with evidence

### 7.1 Half of all rejections are about our retrieval, not about the idea

**Evidence.** `moat_ungrounded` 1,042 + `source_or_die` 256 = **1,298 KILLs, 48.1% of 2,698**
(§3.2). The six universal gates that constitute the actual filter account for 482, **17.9%**.

**Why it matters.** The product promise is "we killed it for a cited reason." For half the kill log the
cited reason is that we could not find sources. That is a receipt about our search, wearing the
clothes of a business judgement.

**Where it lives.** Memory `grounding-bottleneck-is-relevance-not-availability.md`: the passages come
back and are not relevant to the question asked. That points at `query_gen` in
`prospector/prompts.py`, not at the retrieval chain `[ddg, exa, claude_cli]`.

**Cost to move it.** A query-generation change is a golden-set run away from being measurable. At the
current PASS rate, converting even a fifth of the 1,298 into real evaluations is worth more than any
other single change here.

### 7.2 Two hundred and forty-nine ideas were killed by our own outages

**Evidence.** 249 KILLs carry `Composite 0.0000` (§3.3). The archetype is
`store/dossiers/2102bacc6dd75cf9.kill.json`: seven checks all reading
`unverifiable, conf 0.0, "Verdict call failed; fail-safe."`

**Why it matters.** Those dossiers are indistinguishable from reasoned kills without opening them. The
kill log is the product's proof that the filter is real; 9.2% of it is a proof of nothing.

**Already fixed forward.** `verify.py:365` returns `retrieval_failed=True` and `verify.py:693` fires
DEFER instead of contributing `unverifiable` to the gates.

**Cost to close the backlog.** These are re-vettable — `vet --resume` exists. HYPOTHESIS: at $46.10 per
sellable pack and a 4.11% PASS rate, re-vetting all 249 costs roughly $470 of model time and yields
about 10 packs at a list value of about £570. Check: confirm the 249 are still resumable by looking for
`reverify_due_at` on a sample.

### 7.3 The US market is six labels for one country, and the price ladder knows one of them

**Evidence.** §3.5: `us-il` 158, `us` 142, `us-ga` 137, `us-ca` 98, `us-oh` 96, `us-pa` 56.
`config.yaml:1908-1911` declares `market_rung_offset` for exactly two keys, `uk: 0` and `us: 1`.

**Why it matters.** A pack tagged `us-il` matches neither key. It is a US-market opportunity that never
receives the US rung uplift, and 545 dossiers carry a per-state US tag against 142 with the bare `us`.
The taxonomy the engine writes and the taxonomy the ladder reads are different taxonomies.

**Check before acting.** Read `pricing.py:328-330` for what the lookup actually does with an unmatched
key — the clamps mean this degrades quietly rather than raising. HYPOTHESIS: an unmatched market falls
through to offset 0. Confirm by reading the `market_rung_offset` lookup in `price_for`.

**Cost.** Either normalise `us-XX` → `us` at the point of tagging, or declare the states. Under an
hour, plus a decision about whether state-level is a facet worth keeping for discovery
([`growth-marketing.md`](./growth-marketing.md)).

### 7.4 Fifteen of fifty packs on sale carry a figure found in no retrieved passage

**Evidence.** `bridge.py:1475+` records it directly: *"15 of the 50 packs on sale carry a figure found
in no retrieved passage, so switching this on delists ~30% of the catalogue."* The switch is
`config.yaml:1513` `require_figure_verification: false`.

**Why it matters.** The whole product is "source-or-die." A 30% delist is the measured price of
enforcing it on the document the buyer pays for, and the switch is off because nobody has been willing
to pay that price.

**This is a real tension, not an oversight.** `PACK_NARRATIVE_PROGRAM.md:672-678` records the adjacent
defect that WAS fixed: `generate_artifacts` ran a claim-check on the paid prose whose violations
reached *"a `logger.info` and nothing else"*, while the FREE marketing copy on the same gate was
DROPPED when it failed. *"Same check, opposite consequence, and the one let through was the document
the buyer pays for."*

**Cost.** Two routes: fix the 15 packs (repair the figures against retrieved passages, then flip the
switch), or accept a smaller, provably-sourced catalogue. The first is the product answer and it is
per-pack work.

### 7.5 One hundred and nineteen published, seventy-four sellable

**Evidence.** §1.3: 189 bundles, 119 listings, 74 live catalogue rows.

**Why it matters.** 45 packs were built, gated, priced and published, and are not on the shelf. Each
represents the full $46.10 production cost with zero chance of revenue.

**The known causes, each with its fence.** `bridge.py:1466-1471` refuses to LIST a pack whose
`providerPriceId` starts `price_stub_` — the fence added after six packs shipped with a buy button
returning HTTP 500. `bridge.py:1451-1457` refuses to list a pack with no deliverable in R2. Memory
`republishing-stranded-passes-fails-on-link-rot.md` records a third cause: sources that have since
gone dead.

**HYPOTHESIS: most of the 45 are link rot, not stub prices.** Check:

```bash
.venv/bin/python ops/automations/stranded_packs.py
```

That script exists precisely for this population. Run it read-only first.

---

## 8. Failure modes

| # | Symptom | Root cause | Fix | Receipt |
|---:|---|---|---|---|
| 1 | The pack linter reports green on a pack with defective sections | `lint_pack` was handed `artifacts` — 4 of 14 sections | `_create_bundle` fills `sections_out` from `BUNDLE_READING_ORDER`; `publish_pass` passes `pack_sections` | `PACK_NARRATIVE_PROGRAM.md:647-651` |
| 2 | A citation renders with a link and no passage under it | The prose pass DELETES any line ending in `…`; two renderers truncated onto an ellipsis | Mark the cut, then close the sentence — `pack_field._CUT_NOTE` | `PACK_NARRATIVE_PROGRAM.md:640-645` |
| 3 | A repetition check described as live in four comments never ran | `check_repetition` had **zero callers** | Called from `lint_pack`; it takes its own corpus, because repetition exists only in the assembly | `PACK_NARRATIVE_PROGRAM.md:653-655` |
| 4 | A renderer works in the generator and raises on backfill | `pack_manifest._ns` builds attributes from dict KEYS ONLY; verdicts are strings, not enums | `getattr` with a default on every field | `pack_manifest.py:356`, `PACK_NARRATIVE_PROGRAM.md:612-616` |
| 5 | A candidate is killed with seven `unverifiable` checks and a fully-reasoned-looking dossier | A raising verdict call counted as evidence | `retrieval_failed=True` → DEFER | `verify.py:365`, `:693`; 249 historical rows |
| 6 | A SIGKILLed vet destroys the candidate | No dossier and no index entry written | — | memory `a-killed-vet-destroyed-the-candidate.md`; 123 no-decision dossiers |
| 7 | Six packs listed with a live buy button returning HTTP 500 | `store_payments.active_provider` unset → default rail → `price_stub_*` ids | Refuse to LIST a stub id | `bridge.py:1466-1471`, `config.yaml:2001` |
| 8 | A republished pack re-points at a fresh Stripe object | `publish_pass` minted unconditionally | `_resolve_money_rail` reuses the live rail | `bridge.py:1560-1576` |
| 9 | Republishing stranded passes fails | Source link rot since first publish | `ops/automations/stranded_packs.py` | memory `republishing-stranded-passes-fails-on-link-rot.md` |
| 10 | Published one-liners truncate mid-word on the shelf | — | — | memory `published-onelines-truncated-mid-word.md`, 34/63 affected |
| 11 | A source card renders blank | It is a suppressed duplicate quote | — | memory `an-empty-source-card-is-a-suppressed-duplicate-quote.md` |
| 12 | The storefront rate-limits its own server-side render | Shared limiter, 120/min | `RateLimitPolicy.cs:48` | memory `api-rate-limits-its-own-storefront.md` |
| 13 | A UI guard test passes vacuously | Progressive disclosure hides the element the guard asserts on | — | memory `progressive-disclosure-makes-a-guard-test-vacuous.md` |
| 14 | Lane quotas produce unexpected counts | Quotas are WEIGHTS whenever `k` is passed, and the daemon always passes one | Change the weight, not `batch_size` | `config.yaml:597-608`, `run_scheduled.py:932` |
| 15 | The daemon generates nothing all afternoon | A stock brake with unbounded memory; a six-week-old outage still suppressing | Gate on the RATE (`config.yaml:2369`); cap stays 0 | project CLAUDE.md, memory `gate-on-the-rate-not-the-stock.md` |
| 16 | Ideas clear every gate and then score too low to publish | `min_composite_to_pass` per lane | — | memory `ideas-clear-the-gates-then-score-too-low.md`; 744 `min_composite` kills |

---

## 9. Invariants

| # | Invariant | Enforced at | Consequence if broken |
|---|---|---|---|
| P1 | **Nothing is killed at generation time.** Creativity lives in generation; constraint lives in verification. | `prospector/generate.py` has no gates; all gating is downstream | Novelty dies before it is measured. |
| P2 | **Publish only on PASS.** A KILL blocks publication entirely. | `publish/publish.py:82` | An unvetted idea reaches a paying buyer. |
| P3 | **A KILL renders a dossier.** The kill log is the receipt that the filter is real. | `prospector/dossier.py` runs on both outcomes | The filter becomes an assertion. |
| P4 | **The eight deterministic renderers make no model call.** | `pack_offer`, `pack_field`, `pack_bear_case`, `pack_toolkit`, `pack_kicker`, `pack_floors`, `pack_checklist`, `pack_reference` | A pack bought last month and the same pack rebuilt today disagree; the backfill reaches nobody. `PACK_NARRATIVE_PROGRAM.md:606-610`. |
| P5 | **The reading order is fixed and shared.** `BUNDLE_READING_ORDER` drives the bundle, the HTML, the PDF and what the linter grades. | `bridge.py:378`, `:414`, `:1971` | The linter grades a different document from the one the buyer reads. |
| P6 | **What is graded is literally what `pack_html` renders.** | `bridge.py:1971`, `sections_out` keyed by buyer-visible title | Failure mode 1 returns. |
| P7 | **`price_comparables` can never kill.** | `kill_filter.is_hard_fail` and verify's run order, structurally | An absent price page kills a good idea. |
| P8 | **An exception is never evidence; a failed call DEFERS.** | `verify.py:365`, `:693` | Failure mode 5 returns. |
| P9 | **Only `moat_primary()` may rule finally.** | `operator.py:1509` | An untrusted brain publishes on PASS. |
| P10 | **The drain stays trusted-only; generation need not be.** | `run.py::_cmd_resume` at `trusted_only=True` vs `run_scheduled.py:465` at `trusted_only=False` | Re-vetting on a provisional brain re-stamps the row and spends the money for nothing. |
| P11 | **Two loops never merge.** Sales metrics tune what to offer; truth metrics veto what may ship. | Architectural | Demand overrides truth and the catalogue stops being a filter. |
| P12 | **A pack with a stub price id or no R2 object must not be LISTED.** | `bridge.py:1466-1471`, `:1451-1457` | Failure mode 7. |
| P13 | **Golden-set regression gates all changes.** | Part 13B acceptance tests | A discrimination regression ships unmeasured. |

---

## 10. How to change it safely

### 10.1 Adding or changing a pack section

1. Read [`../PACK_NARRATIVE_PROGRAM.md`](../PACK_NARRATIVE_PROGRAM.md) first — the diagnosis is the
   top half, the implementation ledger the bottom half. Append there.
2. Write the renderer **model-free** (P4) or it cannot be backfilled.
3. Read every dossier field with `getattr(obj, "field", default)` — the backfill passes a
   `SimpleNamespace` whose attributes come from dict keys only (`pack_manifest.py:356`).
4. If you truncate, do **not** end the line on `…` — the prose pass deletes it. Copy
   `pack_field._CUT_NOTE`.
5. Add the filename to `BUNDLE_READING_ORDER` (`bridge.py:378`) **and** a title to `_SECTION_TITLES`
   (`bridge.py:414`). Both, or the section renders untitled.
6. Mirror the same five modules in the same order in `tools/backfill_bundle_html.py:335-390`.

**The test that catches a mistake:**
`tests/unit/test_backfill_renders_the_new_sections.py::test_the_backfilled_reader_is_the_generated_reader_byte_for_byte`.
Two whole-archive differences are deliberate and outside the sections:
`patched_md`'s legacy `Evidence goes stale after:` rewrite is backfill-only, and `manifest.jsonld`
digests differ because they are digests OF these bytes (`PACK_NARRATIVE_PROGRAM.md:620-626`).

Anything that stubs `_create_bundle` must accept the `sections_out` keyword.

Also check `pack_floors.QA_SECTION` and `pack_floors.CHECKLIST_SECTION` — they duplicate two
`_SECTION_TITLES` strings to avoid an import cycle on the money rail, and are pinned to that dict by
`tests/unit/test_pack_floors.py`. Change one and that test fails, which is the point
(`bridge.py:409-412`).

### 10.2 Putting a pack change onto the live shelf

`scripts/backfill_packs_parallel.sh --apply`.

`PACK_NARRATIVE_PROGRAM.md:628-630` is explicit: *"That is an operator action — it repoints bundles
buyers can already download — and it is deliberately not something the engine or an agent does on its
own."*

### 10.3 Changing lane weights

1. Re-run the measurement in §4.2. Do not trust §4.2 — it will be stale.
2. Edit `config.yaml:610-614`. **Weights, not counts.**
3. Do not set any lane to 0 (`config.yaml:597-599`): a defunded lane stops being measured, and the
   whole basis of this block is measurement.
4. Update the comment at `config.yaml:589-591` with the new numbers and their date. Leaving refuted
   numbers in a comment is how §4.2 happened.
5. Restart the daemon — config is read at process start.

### 10.4 Turning on a shadow-mode check

The pattern, from `PACK_NARRATIVE_PROGRAM.md:661`: the check RUNS, its findings accrue in the receipt,
and the actuator turns on **against numbers measured across live packs**, not the one pack that
motivated it.

So: run it in shadow, read the receipts on disk (`store/dossiers/*.lint.json`, 123 of them), pick the
threshold from that distribution, then flip the switch. Memory
`the-answer-was-already-on-disk-as-a-receipt.md` is the standing reminder that this data already
exists.

### 10.5 The gate

There is **no pre-commit hook installed in this checkout** as of 2026-08-17. Verify, never assume:

```bash
git config --get core.hooksPath
ls -la "$(git rev-parse --git-path hooks)"/pre-commit
.venv/bin/python scripts/popdd_verify.py --staged
```

`tests/unit/` carries the pack-specific guards. UI tests are advisory while the UI is moving (memory
`ui-tests-are-advisory-while-ui-is-moving.md`).

---

## 11. Open gaps and debt

| # | Gap | Evidence | Cost to close |
|---|---|---|---|
| D1 | **Lane quotas fund the worst converter most.** side_hustle 8.2% on quota 3; smb 3.2% on quota 5. | §4.2 | **Four lines of config.** The highest-yield-per-effort item in this document. |
| D2 | **48% of kills are evidence failures, not judgements.** | §3.2 | Query-generation work in `prompts.py`, measured on the golden set. Days, not hours, and worth it. |
| D3 | **249 kills are our own outages.** Re-vettable. | §3.3 | ~$470 of model time; HYPOTHESIS ~10 packs. Verify resumability first. |
| D4 | **45 published packs are not sellable.** | §1.3, §7.5 | Run `ops/automations/stranded_packs.py` read-only. An afternoon. |
| D5 | **`require_figure_verification` is off; 15 of 50 packs would delist.** | `config.yaml:1513`, `bridge.py:1475+` | Per-pack repair work. This is the source-or-die promise. |
| D6 | **US is six market labels; the price ladder declares one.** | §3.5, §7.3 | Under an hour once the tagging decision is made. |
| D7 | **"Copy you can paste" reads at grade 17.3** — the hardest section in the pack is the one meant to be pasted. | `PACK_NARRATIVE_PROGRAM.md:665-670` | A writing brief. [`content-management.md`](./content-management.md). |
| D8 | **123 dossiers carry no decision** (4.2%). | §3.1 | Diagnosis first. HYPOTHESIS: crashed vets. |
| D9 | **Zero provisional rows on disk**, so the provisional → re-vet machinery has no live traffic exercising it. | §3.1 | Tests only. Low priority while the roster is all-trusted, a trap the day it is not. |
| D10 | **`readability_grades` has no actuator by design**, so nothing improves it automatically. | `PACK_NARRATIVE_PROGRAM.md:662` | Deliberate. Revisit only with a per-section, per-author baseline. |
| D11 | **No sales figures anywhere.** Every product decision here is made on production data with no demand data beside it. | [`finance.md`](./finance.md) §7.4 | 30 minutes: `stripe balance_transactions list`, then append to `docs/DELIVERY_LEDGER.md`. **This is the single most valuable missing number in the estate.** |

D11 deserves the last word. Project CLAUDE.md says *"Two loops never merge: sales metrics tune what to
offer; truth metrics veto what may ship."* The truth loop is instrumented to four decimal places.
**The demand loop has no instrument at all.** Every priority in §7 is ranked by production cost and
funnel yield, because that is the only evidence that exists.

---

## 12. Where to look next

```bash
# Is the estate actually running what you think it is
.venv/bin/python scripts/live_checkout.py
bash ~/.claude/projects/-Users-chidionyema-Documents-code-prospector/.state-probe

# The funnel, right now
python3 -c "import json,glob,collections; c=collections.Counter(json.load(open(f)).get('decision','none') for f in glob.glob('store/dossiers/*.json')); print(c)"

# The shelf, right now
curl -s https://api.mumchimp.com/catalog | python3 -m json.tool | head -60

# Packs that published but are not sellable
.venv/bin/python ops/automations/stranded_packs.py

# What the linter thinks of a pack
ls store/dossiers/*.lint.json | head; python3 -m json.tool store/dossiers/<id>.lint.json | head -60

# Run one candidate end to end
.venv/bin/python -m prospector.run vet --help
```

| Question | Path |
|---|---|
| What the buyer reads, in order | `prospector/bridge.py:378`, `:414` |
| Why that order | `docs/PACK_NARRATIVE_PROGRAM.md:473-513`, `:590-604` |
| How a section is built | `prospector/pack_*.py` — 16 modules, §1.2 |
| How a pack is graded | `prospector/pack_linter.py`, receipts at `store/dossiers/*.lint.json` |
| How a pack is assembled and shipped | `prospector/bridge.py:683` `publish_pass`, `:1678` `_create_bundle` |
| What every check asks | `prospector/models.py:68` |
| How the checks are run | `prospector/verify.py` |
| The hard gates | `prospector/kill_filter.py` |
| How survivors are ranked | `prospector/score.py` |
| Lanes and their bars | `config.yaml:587-720` |
| Every switch | `config.yaml` — §5 lists the ones that matter |
| The eight-step run procedure | `RUN.md` |
| The buyer's side of the counter | `store_platform/src/Store.Web/`, `store_platform/src/Store.Api/` |
| Price, cost, margin | [`finance.md`](./finance.md) |
| Whether a number can be trusted | [`analyst.md`](./analyst.md) |
| The whole estate | [`../ESTATE_MAP.md`](../ESTATE_MAP.md) |

---

*Every number in this document was measured on 2026-08-18. If a figure here disagrees with a command
you just ran, the command is right — fix this file.*
