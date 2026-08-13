# Spec — Engine audit 2026-08-10, remaining MEDIUM/LOW findings

**Source of findings:** `docs/ENGINE_AUDIT_2026-08-10.md` §0 status ledger rows 10-22 and §1
doc drift. Rows 1-9 are already fixed (PRs #173, #175). This spec covers what is left.

**Base:** `origin/main` @ `20284c9`. Worktree `/Users/chidionyema/Documents/code/wt-audit-med`.

**Split of labour.** Part A is dispatched to the MiniMax executor (`pi_execute`) — mechanical,
exact old→new given. Part B stays in Claude Code: money rail, the verdict-trust fence, and one
decision that is the founder's, none of which may leave the trusted session.

---

## Part A — dispatched to the executor

Ten edits across seven files. Every one is a stated old→new. No design latitude.

### A1 · `prospector/verify.py` — delete the shadowed `_DISCONFIRM_TEMPLATES` (finding #10)

`_DISCONFIRM_TEMPLATES` is defined **twice** at module level: first at `:69-82` (11 keys,
including the Stage-1 keys `buyer_intent`, `route_to_market`, `currency`, `claims_verifiable`),
then **redefined** at `:198-205` with only 6 keys. Python rebinds the name at import, so the first
dict is permanently unreachable dead code.

Inert today (`config.yaml:158`'s `template_checks` excludes the Stage-1 keys, and
`queries_per_check: 2` means the branch that would read them never runs), but it silently degrades
disconfirm-query quality the moment either config value changes.

**Edit:** merge, do not just delete. Keep ONE definition at `:198`, and add to it the four Stage-1
keys that only the shadowed dict carried:

```python
    "buyer_intent": ["{q} no demand OR nobody searching OR no buyers OR niche too small"],
    "route_to_market": ["{q} no marketing channel OR hard to reach customers OR ads banned"],
    "currency": ["{q} outdated OR trend over OR declined OR no longer relevant"],
    "claims_verifiable": ["{q} false OR debunked OR no evidence OR contradicted"],
```

Then delete the whole first definition at `:69-82` **including its three-line comment above it**
("Deterministic disconfirming queries for cheap decisive gates…"), moving that comment's substance
onto the surviving definition.

Note the two dicts disagree on `value_durability`: the dead one has two templates, the live one
has one. **Keep the live one's single template** — do not silently double the query budget on a
gate; that is a cost change, not a de-duplication.

### A2 · `prospector/retrieval.py` — three providers still swallow errors to empty (finding #11)

`ExaSearchProvider` (`:534-545`) already does this correctly: it logs, audits, and **re-raises**,
with a comment citing the incident where a bad `EXA_API_KEY` silently zeroed grounding. The
identical failure shape is unfixed in three siblings. A swallowed error returns "ran, found
nothing", which makes `FallbackSearchProvider` **stop** instead of failing over to the next tier.

Dormant under today's `retrieval.provider: [ddg, exa, claude_cli]`; live the moment `brave`,
`deepseek` or `minimax_search` is added to that list.

| Site | Current | Change |
|---|---|---|
| `BraveSearchProvider.search` `:450-456` | `logger.warning(...)`, `audit(... status="error" ...)`, `return []` | keep the log and the audit call **exactly as they are**, replace `return []` with `raise` |
| `DeepSeekSearchProvider._call_search` `:950-952` | `logger.warning(f"DeepSeek search failed: {e}")` then `return "", []` | keep the log, replace `return "", []` with `raise` |
| `MiniMaxSearchProvider._call_search` `:1098-1100` | `logger.warning(f"MiniMax search failed: {e}")` then `return "", []` | keep the log, replace `return "", []` with `raise` |

For the two `_LLMSearchProvider` subclasses this is compounded: the inner `_call_search` swallows
before the outer `search()`'s own correct `raise` (`:844`) ever sees it. Raising from the inner
method is what lets the outer one work as written.

Add a one-line comment at each site pointing at the Exa precedent, e.g.
`# Not "zero evidence" — see ExaSearchProvider.search: a swallowed transport error reads as a`
`# successful empty result and stops the fallback chain.`

**Do not** add a bare `except Exception: raise` anywhere, and do not change the `logger.warning`
text or the `audit(...)` arguments — the audit rows are consumed by the retrieval dashboards.

### A3 · `prospector/retrieval.py` — ContextVar is invisible inside the thread pool (finding #12)

`_market_authority_domains` (`:109-110`) is deliberately a `ContextVar` so one market's authority
list cannot apply to another market's fetches (comment at `:105-108`). But `resolve_sources`
(`:223-243`) — used by `claude_cli.py:375-376`, the **primary** grounding path — dispatches through
a bare `ThreadPoolExecutor`, and a `ContextVar` set in the parent thread is **not** visible to
threads created by `.submit()`/`.map()`. Reproduced: `ThreadPoolExecutor sees: DEFAULT`.

Net effect: a market's own authority domains never receive the 15s timeout bonus on the primary
path. It fails safe (a shorter timeout, not cross-market leakage) but contradicts the file's own
stated rationale.

**Edit** — copy the calling context into each worker:

```python
    from concurrent.futures import ThreadPoolExecutor
    import contextvars
    # A ContextVar set in this thread is NOT visible to threads created by .map()/.submit(),
    # so _get_timeout would read the DEFAULT empty authority set and drop the per-market
    # timeout bonus. copy_context() carries the caller's market scope into each worker.
    ctx = contextvars.copy_context()
    with ThreadPoolExecutor(max_workers=len(cand)) as ex:
        resolved = list(ex.map(
            lambda it: ctx.run(_resolve, str(it.get("url", "")), _RESOLVE_TIMEOUT), cand))
```

Note `_resolve`'s `timeout` is passed positionally through `ctx.run` — `ctx.run(fn, *args)` does
accept keywords, but confirm `_resolve`'s signature before choosing; the existing call is
`_resolve(url, timeout=_RESOLVE_TIMEOUT)`.

Put `import contextvars` at the top of the module with the other stdlib imports if it is not
already there, rather than inside the function.

### A4 · `prospector/score.py` — the scoring fail-safe logs nothing (finding #15)

`:43-49`. The `score_failed = True` flag is a correct fail-safe consumed downstream, but the
`except Exception:` block contains **no logging call at all**, so an operator watching logs has no
signal that a scoring call failed — it only surfaces later, in a dossier field.

**Edit:** change `except Exception:` to `except Exception as e:` and add as the first statement in
the block:

```python
        logger.warning("Scoring call failed; falling back to all-zero scores with "
                       "score_failed=True (this is NOT a real 0/5 verdict): %s", e)
```

`score.py` imports `render` and `stage as telemetry_stage` from siblings; import `logger` the same
way the other engine modules do — `from .telemetry import logger`. Check how `verify.py` or
`retrieval.py` obtains `logger` and match it exactly. Do not change the fail-safe behaviour, the
`score_failed` flag, or the zeroed scores.

### A5 · `prospector/models.py` — `dense_reward` divides by 6.0 against a max of 5.0 (findings #16, #21)

`:401`: `return round(0.8 + (0.2 * comp / 6.0), 3)`.

`composite()` (`score.py:18-21`) is a weighted sum over `config.yaml`'s `weights` block, which sums
to exactly 1.00 (`pain_acuity .20 + money_provability .20 + automatability .15 + distribution .15
+ defensibility .25 + build_feasibility .05`), and each axis is capped 0-5 (`score.py:39`). So the
true maximum composite is **5.0**, not 6.0. A perfect candidate scores
`0.8 + 0.2*5/6 = 0.967` and never reaches the 1.0 ceiling the formula's own shape implies.

Finding #21 is the same code: the `0.8` base and `0.2` span are unconfigurable literals.

**Edit** — module-level constants, corrected divisor, docstring fixed:

```python
#: Dense-reward shaping. A PASS maps to [_DENSE_REWARD_BASE, _DENSE_REWARD_BASE + _DENSE_REWARD_SPAN].
#: The divisor is the maximum attainable composite: score.composite() is a weighted sum over the
#: `weights` block (validated to sum to 1.0 — see _validate_weights in config.py) with each axis
#: capped 0-5, so the ceiling is 5.0. It read 6.0 until 2026-08-10, which compressed every PASS
#: reward to a maximum of 0.967 instead of 1.0.
_DENSE_REWARD_BASE = 0.8
_DENSE_REWARD_SPAN = 0.2
_DENSE_REWARD_COMPOSITE_MAX = 5.0
```

and in the property:

```python
        if self.decision == Decision.PASS:
            comp = self.score.composite if self.score else 3.0
            return round(_DENSE_REWARD_BASE
                         + (_DENSE_REWARD_SPAN * comp / _DENSE_REWARD_COMPOSITE_MAX), 3)
```

Update the docstring's `Formula:` line from `0.8 + (0.2 * composite_score/6.0)` to
`_DENSE_REWARD_BASE + (_DENSE_REWARD_SPAN * composite/_DENSE_REWARD_COMPOSITE_MAX)`.

**Scale break — state it, do not hide it.** This changes a stored training signal: every
`dense_reward` already written to `store/` was computed on the /6.0 scale and is not comparable to
values written after this change. Add that sentence to the docstring. Do not attempt to migrate or
backfill historical values.

Module-level constants rather than `config.yaml` because `dense_reward` is a `@property` on
`Dossier` with no `Config` in scope; wiring config through it is a larger change than this finding
justifies. Named constants close #21's substance (the magic numbers are now one editable place with
a stated rationale) without inventing a plumbing change nobody asked for.

