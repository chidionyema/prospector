# Machine Learning Engineer

**What this is.** A complete audit of every place a model is used across this estate: which model, called how, with what prompt, parsed how, trusted how far, and what happens when it fails.
**Read this if** you are changing a prompt, adding or removing a brain, moving the trust fence, debugging a parse failure, or answering "why did the model say that?".
**Every claim below carries a `file:line` or a command's real output, measured on 2026-08-18.**

Siblings: [analyst.md](analyst.md) (what the outputs mean once written), [architect.md](architect.md), [data-engineer.md](data-engineer.md), [developer.md](developer.md), [principal-developer.md](principal-developer.md), [qa-test-engineer.md](qa-test-engineer.md), [sre-on-call.md](sre-on-call.md), [security.md](security.md). Estate context: [../ESTATE_MAP.md](../ESTATE_MAP.md).

---

## 0. The headline: nothing here is trained

**There is no training in this estate.** Every model use is inference against a pretrained model, reached either over HTTP or by shelling out to a CLI. There is no fine-tune, no gradient step, no saved weights, no learned parameter of any kind that this repo produced.

Proof, all negative searches run 2026-08-18 over `/Users/chidionyema/Documents/code/prospector`:

```bash
rg -n '\.fit\(|train_test_split|\.backward\(|optimizer|loss\.backward|GradientTape' --type py .
# no matches outside tools/experiments

rg -l 'import torch|import tensorflow|from sklearn|import sklearn' --type py .
# tools/experiments/_hhem_sidecar.py
# tools/experiments/e15_hhem_groundedness.py

find . -name '*.pt' -o -name '*.onnx' -o -name '*.pkl' -o -name '*.safetensors' | grep -v node_modules
# (no output)
```

The two `torch` files are inference-only. `tools/experiments/_hhem_sidecar.py:5-7` and `:28` load Vectara's pretrained HHEM cross-encoder in a **separate** virtualenv at `/tmp/prospector-ml-venv`, precisely so the main environment never grows a deep-learning dependency. That experiment scores groundedness; it is not wired into the live pipeline.

The word "checkpoint" appears in `prospector/ops/spend.py`, `prospector/scheduler/guard.py` and `control_center/pages/_spend.py`. In all three it means a byte offset bookmark into `store/prospector.jsonl`, so a reader can resume without re-parsing 270 MB. It never means a model checkpoint.

**Two consequences you must internalise.**

1. There is no model you can retrain to fix a behaviour. Every lever is a **prompt**, a **routing decision**, a **threshold**, or a **deterministic post-processor**. That is the whole surface.
2. Every quality change is therefore a config or prompt change, and the only regression net is the golden set (§10) — nine cases. That net is thin. See §16.

---

## 1. Complete inventory: every model call site in Prospector

Measured by finding every `prompts.render(` and every `complete_json(` call:

```bash
rg -n 'prompts\.render\(' --type py prospector/ tools/ | wc -l   # 19
rg -n '\.complete_json\(' --type py prospector/ | wc -l          # 21
```

| # | Prompt role | Rendered at | Provider chain used | Temperature asked for | Output shape | Consequence tier |
|---|---|---|---|---|---|---|
| 1 | `generate` | `generate.py:520-521`, `run.py:3507` | `noncritical_operator` | 0.9 (`generate.py:572`) | list of candidate objects | Creative. A failure costs a batch, kills nothing |
| 2 | `generate_system` (161 lines) | system half of the above | same | same | — | Creative |
| 3 | `refine` | `generate.py:647-648` | `noncritical_operator` | 0.5 (`generate.py:662`) | revised candidates | Creative |
| 4 | `refine_system` (41 lines) | system half of the above | same | same | — | Creative |
| 5 | `discover` | `discover.py:37` | `noncritical_operator` | 0.9 (`discover.py:40`) | signals | Creative |
| 6 | `classify` | `classify.py:67` | `noncritical_operator` | **0.0** (`classify.py:78`) | `{ambition_tier, structural_form}` | Routing. A wrong tier judges the idea against the wrong lane |
| 7 | `prescreen` | `prescreen.py:221` | `noncritical_operator` | default 0.7 | keep/drop + reason | Triage. Cannot kill a dossier; drops before vetting |
| 8 | `query_gen` | `verify.py:384` | verdict chain | 0.5 (`verify.py:391`) | search queries | Evidence-shaping. Bad queries produce `unverifiable` |
| 9 | `query_gen_batched` | `verify.py:425` | verdict chain | 0.5 (`verify.py:433`) | queries for all checks in one call | Same, and it is the live path (7,684 of 7,688 stamped checks) |
| 10 | `verdict` (79 lines) | `verify.py:512` | **`moat_primary` only** | **0.0** (`verify.py:521`) | `{verdict, rationale, citations}` | **Decisive.** This is the kill |
| 11 | `adversarial` | `verify.py:883` | **`moat_primary` only** | 0.3 (`verify.py:890`) | `{kill_case, decisive, confidence, citations, objections}` | Decisive when `adversarial_decisive` is on |
| 12 | `score` | `score.py:42` | `noncritical_operator` | **0.0** (`score.py:48`) | six integer axes + justification | Decisive via composite |
| 13 | `price_comparables` | `price_comparables.py:215` | verdict chain | **0.0** (`price_comparables.py:225`) | cited price anchors | **Can never kill** — barred twice |
| 14 | `critique` | `critique.py:156-157` | `noncritical_operator` | 0.4 (`critique.py:164`) | objections per candidate | Creative |
| 15 | `critique_system` (52 lines) | system half of the above | same | same | — | Creative |
| 16 | `revise` | `critique.py:199-200` | `noncritical_operator` | 0.5 (`critique.py:206`) | revised candidates | Creative |
| 17 | `revise_system` (49 lines) | system half of the above | same | same | — | Creative |
| 18 | `artifacts` (137 lines) | `artifacts.py:621` | `artifact_operator` | 0.3 (`artifacts.py:630`) | build_spec / gtm_plan / ops_plan | Product. This is the £49 deliverable |
| 19 | `claim_check` | `artifacts.py:1012` | `artifact_operator` | **0.0** (`artifacts.py:1015`) | per-claim verdict | Product integrity |
| 20 | `content_gen` (156 lines) | `artifacts.py:1289` | `marketing_operator` | 0.7 → 0.3 on retry (`artifacts.py:1295`) | listing/shelf/marketing copy | Storefront. Graded by `pack_linter.check_shelf_copy` |
| 21 | `retitle` (119 lines) | `run.py:743-744`, `tools/retitle_catalogue.py:337` | verdict chain | 0.6 → 0.2 on retry (`run.py:758`) | new title | Cosmetic, but writes live catalogue rows |
| 22 | LLM search backstop | `retrieval.py:1018` | per-provider | **0.0** | search results as JSON | Evidence supply |
| 23 | golden fixture grading | `golden_gen.py:82` | operator under test | **0.0** | grade | Test-only |

Prompt files on disk, measured `wc -l prompts/*.md prompts/style/*.md prompts/markets/*/*.md`:

```
 36 adversarial.md      137 artifacts.md          6 claim_check.md       19 classify.md
156 content_gen.md        6 critique.md          52 critique_system.md   48 discover.md
 15 generate.md         161 generate_system.md    9 prescreen.md         37 price_comparables.md
 31 query_gen.md         41 query_gen_batched.md  8 refine.md            41 refine_system.md
119 retitle.md            6 revise.md            49 revise_system.md     15 score.md
 79 verdict.md
 17 style/rationale.md  134 style/voice.md
 47 markets/uk/query_gen_batched_exemplars.md   10 markets/uk/query_gen_exemplars.md
 16 markets/uk/verdict_exemplars.md
 44 markets/us/query_gen_batched_exemplars.md   40 markets/us/query_gen_exemplars.md
--- 1379 total
```

**The prompt is data, not code.** `prompts.py:49` `load_prompt` reads from `PROMPTS_DIR` (`prompts.py:17`), and `render` (`prompts.py:229`) loads the file at call time (`prompts.py:243`). Editing a `.md` file changes behaviour with no code change and no deploy. That is deliberate, and it is also why a prompt edit is not covered by any type checker.

### 1.1 Prompt composition — market and style fragments

`prompts.render` is not a simple format call. It layers three sources:

- **Market fragments** — `market_kwargs` (`prompts.py:148`) injects per-market exemplars. `MOAT_MARKET_KEYS` (`prompts.py:38`) and `OPEN_MARKET_KEYS` (`prompts.py:42`) split which keys a moat prompt may see from those an open prompt may see. `_BASELINE_MARKET` (`prompts.py:31`) is the fallback when a market has no exemplar file.
- **Style fragments** — `style_kwargs` (`prompts.py:90`), keys listed at `prompts.py:25`, pulling `prompts/style/voice.md` (134 lines) and `prompts/style/rationale.md` (17 lines).
- **System/user split** — `split_system_user` (`prompts.py:60`) and `_load_system_prompt` (`prompts.py:55`). Roles with a `_system.md` sibling get a real system prompt; the rest send everything as user text.

**Consequence:** the same role renders differently per market. `uk` has three exemplar files, `us` has two, and every other market code falls back to `_BASELINE_MARKET`. Any A/B between markets is confounded by the prompt itself unless you hold the market fixed.

---

## 2. The operator layer: every adapter, audited

`prospector/operator.py` is 1,791 lines. `BUILDABLE_TIERS` (`operator.py:1632`) is the authoritative list:

```python
BUILDABLE_TIERS = ("claude_cli", "minimax", "minimax_m27", "deepseek", "ollama", "mock")
```

`_build_operator` (`operator.py:1636`) raises an explicit `ValueError` for the three removed tiers — `claude` (the paid Anthropic API tier), `standardcompute`, and `cursor_cli`. A stale config or plist fails loudly at startup instead of silently building a shorter chain. That is a deliberate design choice: a silently shorter chain is a degradation with no trace.

### 2.1 The base contract

Every adapter subclasses `Operator` (`operator.py:291`) and implements exactly one abstract method, `_raw` (`operator.py:306-308`). Everything else — JSON extraction, repair, retry, provisional stamping — is in the base class and therefore identical across brains.

`complete_json` (`operator.py:329-374`) is the whole contract:

