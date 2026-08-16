# Prose corpus programme — a measured target instead of an invented one

Tracked programme. Append results here, never to CLAUDE.md.
Opened 2026-08-16 on the founder's directive.

## The problem, stated plainly

Every rule we enforce about our own writing was invented by us.

- `prompts/style/voice.md` says a sentence may run to 25 words and carry at most two commas.
  Nobody measured that. It is a rule of thumb written into a file.
- `prospector/register_lint.py:353-355` turns those two numbers into gates
  (`LONG_SENTENCE_WORDS = 25`, `CLAUSE_LOAD_COMMAS = 2`) and reports `long_sentence_rate`
  and `clause_load_rate` against them.
- `prospector/register_lint.py:361` counts banned phrases and named constructions from a
  closed list. The list is ours. When a phrase is missing from it, the defect ships.
- `prospector/copy_lint.py` bans dashes and internal identifiers, and rates grammar through
  harper-cli.

All of it is a linter someone wrote. None of it can tell us what a human writing this genre
actually does. So the failure mode is invisible: prose that passes every rule and still
reads like a machine, because the tells are not on our list.

## The fix

Two corpora, a keyness analysis between them, and a distance metric that gates output.

1. **A human reference corpus in the same genre.** Financial Ombudsman Service final
   decisions: every final decision published since April 2013, searchable and downloadable,
   over 384,000 of them across banking, insurance, mortgages, investments, pensions and
   consumer credit. Each carries an outcome (upheld / not upheld) and full reasons.
   Anonymised at source.

   It is the right corpus rather than merely a large one, because it is the same GENRE we
   generate: a claim, the evidence considered, a verdict, the reasons. Written by a
   professional for a lay reader who may be about to disagree. UK English, no marketing
   register, no house-style flourish, and the writer is accountable for every sentence —
   the constraint our packs claim to work under. Nothing else public matches that shape at
   that volume.

   Secondary, for narrative sections: Legal Ombudsman decisions, ASA adjudications, GOV.UK
   guidance (Open Government Licence).

2. **Our own corpus.** ~500k words of generated pack prose.
   `tools/experiments/_corpus.py` already reads dossiers from the store; extend it rather
   than write a second reader.

3. **Keyness.** Tokenise both, rank every word and every 2-4-gram by log-likelihood ratio
   between the two corpora. What falls out is an empirical list of what our generator
   over-uses relative to a human writing the same genre. Not a blog's list of "AI words".
   Ours. Standard corpus linguistics — AntConc does it out of the box, or ~50 lines with
   spaCy and scipy.

4. **Structural distributions, not vocabulary.** For both corpora: sentence length mean and
   σ, clause counts, paragraph length, opener diversity, hedge density per 1,000 words,
   punctuation rates, attribution density. That yields a target INTERVAL from the human
   corpus, replacing the invented 25 and 2.

5. **A distance metric that gates.** Generated prose is scored against the human corpus's
   interval and fails outside it. This is the part that ends the argument: not a rule, a
   measured target with a distance. Swap the corpus and it retrains itself for a different
   genre.

## Step 0, before any download: the licence check

Measuring from a corpus and training on one are different legal questions. We are measuring,
which is the safer footing, and the spec stays there deliberately.

- Read the FOS website terms before fetching anything in bulk, and record what they say in
  this document with the date. If bulk access is restricted, ask FOS rather than scrape.
- Respect robots.txt and rate-limit hard. This is a public body's search interface, not an
  API we are entitled to hammer.
- ASA, Legal Ombudsman and GOV.UK guidance are Open Government Licence, so the secondary
  corpus carries no licensing question.
- No corpus text is committed to this repo. Store under `corpora/` (gitignored), commit only
  the derived frequency tables and the manifest of document ids + hashes, so a result can be
  reproduced without redistributing anyone's text.

**Nothing is downloaded until this section names the terms and their date.**

## Two genres, not one

The founder asked whether this covers the storefront as well. It does not, and pretending
one corpus serves both would be the same mistake in a new coat.

- **Packs** are reasoned decisions. FOS is the right reference.
- **The storefront** is sales copy — `store_platform/src/Store.Web/src/lib/copyConfig.ts`,
  founder-owned, three variants. A judicial corpus is the wrong target for a headline that
  has to sell. The site needs its own reference genre before it gets a measured gate; until
  then it keeps the vocabulary guard it already has
  (`src/__tests__/copyRegister.test.tsx`).

The machinery below is genre-agnostic: corpus in, target interval out. The storefront gets
the same treatment once its reference corpus is chosen.

## Build, in order. Report mode before enforce mode.

Each stage lands read-only first. Nothing gates generation until a measurement says the gate
would fire on real output.

| # | Deliverable | Done when |
|---|-------------|-----------|
| 1 | `docs/` licence findings recorded, with date | This file names the FOS terms |
| 2 | `tools/corpus/fetch_fos.py` — rate-limited fetch to `corpora/fos/`, manifest of ids + hashes | 500k+ words fetched, resumable, robots respected |
| 3 | `tools/corpus/build_ours.py` — 500k words of our pack prose, reusing `_corpus.py` | Two corpora, same tokenisation |
| 4 | `tools/corpus/keyness.py` — log-likelihood over tokens and 2-4-grams, both directions | A ranked table of our over-used items, printed, committed |
| 5 | `tools/corpus/structure.py` — the eight structural measures on both corpora | Human intervals published in this document |
| 6 | `prospector/register_lint.py` reads the measured intervals instead of `LONG_SENTENCE_WORDS = 25` and `CLAUSE_LOAD_COMMAS = 2` | The invented constants are gone; tests pin the measured ones |
| 7 | A distance score per generated document, reported on every run | Scores in the store, no gate yet |
| 8 | The gate: generated prose outside the human interval fails | Measured first: how many of the last N packs would fail |

Stage 8 is a separate, explicit decision. Stage 7 tells us what it would cost.

## Findings

_Nothing measured yet. This section takes the numbers as each stage lands._
