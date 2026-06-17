# Ticket: Audit & remove hardcoded model identifiers

**Status:** Open · **Priority:** Medium · **Owner:** TBD (not money-rail; non-fence work)
**Filed:** 2026-06-16 · **Refers to:** the same anti-pattern as the original
`PaddleTransaction` → `PaymentTransaction` P0 refactor (provider-coupled
identifiers baked into the type, config, and operator modules).

## Why this exists

We are in the middle of a forced migration off `deepseek-chat` (deprecated
2026-07-24, ~5 weeks out). The "fix" proposed was to hardcode
`deepseek-v4-pro` / `deepseek-v4-flash` into `prospector/operator.py:346-347`
and `prospector/retrieval.py:455`. The founder vetoed that approach on the
grounds that **model strings should not be hardcoded in operator code** — the
whole point of the standing config-driven architecture is that swapping models
requires *only* `config.yaml` (or env), not code changes. Hardcoding in
`operator.py` perpetuates the same anti-pattern `deepseek-chat` was, just one
forced migration sooner.

**The actual cost of the anti-pattern:** every time DeepSeek / MiniMax /
Gemini / Claude rolls a new flagship or deprecates an old one, somebody has
to grep the codebase, edit the operator, ship a release, and hope no fixture
or prompt is still pinned to the old name. We just did this twice in one
week (`MiniMax-M3` upgrade, now the `deepseek-chat` → V4 migration). Each
migration risks silently breaking a path (e.g. `retrieval.py:455` had a
latent `deepseek-chat` in the disabled DeepSeekSearchProvider that would
have 500'd on 2026-07-24 if it had been re-enabled).

## Scope: the audit

Find every place a model identifier is hardcoded outside `config.yaml` (and
its env-var overrides). For each, classify it and decide a single canonical
home.

**Likely places to inspect (not exhaustive — the audit must verify):**

| File:line | What it is | Hardcoded? | Should move to |
|---|---|---|---|
| `prospector/operator.py:340-347` (DeepSeekOperator) | `_DEFAULT_MODEL` / `_FALLBACK_MODEL` strings | yes | `config.yaml` `models.deepseek` block, or env |
| `prospector/operator.py:247-248` (MiniMaxOperator) | `_DEFAULT_MODEL` / `_FALLBACK_MODEL` | yes | `config.yaml` `models.minimax` block, or env |
| `prospector/operator.py` (ClaudeOperator, GeminiOperator, GeminiCLIOperator) | any `_DEFAULT_MODEL` | probably yes | `config.yaml` |
| `prospector/retrieval.py:455` (DeepSeekSearchProvider) | `model_name` | yes | `config.yaml` (and provider removed from active chain regardless) |
| `prospector/retrieval.py` (other search providers) | `model_name` for the decomposition step | check | `config.yaml` |
| `config.yaml:13` (operator chain) | names operator kinds, not models | ok | leave |
| `config.yaml` `model:` / `model_fast:` fields | model strings | check | these are the canonical home, verify they exist and are honored |
| `prompts/*.md` | no model refs expected | check | should be none |
| `fixtures/*.json` | mock model outputs | ok | mocks are pinned, that's the point |
| Test fixtures / `tests/**/*.py` | model strings in test setup | check | tests pinning the default for regression are ok; tests *asserting* the default name are pinning-to-implementation, fragile |
| `store/golden_runs/*.json` | `operator` field per run | ok | historical, immutable audit trail |
| `telemetry.py` (`PRICING` dict) | per-model USD prices | yes | `config.yaml` `pricing` block (separately: pricing has the same coupling — if a new model ships, this dict is wrong silently) |
| `run.py` golden CLI invocation | `--operator` flag default | check | defaults should be config-driven |

## Acceptance criteria

1. **Audit doc** listing every hardcoded model identifier in the codebase,
   with file:line and a decision (move / keep / deprecate). Grouped by
   category (operator, retrieval, pricing, prompts, tests, fixtures).
2. **Single source of truth** — every model identifier that's actually
   consumed at runtime reads from `config.yaml` (or env override). The
   operator classes expose a constructor parameter for the model and have
   **no** `_DEFAULT_MODEL` strings.
3. **Pricing follows** — `telemetry.PRICING` is replaced with a config-driven
   lookup. Missing-price = explicit error, not a silent $0.
4. **Migration story** — for the immediate `deepseek-chat` deprecation
   (2026-07-24), document a one-line config change that does the migration
   without code. This is the *demonstration* that the refactor was worth it.
5. **Tests** — a behavioural test that swaps the config model string and
   verifies the operator picks it up without code change. Locks in the
   "no hardcoded names" invariant going forward.
6. **No regressions** — `pytest -q` stays green, golden-set still passes
   (model-version field in run metadata captures the change).

## Progress (2026-06-16)

Step 2 (partial) and step 5 (partial) landed in commit 1d36dd3:

- `cfg.model` and `cfg.model_fast` are now threaded through `_build_operator`
  to all four non-mock operators (gemini, claude, deepseek, minimax).
  Setting `cfg.model = "deepseek-v4-pro"` (or any string) now selects
  that model without code changes. The deepseek-chat 2026-07-24
  deprecation is now a 1-line `config.yaml` change.
- `tests/unit/test_model_config.py` (8 tests) locks the invariant in:
  every config override is reflected in the operator, and every empty
  config falls back to a sensible hardcoded default.
- The Claude SDK tests are skipped — `jiter` (anthropic's native dep)
  is broken in this venv (Python 3.14 compat issue). The other three
  providers are sufficient to verify the threading.

What remains of step 2: the per-operator `_DEFAULT_MODEL` strings are
still in `operator.py`. Removing them requires deciding the empty-config
default at the config layer (a `model_defaults` block in `config.yaml`)
and updating all four operators to source their default from there.
This is the next sub-step.

Audit (step 1) — the per-file table above is the audit. The status
column is filled in for each row; the rightmost column indicates the
target home. This isn't an external doc; it lives in the ticket
itself so the audit is co-located with the fix plan.

Pricing (step 3), retrieval providers (`retrieval.py:455,599,743`),
and the operator factory default-model strings (the remaining `_DEFAULT_MODEL`
constants) are all still TODO.

## Progress (2026-06-16, later) — config home landed, but a shadowing bug found

Reconciling the ticket with current code (it had drifted):

- **DONE since first filing:** the `_DEFAULT_MODEL`/`_FALLBACK_MODEL` constants
  are gone from `operator.py`; a `model_defaults:` block exists in `config.yaml`
  (operator + `search:` sub-block) and `_build_operator` injects it via
  `default_model=`/`fast_model=`. A `pricing:` block in `config.yaml` replaced the
  hardcoded `telemetry.PRICING` dict (missing price = warn, not silent $0).
  `retrieval.py` search providers take `model_name=search_model` from config.
  The only leftover hardcoded identifiers are last-resort string fallbacks inside
  the operator constructors (e.g. `model or default_model or "deepseek-chat"`).
- **V4 migration done in config (the value proof):** `model_defaults.deepseek` →
  `deepseek-v4-pro`, `model_defaults.search.deepseek` → `deepseek-v4-flash`,
  `pricing.deepseek` → `{0.435, 0.87}`. Zero code edits. This is the 1-line-change
  demonstration step 4 asked for.

### ⚠ BLOCKER found by verification — `cfg.model` shadows `model_defaults`

`_build_operator` (operator.py:910–912) reads `cfg.model` (fast=False) /
`cfg.model_fast` (fast=True) and passes it as `model=` to **every** provider,
where it wins over the per-provider `model_defaults`. But `cfg.model` /
`cfg.model_fast` are both pinned to the **Gemini** verdict model
(`"gemini-2.5-flash-lite"`, config.yaml:15-16). The real non-critical chain
(`run.py:359-369`) hands the same `cfg` to the deepseek/minimax tiers, so:

```
deepseek  fast=False/True -> built model: gemini-2.5-flash-lite
minimax   fast=False/True -> built model: gemini-2.5-flash-lite
```

i.e. the cheap-tail operators are built with a **Gemini** model string, which
would 400 on `api.deepseek.com` / `api.minimax.io`. The `model_defaults` block
(and therefore the V4 switch above) is **inert for the chain** until this is
fixed. The leak is already handled for `claude_cli` (passes `model=None`,
operator.py:919-923) — the same fix is needed for the API providers.

`tests/unit/test_model_config.py` currently *asserts* `cfg.model` overrides each
provider — so it locks the leak in. The design intent needs a founder call:
`cfg.model` should be the **Gemini/moat-only** pin; non-moat providers should
take their model from `model_defaults.<provider>` (or a future `cfg.models.<p>`).
Proposed minimal fix: in `_build_operator`, stop forwarding `cfg.model`/
`cfg.model_fast` to deepseek/minimax/ollama/claude (only gemini consumes them),
and update the test to assert per-provider `model_defaults` instead. **Founder
decision required — not applied.**

### Also: `max_tokens` is hardcoded and matters for V4 thinking mode

`DeepSeekOperator` caps output at `max_tokens=8192` (operator.py:379) while the
MiniMax reasoning path uses `32768` (operator.py:289). V4 (`deepseek-v4-pro`)
has thinking mode default-on; the reasoning trace counts against that budget, so
8192 risks exhausting it and returning empty `content` → `ParseError`. Add
`max_tokens` (and ideally a thinking-mode toggle) to the per-provider config and
size it for reasoning models. Belongs in this same audit.

## Out of scope

- The moat routing decision (Claude→Gemini, not hardcoded *here*, but
  worth confirming the operator factory isn't pinning either).
- Renaming existing config keys (forward-compat: keep current names,
  add the new ones, deprecate the old later).
- Anything in `store_platform/` (separate repo; its own ticket).

## Why this isn't urgent right now

`deepseek-chat` deprecation is 5 weeks out; we have time to do this
properly. The DeepSeek V4 migration is a 1-line `config.yaml` change once
the audit is done — that's the point. The current hardcoded strings
are a latent tech-debt bomb that pays out a forced migration every
6-12 months; the audit converts it into a config toggle.

## How to hand off

This is a self-contained refactor (no founder-fence touchpoints, no
money rail). Safe to assign to any executor (DeepSeek / MiniMax / Nina)
once the audit doc is written. The migration one-liner in step 4 should
be the first thing implemented and tested — it's the value proof.

---

*Filed 2026-06-16 after the founder vetoed hardcoding `deepseek-v4-pro`
in `operator.py`. Anti-pattern: same shape as the original
`PaddleTransaction` naming, same risk: forced migration on every
provider release.*
