# Multi-Market Dimension — Execution Spec (Epic D + Market-Readiness Gate)

**Date:** 2026-07-30
**Branch:** `multi-market-dimension-2026-07-30` (cut from the current launch-hardening branch)
**Source story:** `STORY_SCALE_AND_QUALITY.md` (Epic D, the Market-Readiness Gate, risks 3–5, 7)
**Goal:** Make `market` a first-class, config-driven dimension of the engine — generation, retrieval,
prompts, dedup, storage, diagnostics, and the storefront facet — so opening a new market is a config
diff plus a passing readiness probe, never a code change and never a lowered bar.

**Founder fence (stays with the manager/Claude, per `AGENTS.md` §0):** the verdict-prompt changes
(§D3.3), the EF Core migration (§D7), and the backfill of historical dossiers (§D2.4). Everything
else is delegable against this spec.

**Verify commands (all must be green before "done"):**
- Engine: `.venv/bin/python -m pytest -q`
- Golden set: `.venv/bin/python -m pytest tests/ -k golden -q`
- Store.Api: `cd store_platform/src && dotnet test Store.Tests/Store.Tests.csproj`
- Store.Web: `cd store_platform/src/Store.Web && npx tsc --noEmit && npm run build`

---

## STATUS — IMPLEMENTED 2026-07-30 on `multi-market-dimension-2026-07-30`

D0–D7 and the Market-Readiness Gate are built and green. Verified:

| Gate | Baseline (pre-branch) | After |
|---|---|---|
| `pytest -q` | 518 passed, 3 skipped | **609 passed, 3 skipped** |
| golden set | 14 passed | **14 passed** (no regression) |
| `dotnet test` | 99 passed | **105 passed** |
| `tsc --noEmit` + `npm run build` | clean | **clean** |

**New test files:** `tests/unit/test_market_config.py` (16), `tests/unit/test_market_threading.py`
(9, incl. migration against a copy of the live 1,287-row catalogue),
`tests/invariants/test_market_prompts.py` (12), `tests/unit/test_market_retrieval.py` (10),
`tests/unit/test_market_dedup.py` (8), `tests/unit/test_market_readiness.py` (16),
`tests/unit/test_market_diagnostics.py` (10), `tests/integration/test_market_cli.py` (10),
`Store.Tests/Domain/PackMarketTests.cs` (6).

**Deviations from the spec as written, and why:**

1. **Exemplars live in `prompts/markets/<code>/*.md`, not in `config.yaml`.** The spec put the
   query-gen and verdict exemplars in the market block. Putting prompt text in config fights the
   repo's own rule that prompts are `.md` files in `prompts/` so they can be tuned without touching
   config. Fragments resolve nearest-first along the market's ancestry (`us-tx` → `us` → default),
   so `us` inherits the UK verdict precedents by simply not defining its own.
2. **`market_scope` is derived from the market's `label` alone**, not written by hand in config.
   A label is a name, so the moat's only market variable is structurally incapable of carrying a
   claim about the market. Pinned by `test_market_scope_is_derived_from_the_label_alone`.
3. **UK losslessness is golden-set equivalence, not byte equality.** The exemplar move is
   byte-identical, but D3 genuinely adds a market-context paragraph to the non-moat prompts and one
   scope line to `verdict.md`. That is the feature. The golden set is the guard and it is unchanged.
4. **`markets probe` writes dossiers to `store/markets/<code>/probe/`, not the catalogue.** Found
   while smoke-testing: a probe of a closed market wrote catalogue rows that the new
   `market_not_open` alarm then correctly flagged as a breach. The probe now has its own store.
5. **`verify()` was split into a thin `market_retrieval(cfg)` wrapper over `_verify_inner`** so the
   authority-domain context covers every fetch in a vet without indenting the whole function.

**Not done (deliberately out of scope, unchanged):** currency/PPP/i18n,
`FulfilmentService.cs:19` (`GBP`), `terms.tsx`, and opening any market — `us` ships `closed`.

**The one action left for the founder:** `tools/backfill_market.py` is written and dry-run-by-default
but has NOT been applied. 1,287 pre-cutover dossiers still carry `market=''`. Run
`python -m tools.backfill_market` to preview, then `--apply`.

---

## 0. Scope

**In scope (this branch):** Epic D (D1–D5 of the story) + the Market-Readiness Gate + the thin
storefront market facet. The engine becomes multi-market-capable and the UK stays the only *open*
market until a probe says otherwise.

**Explicitly out of scope (separate specs, do not touch here):**
- Epic C (pack completeness) and Epics A/B (yield, de-AI). Market-agnostic; they compound later.
- Currency, PPP pricing, non-GBP payment rails, i18n, localized legal terms.
  `FulfilmentService.cs:19` (`private const string StoreCurrency = "GBP"`) and
  `terms.tsx` **stay exactly as they are** — this is the opportunity-market ≠ buyer-market reframe
  (story Part III). A US-market pack is sold in GBP through the existing Stripe rail.
