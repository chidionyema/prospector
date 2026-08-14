# Retrieval Programme — why the engine stopped yielding, and the map out

> Tracked programme. Append measurements here, never to `CLAUDE.md`. Every number below is
> re-derivable from `store/prospector.db` and `store/dossiers/*.json` with **no model calls**.
> Opened 2026-08-14 after the founder's ruling that patching the retrieval chain was
> "firefighting" and that the problem is multi-dimensional.

## 0. The number that matters

**Vets per shipped pack.** Not pass rate, not coverage, not relevance — the cost in vets of
putting one sellable pack on the shelf.

| window | vets | passes | **vets per pass** | checks ruled `unverifiable` | `retrieval_failed` |
|---|---:|---:|---:|---:|---:|
| 28 Jul – 5 Aug | 340 | 46 | **7.4** | 54.6% | 0 |
| 8 – 14 Aug | 586 | 11 | **53.3** | 68.6% | 0 |
| all time | 2,031 | 75 | 27.1 | 68.2% | — |

`retrieval_failed = 0` in both windows. **There was no outage.** Every retrieval call
succeeded and returned pages that did not answer the question. The collapse is a quality
failure, not an availability failure, and the two regimes differ in exactly one variable:
the share of checks the evidence could not settle.

## 1. The yield equation

```
packs_shipped  =  candidates_generated
                × P(survive prescreen)
                × P(survive vet)          ← collapsed 13.5% → 1.9%
                × P(publishable)          ← 13 PASSes stranded off the shelf
```

`P(survive vet)` decomposes further, and this is where the multi-dimensionality lives:

```
P(survive vet)  =  P(the claim is settleable at all)
                 × P(we asked the right question)
                 × P(we asked the right source)
                 × P(the source returned the passage that settles it)
                 × P(the adjudicator read it correctly)
                 × P(the gate layer agrees)
```

Every fix of the last fortnight — page fetch, anchored windowing, relevance ranking, the
`min_relevance` floor — moved the **fourth** term. The measurements below show the first
three terms are where the mass is.

## 2. The dimensions

### D1 — Candidate formation: the lottery
The engine invents a candidate from a signal, then pays six gates to discover whether the web
has anything to say about it. Evidence is sought *after* the idea exists, so a candidate about
which the open web is silent costs a full vet to discover.

- **Receipt:** 322 of 575 kills in window B (56%) fired `moat_ungrounded` or `source_or_die` —
  gates that fire *after* the composite score has already cleared the bar
  (`prospector/dossier.py:190-207`). The idea scored well enough. It died for want of evidence.
- Genuine refuted hard fails — the idea actually failing — are 126 of 575 (22%).
- **Fix class:** invert. Mine evidence first, form candidates from passages already in hand.
- **Cost:** large. New subsystem.

### D2 — Question formulation: we mostly do not write a research question
This is the defect with the worst effort-to-damage ratio, and it was invisible until the
citation audit.

- **Receipt:** `prospector/verify.py:193-215`. Query = `_keywords(cand, k=6)` — a six-noun bag
  scraped from the candidate title — plus a canned suffix per check:
  - `legality` → `{six nouns} regulation OR licence required OR banned OR illegal`
  - `pain_reality` → `{six nouns} not a real problem OR existing workaround`
  - `payer_solvency` → `{six nouns} budget cuts OR cannot afford OR insolvency`
- The module comment states the intent plainly: these templates **skip the LLM query-gen call**
  on the cheap decisive gates. So the gates that kill the most candidates are the ones that
  never get a thought-out question.
- A bag of nouns retrieves pages that *contain those nouns*. That is precisely how a research
  engine ends up citing dictionaries (§D3).
- **Fix class:** decompose each check into a settleable claim, then write a query in the idiom
  of the source that can settle it.
- **Cost:** medium. Prompt + routing work, no new infrastructure.

### D3 — Source selection: wrong index, and mostly the wrong *kind* of source
13,479 citations, 8–14 Aug:

| domain | citations |
|---|---:|
| en.wikipedia.org | 970 |
| gov.uk | 455 |
| **youtube.com** | 318 |
| **linkedin.com** | 262 |
| fca.org.uk | 128 |
| **merriam-webster.com** | 128 |
| legislation.gov.uk | 116 |
| ico.org.uk | 101 |
| **reddit.com** | 84 |
| **tiktok.com** | 72 |
| **facebook.com** | 66 |
| **worldatlas.com** | 48 |
| **dictionary.cambridge.org** | 42 |
| **simple.wikipedia.org** | 33 |

**Primary-source share of all citations: 8.9% (1,204 / 13,479).** Wikipedia alone (1,003) very
nearly outweighs every `.gov`, `.gov.uk`, `.edu`, `.ac.uk`, `sec.gov` and `europa.eu` citation
the engine holds. Two dictionaries account for 170 citations of evidence about whether business
problems are real.

