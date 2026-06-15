# Prospector — Engineering Handover (for the continuing agent)

You are continuing the build of **Prospector**. The full product spec is
`prospector-master-spec.md` (the single source of truth — read Parts 4, 5, 6, 14, 16
especially). This file tells you **what already exists, how it's wired, the rules you
must follow, and exactly what to build next.**

---

## 0. TL;DR state (as of 2026-06-15)

- The **engine core is built and green**: generate → dedup → prescreen → verify (6
  grounded kill-checks, kill-fast) → kill-filter → score → dossier → store, plus a CLI.
- **67 tests pass offline**, zero-spend: `.venv/bin/python -m pytest -q`.
- The **moat is proven LIVE**: `value_durability → refuted` (conf 0.95) on the fuel-duty
  idea, citing real gov.uk April-2022 red-diesel reform URLs, via the **Gemini CLI**.
- **BILLING BLOCKER RESOLVED via the CLI.** The API key's project has free-tier quota = 0,
  but the local `gemini` CLI runs on the user's free OAuth (Code Assist) quota. The engine
  now defaults to it: `operator: gemini_cli`, `retrieval: gemini_cli` (see §5). The
  mock+fixture path (§4) is still the right choice for fast offline tests/CI.

## TWO TRACKS (user decision 2026-06-15: "both")
The build has been split into two independent, non-blocking tracks:

- **Track 1 = The Store** (see `specs/stage6-storefront-platform.md`). This is the immediate revenue path. Ships first (days). It is a thin storefront on Paddle and **composes none of the modules**. It never waits on the library.
- **Track 2 = The Module Library** (see `specs/platform-modules.md`). "Harvest once, reuse forever." A standalone platform bet for FUTURE products that need first-party payments, identity, or delivery. Its consumer is the next product, NOT the store.
- **Independence:** The store doesn't depend on the library; the library is justified on its own. Neither blocks the other. Recommended order: ship Track 1 first, then Track 2.

---

## 1. How to run (MANDATORY: use the venv)

Homebrew Python 3.14 is PEP-668 externally-managed — system `pip` refuses installs.
A virtualenv already exists at `.venv`. Always use it:

```bash
cd /Users/chidionyema/Documents/code/prospector
.venv/bin/python -m pytest -q                          # 67 passed
.venv/bin/python -m pip install -r requirements.txt    # if deps missing

# Offline vet (no keys, no spend) — works today:
.venv/bin/python -m prospector.run vet --title "Generic AI meal-planner app" \
    --one-liner "another AI meal planner" --operator mock

# Live vet (once a key has quota — set GEMINI_API_KEY or ANTHROPIC_API_KEY in .env):
.venv/bin/python -m prospector.run vet \
    --title "Haulage HMRC fuel-duty PTO rebate" --operator gemini   # or claude
```

Config is `config.yaml`. Secrets go in `.env` (gitignored; see `.env.example`). NEVER
commit keys. NEVER `git add -A` — stage files explicitly (user rule).

---

## 2. Architecture & the contracts you build against

Everything is in `prospector/`. **Do not change the seams below without reason — other
modules and tests depend on these exact signatures.**

### Data contracts — `models.py`
- `Candidate(title, one_liner, hypothesis, who_pays, why_now, tags:dict,
  automatability, weak_monetisation, candidate_id)` + `.to_dict()` / `.from_dict(d)`.
- `Source.make(url, text, published_at=None, query=None)` → has `.source_id` (sha1).
- `CheckResult(check_name, verdict:Verdict, confidence:float, rationale, citations:list,
  sources:list[Source], queries, degraded:bool)`.
- `AdversarialResult(kill_case, decisive, citations)`.
- `ScoreResult(scores:dict, justification:dict, composite:float)`.
- `Dossier(candidate, decision:Decision, gate_fired, reason, checks, adversarial, score,
  model_version, created_at, reverify_due_at)` + `.to_dict()`, `.to_json()`, `.all_sources`.
- `Verdict` enum: SUPPORTED/REFUTED/UNVERIFIABLE. `Decision` enum: PASS/KILL.
- `CHECKS` dict: the six checks {name: question}. `SCORE_AXES` tuple: the six score axes.

### Config — `config.py`
`load_config(path=None) -> Config`. Fields: `.operator`, `.model`, `.retrieval`
(`.provider/.queries_per_check/.results_per_query/.max_passage_chars/.cache`),
`.thresholds` (`.confidence_floor/.min_composite_to_pass`), `.hard_gates` (ordered list),
`.weights`, `.generation`, `.listing`, `.schedule`, `.spend`, `.store_dir` (Path),
`.gate_map()`, `.adversarial_decisive_kills`.

