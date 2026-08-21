# Provider pluggability — requirements, audit, and the work

Founder directives, 2026-08-21, verbatim:

- *"lets add Groq fallback"*
- *"tbh i should be able to add any provider to any part of the engine and also to the hernes
  agnt this has been worked, can you audit the state, the code des not seen to be in nain branch"*
- *"needs to be seanless and preloaded with providers and seanless ability ti add nore"*
- *"reserach all providers possible"*
- *"nake not of all the requrenents"*
- *"also when enabeld fron ops, should be able to test fron ops console and cconfirn nodel is
  active"*
- *"need heatbeat"*
- *"for all nodels in platforn"*

## 1. Requirements, as stated

| # | Requirement | Source |
|---|---|---|
| R1 | Any provider can be added to **any part of the engine** — moat, non-critical, artifacts | "add any provider to any part of the engine" |
| R2 | Any provider can be added to the **harness agent** too | "and also to the hernes agnt" |
| R3 | Ship **preloaded** with providers — not an empty mechanism the operator must fill | "preloaded with providers" |
| R4 | Adding one more is **seamless** — no code edit, no redeploy of behaviour | "seanless ability ti add nore" |
| R5 | **Groq** specifically, as a fallback | "lets add Groq fallback" |
| R6 | Research **all** providers possible, not a shortlist | "reserach all providers possible" |
| R7 | Requirements written down, not held in the session | "nake not of all the requrenents" |
| R8 | A provider enabled from ops can be **tested from ops**, confirming the MODEL answers | "when enabeld fron ops, should be able to test fron ops console and cconfirn nodel is active" |
| R9 | A **heartbeat** — liveness is checked on a cadence, not only when a run happens to call | "need heatbeat" |
| R10 | R8 and R9 cover **every model the platform can build**, not the configured chains | "for all nodels in platforn" |

Standing constraints that bind this work:

| # | Constraint | Source |
|---|---|---|
| C1 | Cheapest possible brain; every recurring cost is a threat | LAW 14, founder: "its too expencice" |
| C2 | A declared provider must **never** silently rule finally | `test_a_provider_can_be_added_by_config_alone.py` §3 |
| C3 | The repo stays the complete system — no behaviour only in a console | CLAUDE.md, 2026-08-18 |
| C4 | config.yaml is committed, so it holds key **names**, never key values | `providers.parse_declared` |
| C5 | Money leaving the account stays the founder's decision | LAW 11 |

## 2. Audit — what is actually on main

The founder's recollection is right that the work was done. The belief that it is missing from
main is wrong, and the measurement says so:

| Piece | State on `origin/main` | Evidence |
|---|---|---|
| Declared-provider parser | **PRESENT**, 191 lines | `prospector/providers.py` |
| Wired into config load | **PRESENT** | `prospector/config.py:1207-1208` |
| Wired into the factory | **PRESENT** | `prospector/operator.py:2044-2058` |
| Test coverage | **PRESENT** | `tests/unit/test_a_provider_can_be_added_by_config_alone.py` |
| Trust fence | **PRESENT** | `operator.is_provisional_provider` (`operator.py:1746`) |
| **Providers actually declared** | **ZERO** | `config.yaml` has no `providers:` block |
| Groq adapter or config, any branch, ever | **NEVER EXISTED** | `git log --all -i --grep=groq` → 1 docs commit |

**So the gap is not the mechanism. The gap is that nothing is loaded into it.** R3 is the whole
of the remaining engine work; R1 and R4 are already true and untested in production only because
no one has used them.

This is one layer up from the defect the mechanism was written to end. Its own test file records
that `OpenRouterOperator` sat on main for weeks as ~300 lines the factory could not construct.
`providers.py` is now the same shape: built, correct, tested, and reaching nothing.

## 3. Why preloading is safe — the load-bearing fact, proved twice

Preloading a catalogue only helps if a provider whose key is absent stays inert instead of
breaking every machine that does not hold that key.