Two separate causes:

1. **The chain is first-answer-wins with the weakest index first.** `make_provider` builds
   `FallbackSearchProvider` over `[ddg, exa, claude_cli]`, so DDG serves nearly everything and
   the better providers are dead weight. Paired live replay, 15 worst queries, identical stack,
   cache off: **ddg coverage 0.359 → exa 0.525, exa better on 12 of 15**, returning
   bills.parliament.uk / aisi.gov.uk / iapp.org where ddg returned Wikipedia, imdb.com and
   youtube.com. DDG also honours `site:` inconsistently — proven on a matched pair of sibling
   queries from `store/dossiers/9ca7b94beb49305e.kill.json`.
2. **The questions have registers, and we ask a search box instead.** Free, keyless,
   authoritative APIs exist for most of what the six checks ask.

### D4 — Retrieval mechanics: largely addressed, keep it
Ranking, page fetch, anchored windowing, and a coverage floor. Live A/B, cache off, floor
OFF → ON: worst-15 queries **0.332 → 0.553** (+0.222, better on 13 of 15); random-15
**0.427 → 0.593** (+0.166, better on 9 of 15). Coverage predicts the verdict — mean
`relevance_score`: supported 0.488 (n=61), refuted 0.447 (n=8), unverifiable 0.300 (n=202).

This dimension is in good shape and is **not** where the remaining mass is. Four files sit
uncommitted on `fix/storefront-header-logo-filter-jump`: `config.yaml`, `prospector/config.py`,
`prospector/retrieval.py`, `tests/unit/test_relevance_failover.py` (12 new tests; green).

### D5 — Adjudication: half of it already shipped; what is left is corroboration
**Correction, 2026-08-14 (measured, not recalled).** The original entry claimed the
adjudication layer has "no notion of source authority". That was wrong when written: the
authority floor is on disk and running — `prospector/admissibility.py` (`tier()` at :115,
`is_ruling_admissible()` at :172) plus the ruling-time demotion at
`prospector/verify.py:511-537`, under `admissibility.policy: P1_check_aware`
(`config.yaml:325`), with a second claim-level gate `health_claims_need_primary`
(`config.yaml:335`). A ruling is demoted to `unverifiable` when EVERY one of its citations
sits in a tier that cannot carry that check.

So D5 reduces to its **second** half, which does not exist anywhere: nothing requires a
`supported` verdict to rest on more than one **independent publisher**. Three pages from one
site count as three sources.

**Measured cost of the missing gate** — `tools/experiments/d5_corroboration.py`, offline,
zero model calls, over all 2,031 dossiers with checks. Independence is judged at the
*registrable* domain, so `assets.publishing.service.gov.uk` and `www.gov.uk` are one
publisher:

| independent publishers behind a `supported` ruling | rulings | share |
|---|---:|---:|
| 1 | 470 | **16.7%** |
| 2 | 499 | 17.7% |
| 3 | 785 | 27.9% |
| 4+ | 1,062 | 37.7% |

2,816 `supported` rulings carry ≥1 cited source; 348 (12.4%) rest on a single citation. The
sole publisher is `other`-tier in 313 of the 470 (`siterecon.ai`, `sparkreceipt.com`,
`thegrowthhackinglab.com`), `ugc_social` in 36 (`facebook.com` 23, `youtube.com` 4,
`reddit.com` 4) — and **`government` in 103** (`gov.uk` 56, `ca.gov` 9, `fca.org.uk` 5,
`nhs.uk` 5).

**Priced against shipped inventory.** The PASS boundary is decided by `grounded_support`
(`dossier.py:32`), not by the composite — a verdict demotion cannot move a score computed
from the candidate narrative — so the flip is exactly computable offline. Replaying all 75
PASS dossiers with the affected rulings demoted:

| policy | passes touched | **flip to KILL** |
|---|---:|---:|
| A blanket ≥2 publishers | 15/75 | **1** |
| B exempt a sole `government`/`academic` publisher | 8/75 | 1 |
| C also exempt `media`/`established_org` | 8/75 | 1 |

