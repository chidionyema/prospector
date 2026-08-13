# Prospector Engine — Fact-Based Code Audit

**Scope:** the "prospector engine" as CLAUDE.md's own Architecture section defines it — `config.py`,
`models.py`, `operator.py`, `errors.py`/`health.py`, `breaker.py`, `retrieval.py`, `prompts.py`,
`generate.py`/`dedup.py`/`prescreen.py`, `verify.py`, `price_comparables.py`, `pricing.py`,
`kill_filter.py`, `score.py`, `dossier.py`/`store.py`/`publish.py`, `bridge.py`, `run.py`. Explicitly
excludes control_center, telegram-adjacent, and Otto/RSI code — those are separate subsystems per
project memory.

**Method:** checked out latest `origin/main` (`434024e`) into a clean worktree, read every file above
in full, verified every claim below against that source with `grep`/`sed`/direct execution — no
speculation, no reliance on memory or prior descriptions. Six review passes ran in parallel, one per
file cluster; headline findings from the two earliest passes were independently re-verified by direct
grep/execution rather than taken on trust (see "Spot-check" notes). **No code was changed.**

Severity is about **blast radius under today's shipped `config.yaml`**, not about how bad the bug
would be in the abstract — a bug that's dead code today is flagged as such.

---

## 0. Status ledger (the part that goes stale — update it here, in the repo)

This file was written as a scratchpad transcript on 2026-08-10 and committed the same day, because a
spec that lives only in a transcript evaporates (project memory: `a-spec-that-lives-only-in-a-transcript`).
The audit BODY below is a dated record and is not edited as fixes land; this table is.

Every fixed row was proved twice: the defect reproduced against pre-fix `origin/main`, then the same
probe re-run against the fix. Findings 5-9 were reproduced by direct execution, not only by test —
notably #6 (two identical publishes minted two different Stripe idempotency keys) and #9 (6 processes
x 12 increments = 72 expected, 22 recorded, 50 lost).

