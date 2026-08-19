# Runbook — CI, merges and deploys: finding out what is actually wrong

> Founder, 2026-08-19: "you need to write up incident note and dos and donts and how to debug
> steps", "runbook", "reflect on all we had to do today, false alarms, and the core issue",
> "ensure agents are across it".

This file is for the next agent who opens a session, sees a wall of red, and is about to spend
four hours on it. Read the first two sections before you touch anything. They are short on
purpose.

`docs/INCIDENT_PROCESS.md` says how an incident is recorded and closed. This file says what to
look at while it is still on fire. `docs/RUNBOOKS.md` covers the `ops/automations/` checks.

---

## The core issue

**Every instrument in this estate reports a SHAPE. None of them report the CONTENT.**

A count. A colour. A status letter. A green tick. An exit code. Each one is a POINTER to a
reason, and reading it as the reason is what cost 2026-08-19. Every false alarm below is the
same mistake wearing different clothes, and each one was settled in seconds by one command that
opened the thing the shape was pointing at.

The expensive version is worse than an agent doing it, because **the machinery does it too.**
The green guard reverts whichever commit is at the HEAD when CI goes red. The head is a shape.
The cause is content. Tonight it amputated an innocent commit and left main red, and then wrote
a ticket saying the innocent commit was at fault — so the next agent inherits a false diagnosis
with a receipt attached.

If you take one habit from this file: **before you act on any red, open the log.** Not the run
list. Not the check rollup. The job log, the actual assertion text. It is one command and it is
never optional.

---

## Tonight, in one table

| What was believed | What was true | The one command that settled it |
|---|---|---|
| CI has no capacity, add machines | 10 of `prospector-ci`'s 12 machines were Fly **standbys**: they register as runners, take a job, and are stopped mid-build by the platform. Usable capacity was 2. | `fly machine list --json` and read `config.standbys` — **state is the one thing a standby gets right**, so state cannot tell you |
| 27 PRs have failing tests | 4 had a test failure. 9 died with the machine, 7 were cancelled by someone else's push, 3 were already green, 2 had never run at all. | `.venv/bin/python scripts/pr_triage.py` |
| Three deploys were missed | Exactly one was (`deploy-engine.yml`). | compare the last successful deploy run's sha against `origin/main` |
| 118 branches hold stranded work | One commit was stranded, in one branch. 23 were already on main, 58 were today's own rescue copies, 11 were absorbed by #451. | `git merge-tree --write-tree origin/main <branch>` — a squash merge defeats commit counting and patch-id comparison both |
| The branch pruner hangs | It was working, silently, and got killed at a 300s timeout. The wrapper reported **exit 0**. | `cmd > out 2> err; echo $?` — `cmd \| tail` reports **tail's** status, not the command's |
| PR #456 has a frozen-label defect | It does not. I had read patch 1 of a 2-page paginated diff. | `gh api --paginate` |
| #463 turned main red, so the guard reverted it | #463 touches one file and was innocent. **#460** landed an unregistered tool; its own CI had already failed and named the file, 19 minutes before it merged. | `gh api repos/OWNER/REPO/actions/jobs/<id>/logs` |

Six of the seven were killed by one command each. None of the seven needed a theory.

---

## The incident: main was red for over an hour and the guard reverted the wrong commit

**Severity: high.** A red main blocks every open PR, which is every agent on the estate.

**The chain, with times, all 2026-08-19 UTC.**

1. `21:46:09` — PR #460's own CI failed. The `python` job failed on
   `tests/unit/test_console_tools_run.py::test_console_tool_registry_has_no_drift`, printing the
   exact cause: `assert not ['scripts/pr_triage.py']`. The PR had added a script with no row in
   the ops-console tool registry. `ci-ok` failed with it.
2. `22:05:30` — **PR #460 merged into main anyway**, 19 minutes after the failure was on screen.
   Its check rollup at merge time read `changes=FAILURE python=SKIPPED ci-ok=FAILURE`.
