# 0010 — The pack is a typed IR compiled to views, and support has two arms

- **Status:** accepted
- **Date:** 2026-08-22
- **Decided by:** founder
- **Supersedes:** nothing. Related: [0008](0008-shared-content-addressed-fetch-cache.md),
  [0011](0011-sourceref-is-minted-by-the-fetch-path.md). Owns the *structure* of a pack;
  `docs/PACK_NARRATIVE_PROGRAM.md` owns what it says.
- **Question it answers:** a pack sells for £2,000 to £27,000. A dropped citation, a corrupted
  currency symbol or a figure that differs between the PDF and the HTML destroys the authority of
  the whole thing. How is a pack built so those are not possible rather than caught?

---

## The decision

**Generate one typed value; render every format from it.** Not prose generated then repaired.

```rust
pub enum Support { Cited(SourceRef), Unverifiable }     // sealed; exactly two arms

pub struct Figure {
    label: String, value: Decimal, unit: Unit,
    as_of: NaiveDate, source: SourceRef,                // no constructor without one
}
```

PDF via Typst, HTML via Askama, plus CSV and JSON — all pure functions of the same value. A
differential gate then asserts every `Claim` and `Figure` in the value appears in every rendered
view, which is what stops the PDF and the web page disagreeing.

## The three additions taken

1. **`Decimal`, not floats, for research figures.** A model a buyer can check must not round. Note
   the scope: the money rail already has no float — `prospector/pricing.py:64` is `price_pence:
   int`. The exposure is growth rates, market sizes and inflation assumptions.
2. **A manifest hash over the whole set.** `prospector/pack_manifest.py:253,269` already writes a
   `sha256` per file, and `prospector/bridge.py:1484` hashes the zip for the R2 key. A zip digest
   moves with compression and entry order; a digest over the sorted file list and their content
   hashes is stable and is the thing a buyer can quote back.
3. **Ship the archived source snapshots as files, under `./sources/`.** Today
   `prospector/archive.py:471` stores a Wayback memento *URL*, best-effort inside a blanket except,
   with the documented worst case "a pack with no mementos". Shipping bytes does not depend on
   archive.org accepting a save, cannot 404 later, and works for pages the Internet Archive will not
   take. It turns "we cite sources" into "here are the pages, as they existed, dated". At this price
   point that is a product difference, not engineering hygiene.

   **ADR 0008 makes it nearly free.** `fetch_cache.body_key` already puts the fetched bytes in R2
   before anything is built from them. The snapshot is a copy, not a second fetch.

## The two things refused

**A third arm, `Support::VerifiedFact`** — true because the model knows it. Refused. It re-admits
prior knowledge into a system whose founding invariant is verdict-from-retrieval-only, and it fails
in exactly the shape of the legality polarity bug: a reasonable-looking addition that quietly
inverts the rule the type was built to enforce. **Two arms. Cited or Unverifiable.**

**`Unverifiable // triggers an explicit listing blocker if unallowed`.** "If unallowed" is the fence
returning as a switch someone can leave off, which is the entire history of programme doc section
33. The point of making an unsourced figure unrepresentable is that section 33 stops being a switch.

## The asymmetry that must survive, and it is easy to lose

**A figure that cannot cite must not be buildable into a pack. A figure that cannot cite must not
kill a candidate.** `prospector/models.py:318-327` records why the second half exists:
`untraceable_figures` is observed only and must never demote a verdict, because an absent number is
*our* extraction failure and `kill_filter` can hard-fail on an `unverifiable` hard gate. Enforcing
the pack rule at the verdict would let our own extraction bug kill sound ideas. Two layers, two
rules, and collapsing them is a regression in whichever direction it happens.

## One overclaim corrected

The proposal states the provider "physically cannot return tokens that violate the schema".
Structured output guarantees **syntactic** conformance. It does not stop a model emitting a
`SourceRef` to a URL it never fetched, or a `Decimal` that appears in no passage. Schema mode kills
parse failures — it would retire `json_repair` Strategy 5 (`prospector/operator.py:203,255`) — and
nothing more. Acting on the stronger reading would cost a real guard. ADR 0011 is that guard.

## Provenance of this decision, stated so it is not over-weighted

This came from a third document that was written in response to the founder's own design. **Two
models agreeing after one has read the other is one opinion with extra steps**, not independent
confirmation (`AGENTS.md` LAW 15). Only the deltas above were taken, and each was checked against
the code before being recorded. The document did not address the engine questions — the
(candidate, check) unit, money as the rate limiter, deletion before rewrite — and is not evidence
about them.

## What this does not decide

Whether to build it. The pack layer today is 17 `pack_*.py` modules including a 121KB linter; this
is what replaces them if and when the strangler reaches that layer, and it is not in the four steps
of [ADR 0009](0009-strangler-sequencing.md).
