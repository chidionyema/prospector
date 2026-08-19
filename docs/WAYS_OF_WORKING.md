# Ways of working

Status: **ADOPTED 2026-08-18. MOSTLY UNENFORCED, AND THAT IS THE POINT.**

This is the tracked list of how work is done here. **30 rules. Part 0 is the complaint register: every founder complaint, quoted, mapped to the rule it produced.** Every agent, every session, every project. It
is the long form of the tenets in `docs/PLATFORM_MANIFESTO.md` Part 2, and the short form lives in
`~/.claude/CLAUDE.md` so a session loads it at start.

**Why it exists.** Founder, 2026-08-18, verbatim: *"everything here reoccurs across all agent
sessions dozens of times a day if not hundreds"*. Each rule below is a named, repeated failure,
not a preference. The complaint is quoted with each one so nobody has to guess what the rule is
protecting against.

**The honest state.** Almost every rule here is enforced by discipline, and discipline is exactly
what has failed hundreds of times. Part 7 marks which rules a machine enforces and which are still
just words. Moving rules from the second column to the first is the actual work.

---

## Part 0. The complaint register

Founder, 2026-08-18: *"ive said a lot, ensure noted in complaints"*. Every complaint made that
day is in this table, quoted, with the rule it produced. Nothing was dropped and nothing was
softened. If a complaint recurs, the row is the receipt that it was already known, which makes
it a defect in enforcement rather than a new discovery.

| # | The complaint, verbatim | Rule |
|---|---|---|
| 1 | "never repeat a mistake, don't see a bug more than once" | W1 |
| 2 | "adopt self healing as first principle" | W2 |
| 3 | "narrating e.g. zsh issues, build issues, never chasing root cause" | W3 |
| 4 | "we don't plan any more, we jump straight into code" | W5 |
| 5 | "building solutions without checking what's there already, duplicating work and effort" | W6 |
| 6 | "no proper ticketing system, claiming work to avoid duplication" | W7, W8 |
| 7 | "i have to always repeat ultra surgical, ultra military, ultra focus" | W9 |
| 8 | "not batch editing, slow and inefficient working practices, no batching" | W10 |
| 9 | "wasting hours, 5 hours sometimes, down rabbit holes" | W11 |
| 10 | "debugging a problem when not even sure the solution is right" | W12 |
| 11 | "narrating issue without investigating, fixing or ticketing" | W13, W14 |
| 12 | "hours and days writing tests for volatile changing elements, ui tests" | W15, W16 |
| 13 | "shipping without verifying" | W20 |
| 14 | "pushing branch without raising pr" | W18 |
| 15 | "raising pr and not following through to shipped" | W19 |
| 16 | "ship but not verify it actually works in prod" | W20 |
| 17 | "when we do ui work we should close browser sessions" | W22 |
| 18 | "branch hygiene", "worktrees not cleaned up etc" | W23 |
| 19 | "ticket hygiene" | W24 |
| 20 | "our repo is an actual mess if you look at what's in there" | W25 |
| 21 | "not being proactive in suggesting improvements, just passive" | W26 |
| 22 | "no researching the web, other solutions, better solutions" | W27 |
| 23 | "no architectural review", "parts of the engine is a pile of mud" | W28 |
| 24 | "conduct a review, architecture and security audit and get baseline" | W29 |
| 25 | "do we have critical path tests? purchase, payment, download pack, receive email, stripe" | W30 |
| 26 | "we need to enforce a lot" | Part 7 |

Founder, same day: *"as a founder i am concerned and need reassurance"*. Reassurance is not a
sentence in a reply. It is Part 7 moving rules out of the "words" column, one at a time, with the
script that enforces each one named. That is the only form of it this document accepts.

---

## Part 1. Never see the same bug twice

This is the first principle. Everything else is downstream of it.

Founder: *"agent manifesto should be never repeat a mistake, don't see a bug more than once, you
should be ruthless about not just fixing things but ensuring they can never occur again, and if
they can occur adopt self healing as first principle"*.