| # | Severity | Finding | Status | Where |
|---|---|---|---|---|
| 1 | HIGH | `ClaudeOperator._raw` has no try/except, so the trusted tier never reaches the persisted dead-mark | **Fixed** | PR #173 (`20e008c`) |
| 2 | HIGH | `_claim_probe`'s "exactly one caller machine-wide" is not cross-process safe | **Fixed** | PR #173 (`20e008c`) |
| 3 | HIGH | `score_checks`-only checks can KILL on an outage with no DEFER | **Fixed** | PR #173 (`20e008c`) |
| 4 | HIGH | Daily spend cap is blind to `standardcompute` | **Fixed** | PR #173 (`20e008c`) |
| 5 | HIGH | A PASS whose publish step fails is indistinguishable from a published PASS | **Fixed** | this PR — `run.publish_and_record`, `Dossier.publish_status`/`publish_error` |
| 6 | HIGH | Stripe idempotency key fingerprints a wall-clock field that changes every call | **Fixed** | this PR — `bridge._bundle_version` |
| 7 | HIGH | `_one_call`/`_refine_wave` catch `ProviderExhaustedError` as bare `Exception` | **Fixed** | this PR — `generate(diagnostics=...)`, mid-run exhaustion reported by `run_signal` |
| 8 | MEDIUM-HIGH | `moat_grounded` gate bypassable on the manual `publish_offline` path | **Fixed** | this PR — `dossier.grounded_support`, one function, two callers |
| 9 | MEDIUM-HIGH | `drain_state.record_unresolved` is an unlocked read-modify-write | **Fixed** | this PR — `fcntl.flock` via `_LedgerLock` |
| 10 | MEDIUM | Duplicate module-level `_DISCONFIRM_TEMPLATES` shadows the Stage-1 templates | **Fixed** | this PR (`90a9eec`) — A1, four Stage-1 keys merged into the surviving dict |
| 11 | MEDIUM | Three `retrieval.py` siblings still swallow errors to empty | **Fixed** | this PR (`90a9eec`) — A2, Brave / DeepSeek / MiniMax now `raise` |
| 12 | MEDIUM | `ContextVar` market authority invisible inside the grounding thread pool | **Fixed** | this PR (`90a9eec`) — A3, `contextvars.copy_context()` + `ctx.run` |
| 13 | MEDIUM | `automatability_floor` is a quality-based drop inside generation | **Fixed — floor DELETED** | this PR — B4; reasoning below the table |
| 14 | MEDIUM | `MOAT_PRIMARY` provisional-stamping single-operator gap | **Fixed** | this PR — B2, `Operator.tier_name` stamped by `make_operator`'s one-tier branch, read by a new base-class `Operator.served_is_provisional`. Keys off the CONFIG TIER, never `op.name`: `ClaudeOperator.name` is `claude/<model>`, absent from `MOAT_PRIMARY`, so name-keying would mark a **trusted** `operator: claude` config provisional — the opposite defect. Fixtures constructed directly carry no tier and stay non-provisional, which is what keeps the publish path testable |
| 15 | MEDIUM | `score.py`'s scoring fail-safe logs nothing at all | **Fixed** | this PR (`90a9eec`) — A4 |
| 16, 21 | MEDIUM / LOW | `dense_reward` divides by 6.0 against a composite maxing at 5.0; constants unconfigurable | **Fixed** | this PR (`90a9eec`) — A5, `_DENSE_REWARD_*`. **SCALE BREAK:** every `dense_reward` already in `store/` used /6.0 and is not comparable; deliberately not backfilled |
| 17 | MEDIUM | `config.py`'s two hardcoded `minimax_fast` defaults disagree | **Fixed** | this PR (`90a9eec`) — A6, one literal |
| 18 | MEDIUM | `weights` block has no schema validation | **Fixed** | this PR (`90a9eec`) — A7, `_validate_weights`; unknown axis / negative / sum≠1.0 all raise, **no silent rescaling** |
| 19 | LOW-MEDIUM | Currency is a hardcoded Python default on both `create_price` methods | **Superseded — designed, not implemented** | Founder decision 2026-08-10 upgraded this from a config nit to "charge US buyers in USD". Design: `specs/b1-usd-billing-design.md`. Blocked on one Stripe go/no-go (can `currency_options` be added to an existing Price?) |
| 20 | LOW | `pricing.py`'s no-ladder fallback price is a hardcoded literal | **Fixed** | this PR — B3, `config.LISTING_DEFAULTS`. `load_config` merges it **under** `config.yaml`, so a declared price always wins and a code default can never re-price the catalogue; `pricing.py` reads that one source instead of carrying a second `4999` on the money path |
| 22 | LOW | `verify.py` docstring overclaims "tracks provider_chain" | **Fixed** | this PR (`90a9eec`) — A8 |
| §1 | doc drift | CLAUDE.md / RUN.md claims that are currently false | **Fixed** | this PR (`90a9eec`) — A10 (all five rows). A9 additionally replaced every stale `operator.py:8xx` citation with the **symbol name**, number dropped, so it cannot go stale again — including the three sites outside A9's allowlist (`config.yaml:9`, `config.yaml:56`, `docs/COMMERCIAL_READINESS_PROGRAM.md:1156`) |

**On #13 — the floor was deleted, not fenced.** The founder delegated the call ("use your best
judgement"). The decisive argument is not the CLAUDE.md invariant ("nothing is killed at generation
time") but the weights themselves: `config.yaml`'s `weights:` block was re-cut on 2026-06-25
*because* rewarding automatability "IS trivially easy to clone = no moat" — `automatability` .20 →
.15, `defensibility` .15 → .25. A hard floor hands `automatability` an **effective veto**, i.e.
infinite weight, on the exact axis the composite deliberately demoted. It also dropped on a
self-graded, pre-retrieval number. Nothing of the intent is lost: the same profile still expresses
"online, no human in the loop" through `structural_forms` + `focus`, which is steering, not killing.
`_automatability_score` is **kept** despite losing its only caller — `sampling.typicality_score`
names it as the rule it mirrors.

