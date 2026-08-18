# The backlog

One ranked list. Everything the estate owes, in the order it should be paid.

Founder, 2026-08-18: "everything has to turn to backlog item, and prioritised analysis plan and
story, we need that discipline, we dont track properly and have no central backlog." Before this
file, work was tracked in a chat session's task list. That list dies when the session ends, so
every new session rediscovered the same work. Thirty programme docs each track their own slice and
none of them rank against each other, so "what should I do next" had no answer anywhere.

## How this file works

Rank order is the only order. P0 before P1, top to bottom inside a band. An item moves up only
when a measurement says it should, and the measurement goes in the item.

Every item carries four things and is not an item without them:

- **Breaks today** — what is wrong, with the number or the `file:line` that proves it. No adjectives.
- **Story** — what a person can do afterwards that they cannot do now.
- **Done when** — the command that returns green. Not a description of done: the probe.
- **Costs** — rough size. S is under a session, M is a session, L is more than one.

Two rules that keep it honest:

- **No item without a measurement.** If nobody has measured it, the item is "measure it", and the
  fix is the item after.
- **Report mode before fix mode.** Any sweep ships read-only first and takes `--fix` second.

## The rule that generated most of this list

**If answering a question required someone to SSH into a box, that is a defect, not an answer.**

On 2026-08-18 the shelf showed 74 packs live. Finding out why took an hour of reading container
filesystems by hand, because the engine decides and records nothing. Every P0 below is a version
of that same defect.

---

# P0 — money on the floor, or we cannot see the money

### B1. The engine's shelf decision is unobservable
**Breaks today.** `prospector/bridge.py:1516` composes six independent fences — uploaded,
pack_complete, priced, bundle_complete, lint_ok, figures_verified — into **one boolean** and
returns it. Five of the six log a sentence when they refuse; the content one refused silently
until 2026-08-18. Nothing counts any of them. `bridge.py:1543` then sends `contentKey=None` for
any unlisted pack, so from the store's side all six failures look identical.
**Story.** An operator asks "why is this pack not on the shelf" and gets the answer from a query,
not an investigation.
**Done when.** `listing_blockers()` returns the failing fence names, `publish_pass` appends one
row per decision to a ledger in the store, and a report prints counts by blocker. Probe:
`python -m ops.automations.stranded_packs --json` returns `status: ok|findings`, never `unknown`.
**Costs.** M.

### B2. 108 registered packs are not on the shelf
**Breaks today.** Live: `{"listed":74,"registered":182}`. 127 listing files on the engine volume,
74 of them live, **53 engine-published packs never went live**, plus ~55 older registered rows.
`/data/store/bundles` and `/data/store/artifacts` are both **empty**.
**Story.** Finished research that cost model spend is on sale instead of sitting in a directory.
**Done when.** Every registered pack is either listed, or carries a named blocker from B1 and a
decision to fix or retire it. Probe: `GET /internal/catalog/unlisted` shows zero `unexplained`.
**Costs.** L. Blocked on B1 — without the blocker names this is 108 hand investigations.
**Tracked as** task #18.

### B3. The stranded-packs probe is blind in production
**Breaks today.** `ops/automations/stranded_packs.py:48` resolves its root from `__file__`, so on
the engine it looks in `/app/store/dossiers` — the code directory — while the store is
`/data/store`. Run on production it returns `status: unknown, error: no dossier directory`. The
one automation built to answer B2 cannot answer it. This is the documented `__file__` trap in
CLAUDE.md, in a file written after the trap was documented.
**Story.** The probe that exists actually reports, so nobody writes a second one.
**Done when.** It resolves the store via `config.store_root()` and returns a real count on the
engine. Probe: run it on `prospector-engine`, exit 0 or 1, never 2.
**Costs.** S.

### B4. Outages are reported and nobody is paged
**Breaks today.** The engine records provider outages and writes them to a ledger. No page is
raised. A three-day outage in the past left the rate series flat and nobody knew.
**Story.** You find out from an alert, not from a shelf that stopped growing.
**Done when.** An outage past its threshold raises a page with the failing provider named.
**Costs.** M. **Tracked as** #16.

### B5. A repair pass that heals nothing writes a row and stops
**Breaks today.** The recovery path can run, fix zero packs, and report success by writing a
ledger row. Silent no-op recovery is indistinguishable from recovery.
**Story.** A repair that does not repair wakes somebody up.
**Done when.** Zero-heal passes page. **Costs.** S. **Tracked as** #44.

### B6. The consumer wedge: a drain pass with no timeout stops the queue
**Breaks today.** One un-timed drain pass halts the queue indefinitely.
**Story.** The queue drains without a person restarting it. **Done when.** Every drain pass has a
deadline and a wedge raises a page. **Costs.** M. **Tracked as** #24.

### B7. Drained rows defer again with nothing spent
**Breaks today.** Rows come off the queue, defer, and no model spend is recorded — so the work
did not happen and nothing says why.
**Story.** A drain either finalises a row or records the reason it could not.
**Done when.** Zero rows defer with zero spend, or each carries a reason. **Costs.** M.
**Tracked as** #25.

### B8. A broken main branch raises no alert
**Breaks today.** `main` can go red and nothing tells anyone. Two known causes are already
documented: a 429 fetching actions, and a workflow shelling out to `gh` on a runner that has no
`gh`.
**Story.** Red main pages within minutes. **Done when.** A failing main run raises a page.
**Costs.** S. **Tracked as** #49.