### W1. A fix is not done until the class is closed

Fix the instance, then name the class, then close the class. Four links, worked, from this estate:
the ops console showed blank tabs → the console API errored → the read model needed a store DB
that was not there → a store path was derived from `__file__`, so it followed the code rather than
the store. The instance was a blank tab. The class is "never derive a state path from `__file__`",
and it is now a rule plus a resolver, `config.store_root()`.

Stopping at link one is the failure. Reporting link one and asking what to do next is worse.

### W2. Self-healing first, guard second, memory file last

In that order, always:

1. **Can the system fix this itself?** Restart the wedged consumer, re-probe the benched provider,
   re-drive the stranded pack. Prefer this even when it is more work.
2. **If not, can a machine refuse it?** A test, a lint rule, a pre-flight check, a guard hook.
3. **If not, write the memory file** so the next session does not pay for it again.

A memory file is the floor, not the answer. Today the estate mostly stops at step three.

### W3. Do not narrate a solved trap

Founder: *"narrating e.g. zsh issues, build issues, never chasing root cause"*.

zsh aborting on an unmatched glob, `cmd | tail` reporting tail's exit status, a recursive grep that
walks 169,000 files, `dotnet test` exiting zero while failing: these are all written down. Hitting
one and describing it costs the founder a paragraph and teaches nobody anything. Either the memory
file was not read, or it was never written. Both are defects with an owner.

### W4. One bug, one guard, same turn

If the failure can recur mechanically, the guard ships in the same commit as the fix. Not a
follow-up ticket. A follow-up ticket for a guard is how the same bug comes back in three weeks.

---

## Part 2. Before code: plan, then claim

Founder: *"we don't plan any more, we jump straight into code, this is why we have lots of code
that does nothing"*. Measured: **219 of 1567 tracked files are referenced by nothing**
(`scripts/estate_census.py`). That is the cost of not planning, as a number.

### W5. Plan first, briefly

Before writing code: what is the smallest change that fixes this, what already exists that does
part of it, and how will I know it worked. Three sentences is enough. A plan is not a document, it
is the thing that stops 200 lines being written for a problem that needed 5.

### W6. Check what exists before building it

Founder, said twice on 2026-08-18: *"building solutions without checking what's there already,
duplicating work and effort"*. Twice means the first telling did not work, so here is the actual
procedure rather than the sentiment.

The estate has 83 tools, 43 scripts, 227 Hermes scripts and 31 tracked jobs. The odds that the
thing you are about to build already exists are not small. Before the first line of a new file:

```bash
graphify query "<the thing you are about to build>" --budget 2000   # 0 tokens, local graph
rg -l "<the concept>" scripts/ tools/ prospector/ ops/              # honours .gitignore
gh issue list --label claimed                                       # is someone already on it
```

A new file needs one sentence saying what existing mechanism was checked and why it cannot serve.
No sentence, no new file.

### W7. Claim the work before starting it

Founder: *"no proper ticketing system, claiming work to avoid duplication"*. Two sessions run in
this checkout at once, routinely, and neither can see the other's intent.

**The system is GitHub Issues, because it already exists, costs nothing and is visible from every
session.** No new tool.

```bash
gh issue list --label claimed          # what someone else is already on. Read this FIRST.
gh issue create --title "..." --body "..." --label claimed   # claim before the first edit
gh issue comment <n> --body "session <id> picking this up"   # claim an existing one
gh issue close <n> --comment "shipped in <sha>, verified by <command>"
```

The rule is simple: **if the work will take more than one turn, it has an issue, and the issue is
claimed before the first edit**. Un-ticketed work is invisible work, and invisible work gets done
twice.

### W8. One ticket, one branch, one pull request

No branch that serves two tickets. No ticket spread across three branches. This is what makes a
half-finished thing legible to the next session instead of a mystery.

---

## Part 3. While working: surgical is the default

Founder: *"i have to always repeat ultra surgical, ultra military, ultra focus approach when this
should be default"*.