| Step | Line | Behaviour |
|---|---|---|
| Default temperature | 329 | `temperature=0.7`, `retries=2` |
| JSON instruction appended | 345 | A JSON-only suffix is added to the user prompt on every call |
| Parse | via `_loads` :40 / `_extract_json` :73 | 5-strategy cascade |
| Repair retry | 370 | On `ParseError`, retries with **temperature forced to 0.0** |
| Give up | 374 | Re-raises `ParseError` after retries are spent |

`_extract_json` (`operator.py:73-258`) is the single most load-bearing function in the ML layer, because every brain's output passes through it. Its cascade, in order:

1. Direct `json.loads`.
2. Strip `<think>...</think>` reasoning blocks — `_RE_THINK` (`operator.py:37`). Required because MiniMax emits inline think blocks; the same problem is handled independently in Hermes at `gateway/stream_consumer.py:344`.
3. Strip markdown fences.
4. Brace/bracket balance scan to find the outermost complete JSON value.
5. `_tail_json_candidates` (`operator.py:261`) — recover a truncated tail.

If all five fail it raises `ParseError` (`operator.py:29`, raised at `:258`).

**Parse failure is not silent and it is not a verdict.** A `ParseError` that survives the repair retry propagates. In the verdict path that becomes an exception inside `verdict_for`, which sets `retrieval_failed=True` (`verify.py:554-570`) and fires the DEFER gate (`verify.py:1134-1151`). A malformed model response therefore **defers the candidate**; it never contributes an `unverifiable` check to a kill gate. That rule was retrofitted on 2026-08-06 and the receipt for its absence is still on disk: `store/dossiers/2102bacc6dd75cf9.kill.json` is a KILL on `min_composite` whose seven checks all read `"Verdict call failed; fail-safe."`.

### 2.2 Adapter table

| Adapter | Line | Transport | Model id | Key | Timeout / deadline | Concurrency | Retry | Temperature actually sent |
|---|---|---|---|---|---|---|---|---|
| `ClaudeCliOperator` | `claude_cli.py:427` | subprocess `claude -p <prompt> --output-format json` (`claude_cli.py:367`) | none — CLI default | none (subscription) | 180s, escalation 1.0, retries 1 (`claude_cli.py:333-334`) | `PROSPECTOR_CLAUDE_CONCURRENCY`, default 2 (`claude_cli.py:50`) | backoffs `(2, 5, 10)` (`claude_cli.py:56`) | **NONE. Accepted and dropped** (`claude_cli.py:433-435`) — no CLI flag exists |
| `MiniMaxOperator` | `operator.py:592` | HTTPS SSE stream to `https://api.minimax.io/v1` (`operator.py:658`, stream at `:763`) | `MiniMax-M3` (`:673`) / `MiniMax-M2.7` (`:674`) | `MINIMAX_API_KEY` (`:664`) | stall 90s (`:642`), total deadline 600s (`:643`) | `Semaphore(PROSPECTOR_MINIMAX_CONCURRENCY)`, default 3 (`:631`) | 429 retry max 4, base 5s (`:632-633`); truncated retry 2 (`:644`); stall retry 1 (`:649`) | **NONE. No temperature key in the payload at all** (`operator.py:731-765`) |
| `DeepSeekOperator` | `operator.py:849` | HTTPS `https://api.deepseek.com/v1` (`:873`) | `deepseek-chat` (`:884`), config default `deepseek-v4-pro` (`config.yaml:201`) | `DEEPSEEK_API_KEY` (`:877`) | 120s / deadline 180s (`:922`) | none | none | **Yes** (`:902`), `max_tokens 8192` (`:903`) |
| `OpenRouterOperator` | `operator.py:970` | HTTPS OpenRouter | 6 free models tried in order (`:1013-1020`) | OpenRouter key | per-model 20.0s (`:1000`) | per-model circuit breakers (`:1027-1030`) | model-level fallback | **Yes** — warmup 0.1 (`:1074`), main (`:1183`) |
| `OllamaOperator` | `operator.py:1269` | HTTP `http://localhost:11434/v1` (`:1278`) | `qwen2.5-coder:7b` (`:1284`) | none | 300s / deadline 360s (`:1318`) | none | none | **Yes** (`:1304`) |
| `MockOperator` | `operator.py:1341` | none | none | none | none | none | none | n/a — fixed usage 100/50/150 (`:1356-1357`) |
| `GeminiOperator` | `operator.py:390` | google-genai SDK | `gemini-2.0-flash` (`:394`) | `GEMINI_API_KEY` (`:398`) | — | — | — | **Yes** (`:411-412`) — but no config selects this tier |

### 2.3 The finding that matters most in this table

**Neither brain in `moat_primary` sends a temperature.**

- `config.yaml:81` reads `moat_primary: [minimax, claude_cli]`.
- MiniMax builds its request body at `operator.py:731-765` and there is no `temperature` key in it.
- Claude CLI accepts the argument and discards it at `claude_cli.py:433-435`, because `claude -p` has no temperature flag.

So `verify.py:521`'s `temperature=0.0` on the verdict call, `score.py:48`'s `temperature=0.0`, `classify.py:78`'s `temperature=0.0` and `price_comparables.py:225`'s `temperature=0.0` are all **no-ops on the live chain**. They take effect only on `deepseek`, `ollama`, `openrouter` and `gemini`, none of which is on `operator:` today (`config.yaml:58` = `[minimax, claude_cli]`).

This is not a defect to patch blindly — MiniMax may not accept the parameter at all, and the CLI certainly does not. It is a fact that must be stated whenever anyone claims a call is "deterministic because temperature is 0". See §11.

### 2.4 Concurrency, and the number behind it

`set_minimax_concurrency` (`operator.py:1461`) installs the width process-globally, read from `config.yaml:321 minimax_concurrency` (default 8) or `PROSPECTOR_MINIMAX_CONCURRENCY`. The default inside the module is 3 (`operator.py:1458`).

The measurement justifying 8 is recorded at `operator.py:1470-1473`: throughput 0.07 calls/s at width 2, 0.60 at 4, 0.89 at 6, **1.36 at 8, with zero 429s**. That is a 19x throughput change from the concurrency knob alone.

`claude_concurrency` is 4 (`config.yaml:402`) and `vet_workers` is 8 (`config.yaml:405`).

### 2.5 Cost, and the tier that has no price

`telemetry.PRICING` (`claude_cli.py:186-196`) is USD per 1M tokens:

| Tier | Input | Output |
|---|---|---|
| `claude` | 3.00 | 15.00 |
| `deepseek` | 0.27 | 1.10 |
| `minimax` | 0.30 | 0.30 |
| `minimax_m27` | 0.30 | 0.30 |
| `ollama` | 0 | 0 |
| `mock` | 0 | 0 |

**`claude_cli` is deliberately absent** (`claude_cli.py:92-97`). It is a subscription, not a metered API, so a per-token price would be fiction. Instead its usage is recorded from the CLI's own reported `total_cost_usd` (`claude_cli.py:98-100`).

`config.yaml:55-57` records the per-check comparison directly: "minimax rules a check in ~6s at ~$0.0004 against claude_cli's ~15s at ~$0.14". That is a ~350x cost ratio and a ~2.5x latency ratio, and it is the entire reason MiniMax leads the chain.

---

## 3. The trust fence

This is the most important boundary in the system. It decides which brain's answer is allowed to be final.

| Symbol | Line | Meaning |
|---|---|---|
| `MOAT_PRIMARY_DEFAULT` | `operator.py:1406` | `frozenset({"claude_cli"})` — the fallback when config is blank |
| `MOAT_PRIMARY_ENV` | `operator.py:1414` | `PROSPECTOR_MOAT_PRIMARY` — one-process override |
| `_coerce_moat_primary` | `operator.py:1424` | Normalises and validates names against buildable tiers |
| `moat_primary()` | `operator.py:1443` | Resolution order: **env > config > default** |
| `set_moat_primary` | `operator.py:1494` | Test/CLI setter |
| `is_provisional_provider` | `operator.py:1509-1514` | `return name not in moat_primary()` — the whole fence, one line |

Live on disk today, `config.yaml:81`:

```yaml
moat_primary: [minimax, claude_cli]
```

`config.yaml:78-83` documents the revert procedure in the same breath: "REVERT = delete `minimax` from this line. That stops FUTURE publishes immediately; packs already listed under the looser fence stay listed until unlisted deliberately."

### 3.1 How provisional propagates

1. `FallbackOperator` records which tier actually served the call in a **thread-local** `_served` (`operator.py:1550`), exposed as `last_served` (`operator.py:1552`). Thread-local matters: `vet_workers: 8` means eight checks run concurrently, and a process-global would attribute the wrong brain.
2. `served_is_provisional` (`operator.py:1557-1561`) asks `is_provisional_provider(last_served)`.
3. `verify.py:62` `_served_provider` and `verify.py:70` `_served_is_provisional` stamp each check.
4. `run.py:864` refuses to publish a PASS whose ruling was provisional.
5. The row is re-vetted later by `vet --resume`.

Measured over all 2,806 dossiers on disk: **`provisional` is `false` on every single one**. Nothing provisional survived to be written as final, which is the fence working — but see the gap in §16, because it also means the fence has no positive test data on disk.

### 3.2 The asymmetry that is deliberate

The generation preflight and the drain use the **same** classifier with different strictness, and that is a design decision, not an inconsistency.

- **Generation preflight** — `scheduler/run_scheduled.py:465` `_moat_blind_reason` calls `health.moat_blind_reason(cfg, trusted_only=False)`. The tick is skipped only when *every* verdict brain, trusted or not, carries a dead mark. One live brain of any tier is enough to generate.
- **Drain** — `run.py::_cmd_resume` runs the same classifier at the default `trusted_only=True`. Re-vetting a `provisional` row on a provisional brain re-stamps it `provisional`: the row does not move and the money is spent.

One shared function, one parameter, so the two can never drift apart by accident.

---

## 4. Failover: `errors.py` and `health.py`

### 4.1 Classification (`prospector/errors.py`, 431 lines)

Failures split into three classes at `errors.py:179-181`: `PERMANENT`, `TRANSIENT`, `NOT_EXHAUSTION`. `classify_exhaustion` (`errors.py:184-197`) decides, and **PERMANENT wins ties by branch order**.