Fix #6 deliberately did NOT take the obvious route of excluding `bundle_version` from the fingerprint.
That would produce *same key + different params*, which Stripe rejects as a hard error — the exact
2026-08-08 failure that left `13795bea31feee47` and `2abc23c3c0d05bab` unlistable. The field was made
deterministic instead.

Regression cover for 5-9: `tests/unit/test_engine_audit_findings_5_to_9.py`.

---

## 1. Documentation drift (fix the docs, not urgent, but currently false)

| Claim in CLAUDE.md | Reality | Evidence |
|---|---|---|
| Architecture: "`dossier.py` / `store.py` / `publish.py`" implies `publish.py` lives in `prospector/` | `prospector/publish.py` is a **0-byte dead stub**; the real, imported module is the top-level `publish/publish.py` (259 lines) | `wc -c prospector/publish.py` → `0`; `git log --follow -- prospector/publish.py` → content removed in `5f95ca7` (2026-06-15); real callers: `tools/publish_offline.py:25`, `tools/publish_passes.py:48`, `run.py:545`, `tests/unit/test_dry_run_gate_mints_nothing.py:190`, `tests/behavioural/test_publish.py:18` |
| `MOAT_PRIMARY` lives at `operator.py:885` (also cited as `:875` in `run.py:291`, `:889` in `claude_cli.py:145`/`cli_auth.py:37-38`) | Actually at `operator.py:1068` in current `main` | Direct read of `operator.py:1068` |
| "default 5 candidates per signal" | `config.yaml:764` sets `candidates_per_signal: 20`; `schedule.batch_size` is `15` (`config.yaml:1389`, "was 5: founder directive 2026-07-31") | Config is correctly the source of truth (no hardcoding violation) — the CLAUDE.md *number* is just stale |
| "embed-match against the catalogue to drop near-duplicates" (`dedup.py`) | `dedup.py` is pure stdlib `difflib.SequenceMatcher` + Jaccard token overlap — **no embeddings**. A real embedding component exists (`prescreen_prefilter.py`) but never affects any decision (`config.yaml:1192-1194`) | Direct read of `dedup.py`; grep for embedding calls |
| RUN.md: "Each batch writes a timestamped run log to `store/runs/`" | No such directory or code path exists; `store/runs` only appears in an unrelated comment (`config.py:134`) and `golden.py:180` (`store/golden_runs`, calibration-only) | `grep -rn "store/runs" prospector/*.py` → no batch-run writer |
| "one PriceDecision mints the provider Price AND writes the catalogue row, so the two cannot drift" | The *price number* is single-sourced correctly, but the two **writes** (`create_price` then `_update_catalog`) are two separate network calls with no transaction/rollback | `bridge.py:995-1008` vs `~1078` |

---

## 2. Findings, most severe first

### HIGH — `ClaudeOperator` failures never reach the persisted dead-mark, defeating its own trust tier
`ClaudeOperator._raw` (`operator.py:172-185`) has **no try/except at all**. Any Anthropic SDK error —
including a genuine 402/credit-exhausted response — propagates as a raw exception, is caught by
`FallbackOperator`'s generic `except Exception as e:` with `hard=False` (`operator.py:1148-1178`), and
therefore never runs through `classify_exhaustion` / never reaches `_health.mark_exhausted`. It only
counts toward the in-process `CircuitBreaker` (default threshold 3, cooldown 60s, **reset on every
process restart, never persisted**). Since `"claude"` is itself one of the two `MOAT_PRIMARY` names,
the one operator kind singled out as trusted has none of the persisted-dead-mark protection every
other adapter (MiniMax, DeepSeek, StandardCompute, Ollama) gets via `looks_exhausted`.
**Failure scenario:** claude_cli's Anthropic key hits a real 402 mid-run; the daemon retries it fresh
on every subsequent tick instead of benching it for the documented 1h, paying the cost of a doomed
call every time. — *Agent: operator/reliability audit.*

