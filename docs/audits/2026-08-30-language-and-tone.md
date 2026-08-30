# Audit — language and tone in the prospector engine

Read-only audit of every part of the engine that decides how our writing sounds. Ordered by how
much damage each finding does, worst first. Every number below came from a command run against
`prospector-main` at `bf315de7` on 2026-08-30; nothing is quoted from memory.

The founder's framing, 2026-08-30: *"we did a lot of work on language and tone, we had quite a few
open-source solutions, we had our own rules, we downloaded corpuses and analysed, it was kind of
stacked together, we need to audit and redesign for the new version."*

The charge is correct about the structure and unfair to the work. This is six systems that each
answer the same question a different way, with no single owner and no gate. It is also the most
carefully measured writing programme in the estate: the corpus study is real science, the
repair-effect diagnostic is honest about its own failure, and the house spec keeps a ledger that
refuses to call an unenforced rule enforced. The problem is not the thinking. It is that almost
none of it is connected to anything.

## What exists — six systems, one question

| # | System | Size | What it decides | Does it reach a buyer's document? |
|---|--------|------|-----------------|-----------------------------------|
| 1 | `prompts/style/voice.md` | 174 lines | How the model is told to write | **Yes** — the only one that does |
| 2 | `docs/HOUSE_WRITING_SPEC.md` | 550 lines | Rules R1–R11, Q1–Q5, and a ledger of what is in force | No — prose, read by people |
| 3 | Hand-written Python linters | 2,147 + 686 + 574 + 380 lines | Whether a pack breaks a rule | Measures only; nothing blocks |
| 4 | The corpus-measured target | 318 + 317 lines + 7 corpus tools | What human writing actually looks like | Six measures armed, one actuator on |
| 5 | Vale 3.17.1 + 6 Mumchimp rules | 6 rule files | Storefront copy style | No — hand-run only |
| 6 | Ops automations | 378 + 378 lines | Whether the repair is working | Diagnostic only, and it cannot run today |

Total: about 6,300 lines of code and documentation, plus a downloaded corpus, aimed at one
question — does this read like a person wrote it.

## Red — the findings that matter

**R-1. Nothing blocks. One actuator is switched on, and half of it does not work.**

Every rule in the house spec's own ledger is marked ADVISORY. Not one is BLOCK. Confirmed in
`config.yaml` today:

```
lint_repetition_block: false        house_spec_block_register: false
house_spec_block_predictions: false max_long_sentence_rate: 0.0
house_spec_block_quotes: false      max_clause_load_rate: 0.0
engine_leak_block: false            max_four_item_list_rate: 0.0
human_register_block: false         max_unsourced_figure_rate: 0.0
human_register_repair: true   <-- the only thing switched on
```

The single live actuator is the rewrite turn: a document that misses the human target gets repair
feedback appended to a retry prompt. Its own effect was hand-measured on 2026-08-21 over 273
documents and recorded in `ops/automations/prose_repair_effect.py`:

| measure | before | after | change | human p5–p95 |
|---|---|---|---|---|
| hyphens per 1k | 31.84 | 16.45 | **−48%** | 0.69 – 7.05 |
| commas per 1k | 61.30 | 48.87 | **−20%** | 13.27 – 49.11 |
| hedges per 1k | 3.51 | 3.69 | **+5%** | 5.67 – 23.05 |
| MATTR | 0.77 | 0.76 | **−2%** | 0.63 – 0.71 |

Two of the four armed measures have never moved. The file says so in its own words: *"Two of four
armed measures had not responded at all, for five days, and no panel could show it."* Nine days
later nothing has changed, because nobody was told to change it.

**R-2. Nobody can re-measure anything today. The evidence is gone.**

- `corpora/` is absent from the checkout. The 270 Financial Ombudsman decisions the human target
  was built from are not on disk.
- The manifest that would let us re-fetch them is written to `corpora/fos.manifest.jsonl` —
  *inside* the ignored directory. `fetch_fos.py`'s docstring promises the manifest is committed
  while its code writes it where git will never see it.
- `prose_target.json`'s `corpus` block records counts only. No decision ids. The human sample is
  not identifiable from the committed target.
- `store/dossiers` holds 14 lint fixtures and **zero** `*.pass.json`. `prose_repair_effect` exits 2
  with *"graded 0 documents, below the declared floor of 30"*.

Every claim about our prose against human prose currently rests on a measurement that cannot be
reproduced. The source is still alive — a FOS decision PDF fetched today returns
`200 application/pdf 120780` — so this is recoverable, but only until the id list is needed and
cannot be found.

**R-3. Zero continuous integration. Twelve workflows, none of them touch any of this.**

```
grep -rlE "vale|copy_lint|register_lint|prose_measure|prose_target|house_style|pack_linter|
           copy_audit|human_register|prose_repair" .github/workflows/   ->  NONE
```

Twelve workflow files exist. Not one names a tone module. Every rule, every measure and every
threshold in 6,300 lines can be broken by any commit and no run will say so.

**R-4. Three rule sources disagree with each other, in production, today.**

R1 is the sentence-length rule. It has three different values:

| Where | Value |
|---|---|
| `docs/HOUSE_WRITING_SPEC.md` line 48, 243, 289, 392 | 28 words |
| `prospector/prose_measure.py:132` `LONG_SENTENCE_WORDS` | 25 words |
| `styles/Mumchimp/SentenceLength.yml` | its own, on `.md` only |