- Opening any market. This branch ships the machinery and the UK-only default; opening US is a
  separate, probe-gated decision (§Gate).
- Audience/archetype expansion beyond `solo_agent` (story Part IV "Audience expansion").

---

## 1. Current state (verified on disk 2026-07-30, not from notes)

| Thing | Where | State |
|---|---|---|
| Lane machinery (the template to mirror) | `config.py:259-286` `for_lane`, `config.yaml:181` `lanes:` | Fully parameterized; overrides `hard_gates`/`thresholds`/`weights`/`generation`, re-applies profile + persona |
| `Candidate` | `models.py:97-154` | **No market/jurisdiction/currency field.** `ambition_tier: str = ""` is the pattern to copy |
| `candidate_id` derivation | `models.py:119-121` → `_id(title, one_liner)` | **Market-blind — a cross-market clone would collide (see §D5.3)** |
| Authority domains | `retrieval.py:78-84` `_HIGH_AUTHORITY_DOMAINS` | `gov.uk` hardcoded in a module-level frozen set consumed by `_get_timeout` (`:86-103`) |
| DDG region | `retrieval.py:603-637` | `ddgs.text(query, max_results=...)` — **no region argument** |
| Search cache key | `retrieval.py:1165-1167` | `sha1(f"{query}\|{k}\|{max_chars}")` — **no region/market component** |
| Provider chain build | `retrieval.py:1302-1356` `_build_search` / `make_provider` | Single place to thread market retrieval config |
| Prompt rendering | `prompts.py:40-67` `render()` | Blind `str.replace` per kwarg — an unpassed `{placeholder}` **leaks literally** into the model input |
| UK-baked prompts | `query_gen.md:23`, `query_gen_batched.md:25,31`, `verdict.md:31,32,34,39`, `generate_system.md:19`, `artifacts.md:26` (GBP) | Confirmed by grep |
| Dedup | `dedup.py:82-146`, called at `run.py:608-609` with `store.catalogue_titles()` (`store.py:158-165`) | Market-blind: "mobile notary bond, Texas" vs "…, UK" collide |
| Catalogue index | `store.py:20-56` schema + `:80-97` idempotent column migration | Additive-column migration pattern already exists — copy it |
| Diagnostics | `diagnostics.py:76` `diagnose_batch`, `:410` `zero_yield`, `:449` `dead_gate` | Aggregate-only |
| Publish contract | `PublishRequest.cs:8-40`, `Pack.cs:3-39` | No market field |
| Live data | `store/dossiers/` 1,094 files, `store/prospector.db`, `store/_cache/` ~8.2k entries | Pre-cutover, all UK-era |

---

## 2. Design decisions (settle these before writing code)

**DD1 — A market is a resolved config dimension mirroring lanes, not a parallel code path.**
`Config.markets` / `Config.active_market` / `Config.for_market()` mirror `lanes` / `active_lane` /
`for_lane`. Engine stays deterministic on config (CLAUDE.md).

**DD2 — A market may configure evidence and framing. It may NOT configure the bar.**
`for_market` merges **only** `retrieval`, `generation`, and prompt-context fields. A market block
containing `hard_gates`, `thresholds`, or `weights` is a **config load error**, not a silent
override. This is the structural refusal of the bar-lowering temptation (story risk 7, AGENTS.md
§2.4 "the filter is universal; only the *lane* moves the bar"). Enforced by a test, not a comment.

**DD3 — Unknown market raises; unknown lane no-ops.** A deliberate divergence from `for_lane`
(`config.py:268-269` returns `self`). Silently running "us" as UK would stamp dossiers with a market
whose evidence chain never ran — fabricated provenance. Fail closed.

**DD4 — Hierarchical codes with parent inheritance.** `us-tx` resolves against `us` for anything it
does not override; `markets` need not define every child. Splits on `-`, walks to the root.

**DD5 — Default behaviour is byte-for-byte today.** `active_market: ""` → `markets.default` → `uk`,
whose config reproduces the current hardcoded values. The golden set is the proof (§5.3).

**DD6 — The verdict prompt gets *jurisdiction scope*, never *market facts*.** Two distinct
variables, and only one reaches the moat:
- `{market_context}` — rich framing (evidence landscape, currency hint, exemplars). Goes to
  generate / query_gen / prescreen / score / artifacts.
- `{market_scope}` — one terse line naming the jurisdiction the claim is about, e.g.
  `Jurisdiction under evaluation: United States (Texas).` Goes to `verdict.md` **only**.

Rationale: feeding the moat substantive market knowledge invites ruling from prior knowledge, which
breaks verdict-from-retrieval-only (AGENTS.md §2.2). Enforced by an invariant test that the verdict
render site never receives `market_context`.

**DD7 — `market` is stamped on the Candidate at generation, not inferred later.** Same place
`structural_form` is stamped (`generate.py:311-315`).

**DD8 — Historical rows get `market=''` by default.** `''` means "pre-market-dimension", not "uk".
Backfilling to `uk` is factually defensible (all pre-cutover generation ran UK-baked prompts) but is
a data-mutation decision → founder-gated, dry-run-by-default script (§D2.4).