It is now the default. Requesting it should never be necessary again.

### W9. Smallest diff that actually fixes it

Extend the mechanism that exists before writing a new one. A new module needs a demonstrated
reason the old one cannot serve.

### W10. Batch everything

Founder: *"not batch editing, slow and inefficient working practices, no batching, no creative
thinking to save time cost or be more efficient"*.

- One round trip per intent. Before a tool call, ask what else this turn needs and send it in the
  same call.
- A verification chain is one command, not six. Typecheck, tests, lint, build, status: one script,
  one set of receipts.
- Independent tool calls go in the same message.
- Batch file edits. Twenty similar changes are one script, not twenty edits.
- Anything over thirty seconds runs in the background while the next independent thing starts.

The measured reason: about 79 percent of the cost of a request is re-reading resident context, so
six claims proven by one script cost roughly one sixth of six separate calls.

### W11. Timebox, then change approach

Founder: *"wasting hours, 5 hours sometimes, down rabbit holes or chasing wrong solutions"*.

Thirty minutes on one problem with no forward progress means stop. Write down what is known and
what was ruled out, then do one of three things: change approach, ticket it and move to something
that is not blocked, or ask one specific question. Continuing to push is the most expensive thing
available and it never once worked.

### W12. Prove the diagnosis before building the fix

Founder: *"debugging a problem when not even sure the solution is right and writing extensive
tests"*.

A fix built on an unproven diagnosis is a guess with a test suite attached. Before writing the
fix: state the cause in one sentence, and name the observation that would be different if the
cause were something else. If that observation cannot be produced, the diagnosis is a hypothesis
and gets labelled one.

### W13. Investigate, fix, or ticket. Never narrate

Founder: *"narrating issue without investigating, fixing or ticketing"*.

Three legal responses to a discovered problem, and only three. Describing it in prose and moving
on is not one of them. If it is out of scope, it gets an issue with the receipt in it, in the same
turn.

### W14. Fix it in the same turn you find it

A defect found inside work in progress gets fixed now, chained into the running command block. The
only exceptions are a founder decision, a permission that is refused, and another session's work.

---

## Part 4. Tests must earn their place

Founder: *"testing, hours and days have been spent writing tests for volatile changing elements,
ui tests... by ui tests i mean ui layout and content and display tests when ui changes constantly
and is volatile"*.

### W15. Do not test a volatile surface

While a surface is changing, do not assert on its shape. No pixel comparisons, no "this heading
says exactly this", no DOM structure assertions on a page still being designed. Those tests fail
for the wrong reason, get muted, and then hide the real failure.

Test the things that do not move:

| Volatile, do not pin | Stable, do test |
|---|---|
| Layout, spacing, colour | The page renders without throwing |
| Exact copy and headings | The API contract behind the page |
| DOM structure and class names | The money path, the entitlement, the fence |
| Which card is third | That the list is non-empty and ordered by the declared key |

The existing rule stands and is now general: **UI tests are advisory while the UI is moving.**

### W16. Write the test after the diagnosis is confirmed

Tests written during exploration pin whatever you happened to believe at the time. Confirm the
cause, write the fix, then write the test that fails without it.

### W17. Every test names what would break in production if it were deleted

If that sentence cannot be written, the test is a tax, not a guard.

---

## Part 5. Ship it, and prove it shipped

Founder: *"shipping without verifying, pushing branch without raising pr, raising pr and not
following through to shipped, ship but not verify it actually works in prod"*.

Four separate failures, each with its own rule. The chain is: commit, push, PR, merged, deployed,
verified in production. **Stopping anywhere before the end is not shipping.**

### W18. Never push a branch without raising the pull request

A pushed branch with no PR is invisible. It is not queued, not reviewed, not merged, and the next
session will not find it.

### W19. Follow the pull request to merged

Raising it is not finishing. The automerge workflow on `main` lands a PR when CI concludes
success, so the follow-through is usually watching, not merging. A PR that has sat with a failing
check for an hour is unfinished work.

