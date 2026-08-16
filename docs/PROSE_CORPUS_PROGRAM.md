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

## What was verified on the site, 2026-08-16

Measured, not assumed. Every line here came back from the live site.

- `robots.txt` has a single `User-agent: *` block. It disallows four PDF proforma forms
  (disputed transactions, lending, professional representative declaration, complaint form).
  It disallows nothing under `/decision/` and nothing under any search path.
- Decisions are PDFs at `https://www.financial-ombudsman.org.uk/decision/DRN-<n>.pdf`.
  `DRN-5344636.pdf` returned 200, 120,780 bytes, 1,167 words of decision text.
- The id space is sparse. Six probed ids returned two 200s and four 404s, and a wider probe
  put the hit rate near 5-15%. So the fetcher SAMPLES ids at random from a range with a
  fixed seed and reports its hit rate, rather than asserting a contiguous range.
- The site returns 403 to a default python user agent and 200 to a browser one. That is the
  documented Cloudflare behaviour on this estate (memory:
  `cloudflare-blocks-urllib-user-agent.md`), not an attempt to look like a person.
- The decisions SEARCH page renders its results in JavaScript: the HTML carries zero DRN
  ids, so there is no cheap id list to harvest. Random sampling is why.

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

### First measurement, 2026-08-16

Corpora: **766 of our documents, 500,758 words** (from 2,381 dossiers in `store/`) against
**235 FOS final decisions, ~420,000 words**. Both through the same tokeniser, both with
boilerplate stripped by the same rule.

Reproduce:

```
python -m tools.corpus.build_ours --store store --words 500000
python -m tools.corpus.fetch_fos --words 500000
python -m tools.corpus.keyness --top 25
python -m tools.corpus.structure
```

#### Structure: where we sit against the human interval

| measure | human mean | human p5–p95 | ours | z |
|---|---|---|---|---|
| hyphens per 1k | 2.61 | 0.64–6.53 | **31.84** | **+13.6** |
| type/token ratio | 0.29 | 0.18–0.41 | **0.52** | **+3.5** |
| commas per 1k | 32.08 | 14.44–49.11 | **61.30** | **+2.8** |
| semicolons per 1k | 0.75 | 0.00–3.96 | **4.58** | **+2.8** |
| parentheses per 1k | 5.73 | 0.00–15.63 | 15.66 | +1.8 |
| sentences over 25 words | 0.31 | 0.13–0.52 | 0.52 | +1.7 |
| hedges per 1k | 13.58 | 5.52–23.05 | **3.51** | **−1.7** |
| clause load per sentence | 1.82 | 1.10–2.55 | 2.57 | +1.6 |
| mean sentence length | 22.30 | 17.10–28.82 | 28.15 | +1.6 |
| dashes per 1k | 2.67 | 0.00–8.57 | 7.35 | +1.4 |
| colons per 1k | 1.23 | 0.00–3.77 | 3.00 | +1.1 |
| attribution per 1k | 10.31 | 2.43–19.27 | 5.74 | −0.8 |
| opener diversity | 0.80 | 0.65–0.94 | 0.86 | +0.6 |
| sentence length σ | 12.87 | 8.19–18.55 | 13.85 | +0.2 |

Distance: **mean |z| = 2.71** across our documents. **764 of 765 sit 2+ sd outside the
human corpus on at least one measure.** No gate is armed; this is the number one would read.

#### Five things the measurement says that no rule of ours did

1. **We hyphenate 12 times more than a human writing this genre.** This is the single
   largest deviation and nothing in `copy_lint.py` or `register_lint.py` looks for it. It is
   the compound-stacking habit: "Front-Door Key-Safe Forensic Re-Siting Round". Ombudsmen
   barely hyphenate at all.
2. **We hedge four times LESS than a professional writing a verdict** (3.51 vs 13.58 per
   1k). Our prose is more assertive than the writer who is legally accountable for it. That
   is the opposite of what a hand-written style rule would have guessed, and it is a
   credibility problem, not a wordiness one.
3. **Our vocabulary churns.** Type/token 0.52 against 0.29. We reach for a different word
   where a human repeats the plain one.
4. **The 25-word sentence ceiling in `voice.md` is stricter than the genre.** A human
   ombudsman exceeds 25 words in 31% of sentences, and the human p95 is 52%. Our rate is
   52% — at the top of the human range but INSIDE it, and our mean sentence length (28.15)
   sits inside the human p5–p95 too. `register_lint.py` is flagging normal writing. Sentence
   length is not our problem; comma and semicolon density (both z=+2.8) is.
5. **Keyness says we write about the evidence instead of about the world.** The top
   over-used items by log-likelihood are `passages` (G2 4004, 1342x), `the passages`
   (G2 2956), `none of`, `passages show`, `no passage`, `passages describe`, `but none`. A
   human decision says what happened to the complainant. Ours says what the passages did or
   did not do. Full table: `corpora/keyness.json`, 4,448 rows over G2 15.13 and 2x.

#### Two defects in the measurement, found and fixed

- **The dash count conflated hyphens with dashes.** Merged, our "dash" rate came out 7.3x
  the human corpus and pointed at a punctuation habit that does not exist. Split, dashes sit
  inside the human range (z=+1.4) and hyphens are the real finding (z=+13.6). Pinned by
  `test_a_hyphen_inside_a_word_is_not_a_dash`.
- **Paragraph length is not comparable yet.** `build_ours.document` writes each field as its
  own paragraph, so our 1.92 sentences per paragraph measures the corpus builder, not the
  writing. Both paragraph measures are printed but excluded from the distance metric
  (`structure.REPORTED_ONLY`) until packs are measured as the buyer reads them.

#### What is not yet done

Stage 6 (delete the invented constants from `register_lint.py` and read the measured
intervals) and stage 7 (a distance score written per run) are not built. Finding 4 above is
the argument for doing stage 6: the constant currently in force is wrong in a measurable
direction.