3. main went red on the same assertion. #460 was not alone: **six PRs merged in three minutes and
   fourteen seconds**, `22:05:14Z` to `22:08:25Z` — #458, #460, #457, #456, #455, #463. Every one
   has `merged_by: chidionyema` and `auto_merge: null`. `automerge.yml` merges with
   `secrets.GITHUB_TOKEN`, so its merges are always attributed to `app/github-actions`. **These
   were not automerge.** They were merged by hand or from the web UI, and `rule-guard.py` fences
   only a typed `gh pr merge`, so nothing refused them. (Confirmed independently by session
   prospector-36; verified here with `gh api repos/OWNER/REPO/pulls/<n> -q .merged_by.login`.)
4. `23:08:24` — PR #463 merged (`bab16b19`). It touches `scripts/launchd_plists.py` and one test
   file, and nothing that assertion reads.
5. CI ran on main with #463 as the head and failed on **#460's** assertion.
6. `23:24:05` — `main-green-guard` reverted **#463** and opened issue #468 titled
   "main was red: bab16b19 reverted by the green guard".
7. main stayed red, because the file that broke it was never touched. The guard had removed
   working code and left the broken code in place.

**First order.** `scripts/pr_triage.py` is now registered, and #463 is restored (PR #472).

**Second order — the two classes, and they are separate.**

- **A PR can merge over a failing required check.** This is the upstream one. Everything else
  tonight is downstream of it. Native branch protection is unavailable on this plan
  (`403 Upgrade to GitHub Pro`), and `rule-guard.py` can only refuse a `gh pr merge` typed into a
  shell on this box. A merge from the GitHub web UI passes through no guard at all. Until a merge
  is impossible while `ci-ok` is red, main will go red again.
- **The revert guard reverts the HEAD, not the CAUSE.** A guard that picks its target by
  position rather than by evidence will hit an innocent commit whenever two changes land close
  together — which, with several sessions pushing, is most of the time. It also produces a
  *confidently wrong* ticket, which is more expensive than no ticket.

**The cheap test for the second one**, and the reason it is a real defect rather than bad luck:
before reverting, run the failing test against `HEAD~1`. If it fails there too, the head is not
the cause and the guard must say so instead of reverting.

---

## Do's

- **Open the log.** `gh api repos/OWNER/REPO/actions/jobs/<id>/logs`. One command, every time,
  before any action. A run list, a rollup and a red X are all pointers.
- **Run `scripts/pr_triage.py` before believing any count of failing PRs.** It separates a broken
  test from a dead machine from a cancelled run, and tonight that was 4 real failures out of 27.
- **Capture the exit status before any pipe.** `cmd > out 2> err; rc=$?` then look at `out`.
- **Use `git merge-tree --write-tree` to ask whether a branch still holds work.** With squash
  merges, `git rev-list --count` and `git cherry` both report landed branches as unmerged
  forever, and a conflict is not evidence of unlanded work — it is usually main's newer version
  of the branch's own change.
- **Paginate.** `gh api --paginate`, and check whether a diff you read was truncated.
- **Read a Fly machine's `config`, not its `state`, when asking whether it is capacity.**
- **Say which commit production is running, with a command.** `scripts/live_checkout.py` and
  `scripts/deploy_status.py`. A merged PR is not a deployed PR.
- **Put a deploy dispatch in its own step with `if: always()`**, and derive what to deploy from
  `compareCommits(before, after)` — from what actually landed, never from bookkeeping that an
  earlier error can lose.
- **Message the peer session whose work you are about to touch.** `ListAgents`, then
  `SendMessage`. It is the cheapest source of contradicting evidence on this box.

## Don'ts

- **Don't infer a cause from a colour, a count, a status letter or an exit code.** That is the
  whole file in one line.
- **Don't merge on a rollup.** `ci-ok` is the gate. If it is not `SUCCESS`, the PR is not green,
  whatever the other rows say.
- **Don't trust `cmd | tail`, `cmd | head` or `cmd | grep` to report failure.** They report the
  last command's status.
- **Don't read a run's newest entry as its verdict.** A push made with the default
  `GITHUB_TOKEN` mints a **ghost run**: `conclusion: action_required`, zero jobs, no red check
  anywhere. It is newer than the real dispatched run underneath it.
