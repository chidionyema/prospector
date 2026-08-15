# Pack contents review (opened 2026-08-15, ANSWERED and SHIPPED 2026-08-15)

Founder's brief, verbatim:

> "why do we need 14 files? we did work to improve presentation and format of pack not to
> increase the number of files, do the files actually contain unique content? i dont like
> md files at all, we are not selling to developers"

All three questions are answered below with the measurement behind each, and the answer has
been implemented in code. Everything below is a MEASUREMENT or a LEAD, labelled as such.

## What shipped

**14 archive entries became 6, and none of them is Markdown.** A buyer now receives:

```
index.html            the whole pack as one readable web page
Complete_Pack.pdf     the same pack typeset for print
First_Fortnight.html  the one page to pin up
Assumptions.csv       every assumption as a spreadsheet
Marketing_Assets.txt  the copy, ready to paste
manifest.jsonld       machine-readable index (a bonus, not a promise)
```

The nine Markdown documents are still composed — they are the render INPUT — but they stop
at the zip boundary. Measured live on pack `0bf4d472ef2b90ad` (its real R2 object, not a
fixture): **14 entries → 6, −40,697 bytes (−15.4%)**, no `.md` remaining, and a second pass
over the new zip is a no-op.

The mechanism is a split of one overloaded tuple in `prospector/bridge.py`:

| tuple | what it now means | count |
|---|---|---|
| `PACK_DOCUMENTS` | the render input, in composition order | 8 (+1 derived) |
| `BUNDLE_READING_ORDER` | reading order = the above with `Evidence_and_Constraints.md` before the QA report | 9 |
| `BUNDLE_FILES` | the archive CONTRACT — `audit_bundle` blocks the listing on any missing one | 5 |
| `BUNDLE_BONUS_FILES` | in the zip, not promised | 1 |

`BUNDLE_FILES` was doing both jobs at once, which is why "what we render" and "what we sell"
could not be changed independently.

**Deliberate behaviour change:** because the rendered files are now the contract, a PDF /
reader / card / CSV render failure takes the pack OFF the shelf (`is_listed` is ANDed with
`audit_bundle`) rather than shipping it quietly short. That is the trade the 59/59 backfill
result bought — see "The backfill job" below.

**The conversion is one-way** and is treated as such: once a pack's `.md` are dropped there
is nothing left to re-render the reader FROM. Two guards refuse rather than write a short
zip (`if not documents: return None`, `if dossier is None: return None`), and R2 keys are
content-addressed, so a backfill writes a NEW object and the pre-conversion one is never
overwritten.

**Two buyer-facing defects the change created, found and fixed the same day.** Both were the
same mistake: prose that named a document by its FILENAME, which was harmless while the file
was in the download and became a direction to open something that is not there.

- `prospector/pack_floors.py` — the executive summary, the first block a buyer reads, said
  "Open **QA_Report.md**". Now names sections (`QA_SECTION`, `CHECKLIST_SECTION`).
- `prospector/pack_checklist.py` — the fortnight page, the one a buyer pins up, interpolated
  its own dict KEYS into five sentences ("It is in *04_Financial_Model.md*"). Now has
  `BUILD_SPEC_SECTION` / `GTM_PLAN_SECTION` / `OPS_PLAN_SECTION` /
  `FINANCIAL_MODEL_SECTION` beside the key constants.

Both sets of constants are pinned by test to `bridge._SECTION_TITLES`, so the copy cannot
drift from the heading the reader actually prints. Verified by rendering both documents over
**92 real local bundles with their real dossiers: zero `*.md` names in the output.**

**The storefront counts two different numbers now.** Nine documents arrive as five files, so
`PackContents.tsx` exports `PACK_DOCUMENTS` (what you read), `PACK_CONTENTS` (what you get)
and `PACK_EXTRAS` (what rides along), each count rendered beside the noun it counts.
`packContents.test.ts` reads all three tuples out of `bridge.py` and fails on drift in either
direction — including a symmetrical guard that the document count is never called "files"
and the file count never called "documents", which is the exact false claim that started
this.