---

## 3. Work packages

### D0 — Branch and baseline (do first, no code changes)

1. `git checkout -b multi-market-dimension-2026-07-30`
2. Capture the pre-change baseline so "lossless" is measurable, not asserted:
   - `.venv/bin/python -m pytest -q | tail -5` → record counts
     (**observed 2026-07-30 on the pre-branch tree: `518 passed, 3 skipped in 32.15s`, exit 0** —
     this is the number the branch must still hit, plus the new tests)
   - `.venv/bin/python -m pytest tests/ -k golden -q` → record the discrimination result
   - Copy the golden output to `store/markets/_baseline/golden-pre-market.txt`
3. Back up `store/prospector.db` (`cp store/prospector.db store/prospector.db.pre-market.bak`).

**Acceptance:** baseline artifacts exist and the suite is green *before* any edit. If it is already
red, stop and report — do not build on a red baseline.

---

### D1 — Config: the `markets:` block and `for_market()`

**Files:** `config.yaml`, `prospector/config.py`

**D1.1 — `config.yaml`, new block placed after `lanes:` (before `generation:`):**

```yaml
# ---- Markets (Epic D) ----
# A market configures the EVIDENCE TERRAIN and the FRAMING for a jurisdiction.
# It may NOT configure the bar: hard_gates / thresholds / weights in a market block
# are a load error (see config.py::_validate_markets). The bar moves per LANE only.
active_market: ""                  # "" => markets.default
markets:
  default: uk
  uk:
    label: "United Kingdom"
    status: open                   # open | probing | closed
    readiness_ref: ""              # UK is the pre-existing baseline; no probe artifact required
    # "us-en" is the ddgs 9.14.4 DEFAULT that UK search has silently been running under
    # (ddgs/ddgs.py:357). Pinned here to preserve current behaviour exactly. Flipping this
    # to "uk-en" is a measured yield change with its own cache_salt — see D4.2 Step 2.
    search_region: "us-en"
    currency_hint: "GBP"
    cache_salt: ""                 # MUST stay "" so the existing store/_cache stays valid
    authority_domains:             # UNIONED with the global base set in retrieval.py
      - gov.uk
      - legislation.gov.uk
      - ons.gov.uk
      - hse.gov.uk
      - companieshouse.gov.uk
      - fca.org.uk
    legality_corpus: [legislation.gov.uk, gov.uk]
    market_context: >
      Jurisdiction: the United Kingdom. Money in GBP (£). Authoritative public evidence
      includes gov.uk guidance, legislation.gov.uk, ONS statistics, HSE, Companies House
      filings, and FCA registers.
    exemplars:
      query_gen:
        - "NHS nurse pension additional voluntary contributions take-up UK"
        - "medication fridge temperature monitoring market vendors UK"
      verdict_negative:
        candidate: "Probate clearance services in the UK."
        passage: "The UK housing market saw a 2% rise in mortgage rates in Q3."
      verdict_positive:
        candidate: "Fixed-fee probate clearance for UK Executors."
    persona_overlay:
      retiree_cohort: >
        UK state pension plus private pension drawdown; ISA/property wealth; NHS-funded care
        assessed by the local authority.
  us:
    label: "United States"
    status: closed                 # opened only by a passing readiness probe
    readiness_ref: "store/markets/us/READINESS.json"
    search_region: "us-en"
    currency_hint: "USD"
    cache_salt: "us"
    require_subdivision: true      # candidates must carry us-XX (see D2.5)
    authority_domains:
      - sec.gov
      - census.gov
      - bls.gov
      - federalregister.gov
      - ftc.gov
      - courtlistener.com
      - usa.gov
    legality_corpus: [federalregister.gov, law.cornell.edu, usa.gov]
    market_context: >
      Jurisdiction: the United States. Money in USD ($). Law is federal PLUS state-level —
      always name the state. Authoritative public evidence includes SEC EDGAR, Census, BLS,
      the Federal Register, state Secretary-of-State registries, and CourtListener.
    exemplars:
      query_gen:
        - "Texas mobile notary bond requirement filings count"
        - "Medicare durable medical equipment supplier enrollment volume BLS"
      # verdict exemplars intentionally omitted until the probe: see D3.3 fallback rule.
    persona_overlay:
      retiree_cohort: >
        Social Security plus 401(k)/IRA drawdown; Medicare at 65 with supplemental coverage;
        state-variable long-term-care funding.
```

**D1.2 — `prospector/config.py`:**
- Add fields on `Config`, next to the lane fields (`config.py:188-200`):
  ```python
  markets: dict[str, Any] = field(default_factory=dict)
  active_market: str = ""
  ```