| Pattern set | Line | Examples |
|---|---|---|
| `_PERMANENT_MARKERS` | 97-107 | credit balance, payment required |
| `_ALLOWANCE_LIMIT_RE` | 128-130 | `\b(spend\|usage\|monthly\|weekly\|daily\|hourly\|session)\s+limit\b` plus an N-hour-limit form |
| `_TRANSIENT_MARKERS` | 131-138 | overloaded, rate limited |
| `_HTTP_TRANSIENT_RE` | 146 | `\b(429\|503\|529)\b` |
| `_HTTP_PERMANENT_RE` | 147 | `\b402\b` |
| `_BILLING_RE` | 150 | billing surfaces |
| `_USED_UP_RE` | 172-174 | exhaustion phrasing |

**The word boundaries are load-bearing and were paid for.** `errors.py:139-145` records the incident: a bare substring match on HTTP codes matched `4291 bytes`, `req_id=a429f0` and `4290 tokens`, benching a healthy brain on a request id. Never remove a `\b` from these patterns.

`_ALLOWANCE_LIMIT_RE` exists because the Claude CLI says **spend** limit, not usage limit. A regex written from the obvious wording would miss the real message.

`looks_exhausted` (`errors.py:263-269`) is the single shared predicate every metered adapter uses. Only a `ProviderExhaustedError` (`errors.py:21`, carrying `provider` and `retry_after_s`) reaches `_health.mark_exhausted`. A failure the classifier misses is retried forever — which is why one function, tested once, is the rule.

`parse_reset_seconds` (`errors.py:276+`) reads a provider's own reset hint. `_MAX_WINDOW_S` is 7 days (`errors.py:347`), so a malformed hint cannot bench a brain for a year.

### 4.2 Persisted health (`prospector/health.py`, 348 lines)

| Constant | Line | Value |
|---|---|---|
| `HEALTH_PATH` | 36 | `store_root()/"provider_health.json"` |
| `NONCRITICAL_HEALTH_PATH` | 42 | separate file for the cheap chain |
| `_MIN_DEAD_S` | 46 | 60.0 |
| `_MAX_DEAD_S` | 47 | 86,400 |
| `DEFAULT_EXHAUSTION_S` | 52 | 3,600.0 (permanent) |
| `TRANSIENT_EXHAUSTION_S` | 57 | 60.0 |
| `_PROBE_AFTER_S` | 71 | 120.0 |
| `_PROBE_BACKOFF_MULT` | 72 | 2.0 |
| `_MAX_STRIKES` | 73 | 6 |

So a transient 429 benches a brain for 60 seconds and a permanent 402 for an hour, both clamped at `mark_exhausted` (`health.py:211`).

**The half-open probe** is `_claim_probe` (`health.py:151-197`). Exactly one caller machine-wide is allowed to re-probe a dead brain, arbitrated by `fcntl.flock` (`health.py:177`). The cross-process locking was added after a 2026-08-10 bug documented at `health.py:160-170`: without it, every process claimed the probe simultaneously and a benched brain was hammered rather than gently retested.

`moat_blind_reason` (`health.py:304-348`) reads the **raw `dead_until` field**, never `is_dead` (`health.py:328-330`). That is deliberate: `is_dead` consumes the half-open probe slot, so a bookkeeping check would steal the probe that a real verdict call should get.

Live state, measured 2026-08-18:

```bash
python3 -c "import json;d=json.load(open('store/provider_health.json'));print(len(d),sorted(d))"
# 8 entries: openrouter model ids, plus 'openrouter' and 'cursor_cli'
python3 -c "import json;print(json.load(open('store/provider_health_noncritical.json')))"
# {}
```

**Neither `minimax` nor `claude_cli` carries a dead mark right now.** Both live moat brains are healthy. The 8 entries are all for tiers no longer on any chain — `cursor_cli` was removed on 2026-08-06 and its dead mark is a fossil. Every entry carries only `dead_until`, `marked_at` and `dead_for_s`; none carries `strikes`, `probe_at` or `last_error`, so those fields are written by a newer code path than anything that has run recently.

### 4.3 The two independent breakers

There are two levels and they exist for different failure horizons.

- **In-run `CircuitBreaker`** — inside `FallbackOperator` (`operator.py:1578-1580`): a tier is skipped if `is_dead` OR its breaker is open. Config: `breaker_failure_threshold: 3` (`config.yaml:440`), `breaker_cooldown_s: 60` (`config.yaml:442`).
- **Cross-process `ProviderHealth`** — the JSON file above, survives restarts.

The non-critical chain has its **own** health file (`health.py:42`) and its own breaker. A brain benched for generation is not thereby benched for verdicts, and vice versa. Confusing the two files is an easy debugging mistake.

When every tier is exhausted, `FallbackOperator` raises rather than degrading (`operator.py:1618-1620`). It never promotes itself into ruling.

---

## 5. Retrieval: the evidence supply

`prospector/retrieval.py` is 2,511 lines. **It contains zero embedding use** — verified by searching for `embed`, `vector`, `cosine` and `faiss` across the file with no matches in live code paths.

### 5.1 The chain

`config.yaml:259`:

```yaml
provider: [ddg, exa, searxng, claude_cli]
```

`backstop_only_providers: [searxng, claude_cli]` (`config.yaml:271`) — those two are never tried first.

| Provider | Class | Line | Key | Notes |
|---|---|---|---|---|
| `ddg` | `DuckDuckGoSearchProvider` | 1444 | none | `ddgs` library, keyless, 3 retries. Measured 5.7s mean over 81 calls (`config.yaml:220-222`) |
| `exa` | `ExaSearchProvider` | 1254 | `EXA_API_KEY` (`:1267`) | 2-4s. Inserted at position 2 for the reason in `config.yaml:226-232` |
| `searxng` | `SearXNGSearcher` | 1372 | none | 6.0s ceiling |
| `claude_cli` | `_LLMSearchProvider` subclass | 1517 | none | Subscription backstop. Correct but slow |
| `brave` | `BraveSearchProvider` | 1170 | key | Not on the chain today |
| `tavily` | `TavilySearchProvider` | 1310 | key | Not on the chain today |
| `deepseek` / `minimax` / `openrouter` search | 1610 / 1758 / 1904 | key | LLM-as-search variants |
| `fixture` | `FixtureProvider` | 1072 | none | Offline test path |
| `gemini` | `GeminiGroundingProvider` | 993 | key | Deprecated, no config selects it |

**The number that justifies exa's position** is on record at `config.yaml:226-232`: in job `20260730T212901866`, 112 grounding calls; 81 resolved on ddg costing 460s total, but the 31 that fell through to `claude_cli` cost ~3,028s — 87% of all grounding time on 28% of the calls, 97.7s mean, 262s max. Replaying the five most expensive through exa took 14.0s against 900s, a 64x difference with identical result counts.

### 5.2 The wrappers, in order

The provider is not raw. `make_provider` (`retrieval.py:2445`) composes a stack:

| Wrapper | Line | What it does |
|---|---|---|
| `FallbackSearchProvider` | 2177 | Per-provider breakers (`:2207-2210`), `min_relevance` escalation (`:2283-2294`), best-effort fallback (`:2353-2370`), raises `GroundingInfrastructureError` when all are down (`:2382-2385`) |
| `RelevanceRankedProvider` | 492 | Over-fetches by `relevance_overfetch: 3` (`config.yaml:318`) then ranks; drops below `min_relevance: 0.35` (`config.yaml:331`) |
| `PageTextEnricher` | 921 | Fetches the page when the snippet is thin. `fetch_min_gain_chars: 400` (`config.yaml:294`), `fetch_max_bytes: 400000` (`:295`), `fetch_timeout_s: 8.0` (`:289`), 8 workers (`:290`) |
| `ProviderStamped` | 395 | Records which provider produced each passage, for audit |
| `DiskCache` | 2011 | `store/_cache`, key `sha1(f"{query}\|{k}\|{max_chars}")[:20]` (`:2041-2046`), atomic write (`:2119-2124`), TTL `1209600` s = 14 days (`config.yaml:337`) |

`_get_timeout` (`retrieval.py:133-151`) gives authority domains 15s and everything else 4s. A `.gov.uk` page is worth waiting for; a blog is not.

**The relevance ranker is the real bottleneck, not availability.** `min_relevance: 0.35` and `coverage_metric: best` (`config.yaml:335`) mean a passage can be retrieved, fetched, and then dropped for insufficient keyword overlap. The estate's own diagnosis is recorded in memory as "grounding bottleneck is relevance, not availability".

### 5.3 Fixtures

`FixtureProvider` (`retrieval.py:1072`) reads `fixtures/golden_fixtures.json` — measured 10 top-level keys, one `_README` plus 9 case keys matching the golden set. When fixtures are enabled, `make_provider` **forces** the chain to `["fixture"]` (`retrieval.py:2465-2466`) and gates the cache (`:2508`). A test cannot accidentally reach the live web.

`FixtureMiss` (`errors.py:44`) is raised when a query has no fixture. That is what makes an offline golden run honest: a query the fixtures do not cover fails loudly rather than returning nothing and scoring as `unverifiable`.

---

## 6. `verify.py`: the moat, hop by hop

1,258 lines. This is where a model's output becomes a decision.

### 6.1 Structure

| Symbol | Line | Role |
|---|---|---|
| `NO_RATIONALE_RATIONALE` | 59 | The sentinel string for "the brain gave a verdict with no reason" |
| `_served_provider` / `_served_is_provisional` | 62 / 70 | Trust stamping |
| `_coerce_verdict` | 84 | Normalise the model's verdict string |
| `_calc_confidence` | 91 | **Replaces the model's self-reported confidence entirely** |
| `_QUERY_NOISE` / `_keywords` | 194 / 217 | Query hygiene |
| `_DISCONFIRM_TEMPLATES` | 239 | Templates that search for evidence AGAINST |
| `_CONFIRM_TEMPLATES` | 253 | Templates that search FOR |
| `_templated_queries` | 263 | Deterministic query fallback |
| `_ENTITY_TEMPLATES` / `_entity_queries` | 287 / 290 | Entity-targeted queries |
| `_check_question` | 338 | The natural-language question per check |
| `gen_queries` / `gen_queries_batched` | 382 / 400 | LLM query generation |
| `verdict_for` | 461 | One check's verdict call |
| `VERDICT_PASSAGE_TRUNCATE` | 717 | 600 chars per passage into the prompt |
| `run_check` | 721 | One check end to end |
| `MAX_OBJECTIONS` / `_SEVERITIES` | 865 / 866 | Adversarial bounds |
| `adversarial` | 870 | The red-team pass |
| `verify` / `_verify_inner` | 978 / 1006 | The orchestrator |