### B9. Nothing alerts when the pass rate or outage rate leaves its baseline
**Breaks today.** Measured baseline: 7.9% pass, 12.9% outage, one pass per 13 candidates ruled.
On 2026-08-18 the defer rate was 66% and the way that surfaced was the founder asking.
**Story.** The engine tells you it has stopped working before you notice the shelf.
**Done when.** A rate outside its band raises a page. **Costs.** M. **Tracked as** #45.

---

# P1 — so the estate runs without a person watching it

### B10. Alerts must launch an agent with the full context
**Breaks today.** An alert pages a human who then reconstructs context by hand.
**Story.** Founder, 2026-08-18: "alerts agent launch with all the context to cut thru noise and
fix root cause right away and document/reflect." An alert starts an agent holding the incident,
the runbook and the code.
**Done when.** One real alert end-to-end produces a diagnosis and either a fix or a ticket, with
no human in the loop. **Costs.** L. **Tracked as** #48.

### B11. The ops console shows engine health, not fleet health
**Breaks today.** On 2026-08-18 three CI runner machines existed and one was doing all the work:
two had been stopped for hours. The console could not show it. The runner rebooted a whole VM
between jobs (fixed in `8c385275`) and nothing surfaced that either.
**Story.** One page answers "is the estate healthy", including CI, runners, and every Fly app.
**Done when.** The console shows per-machine state for every app and goes red on a stopped one.
**Costs.** M. **Tracked as** #51.

### B12. Logging, monitoring and alerting for the whole stack
**Breaks today.** Logs are per-app, ephemeral on Fly, and nothing aggregates or retains them.
**Story.** An incident from last week can still be read.
**Done when.** A retention policy exists and is enforced by a job. **Costs.** L.
**Tracked as** #13 and #15.

### B13. Wire shelf_copy_repair into the recovery path
**Breaks today.** `shelf_copy_repair.rewrite_one` exists and nothing calls it, so a copy-blocked
pack cannot heal. The `PROMIS` detector also has a bug.
**Story.** A pack blocked on copy repairs itself. **Costs.** M. **Tracked as** #43.

### B14. Hermes off the laptop
**Breaks today.** Hermes state and process still depend on the founder's laptop, against the
standing constraint that everything business-critical leaves it.
**Done when.** `prospector-hermes` runs it with state on the Fly volume and the laptop job is
unloaded. **Costs.** M. **Tracked as** #5 and #10.

### B15. Merge the open PRs
**Breaks today.** PRs 341, 339, 335 and 342 are open. Work that is not merged is work that is not
running. **Done when.** Zero open PRs older than a day. **Costs.** S. **Tracked as** #14.

---

# P2 — throughput, cost and portability

### B16. pi/MiniMax stalls after a few minutes
**Breaks today.** Founder: "pi doesnt work anymore, agent nini always getting stuck after few
minutes. i suspect its something we did." Not yet measured.
**Story.** The cheap executor is usable, so expensive brains do less routine work.
**Done when.** The stall is reproduced and named. This is a MEASURE item first.
**Costs.** M. **Tracked as** #50.

### B17. Free portability drills: cold restore, cutover, rollback
**Story.** Leaving Fly is proven, not asserted. **Costs.** L. **Tracked as** #33.

### B18. The managed container adapter
**Story.** The one portability shape the estate lacks. **Costs.** M. **Tracked as** #34.

### B19. Extend the daily live smoke past the shelf to the money
**Story.** A broken checkout is caught by a probe, not a buyer. **Costs.** M. **Tracked as** #39.

### B20. The daily agent job that moves the platform forward
**Story.** Progress without a session being open. **Costs.** L. **Tracked as** #35.

---

# P3 — analysis, hygiene, and things we believe without evidence

### B21. Dissect LUX, POPDD and PDD
**Breaks today.** Measured 2026-08-18: no pre-commit gate is installed in this checkout;
`.lux/receipts` holds **6 rows, newest 2026-06-17**; `popdd_agent.py` is a re-export shim for a
`popdd/` package **that does not exist here**. Only `scripts/popdd_verify.py` is live.
**Story.** A clear answer to what problem this system solves, whether it solves it, and whether it
should exist — against alternatives at code, process and infra level.
**Done when.** `docs/PROOF_SYSTEM_AUDIT.md` states keep, replace or delete, with evidence.
**Costs.** M. **Tracked as** #47.

### B22. Catalogue every tool, script, skill and automation
**Story.** Nobody builds the thing that already exists. **Costs.** M. **Tracked as** #29.

### B23. Audit dead code, dead files and dead docs
**Story.** Report first, delete second. **Costs.** M. **Tracked as** #30.

### B24. Census every automation job in the estate
**Story.** Every scheduled job is known, owned and alive. **Costs.** M. **Tracked as** #32.

### B25. Enumerate all 53 API endpoints against their auth guards
**Story.** No endpoint is public by accident. **Costs.** M. **Tracked as** #40.

### B26. Rotate the two secrets printed into a transcript
**Costs.** S. **Tracked as** #38.

### B27. Build the repeat-mistake detector
**Story.** The tenet "never make the same mistake twice" gets a machine behind it.
**Costs.** M. **Tracked as** #41.

### B28. Measure every incident and keep the runbook beside it
**Story.** Incidents become data that B27 and B10 can mine. **Costs.** M. **Tracked as** #52.

### B29. Marketing pipeline, starting with the syndication that half exists
**Costs.** L. **Tracked as** #36.

### B30. Measure what a learned prescreen would save before building one
**Story.** A MEASURE item. No build until the number exists. **Costs.** S. **Tracked as** #37.

---

## What this file replaces

It does not replace the programme docs. Those hold the diagnosis and the implementation ledger for
one area each. This holds the ORDER, across all of them. When the two disagree about what is next,
this file wins, and the programme doc is out of date.