### HIGH — Half-open probe claim ("exactly one caller machine-wide") is not cross-process safe; race reproduced by execution
`_claim_probe` (`health.py:130-153`) is a read-JSON/compute/atomic-rename sequence guarded only by a
`threading.Lock()` — a **separate lock object per process**. Two independent `ProviderHealth`
instances pointed at the same health file were run against each other directly:
```
process 1 believes it claimed the sole probe slot: True
process 2 believes it claimed the sole probe slot: True
=> both processes would now call the struggling brain simultaneously: True
```
This is the exact stampede the docstring says it prevents, live between e.g. a daemon tick and a
manual `vet --resume` against the same store — a scenario CLAUDE.md's own "Working in a git worktree"
section calls operationally realistic ("this checkout is often shared by two concurrent sessions").
— *Agent: operator/reliability audit.*

### HIGH — `score_checks`-only checks can KILL on an outage with no DEFER, reproducing the 2026-08-06 incident in narrower form
The documented fix ("an exception is never evidence; a failed call DEFERs") is **confirmed for hard
gates, contradicted for score-only checks**. `verify.py:862-870`'s DEFER_GATE only fires `if name in
cfg.gate_map()`; `kill_filter.py:34` also only special-cases `retrieval_failed` there. A lane can
declare `score_checks` entries that are not hard gates — `config.yaml:410-417` (side_hustle lane) does
exactly this for `claims_verifiable`/`payer_solvency`/`distribution`/`pain_reality`. `score.py` has
**zero references to `retrieval_failed`** (confirmed by grep) — a retrieval outage on one of those
checks becomes an ordinary `unverifiable, conf 0.0` claim fed straight to the LLM scorer, which can
legitimately drag the composite below `min_composite_to_pass`, producing `Decision.KILL,
gate_fired="min_composite"` (`dossier.py:157-166`) — a candidate killed by an outage, indistinguishable
from a candidate killed on the merits, on the side_hustle lane specifically. This is the same shape as
the cited incident dossier (`2102bacc6dd75cf9.kill.json`), surviving for the one class of check the
original fix didn't cover. — *Agent: verify.py / the moat audit.*

### HIGH — Daily spend cap is structurally blind to `standardcompute`, now the head of the non-critical chain
`run.py:317`: `_NONCRITICAL_ORDER = ("standardcompute", "claude_cli", "minimax")`. But
`telemetry.py:173-179`'s `PRICING` dict has no `standardcompute` key, so `record_usage`'s `cost`
computes to `0`, and `if cost > 0:` (`telemetry.py:248`) means **no `event:"spend"` ledger row is ever
written** for standardcompute calls. `scheduler/guard.py:126-166`'s `daily_cap_usd` sums only
`event=="spend"` rows. **Net effect: the daemon could run entirely on billed standardcompute calls all
day while the ledger reads $0.00 spent and the cap never trips** — a config-reachable version of this
repo's own tracked defect class (`spend-brake-watches-the-wrong-meter.md`). `report.py:376` also calls
`get_price(root)` with no `cfg` arg, so `config.py:244`'s config-aware pricing path (added specifically
to warn about this) never fires either. — *Agent: run.py orchestration audit.*

### HIGH — A PASS whose publish step fails is silently indistinguishable from a published PASS
`run.py:543-548`: a publish failure is caught, logged at `logger.error` (routed to
`store/prospector.jsonl`, not the interactive progress stream), and swallowed — `vet_candidate`
returns the dossier normally, no exit-code change, no field anywhere in the dossier/model schema
records publish success/failure (`grep -n "published\|listing"` on `dossier.py`/`models.py` → nothing
but an unrelated `Source.published_at`). **Failure scenario:** `vet --publish` or a scheduled batch
prints "PASS" with no visible error while `store/listings/<id>.json` was never written — exactly the
drift class this repo's memory already tracks (`a-listed-pack-had-only-a-kill-dossier.md`). —
*Agent: run.py orchestration audit.*

### HIGH — Stripe idempotency key is fingerprinted over a field that changes on every call, contradicting its own docstring
`bridge.py:993` builds product metadata with `"bundle_version": datetime.utcnow().isoformat()`; that
metadata is hashed into the idempotency-key fingerprint (`bridge.py:1744`, key built at `:1753`).
Because `bundle_version` differs on every invocation, **the idempotency key can never repeat for the
"same" logical publish**, directly contradicting the method's own docstring ("a publish retry after a
network blip replays an identical request under the same key and reuses the Stripe-side product").
**Failure scenario:** a network blip after Stripe accepts `create_product` but before the client sees
the response, followed by a client-side retry, mints a permanently-orphaned second product. The
separate durable republish-dedup (`_resolve_money_rail` reading the catalogue's `providerPriceId`) is
correctly designed and unaffected — this bug is scoped to the *first* mint of a given pack, not
republishes. — *Agent: artifacts/money-rail audit.*

### HIGH — `_one_call`/`_refine_wave` catch `ProviderExhaustedError` as bare `Exception`, hiding mid-run chain exhaustion
`generate.py:386-393` and `generate.py:526-528` both catch the non-critical generation chain's
exhaustion the same way as any other error, so a chain that dies partway through refinement (e.g.
waves 1-2 already produced survivors, wave 3 exhausts) is silently absorbed into "fewer/unrefined
candidates" rather than triggering the documented `_save_pending_signal`/"chain exhausted" logging in
`run.py:763-770` — which only checks the **aggregate** `if not candidates:`, missing exactly this
partial-exhaustion case. — *Agent: generate/dedup/prescreen audit.*

### MEDIUM-HIGH — `moat_grounded` gate can be bypassed on the manual `publish_offline` path
`tools/publish_offline.py:41` trusts whatever `"decision"` string is in a hand-fed dossier JSON file
and calls `publish()` if it reads `"pass"`. The only backstop, `EngineBridge.publish_pass`'s own
re-check (`bridge.py:523-542`), is **weaker** than the real gate in `dossier.py:106-157` — it requires
only `n_supported >= 1` against `confidence_floor`, never checking `moat_grounded` (the
lane-decisive-check requirement) and never preferring `min_supported_confidence`. No signature ties a
persisted `decision` field to the checks that produced it. **Concrete gap:** a dossier JSON hand-edited
from `"kill"` to `"pass"` (or one built before the moat_grounded fix) with one incidental supported
check clears the weaker guard via `--all`. — *Agent: artifacts/money-rail audit.*

### MEDIUM-HIGH — `drain_state.record_unresolved` is an unlocked read-modify-write; concurrent daemon + manual resume can lose an attempt count
`drain_state.py:161-168` does `load → data[cid]+1 → _write` with crash-atomic writes but **no
flock/mutex** around the sequence, unlike the SQLite paths in `store.py` (WAL mode, `timeout=10.0`).
Reachable both from the daemon's automatic drain and a manual `vet --resume` against the same store — a
scenario this repo's own CLAUDE.md names as operationally realistic. A lost increment means a
genuinely stuck row takes longer than `max_resume_attempts` (5) real attempts to be excluded from the
backlog count, quietly re-engaging the "gate on the rate not the stock" brake the founder retired the
stock-based version specifically to avoid. — *Agent: run.py orchestration audit.*

### MEDIUM — Duplicate module-level `_DISCONFIRM_TEMPLATES` dict silently shadows Stage-1 disconfirm templates (dead code today, latent bug)
`verify.py:69-82` defines `_DISCONFIRM_TEMPLATES` with keys including `buyer_intent`,
`route_to_market`, `currency`, `claims_verifiable`; `verify.py:198-205` **redefines the same
module-level name** with a different key set (`value_durability`, `legality`, `incumbency`,
`payer_solvency`, `distribution`, `pain_reality`). Python rebinds the name at import time, so the first
dict is permanently unreachable — an accidental shadow, not a deliberate override. **Currently inert**:
`config.yaml:158`'s `template_checks` doesn't include the Stage-1 keys and `queries_per_check: 2` means
the fallback branch that would read them is never hit under shipped config — but it silently degrades
disconfirm-query quality to a generic single query the moment either config value changes.
— *Agent: verify.py / the moat audit.*

### MEDIUM — `retrieval.py`'s "swallow-to-empty" bug class was fixed once (Exa, SearXNG) and left unfixed in three siblings
`retrieval.py:534-545` (Exa) explicitly raises on transport/auth errors with a comment citing the exact
"bad EXA_API_KEY silently zeroed grounding" incident this fixes. The identical failure shape is still
present, unfixed, in `BraveSearchProvider.search` (`:450-456`), `DeepSeekSearchProvider._call_search`
(`:950-953`), and `MiniMaxSearchProvider._call_search` (`:1097-1099`) — all `except Exception: return
[]` / `return "", []`. For the two `_LLMSearchProvider` subclasses this is compounded: the *inner*
`_call_search` swallows before the *outer* `search()`'s own correct `raise` (`:844`) ever sees it.
**Dormant** under shipped `retrieval.provider: [ddg, exa, claude_cli]` — live the moment `brave`,
`deepseek`, or `minimax_search` is added to that list, where a quota-exhausted key would read as "ran,
found nothing" and stop the fallback chain instead of trying the next tier.
— *Agent: operator/reliability audit.*

### MEDIUM — `ContextVar` market-authority scoping is invisible inside the primary grounding path's thread pool
`retrieval.py:109-124` deliberately uses a `ContextVar` "so a market's authority list cannot silently
apply to another market's fetches" under concurrent vetting. But `resolve_sources`
(`retrieval.py:223-243`, used by `claude_cli.py:375-376` — the **primary** grounding provider) uses a
bare `ThreadPoolExecutor`, and `ContextVar`s set in a parent thread are not visible to threads spawned
by `.submit()`/`.map()` — reproduced directly: `ThreadPoolExecutor sees: DEFAULT` vs the intended
per-market value. Net effect: a market's own authority domains never get the 15s timeout bonus on the
primary grounding path (only the hardcoded global high-authority set and bare `.gov/.edu/.int` do).
Fails safe (shorter timeout, not cross-market leakage) but contradicts the file's own stated rationale.
— *Agent: operator/reliability audit.*

### MEDIUM — `automatability_floor` is a quality-based drop inside generation, contradicting "nothing is killed at generation time" when active
`generate.py:619-635`, config-gated via `config.yaml:945`
(`profiles.online_autonomous_predator.generation.automatability_floor: 0.8`), opt-in and off by
default — but when a profile turns it on, generation itself drops candidates on a quality signal,
which is exactly what CLAUDE.md's "creativity lives in generation; constraint lives in verification"
invariant says never happens. — *Agent: generate/dedup/prescreen audit.*

### MEDIUM — `MOAT_PRIMARY`'s provisional-stamping has a real single-operator gap
`make_operator` (`operator.py:1317-1318`) returns the bare, unwrapped operator when config resolves to
one tier. Only `FallbackOperator` implements `served_is_provisional()`
(`operator.py:1118-1122`) — bare `MiniMaxOperator`/`DeepSeekOperator`/etc. don't, and `verify.py:52-56`'s
own docstring admits it: *"Always False for a single operator... so pinned/test configs never mark
provisional."* A config with `operator: minimax` (a form `cfg.operator` explicitly supports) would
never be stamped provisional and could publish on PASS. Not hit by the current 3-tier production
config, but structurally live for any single-operator config. — *Agent: operator/reliability audit.*

### MEDIUM — `score.py`'s scoring-LLM exception handler swallows to zero with no logging at all
```python
except Exception:
    score_failed = True
    scores = {ax: 0 for ax in SCORE_AXES}
