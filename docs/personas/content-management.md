# The platform for content management

Who writes the words a buyer reads, how those words get on the page, and what you can change without
a deploy.

## Four different kinds of words, four different owners

This is the first thing to get straight, because they are governed completely differently.

| Kind | Where it lives | Who writes it | Changed by |
|---|---|---|---|
| **Pack content** — the research a buyer paid for | Generated per pack, rendered by `prospector/pack_*.py` | The engine, under `source-or-die` | Only by changing a renderer or a prompt |
| **Listing copy** — title, one-liner, card text | `store/listings/`, then the store API catalogue | `content_gen`, then linted | A backfill tool, or a republish |
| **Storefront copy** — the site's own words | `store_platform/src/Store.Web/` | Humans | A code change and a deploy |
| **Operator copy** — console labels, Telegram replies | Console and Hermes source | Humans | A code change and a deploy |

## The rule that governs pack content

**Source-or-die.** Every factual claim and quantitative figure cites a retrievable source or is
marked `unverifiable`. No unsourced numbers ship, ever. A verdict rules only on passages actually
fetched — no prior knowledge, and silence means `unverifiable`, never `supported`.

This is not a style guide, it is the product. The packs are worth money because the claims in them
are checkable.

**The section renderers are deliberately model-free.** Sixteen `prospector/pack_*.py` modules do the
rendering, and `docs/PACK_NARRATIVE_PROGRAM.md` is authoritative on which are buyer-facing section
renderers and which are infrastructure (`pack_html`, `pack_pdf`, `pack_linter`, `pack_manifest`,
`pack_data`, `pack_validation`). Determinism is the point: a model inside a renderer makes the same
pack render differently twice, and a buyer who regenerates and gets different words stops trusting
the citations too.

**Read `docs/PACK_NARRATIVE_PROGRAM.md` before touching any of it.** It carries the reading order the
buyer actually experiences, the three gates that were grading less than they appeared to, and the
switches that are deliberately off. The top half is the diagnosis; the bottom half is the ledger.

## The linters, which are the real editors

- **`prospector/pack_linter.py`** — grades a pack. Its output is a receipt on disk (`*.lint.json`).
  **Read the persisted receipt before re-running anything**; the answer is usually already there.
- **`ops/config/retired_terms.yaml`** — vocabulary that must not appear. Terms get retired when they
  turn out to mislead a buyer.
- **`docs/HOUSE_WRITING_SPEC.md`** — the house voice.
- **`scripts/doc_lint.py`** — checks that documentation cites paths that exist. It only resolves
  **git-tracked** paths, so a doc citing a brand-new untracked file reports `missing_path` until the
  file is committed. That is not a bug in your doc.

## Storefront copy: two things that will surprise you

**The storefront renders no markdown.** Asterisks, underscores and backticks arrive on the page as
literal characters. Copy written in a markdown editor and pasted in will look broken.

**Published one-liners have truncated mid-word.** 34 of 63 at one point. Length limits are enforced
somewhere downstream of where the copy is written, so the writing side must respect them rather than
discover them.

Two more from the same family: an empty source card on a pack page is a **suppressed duplicate
quote**, not missing content. And a share card once carried another product's image, because bundle
keys are content-addressed and a stale key resolved to the wrong bundle.

## Changing copy that is already live

Republishing is not free and it is not always safe.

- Bundle keys are **content-addressed**. Change the content, get a new key. Anything holding the old
  key needs to move with it.
- **Republishing stranded passes fails on link rot.** Sources cited months ago may be gone. Citations
  are archived at vet time (`store/citation_archive.json`) precisely so the claim stays auditable
  after the page dies, but a republish that re-fetches will find the corpse.
- **A price change breaks fulfilment** if it goes through the catalogue instead of the rail. Copy
  changes must not touch price. Use `prospector/bridge.py`'s tools.
- `tools/backfill_bundle_html.py` is the tool for re-rendering existing bundles. There are audit
  trails at `store/shelf_copy_log.jsonl` and `store/retitle_log.jsonl`.

## What you can change without a deploy

- Anything in `ops/config/retired_terms.yaml` and the config-declared copy knobs — these are ops
  levers on purpose. The founder's standing rule is that **everything that can change is changed by
  the operator, not by an edit.**
- Listing copy, via the backfill tools in the console tool catalogue.

What still needs a deploy: storefront page copy, console labels, and anything in a renderer.

## What is not built

There is no CMS. There is no preview environment for copy, no editorial workflow, no scheduled
publishing, and no rollback for a copy change beyond `prospector.ops.undo` on the local half. Copy
review happens by reading the rendered output.

## What to read next

- `docs/PACK_NARRATIVE_PROGRAM.md` — mandatory before editing a renderer or the linter.
- `docs/HOUSE_WRITING_SPEC.md`, `docs/SITE_SPEC_PROGRAM.md`.
- [buyer.md](buyer.md) — what the words are actually for.