### 6.2 The checks

`models.py:111` `DEFAULT_CHECKS`, plus lane-specific ones. Measured counts across all 14,006 checks on disk:

| Check | Times run | supported | refuted | unverifiable | Refute rate |
|---|---|---|---|---|---|
| `legality` | 2,331 | 425 | 32 | 1,874 | 1.4% |
| `payer_solvency` | 2,199 | 259 | 78 | 1,862 | 3.5% |
| `distribution` | 2,141 | 513 | 21 | 1,607 | 1.0% |
| `pain_reality` | 1,682 | 475 | 15 | 1,192 | 0.9% |
| `value_durability` | 1,573 | 393 | 132 | 1,048 | 8.4% |
| `incumbency` | 1,463 | 101 | **300** | 1,062 | **20.5%** |
| `buyer_intent` | 1,107 | 381 | 9 | 717 | 0.8% |
| `currency` | 633 | 261 | 30 | 342 | 4.7% |
| `route_to_market` | 480 | 146 | 17 | 317 | 3.5% |
| `claims_verifiable` | 397 | 125 | 28 | 244 | 7.1% |

`price_comparables` is the seventh, evidence-only check. It is stripped from the run order at `verify.py:1031` and barred again at `kill_filter.py:28-29`. Two independent barriers on the same rule, because "no price page on the open web" is a fact about the web.

**`incumbency` refutes at 20.5%, more than double any other check, and is the only check where refuted outnumbers supported.** HYPOTHESIS: the disconfirm templates at `verify.py:239-251` reliably surface *some* competitor for any idea and the model reads that as a dominant incumbent. The check that would confirm or kill it: take 30 `incumbency`-killed dossiers, read the cited passages, and count how many name a company with the same buyer and the same wedge rather than merely an adjacent player.

### 6.3 Kill-fast

The run order is built at `verify.py:1019-1031` from `cfg.hard_gates` in declaration order. The first hard fail returns immediately (`verify.py:1152-1160`), so later checks never run.

**Two analytical consequences.** A kill dossier has fewer checks than a pass (measured mean 4.99 across all dossiers, max 9). And a reorder of `hard_gates` changes which gate is *credited* for a kill even when the outcome is identical, which silently breaks any time series of `gate_fired`.

Only 865 of 2,806 dossiers carry a `score` block, because scoring runs after the gates and 1,941 candidates died before reaching it.

### 6.4 `_calc_confidence` — where every confidence number comes from

`verify.py:91-192`. The model's self-reported confidence is **discarded**. The replacement is deterministic:

```
CITED_WEIGHT     = 0.30   (verify.py:109)
DIVERSITY_WEIGHT = 0.40   (verify.py:110)
RELEVANCE_WEIGHT = 0.30   (verify.py:111)
CITATION_TARGET  = 3      (verify.py:~133)
```

- **Citation term** (`verify.py:130-136`): `max(cited/retrieved, min(1, cited/3)) * 0.30`, and `0.0` if nothing was cited.
- **Diversity term** (`verify.py:151-171`), stepped: 3+ distinct domains → 0.40; 2 → 0.25; 1 → 0.15; 0 → 0.0.
- **Relevance term** (`verify.py:173-189`): keyword overlap between the best cited passage and the check question, × 0.30.
- Result is `round(..., 3)`, clamped to `[0, 1]`.

`verify.py:93` states the intent: the design deliberately replaces LLM self-calibration with an evidence formula, because a model's stated confidence is a style artefact.

**The defect this formula had, documented verbatim at `verify.py:110-127`.** The old citation term was `cited / total * CITED_WEIGHT`. Over 1,629 production `claude_cli` checks, confidence tracked citation **count**: 1 citation → p50 0.15, 3 → 0.56, 6 → 0.71. A terse brain that cited one authoritative source scored as ungrounded. On 2026-08-15 06:28 it killed the golden PASS case "Construction Statutory Adjudication Arbitrage" whose six checks were **all `supported`** — its two moat checks scored 0.238 and 0.23 against the 0.30 floor, firing `moat_ungrounded`. That failing run is the reason MiniMax's earlier 0.96 was not a verdict about MiniMax. The scorer was measuring style.

The fix raised the lone-domain step from 0.10 to 0.15 and made the citation term `max(fraction, saturating)`. Both changes can only raise a score.

### 6.5 The observed confidence scale is not 0–1

Measured over all 14,006 checks on disk:

| Population | n | min | p25 | median | p75 | max |
|---|---|---|---|---|---|---|
| all | 14,006 | 0.000 | 0.433 | 0.662 | 0.724 | **0.820** |
| supported | 3,079 | 0.130 | 0.460 | 0.600 | 0.700 | 0.800 |
| refuted | 662 | 0.000 | 0.417 | 0.580 | 0.680 | 0.812 |
| unverifiable | 10,265 | 0.000 | 0.430 | 0.700 | 0.733 | 0.820 |

**Not one check in the whole corpus exceeded 0.820, and only 5 reached 0.80.** Exactly 0.000: 1,578 — those are the no-evidence short-circuit at `verify.py:810-827` firing before any model call.

The distribution is spiky. The 0.70–0.75 bucket alone holds 4,235 of 14,006. Those spikes are the stepped diversity term: confidence in this system is close to a discrete ladder, not a continuous score. Full histogram and the calibration-drift finding are in [analyst.md](analyst.md) §5.3–§5.4.

### 6.6 Source-or-die, enforced per check

`verify.py:583-586`: a `supported` verdict whose citations do not resolve to a retrieved source is forced to `UNVERIFIABLE`. Measured: **zero of 3,079 supported checks on disk have zero citations.** Mean 3.59 citations, median 3, max 10. The rule has no exceptions in the live corpus.

### 6.7 `retrieval_failed` and the DEFER gate

`retrieval_failed=True` is set at four sites, all measured this session:

| Line | Trigger |
|---|---|
| `verify.py:569` | The verdict call raised — quota, parse failure, crashed adapter |
| `verify.py:668-672` | The brain returned an empty rationale (the `NO_RATIONALE_RATIONALE` case) |
| `verify.py:787-801` | Retrieval raised inside `run_check` |
| `verify.py:834-842` | Retrieval infrastructure error inside `run_check` |

The gate is `verify.py:1134-1151`: `if res.retrieval_failed: first_failing_gate = DEFER_GATE`. `kill_filter.py:34-35` independently refuses to let a `retrieval_failed` result ever hard-fail. Two barriers again.

Two more DEFER paths: vet-budget exhaustion at `verify.py:1081-1105`, and moat exhaustion during the adversarial pass at `verify.py:1243-1247` producing `"moat_exhausted"`.

**Measured on disk: 0 checks carry `retrieval_failed`, and 0 dossier files carry `decision: defer`.** That is correct by construction — a defer writes an index row, not a file. `sqlite3 store/prospector.db "select count(*) from dossiers where decision='defer'"` returns **45**.

### 6.8 Admissibility and degradation

`verify.py:592-640` demotes verdicts that fail admissibility rules — the `admissibility:` config block starts at `config.yaml:459`. `degraded` marks a check whose evidence was thin or whose synthesised sources were stripped. Measured: **300 degraded checks on disk.**

`verify.py:1170-1209` is the soft early-exit: once `pass_ceiling.pass_impossible_reason` says a PASS is arithmetically unreachable, the remaining checks are skipped. A throughput optimisation, not a judgement.

---

## 7. The golden set and discrimination

### 7.1 The set

`fixtures/golden_set.json` — **9 cases, 7 expected KILL and 2 expected PASS**, measured:

```bash
python3 -c "import json,collections;d=json.load(open('fixtures/golden_set.json'));
print(len(d), collections.Counter(x['expected'] for x in d))"
# 9 Counter({'kill': 7, 'pass': 2})
```

Case schema keys: `idea, fixture_key, expected, gate, must_surface, why, label_basis`. Example, the first case:

```json
{"idea": "Haulage HMRC fuel-duty PTO rebate",
 "expected": "kill", "gate": "value_durability",
 "must_surface": "red-diesel reform",
 "why": "The rebate the business resells was abolished by the 2022 red-diesel reform...",
 "label_basis": "derivable from the fixture passage alone"}
```

`label_basis: "derivable from the fixture passage alone"` is the honesty contract. The label must be reachable from the fixture text, so a failure is the brain's and not the fixture's.

Expected gates across the 9: `value_durability` 3, `distribution` 1, `payer_solvency` 1, `legality` 1, `incumbency` 1, and `None` on the 2 PASS cases.

`fixtures/golden_fixtures.json` holds 10 keys — `_README` plus one passage bundle per case.

**A stale doc, still on disk:** `specs/offline-moat-validation.md:59` says "8 golden cases (6 KILL, 2 PASS)". Disk says 9 (7 KILL, 2 PASS). Fix the spec, not the set.

### 7.2 The metric

`prospector/golden.py`:

```python
passed = decision_match and not deferred and not unusable      # :249
scored = total - deferred_count                                 # :343
discrimination = correct_count / scored if scored > 0 else 0.0  # :344
```

Two exclusions, both deliberate and both documented in the file:

- **Deferred cases leave the denominator** (`golden.py:341-343`): "A deferred case is an unanswered question, and dividing by it scores our outage as the brain's error."
- **`unusable` cases stay in the denominator and count as failures** (`golden.py:240-245`): a case where the brain returned `NO_RATIONALE_RATIONALE` is a defect of the brain, and "a brain is not protected from its own defect by the fact that the defect makes it unusable."

`gate_match` (`golden.py:210-213`) and `surfaced` (`:215`) are **computed and printed but never scored** (correction documented at `golden.py:132-140`). The default bar is `--min-discrimination 1.0` (`golden.py:444`).