### A6 · `prospector/config.py` — two hardcoded defaults for one field disagree (finding #17)

`:201` — dataclass field: `minimax_fast: str = "MiniMax-M3"  # also M3 per standing order`
`:736` — parser fallback: `minimax_fast=raw_md.get("minimax_fast", "MiniMax-M2.7"),`

Two different literals for the same setting, free to drift further, in a codebase whose rule is
"no hardcoded values, params in config."

**Edit:** make `:736` read `raw_md.get("minimax_fast", ModelDefaults.minimax_fast)` so there is one
literal. Use whatever the dataclass is actually named at `:201` — read it, do not assume
`ModelDefaults`. If referencing the dataclass default is awkward at that point in the file, the
acceptable fallback is to change the `:736` literal to `"MiniMax-M3"` and add
`# keep in sync with the dataclass default at :201 — they disagreed until 2026-08-10`.

`M3` is the correct value ("also M3 per standing order"). Do **not** resolve the disagreement in
favour of `M2.7`.

### A7 · `prospector/config.py` — `weights` has no schema validation (finding #18)

Every other block is parsed into a typed dataclass with a validator — `_validate_admissibility`
(`:262`), `_validate_retrieval` (`:286`), `_validate_generation` (`:772`), `_validate_markets`
(`:799`). `weights` is read as a bare dict at `:855`: `weights=raw.get("weights") or {},`.
A typo'd axis name or a block that does not sum to 1.0 fails **silently**.