The spec's ledger records this as open since 2026-08-15, deferred by the founder — *"we dont want
catalogue unlisted, tackle this after"*. It was never tackled. A writer reading the spec and a
linter reading the code are enforcing different rules.

**R-5. Two of our rules contradict each other. One says hedge less, the other says hedge more.**

`copy_lint.check_abstraction_and_hedging` defaults to `max_hedges_per_1k = 2.0` — a ceiling.
`prose_target.json` arms `hedges_per_1k` because our mean of 3.51 sits **below** the human 5th
percentile of 5.67, and the repair asks for more hedging. The hand-written ceiling is below the
measured human floor. A document that satisfies the linter is, by the corpus, further from human
writing than one that fails it.

This is the clearest instance of the stitching the founder named: a rule we invented in 2026-08
and a rule we measured in 2026-08 point in opposite directions, and nothing in the code knows.

**R-6. Vale is an island. It cannot reach a pack, and nothing runs it.**

Vale 3.17.1 with six Mumchimp rules (HouseDashes, OrphanClause, Register, Semicolon,
SentenceLength, VagueQuantity) is configured for `*.md` and `*.{tsx,ts}`. It is invoked from
exactly one place, `scripts/copy_audit.sh`, which a person has to run by hand. It is in no
workflow and no Makefile target. It also cannot ever grade a pack: a pack is assembled in memory
and zipped, never written as markdown, and the scheduler's PATH does not carry `/usr/local/bin/vale`.
Six rules maintained for a lane that has no automatic caller.

## Amber

**A-1. Only one of the six systems reaches the model.** `prompts.py` injects `voice.md` as
`{style_guide}` and `rationale.md` as `{rationale_style}`. The 550-line house spec, the corpus
target's findings and the Vale rules never enter a prompt. The measured target does reach the
retry prompt through `repair_feedback`, which is why it is the only one with any effect at all.

**A-2. A stale docstring says two checks are dead when one is now live.** `copy_lint.py` lines
601–640 state "NEITHER IS CALLED", measured 2026-08-15. `register_lint.check_register` is now
imported at `pack_linter.py:37` and called at line 2060. Anyone auditing from the comment reaches
the wrong conclusion.

**A-3. R3, R7 and Q4 are enforced by nothing at all.** R7 covers passive voice and
nominalisation, which needs a part-of-speech tagger. The dependency list carries `nltk` for Porter
stemming only and `textstat`, which the ledger records as *"RECORDED and never actuated"*. There
is no tagger, so the rule cannot be measured, so it was written and abandoned.

## Green — what is genuinely good and must survive

- **The corpus study is real science.** `docs/PROSE_CORPUS_PROGRAM.md`: 766 of our documents and
  500,758 words against 270 human decisions and 511,336 words, same tokeniser both sides. It found
  that we are 13.6 standard deviations from human writing on hyphens, and that **764 of 765
  documents sit two or more standard deviations outside the human corpus on at least one measure**.
  The keyness result is the sharpest sentence anyone has written about our prose: our most
  over-used phrases are `passages`, `the passages`, `passages show`, `no passage` — *"we write
  about the evidence instead of about the world."*
- **The arming rule is honest.** A measure only arms when our mean sits outside the human 5th–95th
  percentile by at least a tenth of that interval's width. Six of eighteen armed. The other twelve
  are reported and not acted on, which is the correct treatment of a measurement that does not
  separate us from a human.
- **The measurement excludes subject matter by construction.** `classify_item` keeps the form of
  human writing and drops its topic, so no rule here can drag our prose towards complaints or the
  FCA. That was thought about before it became a problem.
- **The ledger refuses to lie.** *"A rule is in force only when this table names the code that
  stops a violation reaching a buyer. Everything else is aspiration."* Every red finding above was
  findable because a previous session wrote that sentence and then filled the table in honestly.
- **`repair_feedback` returns `(findings, failed)` deliberately**, so an empty list cannot mean
  both "reads human" and "could not measure". That is the anti-silent-green discipline, applied
  before it was a law.

## Why it ended up stacked together

Three causes, all structural rather than anybody's mistake:

1. **Each layer was added while the one below it was still advisory.** Nothing was ever switched
   on, so nothing ever forced the layers to agree. Six systems can hold six opinions indefinitely
   if none of them can fail a build.
2. **The reason nothing was switched on is written down and is still true.** The spec: *"a ceiling
   set at today's numbers does not improve the writing, it empties the catalogue."* With 43.9% of
   sentences over 28 words, any real ceiling unlists most of the catalogue. That was the correct
   call and it has no expiry date attached, so it became permanent by default.
3. **The measurement lane and the rule lane were never joined.** The corpus programme measured
   what humans do. The house spec wrote what we should do. Nobody ever ran the second against the
   first, which is why R-5 could exist for two weeks without anyone noticing the two lanes point
   opposite ways.

## The one number that decides the redesign

43.9% of our sentences are over 28 words; the human mean is 31% over 25 words. We are not far from
human on sentence length. We are 13.6 standard deviations away on hyphens, and there the repair
already works (−48%). The gap is not that we cannot fix our prose. It is that we fix it in one
place, measure it in a second, write the rules in a third, and gate it in none.

Redesign: `docs/TONE_REDESIGN.md`.