### W20. Nothing is shipped until production runs it

Merged is not deployed. Deployed is not working.

```bash
.venv/bin/python scripts/live_checkout.py    # is production running the code we think it is
bash ~/.hermes/scripts/verify_estate.sh      # is the estate actually healthy
```

The reason this rule exists as a rule: production once ran 17-hour-old code from a branch nobody
had noticed, and the only way to see it was to run `lsof` on the process by hand.

### W21. Never leave work uncommitted

Founder, verbatim: *"sorry don't ever do this again, this is irresponsible"*. Anything written in
a worktree or scratchpad is committed and pushed in the same turn.

---

## Part 6. Hygiene

### W22. Close browser sessions when the UI work ends

Founder complaint, 2026-08-18. A browser tab left open after UI work is a resource on the
founder's machine and a surprise on their screen. Close what you opened, in the same turn the UI
work finishes, with `tabs_close_mcp`. If a tab must stay open, say why.

### W23. Branch hygiene

- One session, one worktree. Sessions sharing a checkout share one git index.
- A merged branch gets deleted.
- A worktree gets removed when its work lands. Measured 2026-08-18: **26 worktrees existed**, of
  which 3 were clean and fully merged and 23 held either uncommitted work or unmerged commits.
  This is now a tool, not a hope:

```bash
.venv/bin/python scripts/worktree_gc.py         # report: safe to remove, and why each is kept
.venv/bin/python scripts/worktree_gc.py --fix   # removes only clean, merged, unused ones
```

  It will never remove a worktree holding unmerged commits or uncommitted files. That is somebody
  else's unfinished work, and 23 of the 26 are exactly that.
- Never stage everything. `store/` and `storage/` are tracked runtime state that tests write to.

### W24. Ticket hygiene

An issue is closed with the receipt that closed it: the sha, and the command that proves it works.
An issue nobody can tell the state of is worse than no issue.

### W25. Leave no rubbish

Founder: *"our repo is an actual mess if you look at what's in there"*.

Temporary scripts go in the scratchpad, not the repo. A file added to prove something gets removed
or committed with the reason it exists. The 219 unreferenced files did not arrive all at once, and
`.venv/bin/python scripts/estate_census.py` is how that number is now watched rather than felt.

---

## Part 6b. Judgement, not just execution

Three of the founder's complaints are not about sloppiness. They are about an agent that does
exactly what it is told and nothing more. Doing only what is asked, when you can see the problem
behind the ask, is its own failure.

### W26. Be proactive, once, then get on with it

Founder: *"not being proactive in suggesting improvements, just passive"*.

Every piece of work ends with the best improvement you saw while doing it, and it goes somewhere
durable: an issue, or a line in the programme doc it belongs to. Not a paragraph in a reply that
scrolls away. One improvement, the highest value one, filed. Not a menu of five.

The passive failure and the noisy failure are both real. The rule is one filed improvement per
piece of work, with the receipt that made you notice it.

### W27. Research outside this repo before choosing an approach

Founder: *"no researching the web, other solutions, better solutions"*.

For anything new, or anything being rewritten: spend one search on how this is solved elsewhere
before designing it here. Name the alternatives considered and why this one. A design with no
alternatives listed was not a decision, it was the first idea.

This is the cheapest rule in the document to follow and the one most often skipped, because the
first idea always feels sufficient while you are inside it.

### W28. Architectural review before crossing a boundary

Founder: *"no architectural review"*, and *"parts of the engine is a pile of mud"*.

A change that adds a component, adds a dependency, crosses a module boundary or changes a data
contract gets three written sentences before code: what boundary it crosses, what else it forces
to change, and what it makes harder later. Mud is what accumulates when that question is never
asked, one reasonable local change at a time.

The engine's mud is now a tracked baseline rather than a feeling. See W29.

### W29. Architecture and security have a measured baseline, not an opinion

Founder: *"perhaps you can conduct a review, architecture and security audit and get baseline,
treat like all the other, deep link"*.

