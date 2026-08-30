# Language and tone — the redesign

The one answer, not a menu. Evidence: `docs/audits/2026-08-30-language-and-tone.md`.

Six systems become **one rule source, one measured authority, one gate and one dashboard**. No
seventh system is built. The measurement lane moves onto the science plane the founder already
chose on crew#221 rather than staying a hand-run Python script, because a second measurement stack
is exactly the stitching this redesign exists to remove.

## The five decisions

**D-1. One rule source, machine-readable, with three generated consumers.**

`prompts/style/tone.yaml` becomes the only place a threshold or a banned word is written. Three
things are generated from it and never hand-edited:

- `prompts/style/voice.md` — what reaches the model.
- The linter constants (`prose_measure.LONG_SENTENCE_WORDS`, `register_lint`'s word lists,
  `copy_lint`'s ceilings).
- `styles/Mumchimp/*.yml` — the Vale rules.

A generated file that differs from its source fails the build. R-4 (25 vs 28 in three places) and
R-2's whole class stop being possible: today they are three files a person keeps in step, and
after this they are one file a machine expands.

`docs/HOUSE_WRITING_SPEC.md` stays, and stops being a second rule source. It becomes the prose
explaining *why* each row of `tone.yaml` exists, with its ledger generated from the live config
rather than typed. That ledger is the best thing in the current stack and it must keep working.

**D-2. Where the corpus has measured a thing, the corpus wins. Hand-invented thresholds on the
same measure are deleted, not reconciled.**

`copy_lint`'s `max_hedges_per_1k = 2.0` is deleted. The authority on hedging is
`prose_target.json`: human p5 5.67, p50 13.05, p95 23.05, ours 3.51. We hedge too little, not too
much. The generator now validates this at build time — `tone.yaml` cannot declare a threshold on a
measure the corpus target also scores unless it sits inside the human interval. R-5 becomes
uncompilable rather than undetected.

The same rule resolves R1: 25 goes, 28 goes, and the sentence-length row takes the human interval.
This closes the item the founder deferred on 2026-08-15 without asking him to pick a number,
because the number is measured rather than chosen.

**D-3. Ratchet, not ceiling. This is what unblocks two weeks of stalled actuation.**

The reason nothing was ever switched on is written in the spec and is still true: *"a ceiling set
at today's numbers does not improve the writing, it empties the catalogue."* An absolute ceiling on
43.9% long sentences unlists most of the catalogue on day one.

A ratchet does not. The gate compares a pack to the **last published baseline per measure** and
refuses only a pack that is worse than what we already ship. A pack at today's numbers passes. A
pack that regresses fails. The baseline moves down as the repair improves the prose, so the fence
tightens on its own and never has to be argued about again.

This is the same mechanism the estate already runs for Python strictness, and it is the reason no
founder decision is needed to switch actuation on. Six armed measures go from ADVISORY to
BLOCK-ON-REGRESSION in one change, with the catalogue intact.

**D-4. Reproducibility restored before anything else, because every other claim depends on it.**

- `tools/corpus/fetch_fos.py` writes its manifest to `corpora/fos.manifest.jsonl`, inside the
  gitignored directory. It moves to `data/fos.manifest.jsonl`, committed, and the docstring's
  existing promise becomes true.
- `prose_target.json` gains the decision ids its `corpus` block is missing, so the human sample is
  identifiable from the committed target alone.
- `make corpus-refetch` rebuilds the human corpus from the manifest. The source is alive today —
  a decision PDF fetched on 2026-08-30 returned `200 application/pdf 120780`.
- The measurement floor stops being a fixture problem: `prose_repair_effect` grades published
  documents from the store rather than `store/dossiers`, which holds 14 lint fixtures and zero
  passes and makes it exit 2.

**D-5. Measurement lives on the science plane, not in a script nobody runs.**

Per-document measures already land in `<id>.lint.json`. They start emitting as Langfuse scores on
the pack's trace, and the before/after repair comparison becomes an MLflow run instead of a
docstring somebody hand-updates every few days. The dead-measure finding — hedges +5%, MATTR −2%,
nine days with no owner — is then a chart with an owner rather than a paragraph in a file.

This uses the stack already approved on crew#221 (MLflow for runs and evals, Langfuse for scores,
Inspect for the deterministic harness). It builds no new measurement system.

## Order of work, in commands

Each step's acceptance is a command, and each is red before the change and green after.

| # | Step | Accept when |
|---|------|-------------|
| 1 | Commit the FOS manifest outside `corpora/`, add decision ids to the target | `git show HEAD:data/fos.manifest.jsonl \| wc -l` prints the sampled count; `jq '.corpus.ids \| length' prospector/data/prose_target.json` is non-zero |
| 2 | `make corpus-refetch` rebuilds the human corpus from the manifest | measures recomputed from the refetch match the committed target within tolerance |
| 3 | `prose_repair_effect` grades published documents | it exits 0 over at least 30 documents instead of exiting 2 over 0 |
| 4 | `tone.yaml` plus the generator; `voice.md`, linter constants and Vale rules generated | `make tone-generate && git diff --exit-code` is clean; a hand-edit of a generated file fails it |
| 5 | Contradiction check in the generator | a threshold outside the human interval on a corpus-scored measure fails the build; proved by adding `max_hedges_per_1k: 2.0` back and watching it refuse |
| 6 | One CI workflow runs the whole tone lane | `.github/workflows/tone.yml` runs the linters, the target grade and Vale; a rule break turns a pull request red |
| 7 | Ratchet gate on the six armed measures | a pack at baseline publishes; a pack worse than baseline is refused; both directions in the test |
| 8 | Measures emit as Langfuse scores, repair effect as an MLflow run | the score appears on the trace for a live pack; the run appears in `mlflow runs list` |

Steps 1–3 are the prerequisite: until the corpus can be rebuilt, nothing else can be verified.
Steps 6 and 7 are what actually changes the writing. Step 8 waits on the science plane existing —
which, measured on `idp` `origin/main` on 2026-08-30, it does not: argo 0 files, mlflow 0,
inspect 0, jupyterhub 0, marimo 0, pgvector 0.

## What is deleted

- `copy_lint`'s hand-invented ceilings on any measure the corpus scores.
- The 25-word and 28-word constants, both replaced by the measured interval.
- Hand-maintained copies of `voice.md`, the linter constants and the Vale rules — generated now.
- The hand-updated docstring table in `prose_repair_effect.py`, replaced by the MLflow run.

Nothing in the corpus programme is deleted. It is the part that works.

## What this does not decide

Whether the two dead armed measures (hedges +5%, MATTR −2%) can be made to respond at all. The
repair-effect file is right that this is a judgement about English rather than a code change:
telling a model to hedge more is not obviously safe for a document that makes claims about
companies. Step 8 gives it an owner and a chart; if two more weeks of data show no movement, the
honest action is to disarm those two measures and say so, not to leave them armed and dead.
