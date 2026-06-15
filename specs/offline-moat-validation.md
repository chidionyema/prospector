# Spec — Golden-gated cheap-model moat operators (offline / free moat)

**Status:** Ready for a delegate to implement.
**Author:** manager (Claude). **Date:** 2026-06-15.
**Founder-fence note:** This spec changes *how a verdict can be decided* (it lets a
non-Claude/Gemini model rule the moat). That is fence work — the gating logic and the
acceptance criterion below are the fence. A delegate may implement the mechanics; the
**promotion rule (§5) and the acceptance criterion (§8) must not be loosened** without
manager sign-off.

---

## 1. Goal

Let the cheap models **already in the repo** — `DeepSeekOperator` (primary) and
`MiniMaxOperator` (failover) — run the **moat** (verdict ruling + adversarial pass), so a
full run can complete with **zero Claude/Gemini token spend**, *but only after the model
has proven it can discriminate live theses from dead ones on the golden set*.

The founder fence "the moat stays on Claude/Gemini" is a proxy. The real rule is:
**a model may run the moat iff it passes the golden-set discrimination test.** This spec
makes that rule operational and safe.

## 2. Why this approach (rejected alternatives)

- **Ollama (fully offline) / OpenRouter (free cloud):** rejected as the *first* step.
  Both add a new runtime or a new API key, and OpenRouter breaks the standing rule "no
  API-key calls beyond this repo." DeepSeek/MiniMax are **already wired** as both search
  providers and full `Operator` brains — so this deletes the Claude/Gemini cost line with
  *no new dependency*. (Ollama/OpenRouter remain valid *later* options; they reuse this
  same validation gate — see §10.)

## 3. Grounded facts (verified against current files — do not trust from memory)

- `DeepSeekOperator` and `MiniMaxOperator` are **already full brain `Operator`
  subclasses** implementing the standard interface (`_raw` → `complete_json`):
  `prospector/operator.py:179` (MiniMax), `:263` (DeepSeek). **No new operator class is
  needed.**
- The moat operator is selected by the `operator:` list in `config.yaml:1`
  (`[gemini_cli, claude_cli]`), built into a failover chain by
  `make_operator()` → `FallbackOperator` (`operator.py:806`, wrapper at `:701`).
- `verify()` receives the moat brain as `op` and the cheap verdict/query brain as
  `query_op`/`fast_op`; called from `run.py:194` with `query_op=fast_op`
  (vet loop wires `fast_op` at `run.py:524`).
- `ProviderExhaustedError` is raised by `MiniMaxOperator._raw` (`operator.py:245`) and
  `DeepSeekOperator._raw` (`:321`) on quota/limit; `verify()` already catches it and
  returns the `moat_exhausted` / `DEFER_GATE` sentinel (`verify.py:401-405, 385-388`).
  **DEFER-not-KILL is therefore already correct for these operators** — confirm, don't
  rebuild.
- Both operators carry **docstring bans** on moat use: MiniMax `operator.py:184-186`,
  DeepSeek `:265-269` ("MUST NOT be used for kill-check verdicts or adversarial").
- **The existing pytest golden test uses `MockOperator` with hard-coded answers**
  (`tests/test_golden_set.py:162`, router `:70-147`). It is a **prompt/config regression
  gate** and proves **nothing** about a real model's ruling ability. It must stay exactly
  as is.
- The real-model harness already exists: `run_golden_set(op, search, cfg, path)` in
  `prospector/golden.py:47`, with a `main()` CLI (`:133`) accepting `--operator`,
  `--fixtures`, `--golden-set`, `--config`. The 8 golden cases live in
  `fixtures/golden_set.json` (6 KILL across distinct gates, 2 PASS); fixture passages in
  `fixtures/golden_fixtures.json`. Pass criterion: per case, `decision_match AND
  gate_match AND surfaced` (`golden.py:83-102`); aggregate `discrimination = correct/total`
  (`:125`); **promotion requires `discrimination == 1.0`.**

### Two gaps in `golden.py main()` this spec must close
1. `--operator` choices are `["gemini_cli","gemini","claude","mock"]` (`golden.py:137`) —
   **DeepSeek/MiniMax/OpenRouter/Ollama are missing**, so the real model can't even be
   selected.