### Model brain — `operator.py` (PLUGGABLE — Part 1)
`make_operator(cfg) -> Operator`. Adapters: `GeminiOperator`, `ClaudeOperator`,
`MockOperator(responses=dict, router=callable)`. The one method you call:
`op.complete_json(system, user, temperature=0.7, retries=2, validate=None) -> dict|list`
— strict JSON with repair-retries; raises `ParseError` only after all retries.
`op.model_version` is a string for the audit trail.
**RULE: engine brain = Gemini or Claude ONLY. DeepSeek/Minimax are for feature
build-out via aider, never the verification brain (founder fence).**

### Retrieval / grounding — `retrieval.py`
`make_provider(cfg, fixtures=None) -> SearchProvider`. `.search(query, k, max_chars)
-> list[Source]`; **MUST return [] on failure, never raise** (graceful degradation).
Providers: `GeminiGroundingProvider` (live Google Search grounding → real URLs),
`FixtureProvider(fixtures={substr: [{url,text,published_at}]})` (offline/tests),
`DiskCache` (wraps any provider; content-addressed cache in `store/_cache/`).

### Prompts — `prompts.py` + `prompts/*.md`
`render(name, **kwargs) -> (system, user)`. The 8 prompt files are verbatim Part 10 —
**they are the IP; tune them only against the golden set (§3).**

### The moat — `verify.py`, `kill_filter.py`, `score.py`
- `verify.verify(op, search, cfg, cand, on_check=None) -> (checks, adversarial|None,
  first_failing_gate|None)`. Kill-fast: stops at the first hard fail; order is
  **config-driven** (`cfg.hard_gates` order). Enforces source-or-die (a `supported`
  with no valid citation is downgraded to `unverifiable`).
- `kill_filter.apply_gates(checks, cfg, adversarial_decisive=False) -> (killed, gate, reason)`
  and `is_hard_fail(name, result, cfg) -> bool`. Pure, deterministic.
- `score.score_candidate(op, cfg, cand, checks) -> ScoreResult`;
  `score.composite(scores, weights) -> float`; `score.passes_composite(score, cfg)`.

### Plumbing
`generate.py` (`generate(op, cfg, signal_text, ...) -> list[Candidate]`), `dedup.py`
(`dedup(cands, catalogue_titles, threshold) -> (unique, dropped)`), `prescreen.py`
(`prescreen(op, cfg, cand) -> (keep, reason)` — biased to keep, preserves novelty),
`store.py` (`Store(cfg)`: `.save(dossier)`, `.catalogue_titles()`, `.get(id)`, `.all()`),
`dossier.py` (`build_dossier(...)`, `render_markdown(dossier)`), `run.py` (CLI:
`vet_candidate`, `run_signal`, argparse `vet`/`signal`), `spend.py` (`SpendGuard`),
`publish/publish.py` (STUB — real Stripe/Gumroad TODO).

---

## 3. NON-NEGOTIABLE RULES (from the spec + the user)

1. **Source-or-die.** Every factual/quantitative claim cites a retrievable source or is
   `unverifiable`. No unsourced numbers, ever.
2. **Verdict-from-retrieval-only.** Rule solely from fetched passages; silence ⇒
   `unverifiable`, never `supported`.
3. **Kill-fast.** Cheapest decisive gate first; stop at first hard fail.
4. **A KILL with a cited reason is first-class** — always render its dossier.
5. **Two loops never merge.** Sales/demand data must NEVER influence a truth verdict.
   Do not add any sales/demand argument to `verify`/`apply_gates`.
6. **Publish only on PASS.**
7. **Every feature ships with a passing proof in CI** (Part 16). A feature without a
   green test/fixture/metric is NOT done. Mirror the `tests/{unit,behavioural,
   invariants,faults,sim}` layout.
8. **No shortcuts / no stubs left behind** (user rule): port the real logic or ask;
   never `NotImplementedError` punts. Integration tests must be fast & stable.
9. **Never `git add -A`**; stage explicitly. Commit only when the user asks.
10. **Never persist secrets to files.** Use env vars / `.env` (gitignored).

---

## 4. Develop offline (the pattern to use until billing is fixed)