### 7.3 The run history, measured

`store/golden_runs/` holds 77 files.

```
operator        n    min     med     max     mean    runs at 1.0
claude_cli      7    0.667   0.778   1.000   0.841   2
deepseek       63    0.000   0.750   1.000   0.681   12
gemini_cli      1    0.000   0.000   0.000   0.000   0
minimax         6    0.667   0.857   1.000   0.810   1
```

Last eight runs chronologically:

```
20260616T024433955805 deepseek   0.889
20260616T094608383865 gemini_cli 0.000
20260814T235356797444 minimax    0.667
20260815T002101295951 minimax    0.778
20260815T003537664813 minimax    0.889
20260815T004632451541 minimax    0.667
20260815T062809013234 minimax    0.857
20260815T111104521041 minimax    1.000
```

### 7.4 Three findings from that history, all provable

**(a) The 1.00 run really was 9/9 on decisions.** Its `per_case` block reads `passed: True` on all 9, `deferred: False` on all 9, `unusable: False` on all 9. `model_version` is `fallback(minimax+claude_cli)`.

**(b) But it got the *reason* wrong on 5 of 9.** The same run reads `gate_match: False` on 5 cases and `True` on 4. So the brain reached the right verdict while naming a different gate than the label expects, on the majority of cases. `gate_match` is computed and not scored (`golden.py:132-140`). **Discrimination 1.00 means "right answer", never "right reasoning".** Nobody should quote 1.00 as proof of reasoning quality.

**(c) A discrimination of 1.00 does not imply 9 cases scored.** The 0.857 run (`minimax_20260815T062809013234.json`) has 2 deferred cases, so `scored = 7` and `6/7 = 0.857`. A 1.0 could in principle come from 5/5. Always read `deferred` alongside the ratio.

**(d) The claimed promotion evidence is not on disk.** The project `CLAUDE.md` states MiniMax was promoted on "three consecutive golden runs at discrimination 1.00 (9/9)". `store/golden_runs/` contains **one** MiniMax run at 1.0, and its metadata reads `run_index: 1, total_runs: 1`. The other five MiniMax runs scored 0.667, 0.667, 0.778, 0.857, 0.889.

HYPOTHESIS: the three promotion runs were executed with `--runs 3` in a mode that did not persist per-run files to `store/golden_runs/`, or they were run from a different `PROSPECTOR_STORE_DIR`. The exact check that would confirm or kill it:

```bash
rg -n 'runs=3|--runs 3|total_runs' prospector/golden.py | head
python3 -c "
import json,glob
for p in glob.glob('store/golden_runs/*.json'):
    d=json.load(open(p))
    if d.get('total_runs',1)>1: print(p, d['run_index'], d['total_runs'], d['discrimination'])"
grep -rn 'golden' ~/.hermes/logs/*.log 2>/dev/null | grep -i '1.0\|discrimination' | tail
```

Until that returns three 1.00 runs, treat the promotion evidence as **unverified on disk**. This is not an argument to revert the roster — `CLAUDE.md` explicitly warns against reverting on a single failing run, and §6.4 shows the earlier 0.96 was a scorer defect. It is an argument to re-run the gate and persist the receipt.

### 7.5 The related gate: market readiness

`prospector/markets.py:35-46` `DEFAULT_BARS`:

| Bar | Value |
|---|---|
| `min_grounding_rate` | 0.55 |
| `min_authority_rate` | 0.25 |
| `min_discrimination` | 0.70 |
| `min_pass_rate` | 0.05 |

It computes its **own** discrimination at `markets.py:216`, separate from `golden.py:344`. Two formulas named the same thing in one repo. Check which one produced a number before comparing them.

---

## 8. Determinism: what is actually pinned

### 8.1 Temperature, measured across the whole package

```bash
rg -n 'temperature\s*=' prospector/*.py
```

| Call site | Temperature | Role |
|---|---|---|
| `operator.py:369` | 0.0 | forced on the JSON repair retry |
| `verify.py:391` | 0.5 | `query_gen` |
| `verify.py:433` | 0.5 | `query_gen_batched` |
| `verify.py:521` | **0.0** | **the verdict** |
| `verify.py:890` | 0.3 | adversarial |
| `score.py:48` | **0.0** | scoring |
| `retrieval.py:1018` | 0.0 | LLM search |
| `run.py:758` | 0.6 / 0.2 | retitle, first / retry |
| `price_comparables.py:225` | **0.0** | price anchors |
| `golden_gen.py:82` | 0.0 | fixture grading |
| `generate.py:572` | 0.9 | generation |
| `generate.py:662` | 0.5 | refinement |
| `discover.py:40` | 0.9 | signal discovery |
| `critique.py:164` | 0.4 | critique |
| `critique.py:206` | 0.5 | revision |
| `classify.py:78` | **0.0** | tier/form routing |
| `artifacts.py:630` | 0.3 | pack artifacts |
| `artifacts.py:1015` | **0.0** | claim check |
| `artifacts.py:1295` | 0.7 / 0.3 | marketing copy |
| `operator.py:329` | 0.7 | the default when nothing is passed |

The gradient is coherent: creative work runs hot, judgement runs cold.

### 8.2 And none of it reaches the live moat

Repeating §2.3 because it changes how you read the table above: **MiniMax's request body has no `temperature` field (`operator.py:731-765`) and the Claude CLI drops the argument (`claude_cli.py:433-435`).** `moat_primary` is `[minimax, claude_cli]` (`config.yaml:81`). Every 0.0 in the verdict path is therefore aspirational on the live chain.

### 8.3 What is known about repeat-run stability

`prospector/classify.py:73` records the measurement verbatim: "minimax still returned different tiers across repeat runs at 0.0 for 4 of 6 candidates, 2026-08-06". `run.py:560` repeats it. `tests/invariants/test_chain_degradation.py:1-24` repeats it in its docstring and adds that "claude_cli returned the identical answer 18/18".

**No determinism test exists.** Searching for a test that repeats a prompt N times and asserts equality returns nothing; `test_chain_degradation.py` tests exhaustion classification instead, despite its docstring. The 4-of-6 figure is a comment, not a gate.

That is the largest testing gap in the ML layer, and it is directly actionable: a repeat-N harness against fixtures with `mock` and then `minimax` would cost a few hours and would turn a comment into a receipt.

### 8.4 What IS deterministic

Everything downstream of the model:

| Component | Line | Determinism |
|---|---|---|
| `_calc_confidence` | `verify.py:91` | Pure function of sources, citations, question text |
| `composite` | `score.py:20-23` | Pure arithmetic over six integers and six weights |
| `is_hard_fail` | `kill_filter.py:20-51` | Pure predicate |
| `pass_impossible_reason` | `pass_ceiling.py:59-100` | Pure |
| `dossier.build` decision | `dossier.py:100-235` | Pure given the checks |
| `dedup` | `dedup.py:54-73` | Pure string comparison |
| `pricing` rung | `pricing.py` | Config-declared rung, never a computed continuous number |
| Anchor literal check | `price_comparables.py:119-141` | Regex with negative lookaround |

**The design shape is: a stochastic model produces evidence and a categorical verdict; every number derived from it is deterministic.** That is why a prompt change is riskier here than a threshold change — the threshold is testable in isolation, the prompt is not.

---

## 9. Calibration: what is NOT measured

**Nothing in this estate measures whether a confidence is correct.**

```bash
rg -in 'brier|calibration_curve|reliability diagram|expected calibration error' --type py .
# no matches
```

There is no Brier score, no reliability diagram, no binning of predicted confidence against observed outcome. `verify.py:93` states the design deliberately replaces LLM self-calibration with a deterministic formula — but the formula itself is never validated against ground truth.

`prospector/diagnostics.py` has `calibration_alarms` and `run_calibration`, reachable as `run.py diagnose`. Read those before assuming nothing exists — but they check *distributional* alarms over the catalogue, not predictive accuracy.

What this costs, concretely: every threshold in the system (`confidence_floor: 0.4`, `min_supported_confidence: 0.3`, `min_composite_to_pass: 2.5`) was set by looking at a **distribution**, never at an accuracy. We know that moving `confidence_floor` to 0.4 frees 19.8% of replayable kills (`config.yaml:503-513`). We do not know whether those freed candidates were good.

The only labelled data in the estate is the 9-case golden set. That is far too small to calibrate a confidence scale with 14,006 observations on it.

**Cheapest path to a real measurement, and it needs no new modelling:** label the 108 passes and 119 listings by whether they sold, bin by the moat check's confidence, and plot the observed pass-to-sale rate per bin. That is a reliability diagram built from data already on disk.

---

## 10. Machine learning that is present and deliberately switched off

### 10.1 `prescreen_prefilter.py` — the embedding path, in shadow

695 lines. This is the only component in the repo that does anything embedding-shaped, and it is wired off.

| Aspect | Detail |
|---|---|
| Purpose | Predict the LLM prescreen decision from accumulated past decisions, so an obvious drop never costs a model call |
| Method | kNN vote over a similarity space |
| Default backend | `lexical` (`config.yaml:2048`) — bag of content words plus character trigrams (`prescreen_prefilter.py:15-19`, imports `:65-67`). **Not embeddings** |
| Optional dense backend | `ollama:<model>` (`prescreen_prefilter.py:22-27`) — real embeddings via a local Ollama model |
| `sentence_transformers` | Accepted as a backend name and **uninstallable on this box** (`prescreen_prefilter.py:30-31`): no cp314 x86_64 wheels |
| Shadow gate | `shadow_mode: true` (`config.yaml:2026`) |
| Thresholds | `threshold: 0.35` (`:2051`), `neighbours: 5` (`:2052`), `min_similarity: 0.15` (`:2053`), `min_exemplars: 20` (`:2054`), `max_exemplars: 500` (`:2055`) |
| Call site | `prescreen.py:173` |
| Return value | **Discarded** — `prescreen.py:167-168` |
| Shadow record | `record_shadow` (`prescreen_prefilter.py:606`), gate at `:588` |
| Regression net | `test_prescreen_result_identical_with_shadow_on_and_off` |

