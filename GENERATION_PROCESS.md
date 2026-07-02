# Generation Process — End-to-End Extract (for optimisation review)

> Written 2026-06-22. Purpose: a single map of how a candidate goes from "minted" to
> "published on Fly," with every knob's **current value**, **file:line**, and the
> **empirical funnel** (where candidates actually die today) so you can hunt for optimisations.
>
> **Proof status.** Two classes of claim here:
> - **VERIFIED (me, this session):** the empirical funnel numbers in §0 — I ran them over the
>   50 newest dossiers on disk. Reproducible.
> - **RECON (haiku subagents reading the code):** the `file:line` citations and current knob
>   values in §1–§4. High-signal but **spot-check the exact line before editing** — line numbers
>   drift. Where a number matters for a decision, I re-verified it inline and marked it ✅.

---

## 0. TL;DR — where candidates die TODAY (VERIFIED)

Sample: 50 newest dossiers in `store/dossiers/` (today's batches), aggregated by me this session.

```
50 candidates vetted  →  0 PASS  →  0 published

Decision:        50 KILL / 50
Kill gate fired: min_composite        17
                 adversarial_decisive 14
                 incumbency           13
                 value_durability      5
                 payer_solvency        1
Composite score: median 0.00, max 2.50  (min_composite_to_pass = 3.2)

Per-check verdicts (220 checks total):
  unverifiable  177  (80%)   ← THE DOMINANT FAILURE MODE
  refuted        19
  supported      24

Per-check verdict breakdown:
  pain_reality      unverif 25 | supported 6  | refuted 0
  value_durability  unverif 34 | supported 11 | refuted 5
  incumbency        unverif 31 | supported 1  | refuted 13
  payer_solvency    unverif 30 | supported 1  | refuted 1
  distribution      unverif 30 | supported 1  | refuted 0
  legality          unverif 27 | supported 4  | refuted 0

Retrieval: retrieval_failed = 0  (search never errored)
           sources-per-check = {1 source: 216, 0 sources: 4}  ← only 1 passage fetched per check
Brain:     claude_cli 173 checks | deepseek 38 (provisional) | gemini 5
           42/50 dossiers trusted, 8 provisional
```

**The story in one line:** the engine isn't broken and the brain is mostly healthy — but **80% of
checks come back `unverifiable` because each check fetched exactly ONE passage**, and that one page
is usually topically adjacent rather than on-point. Unverifiable → composite floors to ~0 →
`min_composite` kills, with `adversarial`/`incumbency` finishing the rest.

**Root cause (VERIFIED):** `config.yaml` had `queries_per_check: 0` + `results_per_query: 1` →
1 passage/check. Changed this session to `2` / `3` (~6 passages/check). The next batch is the
first that can actually surface supporting evidence. **Not yet proven to lift PASS rate — that's
the open question the next tick answers.**

### 0.1 UPDATE (post-retrieval-fix, VERIFIED via `diagnose_batch`)

Newest 20 dossiers (spanning old + new config), via the new per-batch diagnostic
(`prospector/diagnostics.py::diagnose_batch`, see §6):

```
20 vetted → 0 PASS → 0 published   (7 provisional)
Kill gates:  min_composite 9 · incumbency 6 · adversarial_decisive 3 · value_durability 1 · payer_solvency 1
Grounding:   unverifiable 77.3% · sources/check {1:54, 2:9, 3:25} · retrieval-empty 0
Per-check:   pain_reality   sup 0 | ref 0 | unv 12   ← NEVER grounds
             distribution   sup 0 | ref 0 | unv 12   ← NEVER grounds
             incumbency     sup 3 | ref 6 | unv 10   ← now grounding, and KILLING
             value_durability sup 6 | ref 1 | unv 13
Composite:   9 scored, max 0.70, median 0.0, ZERO within 0.5 of the 3.2 bar
Brain:       claude_cli 50 · deepseek 36 (provisional) · gemini 2
```

**Two findings the deeper retrieval exposed:**
1. **Bottleneck MOVED, not gone.** As sources/check rises (25 checks now hit 3 sources),
   kills shift off `min_composite` (silence) onto **grounded `incumbency: refuted` (6/20)** — the
   generator is aiming at markets that are already occupied. This is a *generation-targeting*
   problem, not a retrieval one.
2. **Two checks never ground at all:** `pain_reality` and `distribution` returned **0 supported /
   0 refuted** across the batch — every verdict `unverifiable`. Their query-gen is not fetching
   on-point passages. This is the next precise retrieval lever (these two checks specifically).

Even the survivors score near-zero (max composite 0.70 vs 3.2 bar) because so many checks are
still `unverifiable` and unverifiable floors the composite. **Still 0 PASS.**

---

## 1. The pipeline, end to end (8 stages)

Driver: `RUN.md` defines the eight steps; `prospector/run.py` orchestrates; the daemon
(`prospector/scheduler/run_scheduled.py`) calls `run_signal("", k=batch_size, publish=True)` every tick.

```
 SIGNAL (or "" = blue-sky)
    │
 1. GENERATE        generate.py / generate_multilane   → up to k raw candidates  (NO quality gate here)
    │
 2. DEDUP           dedup.py                           → drop near-dupes vs catalogue + batch
    │
 3. PRESCREEN       prescreen.py                       → regex FORBID/WEAK + cheap LLM keep/drop
    │
 4. VERIFY (MOAT)   verify.py  ← THE KILL ENGINE       → 6 grounded checks, kill-fast on 1st hard fail
    │                                                     query-gen → fetch (web) → verdict (trusted brain)
    │                                                     then adversarial pass
 5. GATE            kill_filter.py                     → KILL or PASS from verdicts (+ confidence floor)
    │
 6. SCORE           score.py                           → composite = Σ(score×weight); KILL if < 3.2
    │
 6b SOURCE-OR-DIE   dossier.py                         → KILL even if composite passes, if <1 grounded-supported
    │
 7. PUBLISH         publish.py                         → only PASS + non-provisional + grounded
    │
 8. SUMMARY / dossier written to store/ either way (KILL dossiers are first-class receipts)
```

**Design invariant:** *creativity lives in generation; constraint lives in verification.* Nothing
is killed for quality at stage 1; every gate is downstream. (CLAUDE.md)

---

## 2. Stage 1 — GENERATION (the focus)

`prospector/generate.py`. Two entry points: `generate(...)` (single lane) and
`generate_multilane(...)` (fan out across ambition tiers). Returns up to `k` candidates, **no
quality judgement** (`generate.py:1` docstring).

### 2.1 The batching loop (waves × forms × audiences)

For each lane, it runs up to `max_rounds` **waves**; each wave fires several **parallel** LLM
calls, each owning a distinct *structural form* and *audience persona*, until it has `k` candidates
or hits 2 consecutive dry rounds.

| Knob | Current value | Where (config.yaml) | Effect |
|---|---|---|---|
| `candidates_per_signal` | **20** | :329 | default `k` if none passed |
| `max_per_call` | **10** | :330 | max ideas requested per LLM call |
| `max_rounds` | **6** | :331 | max waves before giving up |
| `structural_forms` | 8 forms | :341–349 | PRIMARY diversity axis (one form per call) |
| `audience_forms` | 8 personas | :353–361 | SECONDARY axis; 8×8 = 64-cell matrix |
| `controller.lenses` | 7 lenses | :370 | creativity angles, selected per run |
| `controller.exploration_min/max` | 0.2 / 0.9 | :368–369 | adaptive exploration band |
| `refinement_enabled` | **true** | :333 | per-wave "cynical analyst" critique pass |
| `lane_quota` | side_hustle 4 / smb 3 / growth 3 / venture 3 | :147–151 | how many candidates per ambition tier |

Generation temperature **0.9**; refinement temperature **0.5** (`generate.py:293,337`).

### 2.2 Anti-duplication / diversity (already built)

- **Cross-run memory:** `store.recent_titles(limit=200)` → newest ~120 fed into the prompt's
  `avoid` list (`run.py:546`, `generate.py:133–144`). Plus the last 40 of *this* run.
- **In-run dedup:** two-pass, form-aware — at most one idea per unused form, then backfill
  (`generate.py:476–504`).
- **Prompt-level:** `prompts/generate_system.md` bans dead shapes (middleman/marketplace/registry
  wrappers), demands a named payer + a durable-wedge from a closed taxonomy, runs a "commodity
  pre-mortem" (`generate_system.md:42–102`). The user prompt marks explored idea-families as
  "SPENT" (`prompts/generate.md:13–16`).

### 2.3 Model — generation runs on the CHEAP tail, never the moat

`run.py` builds a non-critical chain `_NONCRITICAL_ORDER = ("deepseek","minimax","gemini")`
with `fast=True` (`run.py:483–486`). The trusted moat (`claude_cli`/`gemini`) is reserved for
verdicts. If all three cheap tiers exhaust → `ProviderExhaustedError` → DEFER (never falls back
to the moat). This is by design (CLAUDE.md: "non-critical chains never touch the moat").

### 2.4 Optional hard floors at generation (profile-gated)

- `automatability_floor` (e.g. 0.8 in the `online_autonomous_predator` profile, `config.yaml:385`)
  drops low-automatability candidates *at generation time* (`generate.py:454–470`).
- `focus` directive (profile-set) injects a binding "every idea MUST satisfy this" constraint
  (`generate.py:239–242`).

> **Optimisation note:** generation is feature-rich and is **not** today's bottleneck — the funnel
> in §0 shows candidates are *minted fine and die at VERIFY on `unverifiable`*. The one generation
> signal worth watching is `quality_decay` (rolling alpha 2.91 in the alert log): the ideas being
> minted are exotic/hard-to-ground (e.g. "parametric income insurance for supply teachers"), which
> guarantees thin retrieval downstream. See lever #3 in §5.

---

## 3. Stage 4 — VERIFY (the moat) — where 80% die

`prospector/verify.py`. Per check, in kill-fast order, it does **query-gen → fetch → verdict**,
and **stops at the first hard fail** (`verify.py:484–506`).

### 3.1 The six checks + kill-fast order

`value_durability → incumbency → payer_solvency → distribution → legality → pain_reality`, then the
**adversarial** pass last. Each gate kills only on a **`refuted`** verdict (config.yaml:99–122).
**`unverifiable` NEVER kills** (`kill_filter.py:31–35`) — but it floors the score, which is how
unverifiable candidates die anyway (via `min_composite`).

### 3.2 Retrieval depth — THE lever we just touched

| Knob | Was | Now (this session) | Where |
|---|---|---|---|
| `queries_per_check` | 0 (template-only, 1 query) | **2** ✅ | config.yaml:59 |
| `results_per_query` | 1 | **3** ✅ | config.yaml:60 |
| `max_passage_chars` | 1500 | 1500 | config.yaml:61 |
| `cache_ttl_s` | 14 days | 14 days | config.yaml:63 |
| `template_checks` | all 6 use deterministic disconfirming templates | unchanged | config.yaml:67 |

Search providers (failover order): `[exa, brave, gemini_cli, claude_cli]` (config.yaml:58).
`retrieval_failed=0` in §0 means these *worked* — they just returned one thin passage each under
the old `results_per_query: 1`.

**Why unverifiable dominated:** with 1 passage/check, the verdict LLM sees a single tangential page
and (correctly, per "verdict-from-retrieval-only") rules `unverifiable`. Rationales in the dossiers
literally say *"the passage describes X but does not address [the check question]."* More passages
= more chances the on-point one is actually in the context window.

### 3.3 Verdict ruling + source-or-die

- Verdict runs on the **trusted moat** (`op`, not the cheap query model), temp 0.0
  (`verify.py:212–299`).
- `supported` with **no citation** → downgraded to `unverifiable` (`verify.py:284–287`).
- Confidence is **deterministic**, not LLM self-reported: citation-fraction (0.30) +
  source-diversity (0.40) + keyword-relevance (0.30) (`verify.py:67–131`). One source caps
  diversity at 0.10 → **another reason 1 passage/check produced weak confidence.**

### 3.4 Adversarial pass

Moat-only, makes the strongest grounded kill case; `decisive=True` requires citations
(`verify.py:397–449`). Fires `adversarial_decisive` (14 of 50 kills in §0).

### 3.5 Provisional / DEFER

- If the trusted moat is exhausted, the cheap tail rules **provisionally** → dossier
  `provisional=True` → **never publishes**, auto re-vets on `vet --resume`
  (`dossier.py:109–115`, `run.py:367–379`). 8/50 today.
- If **both** moat brains exhaust, or retrieval totally fails → **DEFER** (not KILL)
  (`verify.py:347–355`, `dossier.py:45–59`).

---

## 4. Gating, scoring, publishing & cost

### 4.1 Gate → score → publish thresholds

| Threshold | Current | Where | Meaning |
|---|---|---|---|
| `confidence_floor` | **0.0** | config.yaml:88–96 | a `refuted` verdict only kills if conf ≥ floor; 0.0 = any refuted kills, weakly-grounded ones too |
| `min_composite_to_pass` | **3.2** | config.yaml:97 | composite below this → `min_composite` KILL |
| `min_supported_to_pass` | **1** (hardcoded) | dossier.py:86 | PASS needs ≥1 grounded-`supported` check (source-or-die) |
| weights (6 axes) | pain 0.20 / money 0.20 / auto 0.20 / dist 0.15 / def 0.15 / build 0.10 | config.yaml:124–130 | composite = Σ(score×weight) |

Publish requires **all** of: `decision==PASS` **and** `not provisional` **and** ≥1 grounded-supported
check (`run.py:367–379`, `dossier.py:75–98`).

### 4.2 Daemon / cost / reliability

| Knob | Current | Where |
|---|---|---|
| `batch_size` | **20** ✅ (was 5 this session) | config.yaml:476 |
| daemon interval | 7200s (2h) | launchd plist arg |
| `spend.daily_cap_usd` | **20.0** | config.yaml |
| `spend.warn_at_usd` | 15.0 | config.yaml |
| today's spend | ~$1.04 of $20 | store/scheduler/ticks.jsonl |
| kill switch | `store/scheduler/PAUSE` (absent) | guard.py |
| `vet_workers` | 1 candidate at a time | config.yaml:82 |
| `search_timeout` / max / retries | 75s / 150s / 1 | config.yaml:72–86 |

**Alerts** (`alerts.py:150–212`), throttled 1h each, logged to `alerts.jsonl`:
`zero_yield` (batch ran, 0 PASS), `moat_provisional` (cheap tail ruled), `moat_deferred`
(all deferred), `barren_generation` (0 candidates), `liveness` (heartbeat stale), `quality_decay`
(rolling pass-score dropping), `dead_gate` (a configured gate never fires).

---

## 5. Optimisation levers, ranked (with proof status)

Ordered by expected impact on the actual goal — *grounded PASSes landing on Fly*.

**1. Retrieval depth — DONE this session, PROOF PENDING.** `queries_per_check 0→2`,
`results_per_query 1→3`. Directly attacks the 80%-unverifiable root cause. *Verify by re-running the
§0 aggregation after the next tick: does unverifiable% drop and PASS>0? If unverifiable falls but
composites still floor, the bottleneck is idea quality (lever 3), not retrieval.* ⏳

**2. Confidence floor is 0.0 — HYPOTHESIS, needs live calibration.** At `confidence_floor: 0.0`
(config.yaml:88), a *weakly* grounded `refuted` (e.g. 1 source, conf 0.10) still kills. With deeper
retrieval now feeding the deterministic confidence formula (§3.3), some of those `incumbency`/
`value_durability` refutes (18 of 50 kills) may be thin. *Check: after lever 1, inspect the refuted
kills' confidence; if many are <0.3 on a single source, raising the floor to ~0.3 would stop
thin-evidence kills. Do NOT raise blind — calibrate on live confidences first.*

**3. Generation mints un-groundable ideas — VERIFIED smell, fix unproven.** `quality_decay` alert
(rolling alpha 2.91) + dossier examples ("parametric income insurance for supply teachers") show
generation favours clever-but-obscure ideas with little web evidence → guaranteed `unverifiable`.
Levers: tune `controller.exploration_max` down from 0.9 (config.yaml:369) for less exotic ideas,
strengthen the prompt's "named, web-visible payer" requirement, or set a `focus` profile toward
mundane-but-groundable niches. *Proof needed: A/B a lower-exploration batch vs current and compare
unverifiable%.*

**4. min_supported_to_pass is hardcoded to 1 (dossier.py:86).** Not in config.yaml — can't tune
without code. *Process note: lift to config for tunability (matches the "params in config" directive
in memory).* Low risk, low immediate yield.

**5. Cost ceiling for the new settings.** k=20 × ~6 passages/check × 6 checks is ~4–6× the retrieval
of the old config. Today's spend is $1 of $20, so there's headroom, but **watch ticks.jsonl
`today_spend_usd`** after the first k=20 deep-retrieval batch before assuming it's free.

**6. Diversity vs convergence.** Generation has strong anti-dup machinery (§2.2). If, after lever 1,
you still see repeated idea-families, the 64-cell form×audience matrix or `lane_quota` is where to
rebalance — but the data does **not** show duplication as the current problem; don't optimise it
speculatively.

---

## 6. Always-on per-batch diagnostics (NEW — every generation ships with insight)

> Founder requirement 2026-06-22: *"every generation should be run in conjunction with
> diagnostics; we need insight now into every part of the process."* Implemented this session.

**What it does.** Every call to `run_signal` (every daemon tick AND every manual `vet`/`generate`)
now emits a full-funnel diagnostic for that one batch — automatically, no flag. It is purely
additive instrumentation wrapped in try/except, so a diagnostics failure can never break a run.

**Where it lives:**
- `prospector/diagnostics.py::diagnose_batch(dossiers, *, stage_counts, usage, cfg)` — pure;
  derives every stat from the batch's own dossiers + the top-of-funnel counts.
- `render_batch_diagnostics(report)` — the human-readable block.
- `persist_batch_diagnostics(report, store)` — writes the outputs (below).
- Wired in `prospector/run.py` immediately after the calibration-alarms block, before
  `return dossiers` (additive only; the moat is untouched).

**What it captures (every stage of the funnel):**
| Stage | Metric |
|---|---|
| generate | `generated` count |
| dedup | `dedup_dropped` |
| rejection fast-path | `rejection_fastpath` (reused recent kills) |
| prescreen | `prescreen_in` → `prescreened_out` |
| novelty (DPP) | `novelty_selected` |
| verify | per-check verdict matrix (sup/ref/unv × 6 checks), `unverifiable_pct`, sources-per-check distribution, retrieval-empty count, confidence median by verdict, provider mix, provisional count |
| gate | kill-gate histogram |
| score | composite min/med/max, count within 0.5 of the PASS bar, closest-to-pass kills |
| publish | PASS titles |
| cost | token/usage summary (`get_usage_summary()`) |

**Outputs (one place, next to `ticks.jsonl`):**
- `store/scheduler/DIAGNOSTICS_LATEST.txt` — the rendered report for the most recent batch.
- `store/scheduler/batch_diagnostics.jsonl` — one JSON line per batch (the trend trail).

**Read the latest insight any time:**
```bash
cat store/scheduler/DIAGNOSTICS_LATEST.txt
```

**Run it post-hoc on the newest dossiers (no waiting for a tick):**
```bash
python3 -c "
import json, glob, os
from prospector.diagnostics import diagnose_batch, render_batch_diagnostics
from prospector.config import load_config
files = sorted(glob.glob('store/dossiers/*.json'), key=os.path.getmtime, reverse=True)[:20]
print(render_batch_diagnostics(diagnose_batch([json.load(open(f)) for f in files], cfg=load_config())))
"
```
(post-hoc runs omit the top-of-funnel `stage_counts` — those only exist live inside `run_signal`.)

---

## Appendix — how to reproduce the §0 funnel

```bash
cd /Users/chidionyema/Documents/code/prospector
python3 - <<'PY'
import json, glob, os, collections
files = sorted(glob.glob('store/dossiers/*.json'), key=os.path.getmtime, reverse=True)[:50]
dec=collections.Counter(); gate=collections.Counter(); byname=collections.defaultdict(collections.Counter)
for f in files:
    d=json.load(open(f)); dec[d['decision']]+=1
    if d['decision']=='kill': gate[d.get('gate_fired')]+=1
    for c in d.get('checks') or []: byname[c['check_name']][c['verdict']]+=1
print('decision', dict(dec)); print('gate', dict(gate))
for n,c in byname.items(): print(n, dict(c))
PY
```