- Populate in the loader alongside `lanes=` / `active_lane=` (`config.py:383-385`).
- New `UnknownMarketError(ValueError)` and `MarketConfigError(ValueError)` exceptions.
- New `_validate_markets(raw)` called at load:
  - `markets.default` must be present and must name a defined market → else `MarketConfigError`.
  - any market block with a `hard_gates` / `thresholds` / `weights` key → `MarketConfigError`
    naming the offending market and key (DD2).
  - every market must have `label` and `status ∈ {open, probing, closed}`.
- New method, mirroring `for_lane`'s shape:
  ```python
  def resolve_market(self, name: str | None) -> str:
      """'' -> markets.default. Returns the concrete code, raises on unknown."""

  def market_config(self, name: str | None = None) -> dict[str, Any]:
      """Resolved market block with parent inheritance (us-tx <- us). DD4."""

  def for_market(self, name: str | None) -> "Config":
      """Merge ONLY retrieval + generation from the market block; set active_market.
      Never touches hard_gates/thresholds/weights (DD2). Unknown name raises (DD3)."""
  ```
- Application order in `load_config` (`config.py:411-415`): apply `for_market` **before**
  `for_lane`. `for_lane`/`for_profile`/`for_persona` use `replace(self, ...)`, so `active_market`
  and market-merged retrieval survive automatically — assert this with a test rather than assuming.

**Acceptance:**
- `load_config()` with no changes to `active_market` produces a Config whose `hard_gates`,
  `thresholds`, `weights`, and `retrieval.provider` are **identical** to `main`'s.
- `cfg.for_market("us-tx").market_config()["currency_hint"] == "USD"` (inherited from `us`).
- `cfg.for_market("atlantis")` raises `UnknownMarketError`.
- A market block with `thresholds:` fails `load_config` with `MarketConfigError`.

**Tests:** `tests/unit/test_market_config.py` (new) — resolution, default, hierarchy, unknown,
bar-override refusal, compose-with-lane preservation.

---

### D2 — `market` threads end-to-end through the data contract

**D2.1 — `prospector/models.py`**
- Add to `Candidate` (after `ambition_tier`, `models.py:113`):
  ```python
  # Jurisdiction this opportunity lives in (Epic D). "" = not declared => the config
  # default market. Hierarchical: "us" or "us-tx". Orthogonal to ambition_tier (the bar)
  # and to the BUYER's locale (packs are sold in GBP regardless — see STORY Part III).
  market: str = ""
  ```
- Add `market=str(d.get("market", "") or "")` to `Candidate.from_dict` (`models.py:145-154`).
- **`candidate_id` derivation (`models.py:119-121`) — the collision trap.** Cross-market
  replication (§D5.3) clones a UK PASS into US with the same title/one_liner, which today yields the
  **same** `candidate_id` → `store.save()` writes the same path and the UPSERT silently overwrites
  the UK dossier. Change to:
  ```python
  def __post_init__(self) -> None:
      if not self.candidate_id:
          # market participates in the id ONLY when explicitly set, so every existing
          # and default-market id stays byte-identical (no catalogue churn, no dupes).
          self.candidate_id = (_id(self.title, self.one_liner) if not self.market
                               else _id(self.title, self.one_liner, self.market))
  ```
  Confirm `_id`'s signature accepts varargs; widen it if not.

**D2.2 — `prospector/store.py`**
- Add `market TEXT` to `_CREATE_TABLE` (`store.py:21-38`), to the idempotent migration list
  (`:85-92`), and an index `idx_market` in `_CREATE_INDEXES` (`:41-48`).
- Add `market` to `_UPSERT`'s column list **and one more `?`** (`:50-56`) — column/placeholder
  count mismatch is the classic break here.
- Pass `getattr(dossier.candidate, "market", "") or ""` in the `conn.execute(_UPSERT, (...))` tuple
  (`:134-155`), positionally matched to the new column.
- `catalogue_titles()` (`:158-165`) → return `list[tuple[str, str]]` of `(market, fingerprint)`;
  select `market` alongside `title, one_liner`. Update the docstring and the sole caller
  (`run.py:608`).
- Add `def markets_present(self) -> dict[str, int]` (counts by market) for diagnostics (§D6).

**D2.3 — `prospector/generate.py`** — stamp market where `structural_form` is stamped
(`generate.py:311-315`):
```python
market = cfg.active_market or cfg.resolve_market(None)
for c in cands:
    if not c.market:
        c.market = market
```
Set it **before** the candidates reach dedup so §D5 scoping works on the first batch.

**D2.4 — Historical backfill (founder-gated, dry-run default)**
New `tools/backfill_market.py`:
- `--dry-run` (default) prints the row counts it would change; `--apply` performs it.
- Sets `market='uk'` on `dossiers` rows with `market IS NULL OR market=''` **and**
  `created_at < <cutover>`.
- Also rewrites the `market` field inside the corresponding dossier JSON files, atomically
  (write-temp-then-rename, matching `store.py:113-117`), so JSON and index never disagree.
- Refuses to run if `store/prospector.db.pre-market.bak` is absent.
- Prints the justification it is acting on (all pre-cutover generation ran UK-baked prompts) so the
  audit trail records *why* this is a fact and not a guess.