**There is no "act" branch in the code.** Turning `shadow_mode` off does not make the prefilter decide anything; the wiring to use its answer was never written. Anyone planning to "enable the prefilter" must write that branch first.

Before enabling it, read the shadow log: `store/prescreen_shadow/`. It records the prefilter's prediction alongside the LLM's actual decision, which is exactly the agreement rate you need to justify the switch.

### 10.2 `dedup.py` — string similarity, not embeddings

190 lines, pure stdlib, no model. `dedup.py:1-15` states the design: two complementary signals, a pair is a duplicate if **either** fires.

| Signal | Function | Line | Default threshold |
|---|---|---|---|
| Character ratio | `difflib.SequenceMatcher(..., autojunk=False).ratio()` | `dedup.py:68` | `threshold=0.85` (`:57`) |
| Token overlap | Jaccard over content words | `_token_overlap` `:47-51` | `token_threshold=0.34` (`:106`) |

`_STOPWORDS` (`dedup.py:29-36`) is a hand-built list stripping articles, prepositions and business-pitch boilerplate ("service", "revenue", "per month", "customers", "fee"). `_content_tokens` (`:41-44`) keeps non-stopword words longer than two characters.

**Why both signals exist, from the file's own calibration note (`dedup.py:7-12`):** char ratio catches small edits but is blind to the same idea reworded — "Retiree's Garden Legacy" against "Retiree Garden Harvest Share" scores only ~0.43. Token overlap catches those, while genuinely distinct ideas share no content words and score ~0.00. Calibrated against the live catalogue: duplicate pairs ≥0.38, distinct pairs ~0.00 (`dedup.py:27-28`).

The failure it was built to fix is named at `dedup.py:115-118`: the live catalogue accumulated 4 "retiree garden harvest" variants and 2 "probate clear-out" variants, all well under the char threshold.

**Market scoping is a correctness rule, not an optimisation** (`dedup.py:120-124`): the same idea in a different jurisdiction is not a duplicate, because it rests on different evidence. Without scoping, opening a new market would be silently throttled — the second market's candidates collide with the first's and vanish, with nothing in the logs. `drops_by_market` (`dedup.py:183-190`) exists so that throttling is visible if it ever happens again.

**This is where an embedding would genuinely help and does not exist.** A Jaccard over hand-curated stopwords is a bag-of-words method from before 2010. The estate memory records `learning-dedup-semantic-gap.md`. Note the cost though: an embedding dedup needs an embedding backend, and §10.1 shows the only local one is Ollama, which is CPU-only on this box.

---

## 11. Estate-wide: every other model-driven component

The scope here is the whole estate, not just the vetting engine. Same table shape for each.

### 11.1 Hermes — the operator front door

| Aspect | Detail |
|---|---|
| Location | `~/.hermes/hermes-agent`, a fork of an upstream agent framework |
| Scale | `gateway/run.py` 17,343 lines; `cli.py` 13,991; `hermes_cli/main.py` 12,600; `hermes_cli/web_server.py` 12,083; `tui_gateway/server.py` 10,496 |
| Model role | Conversational agent, not a judge. It routes an operator's message to a brain and streams the answer back over Telegram |
| Brain selection | Runtime, per session. `/model` handling at `gateway/slash_commands.py:1143-1513`; short aliases `pi`, `minimax`, `claude`, `cc`, `claude-code` at `:2175-2186` |
| Default provider | `openrouter` (`gateway/slash_commands.py:1143`, `gateway/run.py:10005`) |
| Claude Code as a brain | Via ACP — `hermes-agent/acp_adapter` and `acp_registry`. Warmup is deliberate: "the FIRST ACP turn absorbs asynchronous MCP" (`gateway/slash_commands.py:2210`) |
| Session model override | `gateway/run.py:3079-3092`, logged three ways so a wrong brain is diagnosable |
| Fallback | `gateway/run.py:1611-1613` — the fallback provider resolution once contradicted the operator's config (issue #32790) |
| Think-block stripping | `gateway/stream_consumer.py:344` — the same MiniMax `<think>` problem Prospector solves at `operator.py:37` |
| Consequence tier | Operator-facing. A wrong answer misleads a human; it cannot publish or charge |

**The duplication worth knowing about:** `~/.hermes/.worktrees/feat-prospector-now/` carries a near-identical copy of `gateway/run.py` (17,269 lines against 17,343) and `cli.py` (identical at 13,991). A grep across `~/.hermes` returns both. Always confirm which tree you are reading.

**Hermes has no trust fence.** There is no `moat_primary` equivalent, no provisional stamping, no publication gate. That is appropriate — its output goes to a human, not to a catalogue — but it means the disciplines in §3 do not transfer. Do not assume a Hermes brain switch is as safe as a Prospector one.

### 11.2 Otto and the RSI (recursive self-improvement) loops

| Aspect | Detail |
|---|---|
| Location | `~/.hermes/scripts/otto-*.py` and `otto-*.sh`, 1,585 lines total |
| Files | `otto-dispatch.py` 386, `otto-introspect.py` 293, `otto-learn.py` 221, `otto-why.py` 193, `otto-correction-gate.py` 152, `otto-correction-scan.py` 98, plus 6 shell wrappers |
| Specs | `~/.hermes/specs/otto-recursive-improvement.md`, `~/.hermes/specs/otto-system/`, `~/.hermes/specs/otto-cockpit-audit-2026-07-31.md` |
| What "learning" means | **Policy files, not weights.** `otto-learn.py:26-28`: policies are JSON in `~/.hermes/policies/<id>.json`, firings appended to `~/.hermes/logs/policy-firings.jsonl` |
| Policy id scheme | `pol-YYYYMMDD-NNN` (`otto-learn.py:44-48`) |
| Live state (measured 2026-08-18) | **48 active policies, 227 archived, 115 firings logged** |
| The gate | `otto-correction-gate.py` — three hand-written rule checks: `check_counter_proposal` (`:79`), `check_cron_edit_without_test` (`:98`), `check_orphan_spawn` (`:118`). Logged at `:66` |
| Model use in the gate | **None.** No `claude`, no `model`, no prompt in `otto-correction-gate.py` |
| Model use in the scan | **None.** `otto-correction-scan.py` imports `subprocess` (`:23`) and shells out at `:63`; there is no model call in the file |
| Introspection | `otto-introspect.py:8-13` reports queue depth, in-flight subagents, memory usage, recent failures, regression coverage. Read-only |
| Consequence tier | Meta. It shapes how the agent behaves, and it can edit crons |

**The RSI loop learns rules, not parameters.** A correction the founder makes is turned into a policy file by a human-or-agent decision, and the policy is a `trigger` plus a `rule` string. Nothing is fitted. The 227 archived against 48 active suggests heavy churn — a policy is written, fires or does not, and is retired.

**The known defect class here is that the loops are write-only.** Estate memory records `otto-learning-loops-are-write-only.md` and `rsi-tuned-a-lever-with-no-authority.md`. HYPOTHESIS: some of those 115 firings changed nothing downstream. The exact check: for each firing in `~/.hermes/logs/policy-firings.jsonl`, find the policy's `rule` and test whether any component reads it at decision time — `rg -n "<policy id>" ~/.hermes --glob '!logs'`. A policy no code reads is a comment.

### 11.3 graphify — the code knowledge graph

| Aspect | Detail |
|---|---|
| Binary | `/Users/chidionyema/.local/bin/graphify` |
| Skill | `~/.claude/skills/graphify/SKILL.md`, 675 lines |
| Estate sweep | `scripts/graphify_sweep.py` in this repo, plus `graphify_query_hook.py` and `graphify_session_hook.py` |
| Spec | `docs/GRAPHIFY_ENFORCEMENT_SPEC.md` |
| Output | `graphify-out/graph.json` — **22,310,184 bytes, 19,647 nodes**, keys `directed, multigraph, graph, nodes, links, hyperedges, built_at_commit` |
| LLM use on refresh | **None.** `graphify_sweep.py:21-23` and `:244`: `graphify update` is documented as "no LLM needed", and the sweep uses that path deliberately |
| LLM use on first build | **Yes, possibly.** `graphify_sweep.py:23` and `:385`: a first build runs clustering and may invoke the LLM community-labeller. `--bootstrap` is the flag that permits it |
| Evidence of labelling | `graphify-out/.graphify_labels.json`, 23,651 bytes, last written 2026-08-18 05:40 |
| Query cost | Zero inference. `graphify query "<q>" --budget 2000` is a local BFS over `graph.json` |
| Enforcement check | `python3 scripts/graphify_sweep.py --check-hooks` — exit 0 means wired |
| Consequence tier | Advisory. Graph output is **leads to verify at a `file:line`**, never proof |

**The cost model is the point.** The expensive part (labelling) runs once and is cached in `.graphify_labels.json`; the frequent part (refresh, query) costs CPU and zero tokens. A refresh was running during this session: pid 31641, log `~/.claude/graphify-refresh.log`.

**Never treat a graph answer as a receipt.** The skill and the estate rules both say the same thing: verify at a `file:line`. The graph is a search index that happens to have been labelled by a model once.

### 11.4 pi-bridge — the cheap dev-work executor

| Aspect | Detail |
|---|---|
| Location | `~/.claude/mcp/pi_bridge.py`, 416 lines. Docs at `~/.claude/mcp/README-pi-bridge.md` |
| Default model | `minimax/MiniMax-M3` (`pi_bridge.py:37`) |
| Transport | Shells out to `pi -p -ne` (`pi_bridge.py:215`) |
| The `-ne` flag | Load-bearing (`pi_bridge.py:14`, `:215`): without it, `pi` never exits — observed 300s timeout with work done and the process still alive. With `-ne`: exit 0 in 7s |
| Why two processes | `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` replace the **whole** session brain including verification. It must be a subprocess or Claude loses its own ability to check the work |
| Subprocess discipline | `run` (`pi_bridge.py:130-145`) never raises on non-zero, captures both streams, sets `stdin=DEVNULL`, returns rc 124 on timeout |
| Default timeout | `DEFAULT_TIMEOUT_S`, and `pi_gate` commands default to 600s (`pi_bridge.py:290`) |
| Output | A summary plus a diffstat, never a full diff (`pi_bridge.py:328-329`) |
| Requires | A git repo — "the diff is the audit trail" (`pi_bridge.py:328`) |
| Consequence tier | Writes code. Fenced |

