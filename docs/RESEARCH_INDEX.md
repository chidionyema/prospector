# Research index — every measurement this estate has taken about how it writes

Status: INDEX. Opened 2026-08-21 on the founder's directive: *"you need to aconpie all rearch
iinto on place, both preious and new"*, *"the docks are littered in the repo"*, *"needs better
orgaisation and dep linling"*.

**Written for practitioners who will re-run the numbers.** Every row below carries a measurement
and a deep link to the section that produced it. A row with no number says `NOT MEASURED` and
names the command that would produce one. Nothing here is a summary you may quote — it is a
routing table to the reading, and the reading is what you cite.

Scope: **how the platform WRITES, and whether anyone wants to read it.** Tone, register, titles,
headlines, pack prose, listing copy, and the engagement question behind all of them. Research on
retrieval, cost, models and infrastructure is indexed in [§7](#7-adjacent-research-not-about-writing)
and owned elsewhere.

---

## What is in here

- [1. The spine — three genres, three reference corpora, one of them chosen](#1-the-spine--three-genres-three-reference-corpora-one-of-them-chosen)
- [2. Tone and language — the previous research](#2-tone-and-language--the-previous-research)
  - [2.1 The prose corpus programme — the measurement that replaced our invented rules](#21-the-prose-corpus-programme--the-measurement-that-replaced-our-invented-rules)
  - [2.2 The house writing specification — the normative rules](#22-the-house-writing-specification--the-normative-rules)
  - [2.3 The linters that are actually armed](#23-the-linters-that-are-actually-armed)
  - [2.4 Template-first listing copy — which fields need a model at all](#24-template-first-listing-copy--which-fields-need-a-model-at-all)
  - [2.5 The pack narrative programme — the founder's own teardown of the tone](#25-the-pack-narrative-programme--the-founders-own-teardown-of-the-tone)
  - [2.6 The newspaper brief already exists, and it is queued rather than missing](#26-the-newspaper-brief-already-exists-and-it-is-queued-rather-than-missing)
  - [2.7 Cross-project prior art — the copy voice crisis, and the ten LLM tells](#27-cross-project-prior-art--the-copy-voice-crisis-and-the-ten-llm-tells)
- [3. Attention and engagement — the new research, 2026-08-21](#3-attention-and-engagement--the-new-research-2026-08-21)
  - [3.0 The correction that has to be read first — the 100% is SPECIFIED, not selected](#30-the-correction-that-has-to-be-read-first--the-100-is-specified-not-selected)
  - [3.1 The headline number, and the control that decides it](#31-the-headline-number-and-the-control-that-decides-it)
  - [3.2 The claim the same control killed](#32-the-claim-the-same-control-killed)
  - [3.3 The drift, and the mechanism behind it](#33-the-drift-and-the-mechanism-behind-it)
  - [3.4 Where an engagement signal may attach, and where it may not](#34-where-an-engagement-signal-may-attach-and-where-it-may-not)
  - [3.5 Where the dossiers live](#35-where-the-dossiers-live)
  - [3.6 The attention literature, reviewed 2026-08-21 — and its ceiling](#36-the-attention-literature-reviewed-2026-08-21--and-its-ceiling)
  - [3.7 The selection science — what makes an idea compelling, and what a model can actually score](#37-the-selection-science--what-makes-an-idea-compelling-and-what-a-model-can-actually-score)
- [4. The open hole — a human corpus for the selling genre](#4-the-open-hole--a-human-corpus-for-the-selling-genre)
- [5. The buyer-facing measurements — what a person actually meets](#5-the-buyer-facing-measurements--what-a-person-actually-meets)
- [6. Generation quality — the earlier attempt at the same question](#6-generation-quality--the-earlier-attempt-at-the-same-question)
- [7. Adjacent research, not about writing](#7-adjacent-research-not-about-writing)
- [8. What is not measured](#8-what-is-not-measured)
- [9. Where the data lives](#9-where-the-data-lives)
- [10. The downstream synthesis programme — mining the kill log](#10-the-downstream-synthesis-programme--mining-the-kill-log)
  - [10.1 What the kill log actually holds](#101-what-the-kill-log-actually-holds)
  - [10.2 The finding that changes the design — two thirds of recent kills are OUR failure, not the idea's](#102-the-finding-that-changes-the-design--two-thirds-of-recent-kills-are-our-failure-not-the-ideas)
  - [10.3 The owner already exists, and it is subtractive](#103-the-owner-already-exists-and-it-is-subtractive)
  - [10.4 The grouping dimension exists and is dirty](#104-the-grouping-dimension-exists-and-is-dirty)
  - [10.5 The open questions, and what would answer each](#105-the-open-questions-and-what-would-answer-each)
- [Maintaining this file](#maintaining-this-file)

---

## 1. The spine — three genres, three reference corpora, one of them chosen

Everything in this file hangs off one idea, and it was the estate's own, arrived at in
[PROSE_CORPUS_PROGRAM.md](PROSE_CORPUS_PROGRAM.md#two-genres-not-one) on 2026-08-16: **you cannot
grade writing against a rule you invented. You grade it against a human corpus in the same genre,
and the gate is a distance.**

The platform emits three genres. They do not share a target and must not share one.

| # | Genre | What it is | Human reference corpus | Measured? |
|---|---|---|---|---|
| A | **Pack prose** | a claim, the evidence, a verdict, the reasons | Financial Ombudsman Service final decisions, 235 docs / ~420k words | **YES** — 14 structural measures, mean \|z\| = 2.71 |
| B | **Selling copy** | listing titles, storefront headlines, the one-liner a buyer scans | **NONE CHOSEN** | **NO** |
| C | **Idea titles** | what generation emits, before anything is sold | **NONE CHOSEN** | measured against a *null*, not a human — and see [§3.0](#30-the-correction-that-has-to-be-read-first--the-100-is-specified-not-selected) |

**Genre A is done and is the template for the other two.** Genre B has been an explicitly open
hole since 2026-08-16 — the prose corpus programme named it, refused to fill it with the wrong
corpus, and left it. Genre C was measured for the first time on 2026-08-21 and has the same hole.

**The founder's newspaper-headline question is the proposal that fills B and C.** It is not a new
line of work; it is the missing half of work already scoped. See [§4](#4-the-open-hole--a-human-corpus-for-the-selling-genre).

---

## 2. Tone and language — the previous research

### 2.1 The prose corpus programme — the measurement that replaced our invented rules

Source: **[docs/PROSE_CORPUS_PROGRAM.md](PROSE_CORPUS_PROGRAM.md)** (396 lines, opened 2026-08-16).
The finding table is at
[§ First measurement, 2026-08-16](PROSE_CORPUS_PROGRAM.md#first-measurement-2026-08-16).

766 of our documents / 500,758 words, from 2,381 dossiers, against 235 FOS final decisions /
~420,000 words. Same tokeniser both sides, same boilerplate rule both sides.

| finding | ours | human mean | human p5–p95 | z |
|---|---:|---:|---|---:|
| hyphens per 1k — the single largest deviation, and nothing lints for it | **31.84** | 2.61 | 0.64–6.53 | **+13.6** |
| MATTR (length-invariant vocabulary churn) | 0.773 | 0.672 | — | **+4.2** |
| commas per 1k | 61.30 | 32.08 | 14.44–49.11 | +2.8 |
| semicolons per 1k | 4.58 | 0.75 | 0.00–3.96 | +2.8 |
| **hedges per 1k — we are FLATTER than the writer who is legally accountable** | **3.51** | 13.58 | 5.52–23.05 | **−1.7** |
| mean sentence length — *inside* the human interval | 28.15 | 22.30 | 17.10–28.82 | +1.6 |

**Distance: mean |z| = 2.71. 764 of 765 of our documents sit 2+ sd outside the human corpus on at
least one measure.** No gate is armed on this.

Four things a practitioner must carry out of that section, because each contradicts a rule someone
here wrote by hand:

1. The 25-word sentence ceiling in `prompts/style/voice.md`, enforced at
   `prospector/register_lint.py:353` (`LONG_SENTENCE_WORDS = 25`), **is stricter than the genre**.
   A human ombudsman exceeds 25 words in 31% of sentences; the human p95 is 52%; ours is 52% —
   at the top of the range but inside it. Sentence length is not the defect. Comma and semicolon
   density is.
2. **We hedge four times less than a human.** That is a credibility problem, not a wordiness one,
   and it is the opposite of what a hand-written style rule would have guessed.
3. Keyness says **we write about the evidence instead of about the world**: the top over-used
   n-grams by log-likelihood are `passages` (G2 4004, 1342×), `the passages`, `none of`,
   `passages show`, `no passage`. A human decision says what happened to the person. 4,448 rows
   over G2 15.13 in `corpora/keyness.json`.
4. **Form is adopted, subject matter is never adopted**, and the split is mechanical, not row by
   row: `prose_measure.classify_item` uses the closed class of English function words to split
   every keyness row into form (273 rows, may become a rule), meta (369, may become a rule and is
   itself a defect), content (6,855, never).
   See [§ We are not handling complaints](PROSE_CORPUS_PROGRAM.md#we-are-not-handling-complaints-we-are-adopting-how-a-human-writes).

Reproduce, in order:

```
python -m tools.corpus.build_ours --store store --words 500000
python -m tools.corpus.fetch_fos --words 500000
python -m tools.corpus.keyness --top 25
python -m tools.corpus.structure
```

Code: `tools/corpus/build_ours.py`, `fetch_fos.py`, `keyness.py`, `structure.py`, `text.py`,
`load.py`. Two measurement defects were found and fixed inside this programme and are worth
reading before you trust any punctuation number:
[§ Two defects in the measurement](PROSE_CORPUS_PROGRAM.md#two-defects-in-the-measurement-found-and-fixed)
— a hyphen inside a word is not a dash, and paragraph length measures the corpus builder on our
side and the PDF extractor on theirs, so it is reported and excluded on both sides.

### 2.2 The house writing specification — the normative rules

Source: **[docs/HOUSE_WRITING_SPEC.md](HOUSE_WRITING_SPEC.md)** (550 lines, NORMATIVE from
2026-08-15, author: the founder). Governs every buyer-facing string: pack documents, listing copy,
one-liners, the storefront, the sample page, any downloadable artifact. It does not govern engine
logs, operator surfaces or code comments.

Read it as two halves, and they are read differently: Parts One to Seven are the founder's
specification, normative and unedited; the ledger at the end is engineering's status — for each
rule, what enforces it and where.

- [PART ONE — the paragraph model](HOUSE_WRITING_SPEC.md#part-one--the-paragraph-model)
- [PART TWO — hard rules](HOUSE_WRITING_SPEC.md#part-two--hard-rules)
- [PART THREE — quote handling](HOUSE_WRITING_SPEC.md#part-three--quote-handling), with the
  [failing quotes found on the sample page](HOUSE_WRITING_SPEC.md#failing-quotes-found-on-the-sample-page-2026-08-15)
- [PART FOUR — five before-and-after rewrites](HOUSE_WRITING_SPEC.md#part-four--before-and-after)
- [PART FIVE — the extract / write / edit pipeline spec](HOUSE_WRITING_SPEC.md#part-five--pipeline-spec)

**The relationship between 2.1 and 2.2 is the thing to understand.** 2.2 is what we decided our
writing should be. 2.1 is what a human writing the same genre actually does. Where they disagree,
2.1 is evidence and 2.2 is a preference — and the sentence-length rule is the case where the
preference is measurably wrong.

### 2.3 The linters that are actually armed

Not research, but the enforcement surface every finding above has to land in:

| file | what it grades |
|---|---|
| `prospector/register_lint.py:353-355` | `LONG_SENTENCE_WORDS = 25`, `CLAUSE_LOAD_COMMAS = 2` — both invented, one measurably wrong |
| `prospector/copy_lint.py` | listing copy |
| `prospector/pack_linter.py` | pack documents; `check_repetition` at `:198` sees **one pack at a time**, which is why §5 B1 exists |
| `store_platform/.../src/__tests__/copyRegister.test.tsx` | storefront vocabulary guard — the only thing holding genre B |

### 2.4 Template-first listing copy — which fields need a model at all

Source: **[docs/TEMPLATE_FIRST_COPY.md](TEMPLATE_FIRST_COPY.md)** (431 lines). Counted over the
packs on disk, not estimated. Splits every listing field three ways —
[closed-vocabulary classification](TEMPLATE_FIRST_COPY.md#a-closed-vocabulary-classification),
[extraction from data already held](TEMPLATE_FIRST_COPY.md#b-extraction-from-data-already-on-hand),
[genuine writing that stays model-written](TEMPLATE_FIRST_COPY.md#c-genuine-writing--stays-model-written).
Also records a dead field: [`cta_text` has no consumer](TEMPLATE_FIRST_COPY.md#b-dead-cta_text-has-no-consumer).
Orphaned in the doc tree until this index was written — nothing linked it.

---

### 2.5 The pack narrative programme — the founder's own teardown of the tone

**[docs/PACK_NARRATIVE_PROGRAM.md](PACK_NARRATIVE_PROGRAM.md)** — 792 lines, opened 2026-08-15
after a founder audit of what a buyer actually reads. It is the only document that traces a tone
complaint to the line of code that causes it. Six complaints, six causes:

1. the ban on background removes the affordance for setting a scene;
2. the copy describes a product where the reader wants an opportunity;
3. the hedge-to-the-claim rule strips assertiveness out of every sentence;
4. the length budget cuts the connective tissue a narrative needs;
5. anti-padding is over-tuned, so the output reads hurried and cryptic;
6. the storefront has no editorial voice at all.

Its own summary: the pack has **"the structure of an audit report and the voice of a
disclaimer"** — true and unreadable. It also carries the readability spread across pack sections,
Flesch-Kincaid **5.9 to 17.3**, which is the widest measured inconsistency in our prose and is
not linted for.

Read it before touching any `pack_*.py` renderer. It is the implementation half of §2.1's
diagnosis.

### 2.6 The newspaper brief already exists, and it is queued rather than missing

**[docs/STOREFRONT_REDESIGN_PROGRAM.md](STOREFRONT_REDESIGN_PROGRAM.md)** — 1,030 lines, opened
2026-08-20 on branch `design/storefront-v2`. The founder's newspaper directive is already written
into it as criterion **C20**, verbatim: *"think newspapers and engagement, headline teaser,
graphic/etc, small content linking to page"*. Requirement **R8** is the research task —
*"engagement psychology: first impressions, attention, curiosity, trust without sleaze, pricing
psychology, dark patterns to avoid"* — and it is **queued, not done**. Design criterion **B2**
("the front page reads like a front page": a stranger can say what the business does in five
seconds and name one story they saw) is the acceptance test for it.

§3.6 below is the literature review R8 was waiting for. It is the same question asked twice,
three days apart, and this index is where the two halves meet.

Also on the storefront thread: **[docs/STOREFRONT_CRITIQUE_2026-08-19.md](STOREFRONT_CRITIQUE_2026-08-19.md)**,
an 18-persona teardown of the live site, including headline placement and sizing measured at 320px.

### 2.7 Cross-project prior art — the copy voice crisis, and the ten LLM tells

Not in this repo. It is in the `the-introduction-exchange` project's memory, and it is the closest
thing the estate has to a written theory of human tone:

| file | what it holds |
|---|---|
| `copy-voice-crisis-state.md` | Founder flagged the GTM copy as *"horrendous and amateurish … reads like an AI interaction."* North star: **"write like a discreet senior person to a respected peer."** Ten banned LLM tells: the em-dash hinge, triadic taglines, abstract Capitalised-Noun headers, self-narrating labels, plumbing jargon, hedge phrases, strategy leak. Six marketing pages rewritten, shipped 2026-06-04. |
| `wr020-lexicon-copy-state.md` | Founder principle, verbatim: *"this is trusted human relationships, mutual exchange, mutual benefit / so our tone needs to reflect and embody this principle."* Tone follows the relationship, not the transaction. |
| `no-dash-copy-rule.md` | A hard no-dash rule in public copy, enforced as a human-tone marker. |

Both projects reached "it reads like a machine" independently, and one of them already has the
banned-pattern list. Full paths: `~/.claude/projects/-Users-chidionyema-Documents-code-the-introduction-exchange/memory/`.

**Cross-check against §2.1 before importing any of it.** The em-dash ban and the hedge ban are
directly contradicted by our own corpus measurement: hedges are the one measure where we sit
*below* the human writer (3.51/1k vs 13.58/1k), so a rule that removes more of them moves us
further from the genre, not closer. A rule that was right for one product's marketing pages is a
hypothesis here, not law.

## 3. Attention and engagement — the new research, 2026-08-21

Source: **[docs/ENGINE_100X_PROGRAM.md § 9](ENGINE_100X_PROGRAM.md#9-engagement--the-axis-the-engine-does-not-have)**.
Opened on the founder's directive: *"what is the idea generation lacking to psh it to the next
level of enganenent, in talking dragon den, sharktank level of ideas"*.

**The claim.** The engine has twelve measurement points — six KILL checks (pain_reality,
value_durability, incumbency, payer_solvency, distribution, legality) and six SCORE axes
(`prospector/models.py:114`, weights at `config.yaml:850-855` summing to 1.00). **None of the
twelve measures whether a human finds the idea interesting.**

### 3.0 The correction that has to be read first — the 100% is SPECIFIED, not selected

**Confirmed on disk 2026-08-21, after a peer asked whether the PASS titles came from the same
generation config as the rest of the corpus. They do not.**

`prompts/retitle.md` mandates the frame in writing. Its output contract, verbatim:

```
  title — what the business does, and who pays for it:

      <what the business does> for <who pays>

    Both halves, always.
```

That prompt reaches PASS dossiers on two paths, and neither touches a KILL:

1. `tools/retitle_catalogue.py:394 _write_dossier_title` writes the rewritten title back into
   `store/dossiers/<id>.pass.json`, so a republish preserves it. It ran over the live shelf
   (48–62 packs, `prospector/pack_linter.py:871`).
2. `prospector/field_write.py:143 _propose_title` renders the **same** `retitle` prompt inside the
   engine whenever a title breaches the linter.

**So "100% of PASSes carry the frame" is a prompt instruction observed working, not evidence that
the scoring filter rewards one shape.** The null control in §3.1 is sound; the causal reading I
first put on it was not. It is kept below because the number is still the correct description of
what a buyer meets on the shelf — it is the *inference* that was wrong.

**What survives, and is now the finding: the KILL-only drift in [§3.3](#33-the-drift-and-the-mechanism-behind-it).**
KILL dossiers never reach `retitle.md` on either path, so 8.6% → 16.4% → 25.9% is generation
converging on the frame with no prompt telling it to. That is the real result and it is cleaner
than the one it replaces.

**The open transmission hypothesis, NOT MEASURED.** `store.recent_titles(limit=200)`
(`prospector/store.py:439`, "generation's CROSS-RUN MEMORY") reaches `{avoid}` in
`prompts/generate.md:15` via `prospector/run.py:1725`. That shows the generator 200 frame-shaped
titles under an instruction not to repeat them. Whether a model imitates the *form* of an avoid
list while avoiding its *content* is a real question and nobody here has measured it. The test:
render the avoid list as fingerprints instead of titles, generate a wave each way, compare frame
rates. Until that runs, this is a hypothesis with a name, not a cause.

### 3.1 The headline number, and the control that decides it

[§9.0](ENGINE_100X_PROGRAM.md#90-the-headline-number-and-the-control-that-decides-it). 2,000
random size-64 subsamples of the 2,044-title corpus, fixed seed 20260821
(`scratchpad/measure_template.py`):

| property | PASS (n=64) | ALL (n=2,044) | null p5 | null p95 | verdict |
|---|---:|---:|---:|---:|---|
| `<X> for <buyer>` frame | **100.0%** | 21.2% | 12.5% | 29.7% | outside — **0 of 2,000 draws reached it** |
| names a jurisdiction | 43.8% | 13.2% | 6.2% | 20.3% | outside — 0 of 2,000 |
| ≤ 8 words | 71.9% | 49.9% | 39.1% | 60.9% | outside — 0 of 2,000 |
| contains a digit | 1.6% | 3.2% | 0.0% | 7.8% | inside the null — no effect |

**Every single idea that survives the filter has the same grammatical shape — because
[§3.0](#30-the-correction-that-has-to-be-read-first--the-100-is-specified-not-selected) says a
prompt puts it there. Read that section before quoting this table.**

### 3.2 The claim the same control killed

[§9.0b](ENGINE_100X_PROGRAM.md#90b-the-claim-the-same-control-killed--recorded-so-it-is-not-re-made).
"The filter collapses diversity" is **false**. All four lexical-diversity metrics on the 64 PASSes
land inside the null: distinct-1 0.7034 (5.8th pctile), distinct-2 0.9569 (18.6th),
opening-word entropy 0.9844 (9.8th), mean pairwise Jaccard 0.0160 (88.2nd).
**The survivors are as lexically varied as any random 64 and identical in FORM.**

That correction changes the fix and is the reason this row is in the index rather than deleted:
more diverse generation will not help. The scoring rewards one *shape* of proposition.
Script: `scratchpad/measure_diversity.py`.

### 3.3 The drift, and the mechanism behind it

[§9.6](ENGINE_100X_PROGRAM.md#96-the-mechanism--three-feedback-loops-all-carrying-the-same-signal).
Measured on KILL dossiers only, which is generation's raw output before the filter selects
anything (96.7% of the corpus is killed):

| month | n | `<X> for <buyer>` |
|---|---:|---:|
| 2026-06 | 724 | 8.6% |
| 2026-07 | 220 | 16.4% |
| 2026-08 | 1,032 | **25.9%** |

**A 3.0× rise in two months in generation itself**, not only in the filter. Three paths run from
the filter back into generation and every one carries viability information only:
`prospector/adaptive.py:118 select_lenses` (steered by a kill-rate-derived exploration level);
`adaptive.get_recent_failure_modes` (kill reasons into the generate prompt — its own docstring
calls this "the learning signal"); `prospector/critique.py::_axes_brief` (renders `cfg.weights`
and asks the model to rewrite each idea to remove its weakest axis).

**Consequence a practitioner must not miss:** `critique_revise` is a gradient step on the
composite. Enabling it would raise composite scores, accelerate the collapse, and look like an
improvement on every metric the engine currently has. It is off; keep it off until §4 exists.

**Caveat, stated not buried:** `select_lenses` landed 2026-08-19 and this corpus ends 2026-08-15,
so **none of the data above tests the lens rotation**. Re-run the monthly series against a corpus
extending past 2026-08-19 before crediting or blaming it.

### 3.4 Where an engagement signal may attach, and where it may not

[§9.7](ENGINE_100X_PROGRAM.md#97-where-an-engagement-signal-would-attach) and
[§9.4](ENGINE_100X_PROGRAM.md#94-the-constraint-any-fix-must-respect). Rubric first, rank only,
steer second, **never into `kill_filter`** — CLAUDE.md's "two loops never merge" is the hard
constraint: an engagement score may rank survivors and steer generation, and may never un-kill an
idea that failed a grounding gate.

### 3.5 Where the dossiers live

[§9.5](ENGINE_100X_PROGRAM.md#95-where-the-dossiers-live--wish-25). The corpus every measurement
in §3 was taken over. Surfaced in the ops panel by PR #550.

---

### 3.6 The attention literature, reviewed 2026-08-21 — and its ceiling

Full review with all 48 sources: `scratchpad/RESEARCH_B_copy_engagement.md`. Seventeen claims came
back `unverifiable` and ten thresholds are labelled GUESS; those labels travel with the numbers.

**The ceiling first, because it decides what may be built.** Surface linguistic features predict
the winner of a controlled headline A/B test at **54.42%** on 24,333 held-out pairs — 58.3% even
on the largest-gap pairs, and no better at four times the training data. So a deterministic
engagement linter is a **hygiene gate, not a predictor**. Anything claiming to pick the winning
headline from its text is claiming eight points of accuracy nobody has demonstrated.

| finding | number | what it licenses |
|---|---|---|
| Naming sources raises persuasion **and** credibility together (O'Keefe 1998 meta-analysis) | persuasion r=.073 (k=13, N=2,106); credibility r=.169 (k=4, N=553) | The only property where both move the same way — and only when the cited sources are recognisably sound. This is our existing moat, restated as an engagement lever. |
| Question-form titles: downloaded more, cited less (Jamali & Nikzad, 2,172 PLoS articles) | — | Attention and use diverge. A metric that optimises clicks can cost the thing we sell. |
| Concreteness (Brysbaert 40k-word lexicon) | validates at **r=0.61**; thresholds 2.58 and 3.06 | The only free, model-free metric with a published human-validation coefficient. The two real thresholds in the whole review. |
| Negative words raise CTR | **+2.3% per additional negative word, 370M impressions** | The one reliable lever in the literature, and one we refuse. It is the dark pattern R8 names. |
| "Write 'you'" | failed pre-registered at α=.01 (β=0.05, p=.044) | Folklore. Do not encode. |
| "Keep headlines short" | contradicted (β=+0.07, p=7.6e-8) | Folklore, and pointing the other way. |
| Readability → clicks | null (p=0.17) | Folklore. |

**The gap that matters most: no study in the review measured anyone deciding to pay for a
document.** Every effect above is a click, a download, a citation or a lab rating. Our conversion
event is a purchase. Treat all of it as prior, none of it as target.

### 3.7 The selection science — what makes an idea compelling, and what a model can actually score

Full review: `scratchpad/RESEARCH_A_selection_science.md`. It proposes a **separate** composite,
`E`, computed only for candidates that already reached `Decision.PASS`:

```
E = 0.35 · category_distinctiveness   # deterministic (embeddings / topics)
  + 0.30 · atypical_tail              # deterministic (co-occurrence over retrieved passages)
  + 0.20 · why_now                    # near-deterministic (Source.published_at + one cited link)
  + 0.15 · assumption_denied          # model-judged, must cite the passage it contradicts
  = 1.00
```

**65% of the weight sits on fully deterministic measures and only 15% on a model opinion, and that
ordering is forced by evidence rather than taste.** LLM-judged novelty is anti-correlated with
realised impact (ρ = −0.29, HindSight), diverges from expert labels (RINoBench), and style alone
shifts LLM scores by up to 8% (arXiv:2508.07805). Any weighting that put the model's taste in the
majority would build on the one instrument we have measured evidence against.

Four literatures agree on the shape — a conventional core with an atypical tail beats both the
fully conventional and the wholly strange: Uzzi (17.9M papers, 2x), Askin & Mauskapf (27,000 songs),
Norenzayan (minimally counterintuitive folktales survive), Boudreau (randomised grant review).
Berger & Milkman (6,956 NYT articles) then separates the levers: "interest" (.29) and "surprise"
(.16) stay independently significant alongside anger (.38) and awe (.34), which is the licence to
score engagement without building an emotion model.

**Three corrections the review made to its own brief, each worth more than the citations:**

1. **Loewenstein (1994) does not propose an inverted-U over information-gap size.** He explicitly
   rejects that curve as Berlyne's and Hebb's — *"it is wrong because it is inconsistent with
   commonly observed behavior"* — and predicts monotonically. The real inverted-U is Kang et al.
   (2009) and it is over **confidence**: curiosity peaks at P≈.50 of already knowing the answer,
   r=.44. A compelling idea is one the buyer feels **half-informed** about.
2. **E1 is capped, not monotonic, and the two angles genuinely disagree.** Taeuscher tested and
   rejected curvilinearity; Boudreau, Criscuolo and Haans all find a ceiling. The reconciliation is
   that they measure different evaluators and we contain both — **our buyer is Taeuscher's
   evaluator** (expects novelty, carries no workload or professional risk) while **our engine is
   Boudreau's** (a panel grading against its own expertise). Rising-then-flat is the honest
   encoding; the cap value is **not measured**.
3. **The narrative-transportation story is weaker than its reputation.** The van Laer meta-analysis
   effects for levers a writer controls are small (imaginable plot ρ=.29, verisimilitude ρ=.27,
   character ρ=.20) and shrink ~40% on the validated scale. The original Green & Brock belief
   indexes have α = .28 and .47. An α of .28 is not a scale. Nothing is scored on it.

Davis's twelve-category Index of the Interesting turns the one model-judged axis from an open "is
this interesting?" into a **closed twelve-way forced choice** — each form is "what seems X is in
reality non-X" — with three named failure responses to test against ("That's obvious!" /
"That's irrelevant!" / "That's absurd!"). **E3's weight does not rise on the strength of that
citation.** The trigger is a measurement: κ ≥ 0.6 against two humans on 50 packs, then 0.15 → 0.25.

**How `two loops never merge` is preserved mechanically.** The danger is specific: the score
composite is *already* a kill gate — `min_composite` fires `Decision.KILL` at
`prospector/dossier.py:108` and `:232` via `prospector/score.py:68 passes_composite`. So an
engagement axis dropped into `cfg.weights` would kill ideas for being boring. Four fences, and the
second is the load-bearing one:

1. compute after the decision — `score_engagement()` is called from `run.py` only on a PASS, and
   is not in the call graph of `verify`, `kill_filter` or `dossier.decide`;
2. a code-level refusal a config edit cannot defeat — mirror `PRICING_CHECK`
   (`prospector/kill_filter.py:20`-`:29`), add `ENGAGEMENT_AXES` beside `SCORE_AXES`
   (`models.py:114`), and make `score.composite` drop any engagement axis even if `cfg.weights`
   lists it;
3. a test that fails if the loops touch — `set(ENGAGEMENT_AXES) & set(cfg.weights) == set()`, and
   `composite({**score, **engagement}, weights) == composite(score, weights)`;
4. `E` is a sort key and a shelf-placement key, never a threshold. It never sets a price rung and
   never gates publication.

Cost: three of the four axes need **zero** extra model calls, and `assumption_denied` rides in the
existing verdict call as one extra field — so the marginal cost is roughly one prompt's extra
output tokens per **passing** candidate, and the PASS set is the small one (64 of 2,044).

**Status: PROPOSED, NOT MEASURED.** No axis is implemented, no weight is validated, the E1 cap is
a judgement, and the review's own gap list runs to 18 items.

## 4. The open hole — a human corpus for the selling genre

**This is the founder's newspaper-headline question, and it is the join between §2 and §3.**

Genre A got a measured target because someone found the right human corpus. Genres B and C have
no corpus, so:

- §2's machinery cannot run on titles or storefront copy. It is genre-agnostic by construction —
  corpus in, target interval out — and it is idle for want of the corpus.
- §3's numbers are measured against a *null* (a random subsample of our own corpus). A null says
  the frame is not chance. **It cannot say whether the frame is good**, because our own corpus is
  both the sample and the reference. That is one angle, and §3 is honest that it is one angle.

A human corpus in the attention-capturing short-form genre supplies the second angle and turns
§3's descriptive finding into a gate, exactly as FOS did for packs. The prior research already
refused to substitute the wrong corpus here —
[*"a judicial corpus is the wrong target for a headline that has to sell"*](PROSE_CORPUS_PROGRAM.md#two-genres-not-one)
— and left the slot named and empty. This is that slot.

**Status: PROPOSED, NOT MEASURED. No corpus chosen, no licence checked, nothing built.** The
design must clear the same bar the FOS choice cleared — same genre, professional writer, lay
reader, accountable, at volume, licensed — and must answer the four questions FOS answered:
what is the corpus, what is the licence, what are the structural measures, what is the distance
that gates. Until those four have answers this row stays `NOT MEASURED` and no number from it may
be quoted.

**Prior-art search completed 2026-08-21. The result is that the brief exists and the corpus does
not.** The estate-wide sweep (this repo, the second clone, project memory, checkpoints and session
scratchpads) found the newspaper directive already written down as
[C20 in the storefront programme](#26-the-newspaper-brief-already-exists-and-it-is-queued-rather-than-missing),
and found **no** standalone research on newspaper headlines, Upworthy, clickbait or the curiosity
gap anywhere in the estate. The literature side of that hole is now filled by
[§3.6](#36-the-attention-literature-reviewed-2026-08-21--and-its-ceiling). The *corpus* side is
still empty, and §3.6's 54.42% ceiling is the reason it matters: without a human reference corpus
we have no target, and with one we still only get a hygiene gate.

---

## 5. The buyer-facing measurements — what a person actually meets

Source: **[docs/ENGINE_100X_PROGRAM.md §9.3](ENGINE_100X_PROGRAM.md#93-the-buyer-facing-half--measured-2026-08-21)**,
full working in `scratchpad/RESEARCH_D_buyer_facing_measured_2026-08-21.md`.

| # | Finding | Number | Where |
|---|---|---|---|
| B1 | Packs repeat each other | median **23.7%** of a pack's sentences appear in ≥50% of the catalogue (n=150). `"Fifteen minutes this week or next?"` is byte-identical in **136 of 161** packs | `prospector/pack_linter.py:198` sees one pack at a time; `config.yaml:1919 lint_repetition_block: false` |
| B2 | Buyer search returns nothing | **14 of 27** buyer queries return zero against 77 live packs (`side hustle` 0, `cleaning` 0, `dentist` 0); plurals break six pairs (`vet` 1, `vets` 0) | `Store.Web/src/lib/discovery.ts:246 matchesQuery` is a raw substring match |
| B3 | Related packs are arbitrary | scorer emits **10 distinct values**; **32 of 77** packs have >3 candidates tied for 3 slots | `discovery.ts:686 scoreSimilar` |
| B4 | Price does not track evidence | Spearman(price, sourceCount) = **0.1366**; **23 of 76** adjacent pairs inverted; £29.99 carries more sources on average than £49.99 | — |
| B5 | No A/B is possible | `resolveVariant` pins **every** visitor to `'a'`; last analytics read was 24 rows, all `page_view`, all dev traffic; power calc needs **3,780 impressions/arm** | `Store.Web/src/lib/getCopyVariant.ts` |

**B5 is the one that gates the rest.** Every proposal in §2, §3 and §4 ends in "and then we would
measure the lift". There is no instrument that can measure a lift today.

Adjacent: [docs/PACK_QUALITY_PROGRAM.md](PACK_QUALITY_PROGRAM.md) (392 lines) is the founder's
end-to-end read of a live pack — *"nowhere near ready, needs 50x improvement"* — and
[P4](PACK_QUALITY_PROGRAM.md#p4--we-sell-the-same-2500-words-three-times) is B1 found by a human a
week earlier. [docs/PACK_NARRATIVE_PROGRAM.md](PACK_NARRATIVE_PROGRAM.md) (792) is what the buyer
reads, its eight deterministic renderers, and why they must stay model-free.

---

## 6. Generation quality — the earlier attempt at the same question

Source: **[docs/GENERATION_QUALITY_PROGRAM.md](GENERATION_QUALITY_PROGRAM.md)** (312 lines, opened
2026-08-08). Measured on a 548-dossier August sample.
[Diagnosis](GENERATION_QUALITY_PROGRAM.md#diagnosis-measured-on-the-live-store-2026-08-08-session):
the generator knows its own history (~120-title avoid list) but nothing about the market;
incumbency (206) + value_durability (85) kills dominate.

Read [§ Chunk F — the A/B harness itself was measuring wrong](GENERATION_QUALITY_PROGRAM.md#chunk-f--the-ab-harness-itself-was-measuring-wrong-2026-08-08)
before building any A/B for §4 or §5-B5. Orphaned in the doc tree until this index.

Its founding rule binds everything in §3 and §4: **kill stats are a report card on the generator,
not a target.** Nothing may optimise the pass rate directly.

---

## 7. Adjacent research, not about writing

Indexed here so the search stops at one file; owned by the documents themselves.

| Document | What it measured | Date |
|---|---|---|
| [RESEARCH_EVIDENCE_RECALL.md](RESEARCH_EVIDENCE_RECALL.md) | our abstention rate is **73.3% `unverifiable`** on 14,006 checks against a published comparable of 6.2–9.2% | 2026-08-20 |
| [RESEARCH_CHEAP_INFERENCE.md](RESEARCH_CHEAP_INFERENCE.md) | making the verdict call cheap | 2026-08-20 |
| [ENGINE_BASELINE_2026-08-20.md](ENGINE_BASELINE_2026-08-20.md) | the engine's measured baseline | 2026-08-20 |
| [CARD_IMAGERY_RESEARCH.md](CARD_IMAGERY_RESEARCH.md) | licences, hardware and style consistency for generated card imagery — opened by *"can we use open source image generation for our cards for better engagement"* | 2026-08-15 |
| [ML_OPPORTUNITY_AUDIT_2026-08-15.md](ML_OPPORTUNITY_AUDIT_2026-08-15.md) | where ML would and would not pay | 2026-08-15 |
| [GENERATION_COST_ANATOMY.md](GENERATION_COST_ANATOMY.md) | what one generation tick spends | — |
| [COST_PROGRAM.md](COST_PROGRAM.md) | every cost lever and retired number | ongoing |
| [STOREFRONT_CRITIQUE_2026-08-19.md](STOREFRONT_CRITIQUE_2026-08-19.md) | every storefront finding, its receipt, its verdict | 2026-08-19 |

---

## 8. What is not measured

The honest column. Each line is a claim nobody here can currently support with a number.

| Question | Why it is unanswered | What would answer it |
|---|---|---|
| Is the `<X> for <buyer>` frame *bad*? | measured against a null drawn from our own corpus; one angle | a human reference corpus for genre B/C — [§4](#4-the-open-hole--a-human-corpus-for-the-selling-genre) |
| Does any copy change move a buyer? | `resolveVariant` pins every visitor to `'a'`; 24 analytics rows, all dev | B5 — a working variant split, then 3,780 impressions/arm |
| Did lens rotation fix the drift? | `select_lenses` landed 2026-08-19; the corpus ends 2026-08-15 | re-run the §3.3 monthly series on a corpus past 2026-08-19 |
| Does the storefront read as human? | genre B has no reference corpus and only a vocabulary guard | as above |
| Do the FOS deviations in §2.1 cost us anything commercially? | never joined to any sales outcome | B5 again |

---

## 9. Where the data lives

| What | Where |
|---|---|
| Verdict dossiers (the §3 corpus) | [ENGINE_100X_PROGRAM.md §9.5](ENGINE_100X_PROGRAM.md#95-where-the-dossiers-live--wish-25), surfaced in the ops panel |
| Corpus build outputs, keyness rows | `corpora/` — `keyness.json` is 4,448 rows over G2 15.13 |
| Corpus tooling | `tools/corpus/` — `build_ours.py`, `fetch_fos.py`, `keyness.py`, `structure.py` |
| Measurement scripts for §3 | `scratchpad/measure_template.py`, `scratchpad/measure_diversity.py` |
| Published web pages | [LINKS.md](LINKS.md) — a URL not in that file does not exist |
| What runs where | [ESTATE_MAP.md](ESTATE_MAP.md) |

---

## 10. The downstream synthesis programme — mining the kill log

**Founder directive 2026-08-21, verbatim:** *"the engine is basic in that geerates an idea, we have
data being generated but no downstrean process that acts on those and tries to nap new paths eh
nissed opportinities, problens that hurt different groups or sctors that can be synthesisetd ito a
coherent solution and generate a bter idea, the kill log ishas potential especially when conbined
with new reearch to spot new trend and oppituites etc, sonething to consider"* — and, on pace:
*"this is a slower process but ca end up yield better output"*, *"sonehtoing to explore, reserach
brainstorn add to list"*.

**Status: ON THE LIST. Nothing is being built. What follows is the measurement that decides
whether it is worth building, taken 2026-08-21 so the design starts from numbers.**

### 10.1 What the kill log actually holds

Measured over `store/dossiers` in a clone carrying the full corpus (2,929 dossier JSON files;
2,698 KILL, 108 PASS, 0 DEFER). Reproduce by pointing the loop at `config.store_root()` — do not
copy a worktree path, they come and go.

| dimension | measured |
|---|---:|
| KILL dossiers | 2,698 |
| KILL dossiers carrying at least one cited source | **2,667 (98.9%)** |
| cited sources inside the kill log | **46,220** |
| distinct source hosts | **17,687** |
| `structural_form` values (closed vocabulary) | 30 |
| markets represented | uk 1,879, us-il 155, us 129, us-ga 124, us-ca 96, us-oh 96 |

**The asset is the 46,220 sources, not the 2,698 verdicts.** Every one was fetched, cited and paid
for. It is a research corpus about UK and US market structure that the estate already owns and
nothing reads.

### 10.2 The finding that changes the design — two thirds of recent kills are OUR failure, not the idea's

| gate | kills | share |
|---|---:|---:|
| `moat_ungrounded` | 1,042 | 38.6% |
| `min_composite` | 744 | 27.6% |
| `source_or_die` | 256 | 9.5% |
| `incumbency` | 254 | 9.4% |
| `adversarial_decisive` | 140 | 5.2% |
| `value_durability` | 112 | 4.2% |
| `payer_solvency` | 59 | 2.2% |
| `legality` | 30 | 1.1% |
| everything else | 61 | 2.3% |

`moat_ungrounded` and `source_or_die` both mean **"we could not find the evidence"**, not "this
idea is bad". Together they are 48.1% of the whole log, and in August alone 1,238 of 1,830 kills —
**67.6%**. Mining the kill log for missed opportunities without filtering by gate would mostly be
mining a record of our own retrieval quality.

The same table read the other way is the reason to do it: the 2026-06 log is dominated by
`min_composite` (408 of 714) and the 2026-08 log by `moat_ungrounded` (992 of 1,830). **The kill
log has already changed shape once, and nothing noticed.**

A second look at the evidence quality is warranted before treating these sources as research. The
most-cited hosts across the kill log are `en.wikipedia.org` (2,311), `www.gov.uk` (1,856),
`www.youtube.com` (857), `www.facebook.com` (588), `dictionary.cambridge.org` (587),
`www.linkedin.com` (566), `www.merriam-webster.com` (439), `www.reddit.com` (396). A dictionary is
not evidence about a market. **NOT MEASURED: what share of the 46,220 are substantive.**

### 10.3 The owner already exists, and it is subtractive

**Do not write a new kill-log miner. [`prospector/denylist.py`](../prospector/denylist.py) is the
owner.** It already clusters the full kill corpus into "exhausted families" by content-token
Jaccard and feeds them to generation as a hard directive — denial prompting, arXiv:2407.09007,
cited in its own docstring. It excludes any family with a PASS survivor, and it never kills
anything itself.

Three measured facts decide how much of the founder's ask it already covers:

1. **It is subtractive only.** It tells generation what *not* to propose. The founder is asking for
   the additive half — synthesise a better idea out of the same corpus.
2. **It reads only the store INDEX rows, never the per-dossier JSON**, by design, because it runs
   on every generation call and must not pay that cost (`prospector/denylist.py:6`-`:8`). **So all
   46,220 cited sources are invisible to it.** That is the untapped asset, and it is untapped for a
   stated performance reason — which means the additive process must run offline and on a
   different cadence, exactly the "slower process" the founder described.
3. **It reads 18.8% of the log.** `FAMILY_GATES = {value_durability, incumbency, adversarial}`
   (`prospector/denylist.py:31`) is 506 of the 2,698 kills. The other 2,192 are unread by any
   synthesis path.

The only other consumers are counters: `prospector/report.py` and `prospector/ops/metrics.py`
aggregate `gate_fired` for display. Nothing synthesises.

### 10.4 The grouping dimension exists and is dirty

The founder's "problems that hurt different groups or sectors" needs an axis to group on.
**`Candidate` has no `sector` field** (`prospector/models.py:170`-`:193`) — checked, it is not
missing data, the field does not exist. What exists instead:

- **`structural_form`** — populated on 2,668 of 2,698 kills, a clean closed vocabulary of 30
  values (`vertical_tool` 574, `productized_service` 533, `data_intelligence` 266,
  `transaction_broker` 191, `picks_and_shovels` 181, `risk_financing` 141, …). Usable today.
- **`tags`** — populated on 2,674. Three keys are consistent (`audience` 2,668,
  `durable_wedge_type` 2,667, `commodity_premortem` 2,666) and are the real grouping axis.
- **The free-text tail of `tags` has case and separator drift**: `tech-vertical` (108) /
  `tech_vertical` (57) / `TECH-VERTICAL` (40); `uk` (302) / `UK` (103); `illinois` (60) /
  `Illinois` (66); `ai-native` (81) / `ai_native` (40) / `AI-NATIVE` (57). Any clustering that
  groups on raw tags will split every one of these in two or three. **Normalising the tag
  vocabulary is the cheapest prerequisite and it is a pure data pass.**

### 10.5 The open questions, and what would answer each

| question | what would answer it | status |
|---|---|---|
| Is there signal in the 46,220 sources beyond the verdicts they supported? | Sample 200 sources from `moat_ungrounded` kills and classify: substantive market evidence, or dictionary/social filler? | **NOT MEASURED** |
| Do killed ideas cluster into *unmet problems* rather than *dead shapes*? | Cluster on `tags.audience` after normalisation; count clusters with ≥5 kills, 0 passes, and a shared cited grievance | **NOT MEASURED** |
| Can a synthesised idea beat a generated one? | The only honest test is an A/B into the existing moat: N synthesised vs N generated from the same signals, same config, compare pass rate and composite. Anything short of that is a claim. | **NOT DESIGNED** |
| Does `moat_ungrounded` mark a real gap in the world or a gap in our retrieval? | Re-run the retrieval for 50 `moat_ungrounded` kills on today's chain and count how many now ground | **NOT MEASURED** — and this one is cheap, and it also tells us whether the August shift is a retrieval regression |
| Where does the synthesised output enter? | It must enter as a **signal**, upstream of generation, so every synthesised idea faces the same six gates. It must never enter downstream of a kill. | Design constraint, not a question |

**The hard constraint, restated: this may not become a way to un-kill.** A synthesis pass that
resurrects an idea the moat refused merges the two loops from the other direction. The output of
10.x is a new *signal*, and a new signal is vetted from scratch.

**One dependency, and it is not mine.** `denylist.py` mines the store index, and the canonical
store's SQLite index has been measured with 0 rows against 2,044 dossier files on disk. If that is
still true, the existing miner reads nothing. That defect was handed to the platform engineer on
2026-08-21 and is tracked there, not here.

---

## Maintaining this file

Add a row when a measurement lands, in the same commit as the measurement. A research document
that nothing links to is a document nobody will find: before this file existed, **20 of 132
documents under `docs/` were linked from no other document**, including
[TEMPLATE_FIRST_COPY.md](TEMPLATE_FIRST_COPY.md) and
[GENERATION_QUALITY_PROGRAM.md](GENERATION_QUALITY_PROGRAM.md), both of which answer questions
that were asked again later.

Deep links here are checked mechanically. Run `python3 scripts/doc_lint.py --links`; it resolves
every relative markdown link and `#anchor` in every tracked `.md` and exits 1 on a break.