**D2.5 — CLI surface (`prospector/run.py`)**
- Add `--market NAME` to `vet` (near `:1542`), `signal` (`:1573`), `generate` (`:1602`), and
  `discover` (`:1636`), mirroring `--lane` exactly in help text and plumbing.
- New `markets` subcommand mirroring `lanes` (`run.py:1682-1696`):
  `markets list` (code, label, status, readiness_ref, catalogue count),
  `markets probe --market X --set PATH` (§Gate), `markets open X` / `markets close X`
  (writes `status:` back to config.yaml; `open` **refuses** unless a READINESS.json with
  `verdict: open` and a matching `config_fingerprint` exists).
- **Subdivision rule:** when the resolved market has `require_subdivision: true` and the code has no
  subdivision (`us`, not `us-tx`), generation must inject "name the state" into the market context
  and vetting must reject a bare-parent candidate with a clear error. This is story risk 3
  (legality-check explosion) handled at candidate scope, not by broader searches.

**Acceptance:** a candidate vetted with `--market us` produces a dossier JSON containing
`"market": "us"`, a DB row with `market='us'`, and a `candidate_id` that differs from the same
title/one_liner vetted with no `--market`.

**Tests:** `tests/unit/test_market_threading.py` — model round-trip, id divergence, id stability for
default market, store column migration on a *copy of the real* `store/prospector.db`.

---

### D3 — Prompts are market-injected, not UK-flavored

**D3.1 — `prospector/prompts.py`: one source for the market kwargs.**
```python
def market_kwargs(cfg, *, for_verdict: bool = False) -> dict[str, str]:
    """The market variables every render site must pass. for_verdict=True returns the
    RESTRICTED set (market_scope only) — the moat gets jurisdiction, never market facts (DD6)."""
```
Rationale for centralising: `render()` (`prompts.py:63-66`) only replaces kwargs it is given, so a
`{market_context}` placeholder in a prompt whose call site forgot the kwarg is shipped **verbatim**
to the model. That is a silent quality regression with no error.

**D3.2 — De-hardcode the prompts** (replace the UK literals with placeholders; the `uk` market block
supplies exactly the current strings so the rendered UK output is unchanged):
- `prompts/query_gen.md:23` and `query_gen_batched.md:25,31` → `{market_exemplar_queries}`
- `prompts/generate_system.md:19` (UK construction exemplar) → `{market_context}` + a
  market-neutral rewrite of the exemplar sentence
- `prompts/artifacts.md:26` (`number in GBP`) → `number in {currency_hint}`
- `prompts/verdict.md:31,32,34,39` → §D3.3

**D3.3 — `verdict.md` (founder fence — manager only).**
- Inject `{market_scope}` (one line, jurisdiction only) — never `{market_context}`.
- The UK probate few-shot examples become `{market_verdict_exemplars}`, with the **uk** block
  supplying today's exact text. Fallback rule: a market that defines no verdict exemplars gets the
  `uk` set with jurisdiction nouns neutralised (the examples teach *relevance judgement*, not UK
  facts) — recorded in the market block as `verdict_exemplars_inherited: uk` so it is auditable.
- Keep every existing "rule only from the passages" instruction untouched.

**D3.4 — Thread `market_kwargs` into all nine render sites:**
`verify.py:219` (query_gen), `:250` (query_gen_batched), `:312` (verdict → restricted set),
`generate.py:275`, `run.py:1251`, `artifacts.py:218`, `:362`, `prescreen.py:190`, `score.py:32`.
(`verify.py:499` adversarial: pass the restricted set — the adversarial pass is moat too.)

**Acceptance / tests** (`tests/invariants/test_market_prompts.py`, new):
- **Placeholder coverage:** scan `prompts/*.md` for every `{market_*}` token; assert each is a key
  produced by `market_kwargs`. Fails loudly when someone adds a placeholder without wiring it.
- **No leak:** render every prompt with the standard kwargs and assert no `{market_` substring
  survives in either the system or user output.
- **Moat restriction:** assert the verdict and adversarial render calls receive `market_scope` and
  **not** `market_context`.
- **UK losslessness:** rendered UK `query_gen` / `verdict` prompts are string-identical to the
  pre-change versions (snapshot committed under `tests/fixtures/prompts/uk_baseline/`).

---

### D4 — Retrieval per market

**D4.1 — Authority domains (`retrieval.py:78-103`).** Keep `_HIGH_AUTHORITY_DOMAINS` as the global
base (Reuters/FT/Nature/etc. are authoritative everywhere). Add a per-market overlay carried in a
`contextvars.ContextVar[frozenset[str]]` with a `market_retrieval(cfg)` context manager set by
`make_provider`; `_get_timeout` unions base + overlay.

Use a ContextVar rather than a module global specifically so a future parallel vet (story A4,
`vet_workers` > 1) cannot silently cross-contaminate markets.

**D4.2 — DDG region (`retrieval.py:603-637`). Resolved 2026-07-30, and it found a live defect.**