This is load-bearing for A5: the `_DENSE_REWARD_COMPOSITE_MAX = 5.0` constant is only correct while
the weights sum to 1.0. This validator is what makes that true.

**Edit:** add `_validate_weights(raw_weights: dict | None) -> dict[str, float]` beside the other
validators, and call it at `:855` (`weights=_validate_weights(raw.get("weights"))`). Follow the
house style of `_validate_admissibility`: a docstring saying WHY it fails loudly, and a `ValueError`
naming the offending key and the consequence.

Rules, in this order:
1. `None` / empty → return `{}` unchanged. An absent block is legal (lanes and markets merge over
   it, and tests construct bare `Config`s). **Do not** make an empty weights block fatal.
2. Every key must be in `score.SCORE_AXES`. An unknown axis raises `ValueError` naming the key and
   the valid set — `composite()` iterates `weights`, so a typo'd axis silently contributes 0 to
   every candidate's score.
3. Every value must coerce to `float` and be `>= 0`. Otherwise `ValueError`.
4. If the block is non-empty, the values must sum to `1.0` within a tolerance of `1e-6`. Otherwise
   `ValueError` naming the actual sum. Do **not** normalise the weights for the caller — silently
   rescaling a founder's config is exactly the class of "helpful" fix this codebase forbids.

Import `SCORE_AXES` in a way that does not create a circular import: `config.py` must not import
`score.py` at module scope if `score.py` imports `config.py`. **Check the direction first.** If it
is circular, do the import inside the function body, and say so in a comment.

### A8 · `prospector/verify.py` — docstring overclaims (finding #22)

The module docstring says `verify.py` "tracks provider_chain and per-check provider". Per-check
`provider` attribution is real (`models.py:246-260`, rolled up at `dossier.py:168-171`), but
`provider_chain` — the configured chain description, e.g. `"fallback(claude_cli+minimax)"` — is set
once in `run.py:424`, not tracked per-call in `verify.py`.

**Edit:** correct the docstring to attribute per-check `provider` to `verify.py` and
`provider_chain` to `run.py:424`. Doc-only; change no code.

### A9 · Stale `MOAT_PRIMARY` line citations in code comments (finding §1)

`MOAT_PRIMARY` is at `prospector/operator.py:1093` (verified on this base). Six comments cite
positions that no longer exist:

| File:line | Cited as | Correct |
|---|---|---|
| `prospector/run.py:291` | `operator.py:875` | `operator.py:1093` |
| `prospector/claude_cli.py:145` | `operator.py:889` | `operator.py:1093` |
| `prospector/cli_auth.py:37` | `operator.py:889` | `operator.py:1093` |
| `prospector/adaptive.py:318` | `operator.py:878` | `operator.py:1093` |
| `prospector/coverage.py:67` | `operator.py:892` | `is_provisional_provider`, `operator.py:1096` |
| `prospector/coverage.py:330` | `operator.py:892` | `is_provisional_provider`, `operator.py:1096` |