1. `OpenAICompatibleOperator.__init__` raises `ProviderExhaustedError` at construction when
   `api_key_env` is unset (`operator.py`, the `key = (os.environ.get(api_key_env) or "").strip()`
   branch).
2. `make_operator` catches `RuntimeError` around `_build_operator` and drops that tier from the
   chain with a warning, keeping the rest.

Those two only compose if `ProviderExhaustedError` is a `RuntimeError`. Two independent angles:

- `prospector/errors.py:21` — `class ProviderExhaustedError(RuntimeError):`
- live: `issubclass(ProviderExhaustedError, RuntimeError)` → `True`

**Therefore a preloaded provider with no key is skipped, loudly, and costs nothing.** A key
appearing in the environment is the entire activation step. That is what makes R3 and R4 the
same change.

## 4. Groq — the E-106 answer, unchanged

Groq's free tier is an **availability floor, not a drain**. `openai/gpt-oss-120b` free is
30 RPM / 1,000 RPD / **8,000 TPM** / 200,000 TPD. Our check call is ~12,750 characters, so
8,000 TPM is smaller than two of our calls and the token-per-minute limit binds long before the
request limit. Ceiling: **10-17 vets/day**, 28-47/day after the approved merge.

That cannot drain a backlog. It CAN keep the engine off zero for $0 when the paid brains are out
of credit — which is exactly the state the engine has been in since 23:04Z on 2026-08-20. So
Groq goes in as a **tail**, never as a head, and never inside `moat_primary` (C2).

## 4b. Two defects that made the mechanism inert, both found by using it

**The User-Agent (2026-08-21).** `urllib.request` sends `Python-urllib/3.x` when nothing sets a
User-Agent, and the bot filters in front of several providers refuse that string outright. Same
key, same body, same endpoint, one header apart:

    curl's own User-Agent   -> HTTP 200
    Python-urllib/3.11      -> HTTP 403 Forbidden

A 403 reads as a bad credential, so whoever met it would go and re-issue a key that was fine. It
was invisible until a DECLARED provider was actually used, because the built-in tiers do not come
through `OpenAICompatibleOperator`. Fixed at `prospector/operator.py` (`_OPENAI_COMPAT_UA`),
guarded by `tests/unit/test_declared_providers_are_reachable.py`, which also refuses any UA that
impersonates a browser.

**The reserved-token ceiling (2026-08-21).** Groq counts `max_tokens` against a per-minute token
budget whether or not the answer is long, so our 8192 default failed EVERY call on the free tier
with HTTP **413**, on any prompt:

    max_tokens 8192 -> 413 "on tokens per minute (TPM): Limit 8000, Requested 8267"
    max_tokens 4096 -> 200 "ALIVE"

Two fixes, because there were two bugs. `config.yaml` pins groq at `max_tokens: 4096`. And
`errors.py` classified that message as NOT_EXHAUSTION — no `429`, no "rate limit", and the
allowance regex wants "<period> limit" where this says "per minute" — which is the dangerous
half: a failure the classifier misses never becomes a `ProviderExhaustedError`, so `verify.py`
takes its generic-exception path and a rate limit is recorded as an `unverifiable` CHECK against
the candidate. `_PER_MINUTE_RE` now matches the RATE vocabulary itself. 413 is deliberately NOT
added to the transient HTTP codes: 413 really can mean an oversized body.

## 4c. R8, R9, R10 — the heartbeat and the console test

`prospector/ops/heartbeat.py`. One short call per provider asking for one word, graded on the
ANSWER rather than on the socket opening — so a 200 carrying an upsell body, or a silently
substituted model, reports `answered_wrong` instead of alive. Every state is a different repair:
`no_key` is a config edit, `exhausted_permanent` is money, `exhausted_transient` is a wait.

- **R10, coverage.** `platform_tiers(cfg)` is generated from `providers.buildable_tiers`, so it
  is the built-ins plus everything declared. Measured 2026-08-21: **21 tiers**. `mock` and the
  removed tiers are excluded — a fixture proves nothing about the world.