2. The failure branch is a no-op `pass` (`golden.py:~166`) — `main()` **never exits
   non-zero**, so it cannot gate anything. It must `sys.exit(1)` on `discrimination < 1.0`.

## 4. The core distinction the implementer must preserve

There are **two** golden gates, and they are not interchangeable:

| Gate | Operator | Retrieval | Proves | Role |
|------|----------|-----------|--------|------|
| **Regression gate** `pytest -k golden` | `MockOperator` | fixture | prompts/config didn't regress | runs on *every* change (unchanged) |
| **Promotion gate** `python -m prospector.golden --operator deepseek --fixtures fixtures/golden_fixtures.json` | **real DeepSeek/MiniMax** | **fixture (held constant)** | *this model* can rule + run adversarial correctly | runs once to *promote* a model past the fence |

Retrieval is pinned to **fixtures** during the promotion gate so we measure the model's
**ruling**, not search variance. A fail must be attributable to the brain alone.

## 5. Promotion rule (the fence, in code)

A cheap model is **fence-cleared** to run the moat only when:

1. The promotion gate (§4, real model + fixtures) returns `discrimination == 1.0`, **and**
2. It does so on **K = 3 consecutive runs** (flakiness guard — see §7 edge case on
   adversarial temperature), **and**
3. The run is recorded to an audit trail: append a row to
   `store/golden_runs/<operator>_<ISO8601>.json` containing operator name +
   `model_version`, per-case results, discrimination, and the config hash. (Timestamp is
   passed in / stamped by the caller — `golden.py` must not call `Date.now()`-equivalents
   in a way that breaks determinism; use the process clock at `main()` only.)

Only after 1–3 may `config.yaml` `operator:` be changed to put the cheap model in the moat
chain, e.g. `operator: [deepseek, minimax, gemini_cli, claude_cli]` (cheap first, Claude/
Gemini retained as last-resort failover so an outage still resolves, not DEFERs
prematurely). **A fail keeps the moat on `[gemini_cli, claude_cli]`.**

The docstring bans (`operator.py:184-186`, `:265-269`) must be **rewritten, not deleted**,
to read: *"MUST NOT run the moat UNLESS golden-cleared per
specs/offline-moat-validation.md; see store/golden_runs/ for the clearance record."* The
ban is the default; clearance is the documented exception.

## 6. Changes for the delegate (file by file)

1. **`prospector/golden.py`**
   - Widen `main()` `--operator` choices to match the `vet` subcommand's full list:
     `["gemini_cli","claude_cli","gemini","claude","minimax","deepseek","ollama","openrouter","mock"]`.
   - Make `main()` **exit non-zero on failure**: `sys.exit(0 if discrimination >= 1.0 else 1)`.
     Print a one-line verdict (`GOLDEN <operator>: discrimination=X.XX (n/8) → PASS|FAIL`).
   - Add `--runs N` (default 1; promotion uses 3) and require **all N** runs == 1.0;
     write each run to `store/golden_runs/`. Print the per-run line and an aggregate line.
   - Do **not** alter `run_golden_set()`'s scoring (`:65-102`) — the criterion is fixed.

2. **`config.yaml`** — no functional change in this PR. Add a comment above `operator:`
   pointing to this spec and naming the promotion gate command. (The actual swap to
   `[deepseek, …]` happens only after a clearance run, as a separate, reviewed change.)

3. **`prospector/operator.py`** — rewrite the two docstring bans per §5 (default-ban +
   documented golden-clearance exception). **No behavioural change to `_raw`/failover.**

4. **`tests/`** — add `tests/integration/test_golden_promotion_cli.py` that:
   - asserts `golden.py main()` exits **non-zero** when discrimination < 1.0 (force a fail
     by feeding a deliberately wrong fixture or a stub operator that mis-rules one case);
   - asserts it exits **zero** at 1.0 (reuse the mock router as a stand-in real operator);
   - asserts `--operator deepseek` is now an accepted choice (argparse does not reject it).
   This is a **mock-level** test of the *gating mechanism*; it must not call a real network
   model (CI stays offline/free).

**Out of scope (do not do):** changing prompts, gates, thresholds, lane config, the
scoring formula, or `make_operator`/`FallbackOperator` internals. Do not flip the live
`operator:` to a cheap model in this PR.

## 7. Edge cases (each must be handled or explicitly noted)

