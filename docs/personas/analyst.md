# The platform for the analyst

Your job here is not to build dashboards. It is to answer "where does the funnel leak" and, harder,
"can I trust the number I am about to put in front of the founder".

The second one matters more than usual in this estate, because several numbers here have been wrong
in ways that looked completely healthy.

## The funnel, stage by stage

A signal comes in. Candidates are generated from it. Each candidate runs a gauntlet. Survivors get
scored, and only then can anything be published and sold.

| Stage | What it does | Where the number lives |
|---|---|---|
| Signal | An input observation | `signals/pending/` holds ones that failed and will resume |
| Generate | `candidates_per_signal` ideas per signal, currently 20; `schedule.batch_size` 15 | `store/generation_metrics.jsonl` |
| Dedup | String similarity against the catalogue — `difflib.SequenceMatcher` plus Jaccard token overlap, **not embeddings**. `dedup_threshold: 0.85` (`config.yaml:2005`), `dedup_token_threshold: 0.34` (`config.yaml:2184`) | dropped before any spend |
| Prescreen | Fast, cheap triage that preserves novelty | run records |
| Verify | Seven checks, kill-fast, on a trusted brain | `store/dossiers/*.json` and `*.kill.json` |
| Kill filter | Six deterministic hard gates | the `.kill.json` names the gate |
| Score | Six axes, weighted composite | dossier |
| Publish | Only on PASS | `store/listings/`, then the catalogue |

The embedding-based prefilter exists at `prospector/prescreen_prefilter.py` and is **wired off** in
`config.yaml:2015`. Do not report it as part of the funnel.

## The gates, and what each one can do

Six hard gates, evaluated kill-fast in this order (`config.yaml:551-556`):
`value_durability`, `incumbency`, `payer_solvency`, `distribution`, `legality`, `pain_reality`.

Every one kills on `refuted` and only on `refuted`. Nothing kills on `unverifiable`, because
unverifiable means "no matching passage was found", which is silence, not evidence.

A seventh check, `price_comparables`, is **evidence-only and can never kill**. It is barred in
`kill_filter.is_hard_fail` and in verify's run order. "No price page on the open web" is a fact about
the web, not about the idea.

Two calibration numbers you will be asked about, both taken against live data rather than guessed:

- **`confidence_floor: 0.4`** (`config.yaml:515`). A grounded killing verdict only hard-kills when
  its confidence clears this. Raised from 0.0 on 2026-08-07 by replaying `store/dossiers/*.kill.json`
  through the real gate code: of the 333 kills whose gate reproduces under the shipped config, 66 are
  freed at 0.4, which is 19.8%. Against a firing-check confidence distribution of p10 0.23 / p25 0.40
  / median 0.55 / p90 0.70, that retires the bottom quartile and never touches the median kill. At
  0.5 it frees 43.2%, which is a product decision, not calibration.
- **`min_supported_confidence: 0.3`** (`config.yaml:523`). Calibrated against 504 supported checks in
  `store/dossiers/`: median 0.43, p25 0.40, p10 0.30, max 0.79. **The live confidence scale is
  compressed around 0.43, not spread across 0-1.** If you normalise these as if they were 0-1
  probabilities you will draw the wrong conclusion. A floor of 0.5 would void 76% of genuinely
  supported checks.

## Scoring

Six axes, weights summing to 1.00 (`config.yaml:567-572`):

| Axis | Weight |
|---|---|
| defensibility | 0.25 |
| pain_acuity | 0.20 |
| money_provability | 0.20 |
| automatability | 0.15 |
| distribution | 0.15 |
| build_feasibility | 0.05 |

`min_composite_to_pass: 2.5` (`config.yaml:525`).

The 2026-06-25 re-weighting is the most instructive artefact in the config for an analyst, because it
is a case of a metric rewarding the opposite of the goal. `automatability` (0.20) plus
`build_feasibility` (0.10) meant 0.30 of the composite paid out for "trivially easy to build", which
is the same thing as "trivially easy to clone", which is no moat — while `defensibility`, the only
moat axis, carried 0.15. A generic AI wrapper was the global maximum of that formula. The fix moved
clonability reward 0.30 → 0.20 and moat 0.15 → 0.25.

## Segments

The catalogue is deliberately mixed-ambition. Four lanes run at once
(`config.yaml:588 active_lanes: [side_hustle, smb, growth, venture]`), each candidate is
auto-classified into its natural tier, and each is then judged against **that tier's** bar. Lane
quotas were rebalanced on 2026-08-01 from historical per-lane PASS rates across 221 tier-tagged
dossiers: smb 6/51 = 11.8%, growth 2/41 = 4.9%, side_hustle 4/94 = 4.3%, venture 0/35 = 0.0%.

Those are small denominators. Treat them as direction, not as precision.

## Where the raw data is

- `store/dossiers/*.json` and `*.kill.json` — one file per verdict, with all checks, confidences,
  sources and the provider that ruled. This is the richest dataset in the estate.
- `store/prospector.jsonl` — the append-only ledger: runs, spend, timings.
- `store/generation_metrics.jsonl` — generation counters.
- `store/prospector.db` — one table, `dossiers`, 2995 rows as last counted. The same verdicts as
  the JSON files, in a form you can query. `store/catalog.sqlite3` is 0 bytes and is a leftover;
  do not point anything at it.
- The **sellable** catalogue is not here at all. It lives in the store API's own database on the
  `store_data` volume, with typed metadata columns rather than a JSON blob, and is reached over
  HTTP.
- Store API: `/catalog/stats`, `/internal/analytics/*`, `/internal/catalog/{id}/price-history`.

`PROSPECTOR_STORE_DIR` pins the canonical store. There is exactly one, and it is on the laptop at
`/Users/chidionyema/Documents/code/prospector/store`, even though the engine runs on Fly.

## Numbers here that have been wrong, and how

Read this section before you quote anything.

| The number | How it lied |
|---|---|
| Transcript cost totals | Double-counted per record |
| Composite score in a KILL | A dossier with all seven checks reading `unverifiable, conf 0.0, "Verdict call failed; fail-safe."` was recorded as a reasoned kill on `min_composite`. It was our own outage. `store/dossiers/2102bacc6dd75cf9.kill.json` is the receipt. Failed calls now DEFER |
| Replaying kills | Replay only reproduces **hard gates**, not the full original decision |
| A superset sample | Masked a severity-dependent check |
| Any max or threshold count derived in shell | `awk` and shell compare as **strings** unless an operand is numeric. Coerce with `+0` and re-run. This produced a wrong finding on 2026-08-06 |
| A green single-file regression guard | Reported green while measuring one file |
| Backlog counts | `run.drainable()` is the single definition of backlog. When the count fails it returns `None`, never `0` |

## What is not built

There is no BI tool, no warehouse, and no scheduled reporting. Analysis here means reading JSONL and
SQLite directly, or the `/internal/analytics/*` endpoints. Nothing aggregates the dossier corpus into
a queryable table — that is the single highest-value analytics gap.

## What to read next

- [data-engineer.md](data-engineer.md) — the shape and location of every store.
- [machine-learning-engineer.md](machine-learning-engineer.md) — how the verdicts are actually made.
- `docs/GENERATION_QUALITY_PROGRAM.md` — the quality work the funnel numbers feed.