- **R9, the cadence.** The scheduler tick takes a round, immediately before the moat preflight,
  so the preflight's decision is never older than the evidence. It never raises into the tick,
  and it **marks nothing dead** — it calls `_raw` directly rather than through `make_operator`,
  so it cannot bench a brain or eat the half-open recovery probe a real call is owed.
- **R8, the console.** `read heartbeat` is free and reads the last round off disk. `act
  providers.test` takes a fresh one; its preview names the metered tiers and what they cost
  before anything is called.
- **Cost, which is why there are two cadences.** One `claude_cli` probe measured `cost_usd
  0.0490218`. At the free-tier cadence that is **$4.70/day** to learn something nothing was
  waiting on. `heartbeat.metered_interval_s` (6h) governs the tiers that bill, `interval_s`
  (15m) the rest — $0.20/day at the measured cost.
- **Concurrency.** Distinct HTTP providers are probed together, six at a time. `claude_cli` is
  probed alone (founder: "i dont want consurreny onclaude code").

Live round, 2026-08-21, all 21 tiers: **alive** `claude_cli`, `groq`, `mistral`. Down 18 —
`minimax`/`minimax_m27` timed out on their own retry ladder against a Token Plan usage limit,
`deepseek` and `cerebras` returned 402, `ollama` is not running, and 12 have no key set.

**One more trap closed on the way.** `console_api._CHAIN_PROVIDERS` is a hand-written table
carrying a comment claiming a new provider "appears on this page without anyone remembering to
add it". That was true only for built-ins: the 15 declared providers had **zero** console model
pins, and the pin is the one knob a declaration exists to expose. `refresh_declared_knobs()`
tops the list up once a config is loaded — it could not be done in the import-time loop, because
that runs before `load_config` installs the declared block.

## 5. Open questions for the founder

| # | Question | Why it is not mine to answer |
|---|---|---|
| Q1 | Do Groq's free-tier data terms allow our candidate text to be sent? | A business/legal call |
| Q2 | May any declared provider ever enter `moat_primary`? | It decides what publishes a paid deliverable |
| Q3 | Which paid tiers, if any, to fund now that MiniMax credit is out | Money (C5) |

## 6. Status

| Requirement | State | Evidence |
|---|---|---|
| R7 requirements written down | **DONE** | this file |
| Audit of what exists | **DONE** | section 2 |
| R6 research all providers | **DONE** | 18 endpoints probed live 2026-08-21; 2 rejected for 404 |
| R3 preloaded catalogue | **DONE** | 15 providers in `config.yaml providers:`, each inert until its key is set |
| R5 Groq declared | **DONE** | declared, in `operator:` and `noncritical_operator:`, answering live |
| R8 test from ops | **DONE** | `act providers.test`, preview then apply, reports the model that answered |
| R9 heartbeat | **DONE** | scheduler tick + `read heartbeat`; two cadences |
| R10 all models covered | **DONE** | 21 tiers, generated from `buildable_tiers` |
| R4 seamless add | **DONE for the engine and the config page** | a declaration is one config block; declared providers now carry console model pins |
| R1 any provider, any part | **PARTLY** | moat/noncritical/artifact/marketing/grounding all accept a declared name; the trust fence still bars a declared provider from `moat_primary` until the founder says otherwise (Q2) |
| R2 harness agent | **NOT STARTED** | see below |

Not yet done, and named rather than left implied:

- **Q2 is blocking R1's last inch.** A declared provider rules `provisional` and cannot publish
  a PASS. That is deliberate and it is the fence protecting the £49 deliverable, so lifting it
  is a founder decision, not an implementation gap.
- **The console has no "add a provider" FORM.** Adding one is still an edit to `config.yaml`
  (one block, no code), and the *model pin* for an added provider is editable from the console.
  A create-provider action is the remaining piece of R4 for a non-technical operator.

**R2 note.** There is no provider chain of our own inside the agent harness. `.claude/agents/*.md`
are Claude Code agent definitions and their `model:` frontmatter selects a Claude model through
Claude Code's own runtime, which we do not control. Making R2 true for arbitrary providers is a
different piece of work from R1 and must not be reported as covered by it.