```
(`score.py:43-49`, spot-checked directly). The `score_failed` flag is a real, correct fail-safe signal
consumed downstream — but there is no `logger.error`/`logger.warning` call in the except block at all,
so an operator watching logs has no signal a scoring call failed; only a candidate that later reads
`score_failed=True` in its dossier reveals it, after the fact. — *Agent: config/models/score audit;
independently spot-checked.*

### MEDIUM — `dense_reward` divides by 6.0 against a composite that maxes at 5.0
`models.py:390`: `round(0.8 + (0.2 * comp / 6.0), 3)`. `composite()` (`score.py:18-21`) is a weighted
sum over `config.yaml`'s `weights` block, confirmed to sum to exactly `1.00`
(`pain_acuity .20 + money_provability .20 + automatability .15 + distribution .15 + defensibility .25
+ build_feasibility .05`), with each axis capped 0-5 — so the true maximum composite is `5.0`, not
`6.0`. A perfect-composite candidate gets `dense_reward = 0.8 + 0.2*5/6 = 0.967`, never reaching the
`1.0` ceiling the formula's own structure implies; the reward curve is systematically compressed.
— *Agent: config/models/score audit; independently spot-checked via `composite()` + `config.yaml` weights.*

### MEDIUM — `config.py`'s two hardcoded fallbacks for the same field disagree with each other
The `ModelDefaults` dataclass default is `minimax_fast: str = "MiniMax-M3"`
(`config.py`, dataclass field). The config-parsing function's own fallback for the same field is a
**different literal**: `raw_md.get("minimax_fast", "MiniMax-M2.7")` (`config.py:728`, spot-checked
directly). Two hardcoded strings for the same setting, silently able to drift further apart, in a
codebase whose own rule is "no hardcoded values, params in config."
— *Agent: config/models/score audit; independently spot-checked.*

### MEDIUM — `weights` config block has no schema validation unlike every sibling block
Every other `config.yaml` block (thresholds, generation, retrieval, etc.) is parsed into a typed
dataclass with validation; `weights` is read as a bare dict with no shape/sum check — a typo'd axis
name or a weights block that doesn't sum to 1.0 fails silently rather than erroring at load time.
— *Agent: config/models/score audit.*

### LOW-MEDIUM — Currency is a hardcoded Python default on both provider `create_price` methods
`PaddleClient.create_price(..., currency: str = "GBP")` and
`StripeProvisioner.create_price(..., currency: str = "gbp")`; the only call site
(`bridge.py:1003-1008`) never passes `currency`, so every pack prices in GBP regardless of
`candidate.market`. May be an intentional single-market decision (the module docstring says as much)
but it's a literal in code, not config-declared. — *Agent: artifacts/money-rail audit.*

### LOW — `pricing.py`'s no-ladder fallback price is a hardcoded literal
`pricing.py:126`: `flat = int(listing.get("price_pence", 4999))` (spot-checked directly) — intentionally
documented as a safe degrade for a pre-ladder config, but still a hardcoded price rather than a config
value. — *Agent: config/models/score audit; independently spot-checked.*

### LOW — Reward-shaping constants in `models.py` are unconfigurable
The `0.8` base and `0.2` scaling factor in `dense_reward` (`models.py:388-402`) are literals with no
config knob, compounding the divide-by-6.0 bug above — fixing the divisor won't be config-driven either
unless this is addressed at the same time. — *Agent: config/models/score audit.*

### LOW — Doc-only: `verify.py` docstring overclaims "tracks provider_chain"
Per-check `provider` attribution is real and persisted (`models.py:246-260`, rolled up at
`dossier.py:168-171`). "Provider chain" (the configured chain description, e.g.
`"fallback(claude_cli+minimax)"`) is actually set once in `run.py:424`, not tracked per-call in
`verify.py` — the docstring attributes both halves to the wrong file. Not a functional defect.
— *Agent: verify.py / the moat audit.*

---

## 3. Invariants independently re-confirmed with no defect found

These were checked and hold exactly as CLAUDE.md describes — recorded so this audit doesn't read as
all-bad:

- **Kill-fast genuinely short-circuits.** `verify.py:854-875`'s `return` inside the check loop means
  `run_check` (and its LLM/retrieval calls) is never invoked for checks after a hard-gate fire.
  Verified the loop structure directly; `full_vet=True` is a distinct, explicit opt-out for adaptive
  learning, not a silent bypass.
- **`price_comparables` cannot influence kill-fast**, triple-enforced: excluded from `run_order`
  (`verify.py:822`), hardcoded-excluded in `kill_filter.py:28-29`, and only appended to
  `cand.tags["price_comparables"]`, never to the `checks` list that feeds scoring/kill decisions.
- **Moat exhaustion → provisional-first, DEFER only when the whole chain (including the provisional
  tail) is down** — traced end-to-end through `FallbackOperator._raw`'s per-tier catch/continue and
  `verify.py`'s `ProviderExhaustedError` handling; matches the 2026-08-08 founder directive exactly.
- **HTTP-code word-boundary matching + PERMANENT-wins-ties** — re-executed the documented false-positive
  strings (`"connection reset after 4291 bytes"`, `"req_id=a429f0 timeout"`, `"Error: 4290 tokens"`) and
  a genuine tie case through the real `classify_exhaustion`; all match documented behavior with zero
  false positives.
- **Circuit breaker state machine** (`breaker.py:72-113`) — CLOSED→OPEN, OPEN→HALF_OPEN only after
  cooldown, single-probe admission, reopen-on-half-open-failure — no defect found; unlike `health.py`,
  all mutation is under one in-process lock so there's no cross-caller race here.
- **`GeminiGroundingProvider`/`GeminiOperator` are genuinely unreachable from config** — no `"gemini"`
  branch exists in either `_build_search` or `_build_operator`; matches CLAUDE.md exactly.
- **Cache never persists a failed/empty render** — `DiskCache.search` only writes on non-empty results
  (`retrieval.py:1390`), so the "cached failure pinned the state" bug class this repo has hit before does
  not apply here.
- **Atomic writes are the norm.** `store.py:182-186` (dossiers) and `publish/publish.py:238-240`
  (listings) both use temp-file-then-rename. The one non-atomic write found (`bridge.py:865`, a lint
  receipt) is explicitly best-effort/non-fatal (`except OSError: logger.warning`, not a sellability or
  money record).
- **`_cmd_resume` is trusted-only by contract, generation is not** — one shared `moat_blind_reason`
  function, called with the documented, different `trusted_only` default at each of the two call sites;
  confirmed by reading both call sites directly, not inferred from a comment.
- **`empty/malformed dossier can't reach PASS`** — `dossier.py:126-151` requires `moat_grounded >= 1`
  from actually grounded-supported checks; an all-unverifiable candidate falls through to
  `moat_ungrounded` KILL, matching the 2026-06-16 fix this code comments cite.