`ddgs` 9.14.4 does accept `region`, but with a default that matters:
`ddgs/ddgs.py:351-364` — `_search_sync(..., *, region: str = "us-en", ...)`.

**Live finding: the engine has been searching DuckDuckGo with a US regional bias this whole time.**
`ddg` is the *primary* provider in the grounding chain (`config.yaml:62`), `DuckDuckGoSearchProvider`
never passes `region` (`retrieval.py:629`), so every UK grounding query has silently run under
`us-en`. This is a plausible contributor to UK unverifiable%, and it is invisible to the golden set
(fixtures bypass live search). It is a **yield** issue, not a market-dimension issue, and it must not
be smuggled into this branch as if it were de-hardcoding.

Therefore, split it:

- **Step 1 (this branch, provably lossless):** wire the parameter and pin UK to the *current
  effective* value — `uk.search_region: "us-en"`, with a code comment stating this preserves the
  pre-existing implicit default and is not an endorsement. `uk.cache_salt` stays `""`, so the ~8.2k
  existing cache entries remain valid. Zero behaviour change; the mechanism ships.
- **Step 2 (separate change, measured, NOT this branch):** flip `uk.search_region` to `uk-en` **and**
  change `uk.cache_salt` at the same time (otherwise us-en-sourced cache entries are served for
  uk-en queries — trap 2). Measure it as a before/after on unverifiable% over a real batch, since
  the golden set cannot see it. File this as its own spec under Epic B.

Implementation: `DuckDuckGoSearchProvider.__init__(self, region: str | None = None)`, passing
`region=self.region` to `ddgs.text(...)` only when set; `_build_search` (`retrieval.py:1320-1321`)
passes `region=market_cfg.get("search_region")`.

**D4.3 — Cache key (`retrieval.py:1165-1167`) — the silent-corruption trap.** Once region varies,
the same query text in two markets returns different results but hashes to the same cache file, so
US lookups would be served UK evidence from `store/_cache`. Fix:
```python
def __init__(self, inner, cache_dir=CACHE_DIR, ttl_s=0, key_salt: str = ""):
    ...
def _path(self, query, k, max_chars):
    h = hashlib.sha1(f"{query}|{k}|{max_chars}|{self.key_salt}".encode()).hexdigest()[:20]
```
`make_provider` passes `key_salt=market_cfg.get("cache_salt", "")`. **UK's salt must stay `""`** so
the ~8.2k existing `store/_cache` entries remain valid and no cost spike is triggered.

**Acceptance / tests** (`tests/unit/test_market_retrieval.py`):
- `_get_timeout("https://sec.gov/...")` returns the high-authority timeout under the `us` market and
  the base timeout with no market overlay (`.gov` TLD already qualifies — pick a non-`.gov` domain
  from the US list, e.g. `courtlistener.com`, to make the assertion meaningful).
- Two `DiskCache` instances with different salts write different paths for the same query.
- UK salt `""` resolves to the *same* path as the pre-change implementation (assert against a
  hardcoded expected hash so a regression is caught).

---

### D5 — Market-scoped dedup and cross-market replication

**D5.1 — `prospector/dedup.py`.** Keep the parameter name `catalogue_titles` (five existing tests in
`tests/unit/test_dedup.py:48-86` call it by keyword — a rename is gratuitous churn). Accept both
shapes:
- `list[str]` → legacy, all entries treated as the default market
- `list[tuple[str, str]]` → `(market, fingerprint)`

A candidate compares only against catalogue entries whose market matches its own; `''` entries are
treated as the default market. Intra-batch dedup (`dedup.py:131-137`) likewise compares only
same-market candidates. Return a third element or extend the dropped tuple so the caller can report
**dedup drops by market** (story risk 4: without this, expansion is silently throttled by dedup and
nobody notices).

**D5.2 — `run.py:608-609`** passes the new `(market, fingerprint)` list and logs the per-market drop
counts into the batch diagnostics (§D6).

**D5.3 — Cross-market replication** — new `run.py replicate` subcommand:
`replicate --from uk --to us [--n N] [--min-composite X] [--dry-run]`
- Loads PASS dossiers for `--from` from the store.
- Clones each `Candidate` with `market=<to>` and a **cleared `candidate_id`** so the new id is
  derived with the market component (§D2.1). Assert non-collision explicitly before saving.
- Re-runs the **full** vet from scratch: no verdict, source, or score is inherited. Evidence differs
  by market; a PASS must be re-earned (AGENTS.md §2.1/§2.2).
- Refuses if the target market's `status != open`.
- Records `replicated_from: <source candidate_id>` in `Candidate.tags` for provenance.

**Tests** (`tests/unit/test_dedup_market.py`): same title in two markets survives; same title in the
same market is dropped; legacy `list[str]` call path unchanged (existing tests must pass untouched);
replication produces a distinct `candidate_id` and inherits zero verdicts.

---

### D6 — Per-market observability

**Files:** `prospector/diagnostics.py`, `prospector/report.py`, `prospector/control_center/`