**Still to run:** `scripts/backfill_packs_parallel.sh --apply` rewrites the 59 live archives.
Until it runs, the shelf still serves 14-entry zips containing `.md`.

## Measured (re-verifiable)

**The shelf and the engine agree on the count.** `PackContents.tsx` lists 8 + 6;
`prospector/bridge.py:271` `BUNDLE_FILES` is 8 and `BUNDLE_BONUS_FILES` is 6. The "8
documents" headline is `PACK_CONTENTS.length`, computed not typed. So the storefront is
NOT lying about the archive — which was the previous bug (`d752a9c`, 2026-08-14, and the
comment at `PackContents.tsx:199-209` records that it used to say "8 **files**" while 33
of 45 live bundles held 9 or 10 entries).

**CONFIRMED — almost no real buyer has received a 14-entry pack.** Entry counts across
all 133 bundles under `publish/bundles/`: `{5: 6, 6: 1, 8: 20, 10: 82, 14: 24}`. By day:
`2026-07-31: {8: 20}`, `2026-08-09: {10: 51}`, `2026-08-13: {10: 11}`,
`2026-08-14: {10: 13, 14: 24}`. So the 14-file format is genuinely NEW (all 24 are
2026-08-14) and the shelf is not advertising a legacy shape — but **21 of those 24 are
test fixtures** (`c2-drift`, `c2-flat`, `c2-ladder`, `c2-new`, `c2-rationale`, `c2-reuse`,
`c2-stub`, `dry-cand-001..004`, `gate-live`, `gate-ok`, `gate-stub`, `gate-stub2`,
`test-audience-absent`, `test-audience-case`, `test-audience-ok`, `test-cand-123`,
`test-cardline-absent`, `test-cardline-long`). Only **3 real candidate ids** have 14:
`25363e54b649587a`, `3d20db251950c20a`, `af1647af560711a1`. The 13 real packs generated
the same day still hold 10. Re-derive with a 16-hex-digit `re.fullmatch` on the bundle
directory name.

Consequently `Complete_Pack.pdf` — the shelf's headline extra, "every document above in
one printable PDF" — ships in **24/133 bundles, 21 of them fixtures**. `index.html` is
absent from **27/133 (20%)**. The fullest real pack,
`publish/bundles/ad26e53cae963bc8/prospector_pack_ad26e53c.zip` (18,095 primary words),
contains exactly ten entries and **no PDF**:

```
00_Executive_Summary.md 01_Blueprint_BuildSpec.md 02_Marketing_Plan_GTM.md
03_Operations_Plan.md 04_Financial_Model.md 05_First_Week_Checklist.md
Marketing_Assets.md QA_Report.md index.html manifest.jsonld
```

**Duplication, measured on that full pack.** 8-word shingle overlap of `index.html`
against each of the eight `.md` primaries in turn:

| primary | % of it already inside `index.html` |
|---|---|
| `00_Executive_Summary.md` | 86.8% |
| `01_Blueprint_BuildSpec.md` | 97.2% |
| `02_Marketing_Plan_GTM.md` | 100% |
| `03_Operations_Plan.md` | 97.9% |
| `04_Financial_Model.md` | 100% |
| `05_First_Week_Checklist.md` | 68.6% |
| `Marketing_Assets.md` | 100% |
| `QA_Report.md` | 88.4% |

Median ≈ 97%. The earlier thin-bundle table (`af1647af560711a1`, 694 primary words) is
superseded by this one and should not be quoted.

## What a buyer actually receives today — measured over the LIVE shelf

> ⚠ **CORRECTION (2026-08-15).** An earlier version of this section measured
> `publish/bundles/` and reported "73 of 75 listed packs have 10 entries, only 2 have the
> PDF". **That was the wrong artifact.** `publish/bundles/` is the local build directory
> and is stale against what the store actually serves. Do not measure the product there.

The live shelf is **59 packs** (`GET /catalog` — 75 is the count of local
`store/listings/*.json` files, which is not the shelf). Fetching every one of the 59
CURRENT zips from R2 via the db pointer (`GET /internal/catalog/{id}/content`, header
`X-Internal-Key`) and reading the archives:

```
entry-count distribution: {14: 59}
containing Complete_Pack.pdf: 59
```

**All 59 live packs already ship all 14 entries, PDF included.** The P5 backfill has
already been run against the shelf. A buyer today receives:

```
00_Executive_Summary.md  01_Blueprint_BuildSpec.md  02_Marketing_Plan_GTM.md
03_Operations_Plan.md    04_Financial_Model.md      05_First_Week_Checklist.md
Marketing_Assets.md      QA_Report.md
Assumptions.csv  Complete_Pack.pdf  Evidence_and_Constraints.md
First_Fortnight.html  index.html  manifest.jsonld
```

Confirmed independently by a full dry run of `tools/backfill_bundle_html.py` over all 59
(`scripts/backfill_packs_parallel.sh`, 10 slots): **57 already-correct, 2 would-convert**,
and both of those two are cosmetic —

```
[would-convert] a8333b00e91eec66  289579B -> 289371B (-208B, reordered reader, manifest refreshed)
[would-convert] 64c58072e2585c2b  250603B -> 250386B (-217B, reordered reader, manifest refreshed)
```

**The 8 `.md` are wholly redundant with `index.html`.** Measured across a 12-pack sample
of listed bundles, comparing normalised text and resolving citation markup (a
`[text](url)` rendered as an `<a href>` is the same content, not lost content):

| unit compared | checked | absent from `index.html` |
|---|---|---|
| headings (`^#{1,6}`) | 853 | **0** |
| table cells | 208 | **0** |
| prose runs ≥8 words, citations excluded | 6,743 | **0** |

Provenance: this sample was read from `publish/bundles/`, but the finding carries to the
live packs — the eight `.md` and `index.html` are rendered by the same code from the same
dossier, and both sets are byte-identical for the `.md` (the backfill copies them
unchanged; `backfill_bundle_html.py:283`). Re-run against a live zip if you want it
airtight.

Method note for whoever re-runs it: a naive whole-sentence match reports **9.7%** missing
and a URL-stripped one **2.65%**. Both are artifacts of markdown link syntax, not content
loss — `(source: https://…)` inline parentheticals and `[text](url)` break exact matching
while the prose either side is present verbatim. **Compare prose runs, not sentences**,
or this measurement will manufacture a false finding. The earlier 8-word-shingle table
(68.6%–100%) is superseded for the same reason: shingles break on reflow.

## The founder's three questions

1. **Why 14 files?** Because the P4/P5 fixes were shipped **additively**. `bridge.py:1669`
   quotes the brief — *"markdown files is not the one"* — and the response kept the eight
   `.md` and added four artefacts beside them. That is the increase-not-improve outcome.
2. **Do they contain unique content?** **No, for the eight `.md`** — 0 of 6,743 prose runs,
   0 of 853 headings, 0 of 208 table cells are absent from `index.html`. Deleting all eight
   from the zip costs the buyer nothing readable. `manifest.jsonld` is 0% duplicate but is
   machine-only. The PDF and `First_Fortnight.html` are duplication BY DESIGN — they are
   re-presentations, which is the point of them.
3. **"I don't like md files at all, we are not selling to developers."** Sustained. There
   is no buyer-facing reason for `.md` to be in the download. It is the engine's source
   format, promoted to buyer contract by default rather than by decision. The only thing
   REQUIRING it in the zip is our own listing gate: `audit_bundle` (`bridge.py:354`)
   computes `missing = [f for f in BUNDLE_FILES if f not in written]`, so a pack cannot be
   listed unless all eight `.md` are physically inside the archive.

## The backfill job — ALREADY DONE, do not re-plan it

> ⚠ **CORRECTION (2026-08-15).** This section previously called the PDF backfill "the
> bigger job". It is complete: 59 of 59 live packs carry the PDF (see the section above).
> The history below is retained because it explains the cutoff and is still accurate about
> `publish/bundles/` — but it describes the LOCAL build directory, not the shelf.

The cutoff is exact, not approximate:

- `pack_pdf.py`, `pack_card.py`, `pack_table.py`, `pack_reference.py` were all added in
  **`40212a3`, 2026-08-14 17:39:34 +0100** (`git log --diff-filter=A`). `pack_html.py` is
  older — `1070b99`, 2026-08-01 — which is why `index.html` is in nearly every pack and
  the PDF is in almost none.
- Listed-pack bundle build dates: `2026-08-08: 1`, `2026-08-09: 46`, `2026-08-10: 2`,
  `2026-08-13: 11`, `2026-08-14: 15`.
- The 15 built on 2026-08-14 split cleanly at the commit: **13 were built 00:12–04:02**
  (before 17:39 — no PDF), and **2 at 18:20 and 21:01** (after — and those are exactly the
  2 listed packs that have the PDF). Confirms the mechanism with no ambiguity.

`40212a3`'s own subject line is *"the fixes reach the packs already sold, not only the next
one"*, and `bridge.py:1671` states the extras are deterministic projections of files
already written so **the same renderers can backfill packs already sold**. So the backfill
path is designed for and `tools/backfill_bundle_html.py` is the precedent. It has not been
run for the P5 artefacts.

**Not verified here:** whether any pack containing the PDF has actually been *purchased* —
that needs the sales ledger, not the bundle directory. (The shelf question IS now settled:
all 59 live packs contain it. `GET /v1/listings` → 404 was a path I invented; the real one
is `GET /catalog`, used at `tools/backfill_bundle_html.py:417`.)

## Recommended shape — EXECUTED 2026-08-15

1. ~~**Backfill first, delete second.**~~ **Backfill is DONE** — 59/59 live packs carry the
   PDF, card, CSV and evidence doc. That result is what answered the objection which had
   blocked the deletion ("can't promote the rendered files to contract until they generate
   reliably").
2. ~~Invert the tuples~~ **Done**, though as a SPLIT rather than an inversion: `.md` are
   still generated internally and are no longer in the zip, but the reason the inversion was
   awkward to describe is that `BUNDLE_FILES` was two contracts in one name. It is now
   `PACK_DOCUMENTS` (render input) and `BUNDLE_FILES` (archive contract), and each can move
   without the other.
3. ~~Keep ONE editable artefact~~ **Done** — `Marketing_Assets.txt`, converted with
   `plain_text.to_plain_text`, which strips markup and never rewords. Checked for content
   loss on the smallest one on the shelf: `0bf4d472ef2b90ad`'s asset renders to 386 bytes,
   and the source `.md` is itself 391 chars / 65 words — the delta is the `#` markers, not
   dropped prose.
4. Tests moved with them: `tests/unit/test_bundle_declared_entries.py`,
   `tests/unit/test_bundle_index_html.py`, `tests/unit/test_pack_floors.py`,
   `tests/unit/test_pack_checklist.py`, and `packContents.test.ts` on the storefront side.

**Separate pre-existing issue, surfaced by this work and NOT fixed:** `Marketing_Assets.md`
word counts across the 59 live packs run min 28 / p25 266 / median 392 / max 1600, with
**8 of 59 under 150 words** (smallest: `256f0861192932ff` 28, `0bf4d472ef2b90ad` 65,
`ea773998f6a925b0` 74, `a884727a1b90447c` 78, `b94760e86e62585a` 103) while the shelf
promises "listing page, outreach, social". That is a content-generation problem, not a
packaging one, and needs its own owner.

## Fences that constrain any change here

- `bridge.py` mints the Price object AND the catalogue row together — money rail. Do not
  reshape the bundle without reading `CLAUDE.md`'s bridge.py rule.
- `audit_bundle` iterates `BUNDLE_FILES` asking "did it arrive?"; anything in NEITHER
  tuple is invisible to it by construction. `undeclared_bundle_entries` exists to catch
  that. Tests: `tests/unit/test_bundle_declared_entries.py`,
  `tests/unit/test_bundle_index_html.py`.
- Storefront copy rules live in `docs/SITE_SPEC_PROGRAM.md` — read before touching
  `PackContents.tsx`.