- **`_build_operator` fails loudly on the removed `cursor_cli`** rather than silently building a
  shorter chain — verified the `ValueError` raise directly (`operator.py:1265-1269`).

---

## 4. Summary for triage

| Priority | Count | Theme |
|---|---|---|
| HIGH | 7 | Trust-tier operator (`claude`) has weaker persisted-failure protection than the tiers below it; two independent cross-process races (health-probe claim, drain-attempt counter); one config-reachable outage→KILL gap on score-only checks; one silent money-rail idempotency defect; one silent publish-failure swallow; one spend-cap blind spot on the current lead non-critical tier; one silent mid-run chain-exhaustion swallow in generation.
| MEDIUM-HIGH | 2 | A weaker manual-publish backstop than the automated gate; an unlocked JSON read-modify-write shared between daemon and manual resume.
| MEDIUM | 8 | Dead-but-latent template shadowing; unfixed "swallow to empty" pattern in 3 of 6 search providers; a context-scoping gap in the primary grounding path; an opt-in generation-time kill that contradicts a stated invariant; a single-operator provisional-stamping gap; a silent scoring-exception swallow; a reward-formula off-by-one-axis; two disagreeing hardcoded model-name fallbacks; no schema validation on the weights block.
| LOW / LOW-MEDIUM | 5 | Hardcoded currency default; hardcoded fallback price; unconfigurable reward constants; one doc-attribution overclaim; several stale line-number citations and one stale "default 5" figure in CLAUDE.md.

**No code was modified in the course of this review.** Every finding above cites a `file:line` and,
where practical, the exact command or execution trace used to confirm it — per file:line above.

*Compiled 2026-08-10 from six parallel review passes over `origin/main@434024e`, plus direct
spot-check re-verification of the highest-severity claims from the earliest two passes.*