**The fence is in the server, not in a prompt.** Two tiers, `pi_bridge.py:70-110`:

`HARD_PATTERNS` — never dispatched, and a breach if written anyway:
```
\bbridge\.py\b   \bpricing\.py\b   /Payments?/   \bstripe   \bpaddle
\bwebhook        \bentitlement     PackPrice     MoneyRail
/Auth/           /Identity/        /Contracts?/  \bmigrations?/   \balembic\b
```

`REVIEW_PATTERNS` — dispatched freely, but the run report cannot be read without seeing them:
```
\bcheckout   /Endpoints?/   \bfulfilment   \bfulfillment
```

Three details worth carrying:

1. **The missing trailing `\b` is deliberate** (`pi_bridge.py:80-82`): `\bcheckout\b` needs a non-word character to close, and CamelCase never gives one, so it silently missed `CheckoutEndpoints.cs`. Leading `\b` only.
2. **The two-tier split exists because "never" gets routed around.** `pi_bridge.py:70-75`: before the split, the only way to say "read this carefully" was to say "never", and never is what a human does by hand at full price.
3. **The fence banned a directory once, not a risk.** Estate memory records `pi-bridge-fence-banned-a-directory-not-a-risk.md`, and `pi_bridge.py:48-62` records the correction: 414 source files sat under the over-broad pattern, roughly 40 of them money surface, so it refused almost everything. The patterns now name the money surface itself, and `checkout` is treated as a domain word appearing in every plan.

Checked twice: `fence_violations` (`pi_bridge.py:~112`) is a prose pre-check on the plan, HARD only; `fenced_paths` is the exact post-check on the paths actually written, and a hit prints `!! FENCE BREACH` (`pi_bridge.py:263-264`). A prose check alone would be defeated by a plan that does not name the file.

There is a test: `~/.claude/mcp/test_pi_bridge_fence.py`.

### 11.5 Estate summary

| Component | Trains anything? | Model role | Trust fence | Failure mode if the model is wrong |
|---|---|---|---|---|
| Prospector verdicts | No | Judge | `moat_primary()` + provisional stamping + publish gate | A bad idea publishes, or a good one dies |
| Prospector generation | No | Creative | None needed — nothing is killed at generation time | A wasted batch |
| Prospector artifacts | No | Product author | `pack_linter.check_shelf_copy` regrades and regenerates | A weak £49 deliverable ships |
| Prospector prefilter | No (kNN over past decisions) | Predictor | Shadow mode, return value discarded | None today — it is inert |
| Prospector dedup | No (pure string) | None | n/a | Duplicate catalogue entries |
| Hermes | No | Conversational agent | **None** | A human is misled |
| Otto / RSI | No (JSON policy files) | Rule store, no model in the gate | Hand-written rule checks | A policy fires and changes nothing |
| graphify | No (one-off LLM labelling) | Search index labeller | "Leads, never proof" | A misleading lead, verifiable at a `file:line` |
| pi-bridge | No | Code executor | HARD/REVIEW regex fence, server-side, plus a post-write path check | Code written on fenced surface — caught and reported as a breach |

**One pattern runs through all nine.** Wherever a model's output can cause irreversible harm, there is a deterministic gate downstream of it that the model cannot influence: the kill filter, the shelf-copy linter, the fence regex, the publish gate. Wherever it cannot, there is no gate. That is the estate's actual safety architecture, and it is more robust than prompt-level instruction because a prompt is data the model can be talked out of.

---

## 12. Failure modes

| Symptom | Root cause | Fix |
|---|---|---|
| A dossier where every check reads "Verdict call failed; fail-safe." and the decision is a confident KILL | An exception in the verdict call contributed `unverifiable` to the kill gates | Fixed 2026-08-06. `retrieval_failed=True` (`verify.py:569`) fires DEFER (`verify.py:1134-1151`). Original receipt: `store/dossiers/2102bacc6dd75cf9.kill.json` |
| A live, healthy brain is benched | Bare substring match on an HTTP code hit `4291 bytes` or `req_id=a429f0` | Word boundaries in `_HTTP_TRANSIENT_RE` / `_HTTP_PERMANENT_RE` (`errors.py:139-147`). Never remove a `\b` |
| A brain that recovers in 90s stays benched for an hour | No half-open probe, or every process claiming it at once | `_claim_probe` with `fcntl.flock` (`health.py:151-197`), fixed 2026-08-10 |
| A fully grounded candidate killed as `moat_ungrounded` | `_calc_confidence` took most of its value from citation volume; a terse brain scored 0.238 | `max(fraction, saturating)` and lone-domain 0.15 (`verify.py:110-136`, `:161-171`) |
| A brain is scored FAIL for a style difference | Same defect, seen from the roster side — the 0.96 golden FAIL was the scorer, not the brain | Measure the scorer before reverting a roster (`CLAUDE.md`, `verify.py:110-127`) |
| The daemon mints work no brain can finish | Generation preflight was trusted-only, so a live provisional brain looked like no brain | `health.moat_blind_reason(cfg, trusted_only=False)` (`scheduler/run_scheduled.py:465`) |
| The drain spends money and moves nothing | Re-vetting a provisional row on a provisional brain re-stamps it `provisional` | Drain stays `trusted_only=True` (`run.py::_cmd_resume`). Measured 2026-08-06: provisional −14 / defer +13 over 30 minutes, net −1 |
| A stale config silently builds a shorter chain | A removed tier name was skipped instead of rejected | `_build_operator` raises `ValueError` for `claude`, `standardcompute`, `cursor_cli` (`operator.py:1636`) |
| A brain reaches its usage limit and nothing notices | The classifier missed the wording | `_ALLOWANCE_LIMIT_RE` (`errors.py:128-130`) — the CLI says **spend** limit, not usage limit |
| MiniMax output fails to parse | Inline `<think>` blocks | Stripped by `_RE_THINK` (`operator.py:37`) in strategy 2 of `_extract_json`; Hermes does the same at `gateway/stream_consumer.py:344` |
| A truncated response is lost | Stream cut mid-JSON | `_tail_json_candidates` (`operator.py:261`) plus truncated-retry max 2 (`operator.py:644`) |
| The MiniMax call hangs forever | No stall detection | `_STALL_TIMEOUT_S = 90` (`operator.py:642`), `_TOTAL_DEADLINE_S = 600` (`:643`), stall retry 1 (`:649`) |
| `pi` never exits, 300s timeout with the work already done | Missing `-ne` | `pi_bridge.py:215`. With `-ne`: exit 0 in 7s |
| The pi-bridge refuses almost every plan | The fence banned a parent directory rather than the money surface | Patterns now name the surface; `checkout` moved to REVIEW (`pi_bridge.py:48-62`, `:98-104`) |
| `CheckoutEndpoints.cs` slipped past the fence | `\bcheckout\b` needs a non-word char to close and CamelCase gives none | Leading `\b` only (`pi_bridge.py:80-82`) |
| A market opens and produces nothing, silently | Dedup collided the new market's candidates with the first's | Market-scoped dedup (`dedup.py:120-124`) and `drops_by_market` (`:183-190`) |
| "Discrimination 1.00, the brain reasons correctly" | `gate_match` is computed and not scored; the 1.0 run got the gate wrong on 5 of 9 | Read `gate_match` and `deferred` from the run file, never the ratio alone (§7.4) |
| A `--min-discrimination 1.0` gate compared against a wrong baseline | 1.0 has rarely been reached; `golden.py:444-448` recommends the *relative* bar against the incumbent measured the same day | Use `--min-discrimination <incumbent score>` |

---

## 13. Invariants

Break any of these and the system stops being a filter.

1. **Only a brain in `moat_primary()` may rule finally.** `operator.py:1509-1514`, enforced at publish by `run.py:864`. Break it and an untrusted brain's PASS reaches the catalogue.
2. **A parse failure or exception DEFERS; it never becomes evidence.** `verify.py:569` and `verify.py:1134-1151`, backed independently by `kill_filter.py:34-35`.
3. **The model's self-reported confidence is never used.** `_calc_confidence` (`verify.py:91`) overwrites it at `verify.py:591`.
4. **A `supported` verdict with no resolvable citation is downgraded.** `verify.py:583-586`. Zero violations in 3,079 supported checks.
5. **`price_comparables` can never kill.** `kill_filter.py:28-29` and `verify.py:1031`.
6. **Permanence is classified by one shared function.** `errors.looks_exhausted` (`errors.py:263-269`). A second classifier is a second set of bugs.
7. **A dead brain leaves a trace.** `health.mark_exhausted` writes to `store/provider_health.json`. A fallback chain that works hides its own degradation.
8. **The non-critical chain never rules a verdict.** Its own health file (`health.py:42`), its own breaker, and `_noncritical_order` (`run.py:320`) strips `claude_cli` via `_NONCRITICAL_FORBIDDEN`. If every tier fails it raises rather than promoting itself.
9. **The pi-bridge fence lives in the server, not in a prompt.** `pi_bridge.py:76-110`, checked on the plan and again on the written paths.
10. **Fixtures force the retrieval chain.** `retrieval.py:2465-2466`. A test cannot reach the live web.
11. **`moat_blind_reason` reads raw `dead_until`, never `is_dead`.** `health.py:328-330`. A bookkeeping check must not consume the half-open probe.

---

## 14. How to change it safely

### 14.1 Changing a prompt

The riskiest change in this repo, because it has no type check and no compile step.

1. Edit the `.md` file in `prompts/`. It is read at call time (`prompts.py:243`) — no restart needed, which is also the risk.
2. Run the golden set **offline**, which uses fixtures and costs no web calls:

```bash
.venv/bin/python -m prospector.golden --operator minimax --runs 1
```

3. For a promotion-grade change, three consecutive runs at the bar:

```bash
.venv/bin/python -m prospector.golden --operator minimax --runs 3 --min-discrimination 1.0
```

4. **Read `gate_match` in the run file, not only the ratio.** The 2026-08-15 1.00 run had `gate_match: False` on 5 of 9 (§7.4). A prompt change that improves decisions while degrading reasons will pass the gate.
5. Check the run persisted: `ls -t store/golden_runs | head -3`.