- `diagnose_batch` (`diagnostics.py:76`) gains a `by_market` dict: per market, the funnel
  (generated → deduped → prescreened → vetted → pass/kill/defer), `unverifiable_pct`, the per-check
  verdict matrix, kill-gates fired, dedup drops, and spend.
- Text render (`diagnostics.py:169-181`) adds a per-market block. Keep the aggregate line but label
  it `ALL MARKETS` so it can never be misread as a single market's health (story risk 5).
- `zero_yield` (`:410`) and `dead_gate` (`:449`) alarms are keyed per market and only fire for a
  market with at least `min_market_window` candidates in the window (config, default 10); below
  that, only the aggregate alarm fires. Prevents a newly-probing market from spraying alarms.
- `report.py` / control-center catalogue readers gain a `market` column and filter.

**Acceptance:** `store/scheduler/DIAGNOSTICS_LATEST.txt` from a mixed-market batch shows a separate
funnel per market; a UK-only batch's output is unchanged apart from the `ALL MARKETS` label.

---

### D7 — Storefront market facet (thin slice; migration is founder-fenced)

- `PublishRequest.cs:8-40` → add `string? Market = null` (additive, optional, at the end of the
  optional block to preserve positional compatibility).
- `Pack.cs` → `public string? Market { get; set; }`.
- EF Core migration `AddPackMarket` — **manager only**. Must be proven to apply cleanly to a copy of
  the live `store_platform/src/Store.Api/store.db`, not just to a fresh DB.
- `GET /catalog` and `GET /catalog/{id}` return `market`; `POST /internal/catalog` persists it.
- `prospector/bridge.py::publish_pass` sends `Market` from the dossier's candidate.
- `Store.Web`: a market badge on the pack card and pack page, and a market filter on the catalogue.
  **No currency change** — price stays £49 GBP for every market (story Part III).
- Publish refuses when the candidate's market `status != open` (engine-side gate in `publish.py`,
  belt-and-braces with the store-side field being nullable).

**Tests:** `Store.Tests` — contract round-trip with and without `Market`; migration applies to a
seeded legacy DB; `/catalog` shape. `Store.Web`: `npx tsc --noEmit` + a storefront e2e assertion
that a UK pack renders unchanged.

---

## 4. The Market-Readiness Gate

**New module:** `prospector/markets.py`. **CLI:** `markets probe --market X --set PATH`.

**Calibration set** — `markets/calibration/<code>.jsonl`, ~10 lines, each:
```json
{"title": "...", "one_liner": "...", "hypothesis": "...", "market": "us-tx",
 "expect": "kill", "expect_gate": "incumbency", "note": "why this is ground truth"}
```
Mix of should-PASS and should-KILL, mirroring the golden set's mixed-sector discrimination job.

**Procedure:** run the full vet for every calibration candidate through that market's configured
evidence chain — no shortcuts, the same six checks, the same bar.

**Bars (values are a founder decision — §6.1; these are placeholders until signed):**
| Bar | Placeholder | Why |
|---|---|---|
| `max_unverifiable_pct` | 40.0 | UK baseline is 35.3% (story Part IV) |
| `max_false_pass` | 0 | a should-KILL that passes is disqualifying, full stop |
| `min_should_pass_recall` | 0.5 | an honest engine that kills everything is a closed market |
| `min_structured_sources` | 1 | at least one structured incumbency source must respond |
| `legality_corpus_reachable` | true | required |
| `max_deferred_pct` | 20.0 | above this the probe is INVALID, not failed (below) |

**DEFER handling (invariant AGENTS.md §2.3):** a calibration candidate that DEFERs on infrastructure
does not count as pass or fail. If deferred exceeds `max_deferred_pct`, the probe verdict is
`invalid` and must be re-run. **An outage may never open or close a market.**

**Artifact:** `store/markets/<code>/READINESS.json`
```json
{
  "market": "us-tx",
  "probed_at": "2026-08-04T09:12:33Z",
  "git_sha": "…",
  "config_fingerprint": "sha256 of the resolved market block",
  "calibration_set": {"path": "markets/calibration/us.jsonl", "n": 10, "sha256": "…"},
  "bars": { "...": "as above" },
  "results": {
    "unverifiable_pct": 31.2,
    "should_pass": {"n": 4, "passed": 3},
    "should_kill": {"n": 6, "killed": 6, "false_pass": 0},
    "deferred_n": 0,
    "structured_sources_responding": ["sec.gov", "courtlistener.com"],
    "legality_corpus_reachable": true
  },
  "verdict": "open",
  "reasons": ["unverifiable 31.2% <= 40.0", "false_pass 0", "…"],
  "cost_usd": 2.41,
  "duration_s": 1830
}
```

**Teeth (each needs a test):**
1. `generate` / `signal` / `vet` refuse a market with `status != open` unless `--probe` is passed.
2. `markets open X` refuses unless `READINESS.json` exists with `verdict: "open"` **and** a
   `config_fingerprint` matching the current resolved market block — changing the evidence chain
   after a probe invalidates the probe.
