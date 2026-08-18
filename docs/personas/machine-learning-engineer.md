# The platform for the machine learning engineer

Set expectations first, because the name of the seat is misleading here. **Nothing in this estate is
trained.** There are no model weights, no fine-tuning, no embeddings in the live path, and no feature
store. What exists is a system that makes consequential decisions using language models behind
deterministic gates, and your job is the reliability and calibration of that arrangement.

That is a narrower brief than "ML engineer" usually means, and a harder one, because the decisions
are commercial and the model is a black box you rent.

## Where models actually decide

Nine prompt roles in `prospector/prompts.py`: `generate`, `prescreen`, `query_gen`, `verdict`,
`adversarial`, `score`, `content_gen`, `claim_check`, `price_comparables`.

They are not equal, and the difference is the core of the design.

| Role | Consequence | Who may run it |
|---|---|---|
| `verdict`, `adversarial` | Decides whether an idea lives, and whether it may be sold | Only a brain in `moat_primary` may rule **finally** |
| `generate`, `prescreen`, `score` | Shapes what gets considered | The non-critical chain |
| `query_gen`, `claim_check`, `price_comparables` | Feeds evidence in | Non-critical |
| `content_gen` | Writes words a buyer reads | `artifact_operator` |

**Creativity lives in generation; constraint lives in verification.** Nothing is killed at generation
time. Every gate is downstream. This is deliberate: a model asked to be both inventive and strict is
reliably bad at one of them.

## The trust fence

Read this before changing any roster.

`config.yaml:81 moat_primary:` names the set that may rule finally. Anything outside it that rules is
stamped `provisional` by `operator.is_provisional_provider` (`operator.py:1451`), never publishes on
PASS (`run.py:864`), and is automatically re-vetted.

Live on disk: `operator: [minimax, claude_cli]` (`config.yaml:58`) and
`moat_primary: [minimax, claude_cli]` (`config.yaml:81`). MiniMax leads and is trusted; claude_cli is
the fallback.

The non-critical chain is separate and Claude is **barred** from it, enforced where the chain is
built (`run.py:320 _noncritical_order`). Live: `noncritical_operator: [minimax, minimax_m27]`.

MiniMax is inside `moat_primary` **and** is the only non-critical tier. Those two facts are
independent. A test that hardcodes "minimax is untrusted" pins the roster, not the fence.

## The evaluation harness, and the most instructive failure in it

`tests/test_golden_set.py`, run as a required CI check on shard 0. It measures **discrimination**
across a mixed-sector set: does the pipeline separate ideas that should pass from ideas that should
die.

MiniMax was promoted to trusted-final on receipts: three consecutive golden runs at discrimination
1.00, 9 of 9.

The interesting part is what came before. An earlier run scored 0.96 and failed, which looked like
MiniMax being worse. It was not. **`verify._calc_confidence` took roughly 70% of its number from
citation volume and domain count.** A brain that writes terse, correct, well-sourced answers with
fewer citations was scored as ungrounded — the metric was measuring writing style. Fixing the scorer
produced 1.00 three times.

The lesson is the one worth carrying: **when a model looks worse, measure the scorer before you
believe the score.** Do not revert a roster on a single failing run.

## Calibration numbers, and why they are compressed

Two floors govern how confidence is used, and both were calibrated against live distributions rather
than assumed.

- **`min_supported_confidence: 0.3`** (`config.yaml:523`). Taken over 504 supported checks in
  `store/dossiers/`: median 0.43, p25 0.40, p10 0.30, max 0.79. **The live confidence scale is
  compressed around 0.43, not spread over 0-1.** A floor of 0.5 would void 76% of genuinely supported
  checks. If you model these as calibrated probabilities you will be wrong.
- **`confidence_floor: 0.4`** (`config.yaml:515`), the kill side. Derived by replaying
  `store/dossiers/*.kill.json` through the real gate code: of 333 kills that reproduce, 66 are freed
  at 0.4 (19.8%), concentrated in `incumbency` (31) and `value_durability` (16) — exactly the two
  gates a 2026-06-15 review flagged as over-restrictive. At 0.5 it frees 43.2%, which is a product
  decision, not calibration.

The two are deliberately decoupled so that tightening passes never loosens kills.

## Determinism, and where it is required

**MiniMax is non-deterministic on structured routing even at temperature 0.** Measured: 4 of 6
candidates changed ambition tier across 3 repeat runs. That is why lane classification and other
routing decisions must not be treated as stable, and it is the reason a roster decision was once
argued on determinism grounds.

Where a buyer reads, determinism is mandatory: **all sixteen `pack_*.py` renderers are model-free on
purpose.** A model in a renderer makes the same pack render differently twice, which is not a quality
problem, it is a trust problem.

## Failure handling, which is most of the job

- **An exception is never evidence.** A verdict call that raises returns `retrieval_failed=True`
  (`verify.py:365`) and fires DEFER (`verify.py:693`). It never contributes an `unverifiable` check
  to the kill gates. The receipt for why this exists is
  `store/dossiers/2102bacc6dd75cf9.kill.json`: a KILL whose seven checks all read
  `unverifiable, conf 0.0, "Verdict call failed; fail-safe."` — an idea killed by our own outage, in
  a dossier that reads as fully reasoned.
- **A KILL must be grounded in cited disconfirming evidence.** All six hard gates kill on `refuted`
  only. `unverifiable` means no matching passage, which is silence.
- **Polarity has been inverted once and it killed lawful ideas.** `legality` once killed on
  `supported`. Receipts: `store/dossiers/459b72f3630d21be.kill.json` (heirloom tomatoes, killed for
  being legal) and `7e603974bcde1e09`. Do not "fix" it back.
- **A failed call must leave a trace.** A fallback chain that works hides its own degradation. One
  shared classifier (`errors.looks_exhausted`) decides transient (60s) versus permanent (1h), and it
  matches HTTP codes on **word boundaries** — a bare substring once let a request id bench a live
  brain.
- **Concurrency**: `minimax_concurrency` (`config.yaml:321`, default 8) is installed process-globally
  by `config.load_config` and measured clean at 16/16 with zero 429s.

## What is not built

- No offline evaluation beyond the golden set. No held-out corpus, no per-prompt regression scores.
- No prompt versioning tied to outcomes. `model_version_tag` is filled at runtime for audit, but
  nothing joins it to downstream pack quality.
- No embeddings in the live path. `prospector/prescreen_prefilter.py` is embedding-based and **wired
  off** (`config.yaml:2015`). Dedup is `difflib.SequenceMatcher` plus Jaccard token overlap.
- Ollama exists as an operator but is CPU-only on this box, so it is not a practical local option.

## What to read next

- [analyst.md](analyst.md) — the funnel these decisions move.
- `docs/ML_OPPORTUNITY_AUDIT_2026-08-15.md` — where models could do more.
- `docs/GENERATION_QUALITY_PROGRAM.md`, `docs/RETRIEVAL_PROGRAM.md`.
