# Founder notes

What the founder actually said, dated, in their words where the words matter, with what it
turned into. Nothing in here is a paraphrase of a paraphrase.

Why it exists: founder, 2026-08-18, "everything has to turn to backlog item, and prioritised
analysis plan and story, we need that discipline, we don't track properly and have no central
backlog." Directives were landing in chat transcripts, getting compressed into a memory file,
and then being re-derived wrongly three sessions later. A transcript is not a record. This file
is the record; `docs/BACKLOG.md` is the queue that comes out of it.

The rules that bind every session live in `~/.claude/CLAUDE.md` and `docs/WAYS_OF_WORKING.md`.
This file is the raw material those were built from, kept so the reasoning can be checked.

---

## 2026-08-18 — measure everything, then alert before I find out

> "we should be measuring everything i mean everything because we need the data to know how to
> improve"

> "we should know on average a pass occurs every X hours or every X reviews/judgments"

The trigger: the founder noticed no packs were minted and listed that day, and said they should
never be the one to report it.

**Baseline measured the same day** (120 batches, 1228 candidates vetted, 1070 ruled): 84 pass,
986 kill, 158 defer. **7.9% pass rate, 12.9% outage rate, roughly one pass per 13 candidates
ruled.** Per-day buckets swing 0%–100%, so any alert on this needs a minimum bucket size or it
will page on noise. Memory: `measurement-stops-during-the-outage-it-exists-to-record.md`.

Became: task #45 (alert when the pass or outage rate leaves the baseline), task #52 (measure
every incident).

## 2026-08-18 — alerts must launch an agent, not a human

> "alerts gent launch with al the contet to cut thru noise and fi root cause rught away and
> docunent/reflect"

> "alert response - rootcause fix - verify prove, happens again, self heal"

> "as founcder ny goal is to be hands off agents can run the show safefuky becasue there is no
> roon for error"

The loop the founder wants is one loop, not four: the alert fires, an agent starts with the
evidence already attached, it fixes the root cause, it proves the fix, it writes the incident
up, and a repeat of that class heals itself. Paging a human is the failure mode, not the goal.

Became: task #48 (alerts launch an agent with a context bundle), task #49 (a broken main is one
of those alerts), task #52 (the incident record is also the training data).

## 2026-08-18 — a clueless person must be able to run this

> "military surgical, everything is visible and observable, everything self heals, and runbook
> and quick ops dashboard resolution for anything not self healed or not fixed by agent response
> to alert"

Three tiers, in order: self-heal, then an agent on an alert, then a human with a runbook and one
button on the dashboard. A thing that needs a person to know which script to run has failed all
three.

Became: task #51 (the console shows the delivery fleet, not just the engine), task #52
(runbooks live beside the incident record).

## 2026-08-18 — stop working for hours without committing

> "workig for hours without conniting code is another founder conplaint"

Uncommitted work is invisible to the founder, invisible to the other session sharing this
checkout, and one disk away from gone. Commit at every landable step, not at the end of a
session. Already a rule (W21) with `scripts/session_check.py` behind it; restated here because
it kept being broken anyway.

## 2026-08-18 — dissect the proof system

> "we need nlysis of our lux and popdd and pdd, is it opersatinal, does it nke sene, anything
> better out there what is even the goal, e=everything needs dissceting with aa critial and
> skeptical eye to understand what probeln it is trying to solve why it eists shoukd it even
> exsit if the problen has a better slution fron code level to higher level and even infra"

Not a request to document it. A request to justify it or kill it.

Became: task #47, deliverable `docs/PROOF_SYSTEM_AUDIT.md`.

## 2026-08-18 — use the pi bridge more, and find out why it stalls

> "pybridge could be used a lot nore , we need to optinise it a lot. another issue i have is that
> pi doesnt work anynore, agent ninin always geting stuck after few ninute. i suspect its
> sonething we did."

Measured the same evening from this checkout against the live key: three serial MiniMax calls in
0.8s, 6.6s and 2.1s, $0.000062 each, three for three. The API is up and the key is good, so a
stall after a few minutes is the agent loop or the bridge, not reachability.

Became: task #50.

## 2026-08-18 — we need a super architect

> "we need a suoer architect. for this lol"

Recorded as said. The shape it implies: one role that holds the whole estate in view and rules on
whether a thing should exist at all, rather than each session optimising its own corner. Not yet
a task; it needs a decision from the founder about whether that is a persona doc, a standing
review gate, or a scheduled agent.

## 2026-08-18 — clean the closet

> "clean up the architecture, code and repo, a lot of dragons in closet"

> "no duplication of work, everything reusable across projects seamlessly"

Became: tasks #29 (catalogue every tool with the problem it solves) and #30 (audit dead code and
docs, then delete in a second pass). Report mode first, delete second — that ordering is itself a
founder rule.