1. **Adversarial non-determinism.** `adversarial()` runs at `temperature=0.3`
   (`verify.py:343`); verdict runs at `0.0` (`:205`). A real model at 0.3 can flip a
   borderline PASS case (golden #7/#8) between runs. → That is exactly why §5 requires
   **K=3 consecutive clean runs**. Do **not** silently lower the adversarial temperature
   for validation (it would validate a configuration we don't ship). If 3-of-3 is too
   flaky to ever pass, that is a real signal the model **fails the fence** — report it,
   do not weaken the gate.
2. **Partial pass (e.g. 7/8).** Not a pass. `discrimination == 1.0` is the only promotion
   bar. A 7/8 model stays out of the moat. Record which case failed (the audit row already
   carries per-case results) so the failure mode is legible (almost always an adversarial
   over-kill on a PASS case, or a missed gate on a KILL case).
3. **DEFER must survive the swap.** With `operator: [deepseek, minimax, gemini_cli,
   claude_cli]`, if *all four* exhaust, `verify()` must still return `moat_exhausted` /
   DEFER, never a KILL. This already works (`verify.py:401-405`) because each operator
   raises `ProviderExhaustedError` and `FallbackOperator` propagates when the chain is
   spent — the integration test should include a "whole chain exhausted ⇒ DEFER, not KILL"
   assertion to lock it.
4. **Retrieval variance leaking in.** The promotion gate **must** pass `--fixtures
   fixtures/golden_fixtures.json`. If a delegate runs it against live retrieval, a fail is
   uninterpretable (brain vs search). The CLI should `print` a warning when `--operator`
   is a real model and `--fixtures` is absent.
5. **Audit-trail determinism.** `store/golden_runs/` filenames use a timestamp; take it
   once at `main()` entry and thread it through, so a single run writes a single coherent
   record. Do not scatter clock reads through `run_golden_set`.
6. **The mock regression gate must not change.** `tests/test_golden_set.py` stays mock +
   100% deterministic. If a delegate "improves" it to call a real model, that breaks
   offline CI — reject that.
7. **Cost ceiling.** One promotion run = 8 candidates × (≤6 verdicts + 1 adversarial),
   heavily truncated by kill-fast. K=3 ⇒ ~tens of cheap DeepSeek/MiniMax calls. Acceptable;
   no batching needed. Note it in the PR so the reviewer sees the bound.

## 8. Acceptance criteria (definition of done)

- `python -m prospector.golden --operator deepseek --fixtures fixtures/golden_fixtures.json --runs 3`
  runs end to end, prints per-run + aggregate verdict lines, writes 3 records to
  `store/golden_runs/`, and **exits 0 iff all three runs == 1.0**, else exits 1.
- `--operator minimax` is likewise selectable and runnable.
- `pytest -q` is green, including the new `test_golden_promotion_cli.py`.
- `pytest -k golden` (the mock regression gate) is **unchanged and green**.
- `golden.py main()` exits **non-zero** on any discrimination < 1.0 (proven by the new
  test forcing a fail).
- No prompt/gate/threshold/lane/scoring change in the diff (verify with `git diff --stat`;
  the only edits are `golden.py`, `operator.py` docstrings, `config.yaml` comment, new
  test).
- The `operator:` line in `config.yaml` is **still `[gemini_cli, claude_cli]`** at the end
  of this PR (the live swap is a separate, reviewed change made only after a real clearance
  run is recorded).

## 9. Reviewer (manager) checklist

- [ ] Promotion bar is exactly `discrimination == 1.0`, K=3 — not relaxed anywhere.
- [ ] Fence ban rewritten (default-ban + golden-clearance exception), not deleted.
- [ ] DEFER-not-KILL holds when the whole cheap-first chain exhausts (test present).
- [ ] Promotion gate is pinned to fixtures; live-retrieval warning present.
- [ ] Mock regression gate untouched; CI stays offline/free.
- [ ] No moat semantics changed beyond *which operator* may be selected.

## 10. Follow-on (not this PR)

Once the gate exists, the **same harness** clears any future free brain — `OllamaOperator`
(`operator.py:619`, fully offline) or `OpenRouterOperator` (`:341`, free Gemma/Qwen). Each
must pass §5 before entering the moat chain. That is how "fully offline/free" lands without
ever weakening the fence: the bar is the golden set, and we already own the bar.
