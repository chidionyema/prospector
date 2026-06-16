# Prospector

A grounded business-opportunity vetting engine. It sources candidate ideas from
signals, runs each through **six evidence-grounded checks**, kills the losers with
a cited reason, ranks the survivors, and publishes only the ones that pass — every
factual claim backed by a retrievable source or marked `unverifiable`.

**The moat is the filter, not the ideas.** Generation is deliberately unconstrained
and creative; all the rigour lives downstream in verification. The model rules
*only* from passages it actually fetched (web search or fixture) — no prior
knowledge, no unsourced numbers. A **KILL with a cited reason is a first-class
output**: the receipt that the filter is real and grounded.

---

## Table of contents

- [The core idea](#the-core-idea)
- [How it runs (no hosted API, no keys)](#how-it-runs-no-hosted-api-no-keys)
- [Quickstart](#quickstart)
- [The CLI](#the-cli)
- [The eight-step pipeline](#the-eight-step-pipeline)
- [The six grounded checks (the moat)](#the-six-grounded-checks-the-moat)
- [Ambition lanes — one engine, four bars](#ambition-lanes--one-engine-four-bars)
- [Two model chains: the moat vs. the cheap stuff](#two-model-chains-the-moat-vs-the-cheap-stuff)
- [Resilience: failover, circuit breakers, DEFER](#resilience-failover-circuit-breakers-defer)
- [Principal Upgrades — Architectural Resilience](#principal-upgrades--architectural-resilience)
- [Polymorphic Vetting — The Persona System](#polymorphic-vetting--the-persona-system)
- [Self-tuning and calibration](#self-tuning-and-calibration)
- [Configuration](#configuration)
- [Where output lives](#where-output-lives)
- [Module map](#module-map)
- [Invariants (the rules the code enforces)](#invariants-the-rules-the-code-enforces)
- [Tests](#tests)
- [Key docs](#key-docs)
- [Pi Agent Autonomous Workflow](#pi-agent-autonomous-workflow)

---

## The core idea

Most "idea generators" are creativity engines with no brakes. Prospector inverts
that: **creativity lives in generation, constraint lives in verification, and the
two loops never merge.** An idea is generated freely, then has to *survive* a
fixed gauntlet of grounded checks before it can be published or sold.

Three outputs are possible for any candidate:

| Decision | Meaning |
|----------|---------|
| **PASS** | Cleared every hard gate **and** survived adversarial review **and** beat the lane's composite-score threshold. Eligible to publish. |
| **KILL** | Failed a hard gate. The dossier records *which* gate fired and the *cited evidence* for it. A kill is grounded in passages the operator can see — never the model's opinion. |
| **DEFER** | Retrieval or the brain was unavailable (infrastructure outage / quota exhaustion). Never a verdict, never published — the candidate is re-vetted when infra recovers. |

Every run — pass, kill, or defer — writes a full dossier to `store/`. That log is
the audit trail and the basis for the engine's self-tuning.

---

## How it runs (no hosted API, no keys)

The entire engine runs **locally or inside your Claude Code / Gemini CLI
subscription**. There are no hosted inference calls and no API-key billing in the
default path — the brain and grounding are driven through the installed `gemini`
and `claude` CLIs. This is an operating rule, not an accident (see `CLAUDE.md`).

**Provider failover is built in.** Both the verdict brain and web grounding take an
*ordered chain* of providers. If one runs out of quota/credit mid-run, the next
takes over for the rest of the run; a provider that legitimately returns nothing is
*not* treated as a failure. If **all** providers are exhausted, the candidate
**DEFERs** — an outage never produces a false KILL.

> Note: Gemini meters two separate quotas — *inference* and *web-search/grounding*.
> The web-search bucket can be spent while inference still works, which is exactly
> the case where failover to `claude_cli` grounding takes over.

---

## Quickstart

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt

# 1. Offline single vet (no model calls — uses the mock brain + fixture passages)
.venv/bin/python -m prospector.run vet \
  --title "Haulage HMRC fuel-duty PTO rebate" \
  --operator mock --fixtures fixtures/fuel_duty_passages.json

# 2. Generate + vet candidates from a signal (live, uses the failover chain)
.venv/bin/python -m prospector.run signal --file signals/example.txt --count 4

# 3. Blue-sky multi-lane run (no signal) — generates a MIXED catalogue across tiers
.venv/bin/python -m prospector.run generate --candidates 12

# 4. See what came through, the truth-loop health, and what it cost
.venv/bin/python -m prospector.run report            # catalogue (default)
.venv/bin/python -m prospector.run report --metrics  # kill rate, gate distribution, per-lane, grounding/outage stats
.venv/bin/python -m prospector.run report --costs    # spend by agent/provider, tokens, repairs, slow ops
.venv/bin/python -m prospector.run report --full

# 5. Tests
.venv/bin/pytest -q
```

---

## The CLI

All commands are subcommands of `python -m prospector.run`. `config.yaml` governs
every parameter; flags override config per-run.

| Command    | What it does | Key flags |
|------------|--------------|-----------|
| `vet`      | Vet a single candidate you supply, end to end. | `--title` (required), `--one-liner`, `--why-now`, `--operator`, `--lane`, `--fixtures`, `--publish`, `--resume` |
| `signal`   | Generate N candidates from a signal, then vet all. | `--text` \| `--file` (one required), `--count`, `--operator`, `--lane`, `--profile`, `--focus`, `--fixtures`, `--publish` |
| `generate` | Blue-sky run: generate + vet with **no signal**. Multi-lane by default. | `--candidates`, `--exploration`, `--operator`, `--lane`, `--profile`, `--focus`, `--fixtures`, `--publish`, `--resume` |
| `discover` | Self-source a diverse, sector-spread signal portfolio, save it to `signals/`, then run the full pipeline over each. | `--signals N`, `--sectors LIST`, `--count`, `--dry-run`, `--no-save`, `--operator`, `--lane`, `--fixtures`, `--publish` |
| `report`   | Read-only views over stored state (no model calls). | `--catalogue` (default) \| `--metrics` \| `--costs` \| `--generation-quality` \| `--trend` \| `--full`, `--decision` |
| `diagnose` | Calibration health: free in-catalogue alarms, plus an optional golden-evidence calibration run. | `--deep`, `--floor` |

**Resume after an outage:**

```bash
# Re-vet candidates that DEFERRED because the moat (Claude+Gemini) was down.
.venv/bin/python -m prospector.run vet --resume

# Re-run the full pipeline for signals that failed at generation time
# (when the non-critical chain — DeepSeek/MiniMax/Gemini-flash — was all down).
.venv/bin/python -m prospector.run generate --resume
```

`--lane NAME` pins a single ambition lane (`side_hustle`, `smb`, `growth`,
`venture`). Omit it to run **all active lanes** (the default — a mixed catalogue).

**Targeting generation (`--profile` / `--focus`).** These steer *what kind* of idea
is generated — and only that. They never touch the gates, thresholds, or the moat,
so they **cannot manufacture a pass**; an idea still has to survive the same six
grounded checks. Omit both and generation runs exactly as before.

- `--focus "TEXT"` — a free-text targeting constraint applied to this run only
  (one-off experiments). It is injected into generation as a *binding constraint*
  ("an idea that does not fit is INVALID").
- `--profile NAME` — a reusable bundle from `config.yaml: profiles.*` that pairs a
  restricted set of `structural_forms` with a baked-in focus directive (and,
  optionally, an `automatability_floor`). A profile composes over `--lane` (its
  forms/focus win); `--focus` overrides a profile's focus.

```bash
# One-off steer:
.venv/bin/python -m prospector.run generate \
  --focus "online only, fully automated, acute pain, makes money directly online"

# Reusable profile (ships in config.yaml):
.venv/bin/python -m prospector.run generate --profile online_autonomous_predator
```

The shipped `online_autonomous_predator` profile targets online-native,
no-human-in-the-loop businesses that attack an acute pain and take payment directly
online. Add your own under `profiles:` in `config.yaml`.

**Automatability hard floor (`generation.automatability_floor`).** Optional and
opt-in. The focus directive *asks* the model for high automation; the floor *enforces*
it. Set a `0–1` minimum (the shipped profile uses `0.8`) and any candidate whose
self-reported automatability is below it — or unstated — is dropped at generation
time, before the moat ever sees it. This turns "no human in the loop" from a
preference into a guarantee. It is a **generation filter, never a verdict gate**: it
shapes the candidate pool, it does not judge truth. Unset (the default) = no
filtering, generation behaves exactly as before.

---

## The eight-step pipeline

Every run executes these eight steps in order (`RUN.md` is the canonical
procedure; the engine is the guarantee):

```
1. GENERATE      divergent candidates from a signal (or blue-sky), per-lane fan-out
2. DEDUP         embed-match against the catalogue; drop near-duplicates
3. PRE-SCREEN    fast, cheap triage; kill only the obviously dead, keep-biased
4. VERIFY        the moat: 6 grounded checks, kill-fast; then adversarial pass
5. GATE          hard_gates → KILL or PASS; render a dossier either way
6. ARTIFACTS     (PASS only) score on 6 axes; build spec/GTM/ops/financials;
                 generate + claim-check marketing copy
7. PUBLISH       (PASS only) write listing JSON with tiers; print syndication intent
8. SUMMARY       decision, gate fired, source count, cost, timing
```

Steps 1–3 are cheap and run on the **non-critical chain**. Step 4 — the moat — is
the only step that produces verdicts, and it runs **exclusively on Claude/Gemini**
(see [Two model chains](#two-model-chains-the-moat-vs-the-cheap-stuff)).

---

## The six grounded checks (the moat)

`verify.py` runs six universal checks against every candidate. They are the same
six for any business, any sector, any scale — only the *bar* changes per lane.
For each check the engine:

1. **Generates disconfirming queries** — phrased to surface the evidence that
   would make the idea *fail* (negative-first search). By default *all six* checks
   use deterministic templates and skip the query-gen LLM call entirely
   (`queries_per_check: 0`, every gate listed in `template_checks`): query
   generation is a lookup, not judgment, so it lives in code.
2. **Fetches real pages** — via the grounding chain; URLs are HEAD-validated so a
   hallucinated link can't become a citation.
3. **Renders a verdict from passages only** — `supported` / `refuted` /
   `unverifiable`. **Source-or-die:** a `supported` verdict with no valid citation
   is downgraded to `unverifiable`. Confidence is computed *algorithmically*
   (citation fraction + source diversity + keyword relevance), not by LLM
   self-rating.

The six gates run in this **kill-fast order** (the order in `config.yaml:
hard_gates`; the run short-circuits at the first hard fail). The *killing verdict*
depends on each check's question framing — positively-framed checks kill on
`refuted`, the two negatively-framed checks (`incumbency`, `legality`, where a YES
is the bad case) kill on `supported`:

| # | Check | Kills on | Meaning of a kill |
|---|-------|----------|-------------------|
| 1 | `value_durability` | `refuted` | the value is structurally commoditised — a wrapper, no durable wedge |
| 2 | `incumbency`       | `supported` | an incumbent already solves this (a YES is the bad case) |
| 3 | `payer_solvency`   | `refuted` | no plausibly solvent payer |
| 4 | `distribution`     | `refuted` | no realistic route to the buyer |
| 5 | `legality`         | `supported` | the margin *depends on* breaking law/terms or falsifying a measure (a lawful workaround survives; silence ≠ kill) |
| 6 | `pain_reality`     | `refuted` | no evidence the pain is real / acute |

This is the **venture** (default) gate set. Each lane swaps which checks are hard —
see [Ambition lanes](#ambition-lanes--one-engine-four-bars). `unverifiable` is never
a killing verdict for any gate: a kill must rest on *cited* disconfirming evidence,
never on silence.

After the checks, an **adversarial pass** makes the strongest evidence-based case
that the idea is dead and records whether that case is *decisive*. Whether the
adversarial pass may kill is lane-aware (`adversarial_decisive` in config).

---

## Ambition lanes — one engine, four bars

Prospector is **multi-lane by default**. The same grounded machinery judges every
idea, but the *bar* it's held to depends on the idea's **ambition tier** — the
scale of business it implies. These are two orthogonal axes:

- **Ambition tier** (`side_hustle` / `smb` / `growth` / `venture`) — the **scale**
  an idea is judged by, and therefore which gates and thresholds apply.
- **£30 pack** — a downstream **selling format** applied to *every* tier's PASS
  output. It is *not* a lane's idea space. (An earlier bug baked "£30 info-product
  pack" into the side-hustle lane's *generation*; that is fixed — side_hustle now
  generates diverse side-hustle-*scale* opportunities.)

| Lane | What it judges | Floor | Hard gates / kill criterion |
|------|----------------|-------|------------------------------|
| `side_hustle` | DEMAND + DELIVERABILITY for a solo operator | **2.0** | hard: `buyer_intent`, `currency`, `route_to_market`, `legality`. The moat checks are demoted to soft `score_checks` (never kill); "commoditised" is explicitly *not* a kill reason (crowds = buyers) |
| `smb` | a real 1–20-staff business with owner income | **2.6** | hard: `buyer_intent`, `payer_solvency`, `distribution`, `legality`; adversarial kills only on broken unit economics |
| `growth` | a repeatable, scalable growth motion | **2.9** | hard: `pain_reality`, `payer_solvency`, `distribution`, `legality`; adversarial kills on no scalable channel / no retention |
| `venture` | a defensible, durable company | **3.2** | the full moat — all six gates hard; the original, strictest bar (= the top-level default) |

Each lane also carries an `adversarial_directive` that re-frames the adversarial
pass for its bar (e.g. for `side_hustle`/`smb`, lack of a moat is *not* a valid kill
reason) and a `lane_directive` that re-aims generation at that tier's *scale* of
opportunity.

A run fans out generation per lane (quotas in `config.yaml: lane_quota`), tags each
candidate with its `ambition_tier`, optionally **re-classifies** it to its natural
tier (`classify.py`), and then vets each candidate on **its own lane's bar**
(`cfg.for_lane(tier)`). The result is a single heterogeneous catalogue where an
idea that PASSes `side_hustle` may legitimately KILL `venture`.

---

## The model chains: the moat vs. the cheap stuff

This is the central cost/quality decision in the system. Three distinct provider
chains do different jobs, each with its own failover, health file, and circuit
breaker. The one rule that never bends: **DeepSeek/MiniMax (and Ollama/OpenRouter)
never rule a verdict or an adversarial pass.**

1. **The verdict brain (moat ruling) — Claude / Gemini only.** Every kill-check
   verdict and every adversarial pass is *ruled* by a high-quality brain
   (`operator: [gemini_cli, claude_cli]` by default). The cheap models are
   **forbidden** here. This is the founder fence: the product is the integrity of
   the kill, so the ruling is never cheapened.

2. **The grounding / search chain — its own ordered failover.** Fetching pages is a
   *separate* concern from ruling on them. The default search chain is
   `deepseek → minimax_search → brave → gemini_cli → claude_cli`. DeepSeek and
   MiniMax appear here as **search providers** — they *fetch and synthesise
   passages*, they do not decide the verdict, so this does not breach the fence.
   Every provider returns `[]` on failure so the chain continues.

3. **The non-critical generation chain — DeepSeek → MiniMax → Gemini-flash.**
   Generation, prescreen, and scoring don't need the expensive brain. If all tiers
   fail, this chain raises `ProviderExhaustedError` and the signal is saved for
   `generate --resume` — it **never silently falls back to the moat brain.**

```
                 ┌─────────────────────────────────────────────┐
  signal ─────▶  │ GENERATE · PRESCREEN · SCORE                 │  non-critical chain
                 │ DeepSeek → MiniMax → Gemini-flash            │  (cheap, creative)
                 └───────────────────┬─────────────────────────┘
                                     │ candidates
                 ┌───────────────────▼─────────────────────────┐
                 │ VERIFY (6 checks) · ADVERSARIAL             │  the MOAT
                 │  rule on passages: Gemini → Claude   ONLY    │  (the verdict — never cheapened)
                 │  fetch passages:  DeepSeek → MiniMax →       │  (grounding — a SEPARATE chain;
                 │     Brave → Gemini → Claude                  │   search ≠ ruling)
                 └───────────────────┬─────────────────────────┘
                                     │ verdicts + cited sources
                                  KILL / PASS / DEFER  →  dossier → store/
```

---

## Resilience: failover, circuit breakers, DEFER

The engine is designed to keep running through quota exhaustion and transient
outages, and — critically — to **never turn an outage into a false KILL**.

- **Circuit breaker** (`breaker.py`) — per-provider, three states (CLOSED → OPEN →
  HALF_OPEN). A transient failure counts toward a threshold; a hard failure (quota
  exhaustion) trips *immediately*. After a cooldown the breaker half-opens and
  admits one probe; success closes it, failure re-opens it.
- **Cross-run health** (`health.py`) — `store/provider_health.json` records, in
  wall-clock time, that a provider is "dead until T" (parsed from the error's reset
  window). The next run skips a known-dead provider from call #1 — no wasted re-probe.
- **Failover chains** (`FallbackOperator`, `FallbackSearchProvider`) — walk the
  ordered provider list, skipping any that are breaker-open or health-dead. A
  provider returning `[]` is real evidence of *nothing*, not a failure, and is
  returned as-is.
- **DEFER, not crash** — when *every* provider in a chain is exhausted, the moat
  raises `ProviderExhaustedError`; the candidate gets a `DEFER` decision (gate
  `moat_exhausted` / `retrieval_unavailable`) and is picked up by `vet --resume`
  once the chain recovers. Source-or-die means silence is `unverifiable`, never
  `supported`; an outage is `DEFER`, never `KILL`.

---

## Principal Upgrades — Architectural Resilience

As a Principal Engineer upgrade (Part 16), the engine implements three advanced strategies to ensure grounding integrity and maximize the value of failure data.

- **Domain-Aware Patience (Tiered Timeouts):** The engine doesn't treat every URL equally. While a general 4s timeout prevents waiting on dead hosts, **authoritative sources** (e.g., FT, Reuters, .gov, .edu, .int) are granted a **15s "Deep-Grounding" window**. This prevents "Low-Brow Drift" where the engine biases toward fast SEO junk and drops high-quality, high-latency evidence.
- **Stochastic Full-Vetting (1-in-10 Audit):** To keep the Adaptive Controller from playing "whack-a-mole," every 10th candidate bypasses the kill-fast short-circuit. Even if it fails gate #1, it is forced through the entire gauntlet. This sacrifices ~10% efficiency to gather a **multi-dimensional failure surface**, allowing the system to identify correlations between different business-model failures.
- **Shadow Moats (Parallel Verification):** The engine infrastructure supports running an **experimental operator** in parallel with the primary moat. Drift between the primary and experimental verdicts is logged to `prospector.jsonl`, allowing new models (e.g. DeepSeek-R1 or O1) to be vetted against the "Founder-Fence" invariants before they are promoted to primary.

---

## Polymorphic Vetting — The Persona System

Prospector implements a **Polymorphic Vetting Pipeline** (Part 16 principal upgrade) that allows the entire engine to be "tinted" with a specific analytical persona. This separates the clinical **grounding in reality** (the Moat) from the **analytical judgment** (the Persona).

- **Analytical Personas (`--persona`):** Swappable lenses that provide unique biases for generation, truth-judgment, and adversarial analysis.
  - `shark`: Kevin O'Leary mode — obsessed with margins, moats, and $100M+ scale.
  - `minimalist`: Solopreneur mode — focused on automation, low-complexity, and high laptop cashflow.
  - `academic`: Research mode — requires high-fidelity peer-reviewed evidence and first-principles logic.
- **Advisory Board (`--board`):** Enables **Analytical Multi-Tenancy**. The candidate is vetted by multiple shadow personas in parallel. Discrepancies between the primary decision and the Advisory Board (e.g., "Shark passes, but Minimalist kills on complexity") are logged for deep analysis.

Example usage:
```bash
# Vet with a specific persona
python -m prospector.run vet --title "X" --persona shark

# Run a signal through the full Advisory Board
python -m prospector.run signal --file signal.txt --board
```

---

## Self-tuning and calibration

The kill log is not just an audit trail — it feeds back into generation and guards
against the filter quietly drifting into over-restriction.

- **Adaptive exploration** (`adaptive.py`) — the recent kill-rate sets a creativity
  dial (0.0–1.0). A very high kill-rate widens exploration (more divergent lenses);
  a low one narrows it. The engine also mines recent kill reasons and domains to
  steer generation *away* from already-dead zones.
- **Diagnostics** (`diagnostics.py`, `diagnose` command) — free in-catalogue
  alarms: `zero_yield` (0 PASS — generation problem vs. over-tight filter),
  `gate_dominance` (one gate eating >85% of kills), `dead_gate` (a configured gate
  that never fires). `--deep` runs a calibration pass against fixed golden evidence.
- **Golden-set regression** (`golden.py`, `tests/`) — a curated set of mixed-sector
  cases the engine must discriminate correctly. It runs on the deterministic
  mock+fixture path and **gates every prompt or config change**: a change that
  regresses discrimination below the floor blocks ship.

---

## Configuration

**Everything that affects verdicts or economics is in `config.yaml`** — swapping
operators (e.g. Claude Code → an API operator) needs only a config change, no code:

- `operator`, `retrieval.provider` — a single provider name **or** an ordered
  failover chain, e.g. `[gemini_cli, claude_cli]`
- `model`, `model_fast`, `model_version_tag`
- `retrieval` — `queries_per_check`, `results_per_query`, `max_passage_chars`,
  `cache`, `template_checks`, `search_timeout` (+ escalation), breaker thresholds,
  per-CLI concurrency, `vet_workers`
- `thresholds` — `confidence_floor`, `min_composite_to_pass`
- `hard_gates` — gate **order** (kill-fast), killing verdicts per gate, `adversarial_decisive`
- `weights` — the six scoring axes
- `active_lanes`, `active_lane`, `lane_quota`, `lanes.*` — multi-lane setup and
  per-lane bars/gates/generation
- `profiles.*`, `active_profile` — reusable generation-targeting bundles
  (restricted `structural_forms` + a `focus` directive + optional
  `automatability_floor`); selectable with `--profile`
- `generation`, `listing`, `schedule`, `spend`, `store.dir`

**Operational knobs are environment variables:**

| Env var | Purpose | Default |
|---------|---------|---------|
| `GEMINI_BIN` / `CLAUDE_BIN` | CLI binary paths | `gemini` / `claude` |
| `PROSPECTOR_GEMINI_CONCURRENCY` / `PROSPECTOR_CLAUDE_CONCURRENCY` | max concurrent CLI subprocesses | `2` |
| `PROSPECTOR_JSON_LOG` | emit structured JSON audit log to `store/prospector.jsonl` | off |
| `PROSPECTOR_QUIET` | suppress console logging | off |

`GEMINI_API_KEY` / `ANTHROPIC_API_KEY` are used **only** by the API-direct `gemini`
/ `claude` operators, which are *not* part of the default subscription-CLI path.
The CLI adapters deliberately strip `GEMINI_API_KEY` from the child env to force the
free OAuth quota.

---

## Where output lives

```
store/
  dossiers/<id>.<decision>.json   full dossier per candidate (PASS, KILL, DEFER all kept)
  listings/<id>.json              published listing artifacts (PASS only, with --publish)
  prospector.db                   SQLite index behind the `report` views
  prospector.jsonl                structured audit log (spend, tokens, latency)
  provider_health.json            cross-run "dead until T" provider marks
  _cache/                         content-addressed search cache
  pending/                        signals saved for `generate --resume`
signals/                          signal files (operator-pasted or discover-sourced)
```

`store/` is gitignored — it is local state, never committed.

---

## Module map

| Module | Responsibility |
|--------|----------------|
| `config.py` | typed config loader; `for_lane()` lane resolution; `for_profile()` generation-targeting resolution |
| `models.py` | data contracts: `Candidate`, `Source`, `CheckResult`, `Dossier`, `ScoreResult`; the check vocabulary |
| `operator.py` | swappable brain + `FallbackOperator`; routes moat vs. non-critical |
| `retrieval.py` | grounding chain, URL validation, disk cache, `FallbackSearchProvider` |
| `gemini_cli.py` / `claude_cli.py` | subscription-CLI adapters (invoke, quota-detect, token-track) |
| `breaker.py` / `health.py` | in-run circuit breaker / cross-run provider health |
| `errors.py` | `ProviderExhaustedError` + exhaustion classifier + reset-window parser |
| `generate.py` | divergent generation; `generate_multilane()` per-lane fan-out |
| `classify.py` | classify a candidate into its natural ambition tier |
| `discover.py` | self-source a diverse signal portfolio |
| `prescreen.py` / `dedup.py` | cheap structural + LLM triage / near-duplicate drop |
| `prompts.py` | load + render the prompt templates (system/user split, cached) |
| `verify.py` | **the moat** — six grounded checks + adversarial pass |
| `kill_filter.py` / `score.py` | deterministic gates / six-axis composite scoring |
| `artifacts.py` | (PASS only) build spec / GTM / ops / financials + claim-checked marketing copy |
| `dossier.py` / `store.py` | assemble the audit record / SQLite + JSON persistence |
| `packs.py` / `publish.py`, `publish/publish.py` | compose the tiered (£30) packs / write listing + syndication intent |
| `report.py` / `diagnostics.py` / `adaptive.py` / `golden.py` | reporting / alarms / self-tuning / regression harness |
| `decay.py` | reverify scheduling (`reverify_due_at`) — dossiers go stale and re-vet |
| `spend.py` / `telemetry.py` / `progress.py` | budget caps / audit logging / live run progress |
| `api.py` | optional REST surface over the catalogue |
| `run.py` | CLI entry point; orchestrates the eight steps and lane resolution |

---

## Invariants (the rules the code enforces)

These are enforced by tests and are not negotiable:

- **Source-or-die** — every factual claim cites a retrievable source or is
  `unverifiable`. No unsourced number ships.
- **Verdict-from-retrieval-only** — the model rules solely from passages it fetched.
  Silence → `unverifiable`, never `supported`.
- **DEFER ≠ KILL** — infrastructure failure defers; it never produces a verdict.
- **The filter is universal** — the same six checks apply to every idea; only the
  lane's bar changes.
- **Kill-fast** — stop at the first hard fail; don't burn budget on dead ideas.
- **Publish only on PASS** — a KILL blocks publication entirely.
- **Two loops never merge** — demand metrics tune *what to offer*; truth metrics
  *veto what may ship*. Demand never overrides truth.
- **The moat stays on Claude/Gemini** — cheap models never touch a verdict or an
  adversarial pass.
- **Golden-set gates every change** — a discrimination regression blocks ship.

---

## Tests

```bash
.venv/bin/pytest -q                    # quick unit + behavioural
.venv/bin/pytest -v tests/unit         # gate logic, lanes, failover, scoring
.venv/bin/pytest -v tests/behavioural  # source-or-die, novelty, publish, observability
.venv/bin/pytest tests/ -k golden      # the discrimination regression gate
```

Layout: `tests/{unit,behavioural,faults,invariants,integration,sim}/`. The fault
tests assert graceful degradation (outages → DEFER, not crash); the invariant tests
assert the two loops never merge.

---

## Key docs

- **[AGENTS.md](AGENTS.md)** — the onboarding contract for any agent working on this
  repo: orientation order, the truth invariants, the reasoning DNA, and how to pick up
  the handover. Read it first.
- **[CLAUDE.md](CLAUDE.md)** — operating rules + module map (the canonical constraints).
- **[RUN.md](RUN.md)** — the eight-step per-run procedure with concrete commands.
- **[prospector-master-spec.md](prospector-master-spec.md)** — full spec: prompts,
  golden-set acceptance tests, roadmap.

The engine is deterministic on config; the golden-set regression suite gates every
change.