The two `coverage.py` sites and `tests/unit/test_coverage_illumination.py:199` /
`tools/experiments/e1_hybrid_query_arms.py:170` say `:892` in the context of *stamping* something
provisional, which is `is_provisional_provider` at `:1096`, not the frozenset at `:1093`. Read each
comment and pick the symbol it actually means.

Also update `tests/unit/test_cli_auth.py:51` and the two files above so no stale number is left.
Comment-only: change no code, no test assertions.

**A line number in a comment goes stale the next time the file moves.** Where the surrounding
sentence still reads correctly, prefer naming the symbol (`MOAT_PRIMARY` /
`is_provisional_provider`) and dropping the number, over updating the number.

### A10 · `CLAUDE.md` + `RUN.md` doc drift (finding §1)

Four claims in the repo's own instruction files are currently false. Fix the docs, not the code.

1. **`CLAUDE.md:56`** — "**dossier.py / store.py / publish.py**" implies `publish.py` lives in
   `prospector/`. `prospector/publish.py` is a **0-byte dead stub** (`wc -c` → `0`; content removed
   in `5f95ca7`, 2026-06-15). The real module is top-level `publish/publish.py` (259 lines),
   imported by `run.py:545`, `tools/publish_offline.py:25`, `tools/publish_passes.py:48`.
   → Change the bullet to `**dossier.py / store.py / publish/publish.py**` and add a clause:
   `(the top-level` `publish/` `package — ` `prospector/publish.py` ` is a dead 0-byte stub)`.

2. **`CLAUDE.md:32`** — "default 5 candidates per signal". `config.yaml:764` sets
   `candidates_per_signal: 20` and `schedule.batch_size` is `15` (`config.yaml:1389`, annotated
   "was 5: founder directive 2026-07-31"). Config is correctly the source of truth — only the
   number in the prose is stale.
   → Replace "default 5 candidates per signal" with
   "candidates per signal is config-declared (`config.yaml candidates_per_signal`, 20 as of
   2026-08-10; `schedule.batch_size` 15)".

3. **`CLAUDE.md:50`** — "embed-match against the catalogue to drop near-duplicates". `dedup.py` is
   pure stdlib `difflib.SequenceMatcher` + Jaccard token overlap — **no embeddings**. An embedding
   component does exist (`prescreen_prefilter.py`) but never affects any decision
   (`config.yaml:1192-1194`).
   → Replace "embed-match" with
   "string-similarity match (`difflib.SequenceMatcher` + Jaccard token overlap — not embeddings;
   `prescreen_prefilter.py` is embedding-based but is wired off at `config.yaml:1192-1194`)".

4. **`RUN.md:126`** — "Each batch writes a timestamped run log to `store/runs/`." No such directory
   and no such code path exists; `store/runs` survives only in an unrelated comment
   (`config.py:134`) and in `golden.py:180` (`store/golden_runs`, calibration-only).
   → Delete that sentence. Do not invent a replacement path.

Verify each claim against the tree before editing — if any no longer holds on this base, leave that
item alone and report it rather than writing something new that is also false.

### Part A verification

Run from the worktree root, in this order, and report each verdict:

```
.venv/bin/python -c "import prospector.config, prospector.verify, prospector.retrieval, prospector.score, prospector.models, prospector.operator; print('IMPORTS OK')"
.venv/bin/python -c "from prospector.verify import _DISCONFIRM_TEMPLATES as d; print('disconfirm keys:', sorted(d)); assert 'buyer_intent' in d and 'value_durability' in d"
.venv/bin/python -c "from prospector.config import load_config; c=load_config('config.yaml'); print('weights sum:', round(sum(c.weights.values()),6)); print('minimax_fast:', c.models.minimax_fast)"
ruff check
.venv/bin/python -m pytest -q tests/unit -x -q --timeout=150 --timeout-method=signal
```

`ruff check` with **no path argument** — the commit gate lints the whole tree, so linting only the
diff is how a green local run becomes a red gate.

`config.load_config`'s exact name and signature may differ; read it and adapt the third command
rather than reporting a failure caused by the probe.

**Expected:** all green. `tests/unit` was `2910 passed` on this base (signed POPDD receipts,
`.lux/receipts/2026-08-10.jsonl`). Any test that now fails is a real regression from these edits —
report it, do not "fix" it by relaxing an assertion. If a test asserts the OLD `dense_reward`
value (`/6.0`), that is the one legitimate expected-value update: change the expected number, never
the formula, and name the test in your report.