3. `publish` refuses a candidate whose market is not open.
4. A probe with `verdict: "closed"` still writes the artifact. The kill log is the product
   (CLAUDE.md: "A KILL with a cited reason is first-class") — "what about Africa?" gets a dated,
   re-runnable measurement, not an opinion.

---

## 5. Test plan

**5.1 Unit** — `test_market_config.py`, `test_market_threading.py`, `test_market_retrieval.py`,
`test_dedup_market.py`, `test_markets_readiness.py` (bar arithmetic, DEFER→invalid, artifact schema).

**5.2 Invariants** (`tests/invariants/`) — these encode §2 rules and must never be weakened:
| Test | Asserts |
|---|---|
| `test_market_cannot_move_the_bar` | a market block with `hard_gates`/`thresholds`/`weights` fails config load (DD2) |
| `test_market_prompts.py` | placeholder coverage, no `{market_` leak, verdict/adversarial get only `market_scope` (DD6) |
| `test_closed_market_cannot_publish` | publish and generate refuse a non-open market |
| `test_defer_never_opens_or_closes_a_market` | an all-DEFER probe yields `verdict: "invalid"` |
| `test_cache_key_market_isolation` | different salts ⇒ different cache paths; UK salt ⇒ legacy path |

**5.3 Golden-set regression (the ship gate, AGENTS.md §2.9).**
`.venv/bin/python -m pytest tests/ -k golden -q` must produce **the same discrimination result** as
the D0 baseline with default config. This is the proof that de-hardcoding is lossless — that
`{market_context}` injection carries what the baked UK examples carried. If it regresses, the
injection is wrong; **do not adjust the golden set.**

**5.4 Offline probe rehearsal.** Run `markets probe --market us --set …` against
`tests/fixtures/` with `FixtureProvider` before spending a penny on live retrieval. Proves the
harness, the artifact schema, and the bar arithmetic with zero cost.

**5.5 Live US probe (budgeted, after everything above is green).** ~10 candidates through the live
chain. Record cost against `spend.daily_cap_usd`. This is the first real answer to "can the moat see
the US?" and its output is the READINESS artifact either way.

---

## 6. Open founder decisions

**Blocking the probe (not the code) — needed before §5.5:**
1. The readiness bars in §4 (max unverifiable %, calibration-set size, recall floor) and **who signs
   a market open**.
2. `require_subdivision` for the US: mandate `us-XX` at generation, or allow bare `us` for
   federal-only opportunities? (Spec assumes mandate; it is one config flag either way.)

**Blocking one work package:**
3. §D2.4 backfill: set `market='uk'` on the 1,094 pre-cutover dossiers, or leave them `''`?

**Not blocking this branch** (confirm before Phase-1 marketing, per story Part VII): flat £49 for
non-UK packs pre-PPP; the cross-border tax/VAT-OSS review trigger; when audience expansion beyond
solo is revisited.

---

## 7. Definition of done

- [ ] `.venv/bin/python -m pytest -q` green (exit code 0, witnessed — AGENTS.md Pillar 4)
- [ ] `pytest tests/ -k golden -q` matches the D0 baseline exactly
- [ ] `dotnet test Store.Tests/Store.Tests.csproj` green; `npx tsc --noEmit` and `npm run build` clean
- [ ] Default config produces byte-identical behaviour: a UK vet run before and after the branch
      yields the same decision, gate, and composite for the same candidate
- [ ] `markets list` shows `uk: open` and `us: closed`; `markets open us` refuses with no artifact
- [ ] An offline fixture probe writes a schema-valid `store/markets/us/READINESS.json`
- [ ] A `--market us` candidate renders a US-badged pack in the storefront with £49 GBP pricing and
      no UK contamination in its artifacts (story AC-D1)
- [ ] `DIAGNOSTICS_LATEST.txt` shows per-market funnels
- [ ] Checkpoint written to `checkpoints/LATEST.md` per AGENTS.md §6

---

## 8. Trap list (found in the code during this spec; each has a test above)

1. `candidate_id` is market-blind → a cross-market clone **overwrites the source dossier** (§D2.1).
2. `DiskCache` key omits region → US queries served **cached UK evidence** (§D4.3).
3. `render()` silently ships unreplaced `{placeholders}` to the model (§D3.1).
4. `_UPSERT` column/placeholder count must change together (§D2.2).
5. `dedup`'s parameter is called by keyword in five tests — accept both shapes, don't rename (§D5.1).
6. Module-global authority domains would cross-contaminate under parallel vet → ContextVar (§D4.1).
7. Backfilling `market='uk'` fabricates provenance unless justified and founder-approved (§D2.4).
8. `ddgs` defaults `region="us-en"`, so UK grounding has silently run US-biased; wiring the
   parameter naively would look like de-hardcoding while actually changing UK behaviour (§D4.2).
9. The EF migration must be proven against a copy of the **live** `store.db`, not a fresh one (§D7).
10. Aggregate diagnostics become lies the moment a second market opens (§D6).