The single flip is the same under all three: `b94760e86e62585a.pass.json` ("Unpaid-hours
audits for NHS doctors and nurses", lane `growth`, moat `payer_solvency,distribution`) —
**currently on the shelf** (`store/listings/b94760e86e62585a.json`). Its `value_durability`
rests on `nhsleavecalculator.co.uk` cited twice plus two sibling calculator sites.

- **Fix class:** an independent-publisher floor at ruling time, tier-aware. **Recommend B**:
  requiring a blog to corroborate `legislation.gov.uk` makes the evidence worse, not better,
  and B spares 108 government/academic rulings at no extra flip cost.
- **Cost:** 1 of 75 all-time passes (1.3%), one of which is live inventory that would need
  delisting. Everything else it touches is already a KILL.
- **Status: SHIPPED 2026-08-14 (policy B), uncommitted.**
  `admissibility.corroboration_reason()` + `registrable()` / `publishers()`;
  called from `verify.py` in the same demotion chain as the other two gates, **SUPPORTED
  only** (a refutation from one source still kills — corroborating kills was never measured);
  `config.yaml admissibility.corroboration_min_domains: 2` /
  `corroboration_exempt_tiers: [government, academic]`, with `corroboration_min_domains: 1`
  as the off switch, so the change is reversible by config alone.
  `tests/unit/test_corroboration_floor.py` — 40 tests, green.
  `registrable()` collapses single-registrant state suffixes (`gov.uk`, `nhs.uk`, `gov.au`…)
  to the suffix itself but NOT `co.uk`/`ac.uk`, where `ox.ac.uk` and `cam.ac.uk` are two
  publishers. The measurement script imports that same function — a measurement that
  classifies domains differently from the code it prices is not a measurement of that code.
  Fixing it moved the headline from 434 (15.4%) to 470 (16.7%) and left the flip count at 1.
- **Still to do:** `b94760e86e62585a` is live on the shelf and would now fail a re-vet. It is
  not delisted by this change (the gate rules at verdict time, not over stored dossiers); the
  next `vet --resume` over it will demote it. Decide then whether to delist or re-ground.

### D6 — Decision layer: we pay full price for kills we have already decided
`verify.py:957` permits the soft early-exit only when `not remaining_hard` — no hard-gated
checks left in the run order. So once the lane's moat check returns `unverifiable`, PASS is
already impossible but the run continues.

| lane | kills | checks run | ran **after** the kill was certain |
|---|---:|---:|---:|
| smb | 123 | 502 | 251 (50%) |
| side_hustle | 57 | 236 | **179 (76%)** |
| growth | 56 | 238 | 63 (26%) |
| **total** | **236** | **976** | **493 (50.5%)** |

`side_hustle` is worst because its moat check (`buyer_intent`) is *first* in the run order.

This is a **cost** dimension, not a yield dimension: it halves the price of being wrong and
ships no extra packs. Trade-off if taken: a candidate that would have been killed on `legality`
with a cited refutation gets killed on `moat_ungrounded` instead — same decision, weaker
receipt. The DEFER guard at `verify.py:955` (never soft-exit when any check hit
`retrieval_failed`) must stay untouched.

Lane configuration is **correct** and was verified, not assumed: per-lane
`moat_critical_checks` at `config.yaml:499` (side_hustle → `buyer_intent`), `:565`
(smb → `payer_solvency`), `:616` (growth → `payer_solvency, distribution`). A hypothesis that
these lanes had a structurally unreachable PASS was formed and killed — all-time passes are
smb 9, side_hustle 18, growth 14. The 2026-06-28 lane-aware fix is intact.

### D7 — Publication: finished inventory nobody can buy
13 PASSes are off the shelf; 12 are blocked by **15 dead citation URLs**, e.g.
`https://www.libertyyachts.co.uk/?page_id=388 → HTTP 404`. The machinery to unblock them
already exists: `pack_linter.py:1077` downgrades a dead citation to a *warning* when a probed
Wayback memento stands in, and `archive.py::save_snapshot` fetches one. Independent of every
other dimension.

Note the diagnostic value of the dead list — `aol.com/news/2013-01-29-…`,
`blog.factorfunding.com`, `ukdebtteam.co.uk/blog/who-called-from-0333-…`. Link rot is
concentrated in exactly the low-authority sources D3 and D5 exist to exclude. Fixing D5 shrinks
D7 permanently.

### D8 — Observability: we cannot audit our own retrieval — **SHIPPED 2026-08-14, uncommitted**

`Source.retrieved_by` (`models.py`), stamped by `retrieval.ProviderStamped` which
`make_provider` wraps around **every** built provider — so attribution is a property of the
composition, and the next provider class added inherits it without touching its own code.
Reader shipped with it: `tools/citation_quality_by_provider.py` (read-only, `mode=ro`), which
reports citations, primary-source share, low-authority share and verdict mix **per provider**.
A field with no reader is write-only state, which this repo has paid for before.

Proof: 12 new tests in `tests/unit/test_source_provider_attribution.py`, all green; 430 passed
across the retrieval/grounding/source/dossier groups (one timing test failed at load average
99.5 and passes at 0.09–0.14s against its 0.5s budget when measured directly — not this
change, which touches `retrieval.py` only at the new class and `make_provider`).
End-to-end: `CheckResult.to_dict()["sources"][0]["retrieved_by"] == "exa"`.

**Stamps forward only.** Backfill is impossible — the provider behind an existing citation was
never recorded. The reader buckets those as `unattributed (written before 2026-08-14)`.

Original finding, for the record:
A stored source is `{source_id, url, text, published_at, query, fetched_at}`. **There is no
provider field.** Which engine supplied which citation is unrecorded, so "is DDG the problem"
cannot be answered from our own dossiers — every provider-level claim in this document had to
be re-derived by live replay instead of read off disk.

**This gates the measurement of D2, D3 and D5.** It is a one-line write and it lands first.

## 3. Dependency order

```
D8 (record provider on every source)
     │  unblocks measurement of ↓
     ├──► D5 (authority floor + independent-domain corroboration)   ← cheapest real win
     │
     ├──► D3 (route to registers; providers as a panel, not a chain)
     │        └── coupled to ──► D2 (write the query in that source's idiom)
     │
     └──► D1 (evidence-first candidate formation)   ← largest, gated on D2/D3 working

D4 — done, keep.        D6 — parallel, cost only.        D7 — parallel, independent.
```

D2 and D3 are one piece of work, not two: choosing the source and phrasing the query are the
same decision. Routing is per **check**, because the checks ask categorically different
questions:

| check | what can actually settle it |
|---|---|
| `legality` | legislation.gov.uk, Federal Register, EUR-Lex, regulator registers — **only** |
| `payer_solvency` | Find a Tender, Contracts Finder, SAM.gov, USAspending, Companies House accounts |
| `incumbency` | Companies House, SEC EDGAR full-text, G-Cloud/Digital Marketplace, app stores |
| `value_durability` | OpenAlex/Crossref, patents, regulatory trajectory |
| `distribution` | marketplace listings, app stores, ad libraries |
| `pain_reality` / `buyer_intent` | the open web — but complaint threads, job postings and review sites, **not** a general index's top-k |

`pain_reality` is the one check the web is genuinely right for. That is why a global "primary
sources only" rule would be wrong and the routing must be per-check.

## 4. Sequenced plan — measure, then build, then verify

Each step ships behind its own measurement. No step begins before the previous one's number
exists.

1. **D8.** Record the supplying provider on every `Source`. Backfill is impossible; this only
   measures forward. **Gate:** provider attribution present on a fresh batch.
2. **D5.** Source-authority floor + independent-domain corroboration for `supported`.
   **Gate:** primary-source share of citations backing `supported` verdicts, before and after.
   **Expect `unverifiable` to rise first** — that is the floor working, not a regression.
3. **D2+D3, one check at a time, `legality` first.** It has the cleanest register and the
   crispest question. **Gate:** `unverifiable` rate on `legality` alone, before and after.
4. **D3 panel.** Providers queried together and pooled by URL, rather than first-answer-wins.
   **Gate:** coverage and primary-source share per provider — needs D8.
5. **D1 pilot.** One source (UK Find a Tender: open OCDS API, no key, dated, every record names
   a payer who is *already paying* for the problem). ~50 bundles, candidates formed through the
   existing generation brain constrained to retrieved passages, existing vet unchanged.
   **Gate:** vets per pass against §0's baseline. If it does not move, the inversion dies for £0.
6. **D6, D7** in parallel whenever convenient. Neither blocks anything.

## 5. Two ways this programme can produce a fraud

**Circularity.** If a candidate is minted from passage P (D1) and then `pain_reality` cites P,
the check confirms what the candidate was built from. Yield would jump and mean nothing.
**Formation evidence and vetting evidence must be disjoint:** the vet re-retrieves
independently, and no check may reach `supported` on formation-only passages or on a single
domain. This is why D5 must land *before* D1, not after.

**Selection bias toward the already-procured.** Mining procurement and regulatory sources finds
problems institutions already buy solutions for. That strengthens `payer_solvency` and
`pain_reality` and **weakens `incumbency`** — a live tender implies incumbents. Expect the kill
distribution to move rather than shrink. Whether vets-per-pass actually falls is empirical,
which is what step 5's gate is for.

## 6. What is still unproven

- That removing an `unverifiable` check turns it into a `supported` one. It makes the claim
  *decidable*; some fraction will come back `refuted`. Window A is the honest guide: at 54.6%
  unverifiable the engine ran 7.4 vets per pass, so returning there alone is a ~7x cost
  reduction per shipped pack.
- That register APIs answer the checks' questions at the rate assumed here. Step 3 measures it
  on one check before the pattern is generalised.
- Yield itself, on any of this. Coverage is the mechanism; vets-per-pass is the business number
  and it has not yet been measured on fixed code.