The test that catches a mistake: `tests/test_golden_set.py:163` asserts discrimination == 1.0 (`:189`) and the set length == 9 (`:190`). `tests/unit/test_golden_score_is_decision_only.py` pins the decision-only scoring rule.

### 14.2 Changing the provider roster

1. Edit `config.yaml:58` (`operator:`) and/or `config.yaml:81` (`moat_primary:`). **Order is call order.**
2. Names must be in `BUILDABLE_TIERS` (`operator.py:1632`) or startup raises.
3. Run the golden gate above with the new tier as `--operator`.
4. Verify no dead mark blocks it: `python3 -c "import json;print(json.load(open('store/provider_health.json')))"`.
5. To revert the trust fence, delete the name from `moat_primary:` only. Per `config.yaml:78-83`, that stops future publishes immediately; already-listed packs stay listed until unlisted deliberately.
6. Promotion is a config line plus the golden gate. Never a source patch.

Tests that catch a mistake: `tests/invariants/test_chain_degradation.py`, `tests/integration/test_golden_promotion_cli.py:90/:110/:166`.

**Do not write a test that hardcodes "minimax = untrusted".** As of 2026-08-15 MiniMax is inside `moat_primary`. A test asserting otherwise pins the roster, not the fence. Assert on `is_provisional_provider(name)` against `moat_primary()`, never on a brand name.

### 14.3 Changing a threshold

1. Edit the key in `config.yaml` — `thresholds:` at `:496`, lane blocks at `:615`.
2. Replay historical kills through the current gate logic before shipping:

```bash
.venv/bin/python tools/experiments/e11_confidence_floor.py
```

3. **Know what the replay cannot see.** It reproduces hard gates only, which is 516 of 2,698 kills — 19.1%. `moat_ungrounded`, `min_composite` and `source_or_die` (75.7% of kills) are not replayed. Any threshold conclusion from this harness covers the smaller fifth of the problem.
4. Re-measure the confidence distribution afterwards; see [analyst.md](analyst.md) §5.3 for the method and the current numbers.

### 14.4 Changing `_calc_confidence`

The highest-blast-radius change available, because every threshold in the system is calibrated against its output distribution.

1. Change the weights or a term at `verify.py:109-192`.
2. Recompute the distribution over the existing 14,006 checks **offline** — the function is pure, so you can replay it from the stored `sources` and `citations` without a single model call.
3. Compare the new distribution against `confidence_floor: 0.4` and `min_supported_confidence: 0.3`. The 2026-08-15 change already moved the supported median from 0.430 to 0.630 without anyone updating those floors (`config.yaml:517-524` is now stale — see [analyst.md](analyst.md) §5.4).
4. Run the golden gate. The 2026-08-15 defect was caught by a golden PASS turning into a KILL, which is exactly what the gate is for.

### 14.5 The commit gate

There is no pre-commit hook installed in this checkout as of 2026-08-17. Check, never trust prose:

```bash
git config --get core.hooksPath          # set => THAT directory wins
ls -la "$(git rev-parse --git-path hooks)"/pre-commit
```

Preflight without committing: `.venv/bin/python scripts/popdd_verify.py --staged`.

---

## 15. Open gaps and debt

| Gap | Why it costs you | Cost to close |
|---|---|---|
| **No determinism test.** The "4 of 6 candidates changed tier across 3 repeat runs at temperature 0" figure is a comment at `classify.py:73`, not a gate | A brain can become non-deterministic and nothing notices. The routing call this affects picks the lane the idea is judged against | **Low.** A repeat-N harness over fixtures, asserting stability per role. Half a day |
| **Temperature is a no-op on both live moat brains** (`operator.py:731-765`, `claude_cli.py:433-435`) | Every "deterministic because temperature is 0" claim about the verdict path is false today | **Low to investigate, unknown to fix.** Check whether the MiniMax API accepts `temperature`; if it does, add it to the payload and re-run the golden gate. The CLI cannot be fixed — no flag exists |
| **No calibration measurement of any kind** (§9) | Every threshold was set against a distribution, never an accuracy | **Medium.** Needs labelled outcomes. Cheapest first step is sale-outcome labelling of 108 passes + 119 listings, binned by moat-check confidence |
| **The golden set is 9 cases** and it is the only regression net for every prompt | A prompt change that degrades a whole category can pass 9/9 | **Medium.** `prospector/golden_gen.py` exists to generate cases. Growing to 30 with the same `label_basis` discipline is mechanical work |
| **The MiniMax promotion receipt is not on disk** (§7.4d) — one 1.00 run, `total_runs: 1`, against a documented claim of three consecutive | The trust fence's justification cannot be checked | **Trivial.** Re-run `--runs 3 --min-discrimination 1.0` and let it persist |
| **`gate_match` was False on 5 of 9 in the best run ever recorded**, and it is not scored | The brain reaches the right verdict by a different route than the label. Nobody is tracking whether that gap grows | **Low to measure**, since the field is already written to every run file. A trend line costs one script |
| **`e11`-style replay covers hard gates only** — 19.1% of kills | Threshold work systematically ignores the dominant failure mode | **Low-medium.** Extend the harness to call `pass_ceiling.pass_impossible_reason` and `dossier.build` |
| **The embedding prefilter has no "act" branch** (§10.1) | "Enable the prefilter" is not a config change; the wiring does not exist | **Medium.** Write the branch, then justify it from `store/prescreen_shadow/` agreement rates |
| **Dedup is Jaccard over a hand-curated stopword list** (§10.2) | Semantically identical ideas in different words survive | **Medium.** Needs an embedding backend; the only local one is Ollama, which is CPU-only on this box |
| **`store/provider_health.json` holds 8 fossil entries** for tiers no longer on any chain, including `cursor_cli`, removed 2026-08-06 | Health output is misleading at a glance | **Trivial.** Prune entries whose name is not in `BUILDABLE_TIERS` |
| **`specs/offline-moat-validation.md:59` says 8 golden cases; disk has 9** | A spec that disagrees with the fixture it describes | **Trivial.** One-line edit |
| **Otto's RSI loops may be write-only** — 115 firings, 48 active policies, 227 archived | A policy that fires and changes nothing is a comment with a log line | **Low to measure.** For each policy id, grep the estate for a reader outside `logs/` |
| **Hermes has no trust fence** (§11.1) | Correct for its role, but the safety patterns in §3 do not transfer, and someone will assume they do | **None** — document it, which this does |

---

## 16. Where to look next

Model routing and trust:

```
prospector/operator.py:291    Operator ABC — the one contract every brain implements
prospector/operator.py:329    complete_json — JSON suffix, repair retry, re-raise
prospector/operator.py:73     _extract_json — the 5-strategy parse cascade
prospector/operator.py:1443   moat_primary() — env > config > default
prospector/operator.py:1509   is_provisional_provider — the fence, one line
prospector/operator.py:1516   FallbackOperator — thread-local served tier, breaker skip, raise on exhaustion
prospector/operator.py:1632   BUILDABLE_TIERS
prospector/operator.py:1636   _build_operator — explicit ValueError for removed tiers
prospector/claude_cli.py:427  ClaudeCliOperator — subprocess, temperature dropped at :433
prospector/claude_cli.py:186  telemetry.PRICING — and why claude_cli is absent
```

Judgement:

```
prospector/verify.py:91       _calc_confidence — and the defect note at :110-127
prospector/verify.py:461      verdict_for
prospector/verify.py:721      run_check
prospector/verify.py:870      adversarial
prospector/verify.py:1019     the run order
prospector/verify.py:1134     the DEFER gate
prospector/kill_filter.py:20  is_hard_fail
prospector/pass_ceiling.py:59 pass_impossible_reason
prospector/dossier.py:100     the decision
```

Failover:

```
prospector/errors.py:184      classify_exhaustion
prospector/errors.py:139      the word-boundary incident note
prospector/health.py:151      _claim_probe — the half-open probe under flock
prospector/health.py:304      moat_blind_reason
```

Evidence:

```
prospector/retrieval.py:2445  make_provider — the wrapper stack
prospector/retrieval.py:2177  FallbackSearchProvider
prospector/retrieval.py:492   RelevanceRankedProvider
prospector/retrieval.py:1072  FixtureProvider
prospector/prompts.py:229     render — market + style layering
```

Regression:

```
prospector/golden.py:249      passed = decision_match and not deferred and not unusable
prospector/golden.py:343      scored = total - deferred_count
prospector/golden.py:132      why gate_match is reported and not scored
fixtures/golden_set.json      9 cases
store/golden_runs/            77 run files
prospector/markets.py:35      DEFAULT_BARS — the market readiness gate
```

Estate:

```
~/.hermes/hermes-agent/gateway/slash_commands.py:1143   Hermes model routing
~/.hermes/hermes-agent/acp_adapter/                     Claude Code as a Hermes brain
~/.hermes/scripts/otto-learn.py:26                      the policy store
~/.hermes/scripts/otto-correction-gate.py:79            the three rule checks
~/.claude/mcp/pi_bridge.py:76                           HARD_PATTERNS
~/.claude/mcp/pi_bridge.py:215                          the -ne flag
scripts/graphify_sweep.py:244                           the LLM-free refresh path
docs/GRAPHIFY_ENFORCEMENT_SPEC.md                       the enforcement programme
```

Commands:

```bash
.venv/bin/python -m prospector.run operators          # which chains are live
.venv/bin/python -m prospector.run lanes              # per-lane gates and thresholds
.venv/bin/python -m prospector.golden --operator minimax --runs 1
python3 scripts/graphify_sweep.py --check-hooks       # exit 0 = graph enforcement wired
python3 -c "import json;print(json.load(open('store/provider_health.json')))"
```

Sibling personas: [analyst.md](analyst.md) for what the outputs mean once written; [data-engineer.md](data-engineer.md) for how the store is written; [sre-on-call.md](sre-on-call.md) and [ops.md](ops.md) for the daemon; [security.md](security.md) for the key surface; [qa-test-engineer.md](qa-test-engineer.md) for the suite. Estate map: [../ESTATE_MAP.md](../ESTATE_MAP.md).

**Last measured: 2026-08-18.** Line numbers move. Re-check any `file:line` before quoting it.