`docs/ARCHITECTURE_SECURITY_BASELINE.md` is that baseline: what the system is, where the mud is,
what the security posture actually is, each finding with the command that produced it, and a
ledger. It is re-measured on a schedule, so drift shows as a number changing rather than as a
founder noticing.

### W30. Every critical path has a test that fails when the money stops

Founder: *"do we have critical path tests? purchase, payment, download pack, receive email, test
stripe? and also engine, do we have critical tests?"*

The paths that are allowed to have no gaps: take payment, record the entitlement, deliver the
pack, send the email, and on the engine side, rule a verdict and publish only what passed. Every
one of those has a test today, and the list is in the baseline doc with the file that covers each
link. Where the coverage is in-process only, the baseline says so rather than counting it as
covered.

---

## Part 7. Enforced by a machine, or only by words

The founder's complaint is that these recur hundreds of times a day. Rules that recur that often
are not being enforced by anything. Here is the honest split.

| Rule | Enforced by | Reality |
|---|---|---|
| W21 nothing uncommitted | `scripts/session_check.py` | now caught mechanically |
| W18 push implies PR (dup below) | `scripts/session_check.py` | now caught mechanically |
| W3 do not narrate solved traps | words + memory | the memory exists, reading it is optional |
| W7 claim before starting | nothing yet | duplicate work happens |
| W11 timebox | words | never once self-enforced |
| W15 no volatile UI tests | partly, advisory lanes | tests still get written |
| W18 push implies PR | `~/.claude/scripts/push-pr-fence.py` refuses the push; `branch-pr-guard.py` blocks the turn end | enforced since 2026-08-18 |
| W20 verify in production | `scripts/live_checkout.py`, plus `ops/state_probe.sh` at every session start | the probe is automatic; running `live_checkout.py` is still optional |
| W22 close browser sessions | nothing | founder complaint |
| W10 batching | `~/.claude/scripts/tool-drip-guard.py` exits 2 on the third consecutive read-only call | enforced, and it fires |
| W23 branch hygiene | `scripts/worktree_gc.py` reports drift and `--refresh` closes the safe gaps; `scripts/process_audit.py` grades it | measured 2026-08-19: 34 worktrees behind main, 19 by 25+ commits, worst 719 |
| W6 check before building | words + `graphify query` | complained about twice in one day |
| W26 proactive | nothing | founder complaint |
| W27 research alternatives | nothing | founder complaint |
| W28 architectural review | nothing | "parts of the engine is a pile of mud" |
| W30 critical path tests | the suites themselves | covered in-process; no live drill |

**The work this table implies**, cheapest first:

1. **A session-end checklist that runs**, not one that is remembered: uncommitted work, unpushed
   branch, pushed branch with no PR, open browser tab, stale worktree. One script, read-only,
   printed at the end of a session. This closes W18, W21, W22 and W23 at once and it is a
   morning's work.
2. **Claim checking in the same script**: list issues labelled `claimed` at session start.
3. **A repeat-mistake detector**: when a command fails with a signature that matches an existing
   memory file, say which file and stop. That closes W3 mechanically.
4. Everything else stays discipline until measured otherwise, and is marked as such rather than
   pretended.

---

## Part 8. Ledger

| Date | Change | Receipt |
|---|---|---|
| 2026-08-18 | Adopted, 25 rules, from the founder's list of recurring failures | this file |
| 2026-08-18 | Short form wired into `~/.claude/CLAUDE.md`, loads in every session, every project | Part 2 of the manifesto |
| 2026-08-18 | Session-end checklist built: W21, W18, W19, W23, W7 now mechanical | `scripts/session_check.py` |
| 2026-08-18 | Worktree gc built, report mode first | `scripts/worktree_gc.py`, 26 found, 3 safe |
| 2026-08-18 | Complaint register added, every complaint mapped to a rule | Part 0 |
| 2026-08-18 | W26 to W30 added: proactive, research, architecture, baseline, critical paths | Part 6b |
| | Repeat-mistake detector | **not built** |
| | Architecture and security baseline | `docs/ARCHITECTURE_SECURITY_BASELINE.md`, in progress |