- **Don't add capacity before proving capacity is the constraint.** On 2026-08-19 six Fly
  machines were bought to solve a queue that did not exist; the real cause was one red test.
- **Don't revert the head because main is red.** Prove the head is the cause first.
- **Don't add `cancel-in-progress` to any ref except main.** With several sessions pushing, every
  push destroys another agent's in-flight run, and the result is indistinguishable from a flaky
  test. Measured here: 7 successes and 16 cancellations in 60 runs.
- **Don't force-push a PR branch.** Auto-merge pushes a merge onto the branch when main moves, so
  a rejected push is the guard working. Fetch first.
- **Don't land a script without its ops-console row.** That is literally tonight's incident.
- **Don't merge from the GitHub web UI.** No guard on this box can see it, and it is how six red
  PRs reached main in three minutes.
- **Don't start fixing a red main before checking `gh pr list --label fixes-main`.** Two sessions
  wrote the same fix tonight.

---

## How to debug, by symptom

### "Every PR is failing"

```bash
.venv/bin/python scripts/pr_triage.py
```

It classifies each open PR by cause. Only the `TEST` rows are your code. `MACHINE` means the
runner died, `CANCELLED` means another push killed the run, `GHOST` means no run ever executed.

If it says nothing is really failing, the queue is the problem, not the code. Go to the next
section.

### "main is red"

```bash
.venv/bin/python scripts/main_red.py
gh run list --branch main --limit 5 --json databaseId,conclusion,headSha
gh run view <id> --json jobs -q '.jobs[]|.name+" "+(.conclusion//"-")+" "+(.databaseId|tostring)'
gh api repos/chidionyema/prospector/actions/jobs/<failing-job-id>/logs | rg -n 'FAILED|AssertionError|short test summary'
```

Then, **before blaming the newest commit**, check the one before it:

```bash
git stash list >/dev/null; git worktree add --detach /tmp/redcheck HEAD~1
cd /tmp/redcheck && .venv/bin/python -m pytest <the failing test> -q
```

Failing on `HEAD~1` too means the head is innocent and something older is the cause. That is
what happened tonight.

### "main is red and now NOTHING will build"

That is deliberate. `ci.yml`'s `changes` gate refuses to build any PR while main is red, because a
PR tested against a red base proves nothing. The escape hatch is one label:

```bash
gh pr edit <n> --add-label fixes-main
```

`ci.yml:236` reads it and skips the gate for that PR only. Two things about it:

- **Label the PR that actually repairs main, and nothing else.** Labelling your own unrelated PR
  to get it moving re-opens the hole the gate exists to close.
- **The label must exist before the run starts.** A PR's labels in the event payload are frozen at
  dispatch, so adding the label to a run already in flight changes nothing — re-run it after
  labelling.

Before you write that fix, check whether someone already has: `gh pr list --label fixes-main`.
Tonight two sessions fixed the same one-line drift independently, ten minutes apart.

### "My PR merged but nothing changed in production"

A merge is not a deploy. The deploy dispatch lives in `.github/workflows/automerge.yml` and
selects workflows by path filter.

```bash
.venv/bin/python scripts/deploy_status.py     # is the live stack running what is on main?
gh run list --workflow deploy-engine.yml --limit 3 --json headSha,conclusion,createdAt
git rev-parse origin/main
```

If the last successful deploy's `headSha` is behind `origin/main`, the deploy was skipped. Two
causes, in this order of likelihood:

1. **The dispatch never ran**, because an earlier error in the same `github-script` block threw
   and everything below it was silently dropped. Read the automerge job log to the end.
2. **The path filter did not match.** The three filters are in `automerge.yml` around line 115.

Recover by dispatching by hand:

```bash
gh workflow run deploy-engine.yml -f dry_run=false
```

Then prove it landed. A dispatch that succeeds is still a shape:

```bash
fly releases -a prospector-engine | head -3
```

### "A run exists but has no jobs / there is no check at all"

That is a **ghost run**. GitHub refuses to build a push made with the default `GITHUB_TOKEN`,
and gives you `conclusion: action_required` with zero jobs and no red X anywhere. The real run
is the older `workflow_dispatch` one at the same head.