### Scope for Part A — an allowlist, not a denylist

Part A may modify **only** these files. Anything else is Part B and must be left alone:

```
prospector/verify.py      prospector/retrieval.py   prospector/score.py
prospector/models.py      prospector/config.py      prospector/run.py
prospector/claude_cli.py  prospector/cli_auth.py    prospector/adaptive.py
prospector/coverage.py    CLAUDE.md                 RUN.md
tests/unit/test_cli_auth.py   tests/unit/test_coverage_illumination.py
tools/experiments/e1_hybrid_query_arms.py
```

`prospector/operator.py` is **read-only** for Part A — A9 quotes its line numbers but changes
nothing in it.

An allowlist rather than a list of forbidden paths, on purpose: the executor's own founder fence is
a token scanner, so naming the money-rail files *in order to exclude them* reads to it exactly like
naming them to edit them, and it refuses the whole plan. Enumerating what may be touched says the
same thing without tripping it.

Do not run `git add -A`: `store/` and `storage/` are tracked runtime state the test suite writes to.

---

## Part B — stays in Claude Code

### B1 · Stripe bills in USD for US buyers (founder decision, 2026-08-10) — MONEY RAIL

Supersedes audit finding #19, which called the GBP literal a config nit. The founder's decision is
that a US visitor is **charged** in USD, not merely shown a converted figure.

Today, display and charge disagree by design. `lib/fx.ts:5-7` states it: *"The buyer keeps paying in
GBP (the store's source of truth is GBP)"*. Verified live 2026-08-10:
`curl -H "Fly-Client-Country: US" https://mumchimp.com/` renders `$` prices (61 occurrences vs 10
on the unheadered UK response), converted at `formatPriceForMarket` (`fx.ts:109`) from
`currencyForCountry('US') → 'USD'` (`fx.ts:70-74`), country taken from the `fly-client-country`
header at `pages/index.tsx:2078`. The card is then billed £.

Scope, not yet designed:
- A Stripe `Price` is single-currency. Either a second `Price` per product or `currency_options`.
- The catalogue row holds one price (`price_pence`) and no currency column.
- The fulfilment fence matches on price — memory `price-change-breaks-fulfilment`.
- `bridge.py:1050` is the single `create_price` call site and passes only `amount_pence`;
  `PriceDecision` (`pricing.py:21-38`) has no currency field.
- The L1 ladder rungs (`config.yaml listing.pricing`) are pence-denominated. A USD ladder is a
  second rung set, or a converted-and-rounded one — a pricing decision, not a mechanical one.
- FX at charge time is a different problem from FX at display time: a cached 24h display rate that
  disagrees with the charged amount is a chargeback.

Not started. Design first, in this session, before any edit.

### B2 · `MOAT_PRIMARY` single-operator provisional gap (finding #14) — verdict-trust fence

`make_operator` (`operator.py:1343`) returns the bare operator when config resolves to one tier.
Only `FallbackOperator` implements `served_is_provisional()` (`:1143-1147`), and
`verify.py:_served_is_provisional` (`:52-56`) admits it: *"Always False for a single operator… so
pinned/test configs never mark provisional."* A config of `operator: minimax` — a form `cfg.operator`
explicitly supports — would never be stamped provisional and **could publish on PASS**.

Not hit by today's 3-tier production config, structurally live for any single-operator config. This
governs what may publish, so it stays in the trusted session.

### B3 · `pricing.py:126` hardcoded fallback price (finding #20) — money rail

`flat = int(listing.get("price_pence", 4999))`. Documented as a deliberate safe degrade for a
pre-ladder config, but a price literal in code. Small, but it is on the publish path and B1 may
move it anyway.

### B4 · `automatability_floor` contradicts a stated invariant (finding #13) — founder's call

`generate.py:619-635`, gated by `config.yaml:945`
(`profiles.online_autonomous_predator.generation.automatability_floor: 0.8`) — opt-in, off by
default. When a profile enables it, **generation itself** drops candidates on a quality signal,
which is what CLAUDE.md's "creativity lives in generation; constraint lives in verification"
invariant says never happens.

Two honest resolutions, and picking between them is not an implementation decision:
(a) delete the floor and let the downstream gates do their job, or
(b) keep it and amend the invariant in CLAUDE.md to name this documented exception.

Currently inert (the profile is not active), so nothing is broken today. Leaving it undecided and
silently contradicting the stated invariant is the one option that is not acceptable.

---

## Ledger

Update `docs/ENGINE_AUDIT_2026-08-10.md` §0 as rows land — that table is the part kept current; the
audit body below it is a dated record and is not edited.