---

## Part 9. The three workstreams, and where a complaint or a failure goes

This section used to be a file of its own at this path. It is kept here in full because the
rules above are stream A, and a reader who arrives from `INCIDENT_PROCESS.md` or from
`LAUNCH_OPS_PROGRAM.md` §9 needs the other two.

> Founder, 2026-08-17: "claude code sloppiness is one stream, hermes agent is another, and
> the whole ops readiness programme also."
>
> This file is an INDEX and nothing else. The first draft of it restated the working-method
> register in full, and there was already one — `LAUNCH_OPS_PROGRAM.md` §9, WM-1 to WM-5.
> Writing a second register is the same defect as losing the first, so the detail was folded
> back into §9 and this page kept to a page.

Each stream names a PROBE: a command that answers "where is this?". A status written in prose
drifts; a status printed by a command cannot.

| # | Stream | Register | Probe | Tasks |
|---|--------|----------|-------|-------|
| A | **Claude Code ways of working** | `LAUNCH_OPS_PROGRAM.md` §9 (WM-1…WM-7) | `python3 ~/.hermes/scripts/complaint_ledger.py --print` | #10 |
| B | **Hermes agent** | `~/.hermes/capabilities.json` | the `capabilities` panel, or `python3 ~/.hermes/scripts/capability_audit.py` (slow) | #5, #6, #7 |
| C | **Ops readiness programme** | `LAUNCH_OPS_PROGRAM.md` §1 and §4 | `.venv/bin/python scripts/ops_status.py` | #11 |

`ESTATE_QUIRKS.md` sits beside these three. It is not a fourth stream. It is the register of
platform behaviours that made a healthy thing look broken, so that the next diagnosis does not
start from scratch. Read it before believing any red line.

The Hermes agent can be across all three and should be. A and C are both things it can grade
on a schedule and report unasked. A workstream nobody probes goes dark exactly like a
capability does.

### Where each one stood on 2026-08-17

- **A** — of seven rails, two are enforced by hooks (`hang-guard.py`, `memory-loop.py`) and
  neither has ever been raised again as a complaint. The rest are instruction-only in the
  global `CLAUDE.md`, and every one of them has been raised more than once. That is the whole
  argument for moving a rail from instruction to enforcement.
- **B** — 34 of 42 capabilities producing, 8 dark; gate `GATE: FAIL` at 20 passed / 4 failed,
  where most remaining failures assert panels that were never built.
- **C** — `ops_status.py` grades 44 ids against `origin/main`, never the working tree. It has
  already caught two claims of "done" that were true only in an unmerged PR.

### How a complaint becomes work

1. The founder says the way we work is wrong.
2. `reflect.py` finds it in the transcripts; `complaint_ledger.py` writes it down so it
   survives the session.
3. It gets a WM number in §9 and a task id.
4. It closes when a rail enforces it, or when the founder says the instruction is enough.

A complaint that only ever produced an apology is still open, whatever the reply said.

### How a failure becomes a mechanism

The loop above is for complaints, which arrive in words. The loop for failures, which arrive as
broken things, is [`INCIDENT_PROCESS.md`](INCIDENT_PROCESS.md). The two are the same shape and
deliberately so: something goes wrong, it is written down where the next session will find it, it
closes only when a machine refuses the repeat, and it is graded afterwards to prove the refusal
worked.

| | complaint | failure |
|---|---|---|
| written down by | `complaint_ledger.py` | `docs/incidents/*.json` |
| checked by | `reflect.py`, every four hours | `scripts/incident.py check`, in CI |
| closes when | a rail enforces it | the mechanism landed **and** the grade came back zero |

The register in `LAUNCH_OPS_PROGRAM.md` §9 is where a complaint gets its WM number. An incident
does not need one: its id is its filename.