```bash
gh api "repos/chidionyema/prospector/actions/runs?head_sha=$SHA" \
  -q '.workflow_runs[]|.name+" | "+.event+" | "+(.conclusion//.status)+" | "+.created_at'
```

Discard rows whose event is `push` and conclusion is `action_required`.

### "A job failed but no step failed"

The runner died. There is no failing step because the steps simply stop concluding. The only
place the truth is written is the check-run **annotation**: "The self-hosted runner lost
communication with the server".

```bash
gh api repos/chidionyema/prospector/check-runs/<check_run_id>/annotations -q '.[].message'
.venv/bin/python scripts/ci_fleet_probe.py     # machines against runners, per fleet
```

The usual cause here is a Fly **standby** machine. It registers as a runner, accepts a job, and
Fly stops it — logged as `stop | user`, which looks like a person or a script did it. Nobody
did.

### "A workflow permission error"

`403 Resource not accessible by integration`. An explicit `permissions:` block is a **whitelist**
— every scope you do not list becomes `none`, not "default". And a **job-level** `permissions:`
block **replaces** the top-level one outright; it does not merge. Adding one scope to a job can
therefore remove five.

### "A tool printed nothing and I killed it"

A tool that prints nothing for five minutes is indistinguishable from a hung one, so every
caller with a timeout kills it. Before concluding a tool hangs, run it capturing both streams
and the real exit code, and give it a generous timeout:

```bash
timeout 900 .venv/bin/python scripts/<tool>.py > /tmp/out 2> /tmp/err; echo "rc=$?"
wc -c /tmp/out /tmp/err
```

`rc=124` means the timeout killed it — not that it failed. Any long-running tool in this repo
should print progress to **stderr**; if it does not, that is a defect worth fixing in the same
turn.

---

## The instruments, and what each one lies about

| Instrument | What it does not tell you |
|---|---|
| `gh pr list` / check rollup | Whether `ci-ok` passed. Read `ci-ok` specifically. |
| `gh run list` newest entry | Ghost runs sort newest and have zero jobs. |
| A failing job's step list | Nothing, when the runner died. The annotation has it. |
| `fly machine list` state | Whether a machine is a standby. Read `config.standbys`. |
| `fly status` machine count | Usable capacity. Tonight: 12 shown, 2 usable. |
| `git rev-list --count` / `git cherry` | Whether a squash-merged branch has landed. Use `merge-tree`. |
| A merge conflict | That the work is unlanded. It is usually main's newer copy of it. |
| `cmd \| tail` exit status | The command's exit status. |
| `gh api` first page | The rest of the pages. Use `--paginate`. |
| A green deploy workflow run | That production changed. Check `fly releases`. |
| An issue opened by a guard | That the guard identified the right commit. |

---

## What is guarded, and what is still only words

**Guarded — a machine refuses or fails.**

| Class | Mechanism |
|---|---|
| A push that kills another agent's live CI run | `~/.claude/scripts/push-pr-fence.py` |
| Creating a Fly standby by cloning | `~/.claude/scripts/rule-guard.py::rule_clone_makes_a_standby` |
| A tool on disk with no ops-console row | `tests/unit/test_console_tools_run.py::test_console_tool_registry_has_no_drift` |
| Triage reporting green for a conflicting or draft PR | `tests/unit/test_pr_triage_reads_the_cause_not_the_colour.py` |
| An incident closed without a graded mechanism | `scripts/incident.py check` |

**Not guarded — these are still only written here.** Each is a ticket, not a note.

1. **A PR merging over a failing `ci-ok`.** The upstream cause of tonight. Nothing refuses it.
2. **The green guard reverting the head rather than the cause.** It must test `HEAD~1` before
   choosing a target, and refuse to revert when the failure predates the head.
3. **A `github-script` block where one API error silently drops the deploy dispatch below it.**
   The fix is a separate `if: always()` step; designed, not yet landed.
4. **A standby machine counted as capacity.** The refusal exists in `rule-guard.py`; the test
   that survives a clone made from the Fly dashboard is written but not raised.
5. **A cleanup tool whose cost scales with the mess.** Fixed and tested in PR #467, open.

An entry in this list is an admission, not a plan. Move it up to the table above.
