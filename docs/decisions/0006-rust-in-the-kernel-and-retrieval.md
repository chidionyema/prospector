# 0006 — Rust in exactly two places: the invariant kernel and retrieval/extract

- **Status:** accepted
- **Date:** 2026-08-22
- **Decided by:** founder
- **Supersedes:** narrows [0002 — Keep the engine in Python](0002-engine-runtime-and-engineering-standards.md).
  0002 is not reversed; see below. Related: [0009](0009-strangler-sequencing.md).
- **Question it answers:** ADR 0002 measured the rewrite case and rejected it on 2026-08-19. What
  changed, and where exactly does Rust go?

---

## The decision

**Two places, and nowhere else.**

1. **The invariant kernel** — verdict types, gate polarity, trust provenance, the price decision,
   the config split. Two to three thousand lines.
2. **Retrieval and extraction** — fetch, extract, passage select, rank. The one layer whose CPU cost
   grows with candidate count.

Everything else stays where it is: the storefront API in .NET, the ops console in Next, the prompts
as `.md` files, and the LLM call as HTTP and JSON where no language has an advantage.

## What ADR 0002 got right and still stands

0002 classified nine incidents and found a type checker would have caught one and partly a second.
**That measurement is not disputed and this decision does not overturn it.** Its two largest defect
classes — a check that cannot fail (4 of 9) and an assumption about the environment (2 of 9) — are
language-independent, and a Rust kernel does nothing for either. Its conclusion that unenforced
standards, not Python, are the bug driver remains the operative one for the other 132,000 lines.

0002 also established that a working lease already exists (`prospector/store.py:585`), correcting an
assertion made in chat before the code was read. That correction still holds and is why
[0007](0007-spend-is-a-leased-budget.md) is careful to say it leases *money*, not rows.

## What changed

**A different question is being asked.** 0002 asked "would types have caught our recent bugs?" and
answered no. This asks "which invariants can only be enforced by a compiler, and how much do they
cost?" — and the answer is a short, specific list:

| Invariant | Enforced how today | Enforced how in the kernel |
|---|---|---|
| Legality polarity | configured per check | derived from a sealed `Verdict` |
| An exception is never evidence | convention plus a test (`verify.py:365`, `:693`) | `Result<CheckOutcome, RetrievalFailure>` |
| Provisional never publishes | a runtime check at `run.py:864` | `publish` accepts only `Ruling<Trusted>` |
| Price cannot drift | `bridge.py` exists solely to prevent it | `PriceDecision` moves; two consumers is a compile error |
| Market override keys | a runtime list plus a test (`MARKET_FORBIDDEN_KEYS`) | two structs; the override simply lacks the fields |

**And a second reason 0002 did not weigh: retrieval is real CPU work that scales with volume.**
That is a throughput argument, not a correctness one, and it is the stronger of the two.

## The evidence that it pays, measured

`engine-rs/crates/prospector-retrieval` was written against `prospector/retrieval.py:fetch_page` and
graded byte-for-byte by `scripts/retrieval_parity.py`. Grading found a live grounding defect: the
Python decoded every page served as bare `text/html` as ISO-8859-1, because that is what RFC 2616
tells `requests` to report. UTF-8 pages reached the verdict brain as mojibake — 32 corrupted
characters in 5,504 on one page. **None of 8,431 tests could see it**, because mojibake is still
well-formed text. The fix landed in the Python. A second implementation is an instrument the test
suite is not, and that is a cost of the port already recovered before it replaced anything.

## What was rejected

- **Rewrite the engine.** Months of owning two systems, with the bug surface being the disagreement
  between them. Refused; 0002's reasoning is why.
- **`pyright --strict` on the domain core instead.** Reachable for four of the five invariants
  above, and cheaper. It is not refused — it is simply not what was chosen, and it remains the right
  move for the Python that stays. Recorded here so the option is not lost.
- **PyO3 as the permanent shape.** The seam stays available for an irreplaceable library. Nothing is
  designed around it.

## How we will know it was wrong

If the kernel grows past roughly three thousand lines, or if a prompt change starts needing a
rebuild, the boundary has moved and this decision needs revisiting.
