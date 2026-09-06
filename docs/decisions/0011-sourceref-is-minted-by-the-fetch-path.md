# 0011 — A SourceRef can only be minted by the fetch path, never by a model

- **Status:** accepted
- **Date:** 2026-08-22
- **Decided by:** founder
- **Supersedes:** nothing. Related: [0010](0010-the-pack-is-an-ir.md),
  [0008](0008-shared-content-addressed-fetch-cache.md),
  [0006](0006-rust-in-the-kernel-and-retrieval.md).
- **Question it answers:** ADR 0010 makes an **unsourced** figure unrepresentable. What stops a
  **falsely-sourced** one?

---

## The gap

A type system can require that a `Figure` carries a `SourceRef`. It cannot, by itself, require that
the `SourceRef` points at a page anyone fetched. If the generation layer can construct one, the
model can invent one: a plausible URL, a plausible title, a figure that appears in no passage. The
pack then passes every structural gate and is wrong in the one way a buyer can check.

Structured output does not close this. It guarantees the shape of the tokens, not their truth.

## The decision

**Make `SourceRef` unconstructable outside the fetch and archive path.**

```rust
pub struct SourceRef(FetchId);          // field is private to the retrieval crate

impl SourceRef {
    // No public constructor. No From<String>. No Deserialize that builds one.
    pub(crate) fn mint(row: &FetchCacheRow) -> Self { .. }   // the ONLY way one exists
}
```

The generation layer receives `SourceRef` values; it cannot make them. A model can only reference
the sources it was handed. **Fabricating a citation stops being a thing to detect and becomes a
thing that does not compile.**

The minting authority is the `fetch_cache` row from [ADR 0008](0008-shared-content-addressed-fetch-cache.md)
— a real fetch, with a status, a body in R2, and a timestamp. That is also what makes ADR 0010's
`./sources/` directory correct by construction: every `SourceRef` in a pack has a body to ship,
because it could not have existed otherwise.

## Why this is the right shape

It is the pack-layer form of a rule the engine already enforces: **a kill needs a citation.** The
engine has never let a verdict be an opinion; this stops a figure being one.

It also completes [ADR 0006](0006-rust-in-the-kernel-and-retrieval.md). Four invariants there become
compile errors about *where a value may travel*. This one is about *who may create a value*, which
is the other half of what a type system buys and the half the earlier list missed.

## What has to be true for it to hold

- **Deserialisation is the back door.** Any `impl Deserialize for SourceRef` that reads a string
  re-opens exactly the hole this closes. Round-tripping a stored pack must resolve refs through the
  cache, not reconstruct them.
- **It is not retroactive.** `prospector/models.py:142` `Source` is a plain dataclass with a public
  `url`, constructible anywhere. Existing dossiers cannot be re-typed; the guarantee starts where
  the Rust path starts.
- **It does not check that the figure is *in* the passage.** It guarantees the source was fetched,
  not that the number appears in it. That is what `untraceable_figures`
  (`prospector/models.py:327`, `figure_check.py`) measures today and it stays.

## The alternative

**Detect fabricated citations after generation** — probe every URL, then compare figures against
retrieved passages. That is what the estate does now, and it works: `pack_linter.py:1830-1836`
probes a memento before trusting it. It is also a check that has to keep working forever, on every
path, and a check that can fail is the largest defect class in the incident record
([ADR 0002](0002-engine-runtime-and-engineering-standards.md): 4 of 9). Making the value
unconstructable removes the check rather than adding one.