Use `MockOperator(router=fn)` + `FixtureProvider`. The `router(system, user)` returns a
dict/list (the model's would-be JSON) or `None`. To make grounded verdicts pass
source-or-die, the router must cite the passage id — parse it from the user text:
```python
import re
ids = re.findall(r"\[([0-9a-f]{16})\]", user)   # the [source_id] tags in the passages
return {"verdict":"refuted","confidence":0.9,"rationale":"...","citations": ids[:1]}
```
See `tests/unit/test_kill_fast.py` and the offline flagship proof for the exact idiom.
Real gov.uk fixtures live in `fixtures/fuel_duty_passages.json`.

---

## 5. LIVE PROVIDER — the Gemini CLI (working today)

The live path is the local **`gemini` CLI** (`prospector/gemini_cli.py`), used as both
brain and grounding provider. It runs on the user's free OAuth (Code Assist) quota — the
raw API key is NOT used (its project has free-tier quota = 0). The adapter strips
`GEMINI_API_KEY`/`GOOGLE_API_KEY` from the child env and runs
`gemini --skip-trust -o json [-y] -p <prompt>`, reading the `.response` field.

Default `config.yaml`: `operator: gemini_cli`, `retrieval: gemini_cli`, `model: ""`
(lets the CLI pick its default model). Run live:
```bash
.venv/bin/python -m prospector.run vet --title "Haulage HMRC fuel-duty PTO rebate" \
    --one-liner "recovers HMRC red-diesel/PTO fuel-duty rebates for haulage"
```
Caveats: each check makes ~3 CLI calls (query_gen + search + verdict); a full 6-check vet
is minutes, so kill-fast + the DiskCache (`store/_cache/`) matter. Latency, not cost, is
the constraint now. Other adapters remain available: `gemini`/`claude` (need quota/credit;
for Claude grounding, build a `ClaudeGroundingProvider` on the `web_search_20250305` tool).

**PROVEN LIVE (2026-06-13):** flagship `value_durability → refuted` (conf 0.95) citing
`gov.uk/.../changes-to-rebated-fuels-entitlement-from-1-april-2022`. The moat grounds.

---

## 6. WHAT TO BUILD NEXT (roadmap steps 4–8, in order)

Each task ends only when its proof is green (§3 rule 7). Build in this order:

### Task A — Golden-set harness (Part 14 step 4, Part 16) — DO THIS FIRST
- New `prospector/golden.py` + `tests/test_golden_set.py`. Load `fixtures/golden_set.json`
  (8 mixed-sector cases, each with `expected` pass/kill + `gate` + `must_surface`).
- For each case: run the full vet (live if unblocked, else with curated per-case
  fixtures you add to `fixtures/`), assert the decision matches `expected` AND the
  firing gate matches `gate` AND a citation domain/text matches `must_surface`.
- Report a **discrimination metric** (correct-decisions / total). This is the Phase-0
  acceptance gate and the anti-rubber-stamp guarantee. Wire it to run on prompt/config
  changes.

### Task B — Secondary artifacts + claim-check (Part 5)
- `prospector/artifacts.py`: on PASS, generate build_spec, GTM, ops_plan, financial_model
  — each grounding premises to sourced benchmarks; label unsupported figures
  `assumption — unverified`. Then `content_gen` (4 copy types, brand voice Part 15A) →
  `claim_check` (every factual statement must trace to a verified Claim; regenerate on
  fail). Prompts already exist (`content_gen.md`, `claim_check.md`).
- Proof: planted fantasy number gets stripped/labelled; copy with an unsupported claim
  ⇒ `claim_check pass=false`. (Part 16 tables "Artifact grounding", "Claim-check".)

### Task C — Packs + publish-on-pass (Part 6, 11)
- `prospector/packs.py`: compose Scout / Operator / Founder-Investor from one artifact
  graph; pricing tracks composite, automatability weighted hardest. Gated content absent
  from teaser tiers; exclusivity delists after N sales.
- Flesh out `publish/publish.py`: real own-store + Gumroad syndication; a syndication
  outage must never block canonical publish. Proof: publish called iff PASS + trust
  metadata present; syndication-outage integration test.

### Task D — Headless read/commerce API (Part 15C)
- FastAPI app exposing `Dossier`, `Pack`, `Listing`, `Claim`, `Entitlement` as versioned
  JSON resources; teasers public, full dossiers entitlement-gated. The storefront is the
  first thin client. Proof: entitlement gating tests (pos/neg) + versioned contract tests.

### Task E — Loops & hardening (Parts 3, 7, 8, 9)
- Decay loop (`reverify_due_at` → re-verify on SLA → refresh or delist).
- Adaptive-creativity controller (Part 3): rolling kill-rate raises `exploration_level`
  and varies the lens — **smarter generation, never a softer filter** (anti-gaming).
- Rejection fast-path (freshness-gated), spend-guard circuit-breaker, bounded concurrency.
- Proofs: clock time-travel sim; "two loops never merge" invariant (already have a basic
  one); "yield without gaming" (rising pass-rate never coincides with falling golden-set
  discrimination).

---

## 7. Suggested first session for the continuing agent
1. `.venv/bin/python -m pytest -q` → confirm 67 green.
2. Build **Task A (golden-set harness)** with offline fixtures — it's the acceptance
   gate everything else leans on, and it needs no live API.
3. If/when a key gets quota, run the live flagship (§5) and the golden set live.
4. Then Task B. Keep each task's proof green before moving on.
