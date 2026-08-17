# Estate quirks — platform behaviours that produced a wrong diagnosis

Every entry here cost real time. Each one is a case where the machine, the scheduler or the
shell behaved in a way that made a healthy thing look broken, or a broken thing look healthy.

This is not a runbook. `RUNBOOKS.md` says what to do when a line goes red. This file says why
the line may be lying to you.

Each entry has the same four parts: what it is, the receipt that proved it, the check that
exposes it, and the fix. An entry with no receipt does not belong here.

---

## Q1 — `LowPriorityIO` starves a job whose whole cost is disk IO

`LowPriorityIO=true` and `ProcessType=Background` in a launchd plist set `IOPOL_THROTTLE`. The
kernel then parks the process whenever any un-throttled process touches the disk. On a job
that is mostly CPU that is politeness. On a job that is entirely disk IO it is starvation.

**Receipt, 2026-08-17, `com.estate.costsentinel`** (reads 1,593 transcripts, 0.28 GB, every
900s):

| run | band | wall | CPU used |
|---|---|---|---|
| by hand | normal | 220s | 40.1s |
| launchd pid 94075 | throttled | 1306s, still going | **0.54s** |
| `taskpolicy -b -d throttle` pid 3627 | throttled | 220s, still going | 3.6s |

Half a second of work in twenty-one minutes. Receipt durations before the fix ran 674s, 870s,
1047s, 1973s, 7570s, with a maximum of 32,628s, against a median of 83s. After deleting the
two keys and reloading, the next receipt read `duration_s: 83.18`.

**Check.** Compare CPU time against elapsed time, not elapsed time alone:

```bash
ps -Ao pid,etime,time,%cpu,command | grep <script>
```

A process with minutes of elapsed time and under a second of CPU is blocked, not slow.

**Fix.** Use `Nice` instead. It keeps the job off the CPU when the box is busy without
throttling its reads.

```bash
plutil -remove LowPriorityIO ~/Library/LaunchAgents/<label>.plist
plutil -replace Nice -integer 5 ~/Library/LaunchAgents/<label>.plist
launchctl bootout gui/$UID/<label>; launchctl bootstrap gui/$UID ~/Library/LaunchAgents/<label>.plist
```

Applied to `com.estate.costsentinel`, `com.chidionyema.graphify-sweep`,
`com.chidionyema.reflect`. Backups at `<label>.plist.bak-throttle`.

---

## Q2 — A slow job reads as DARK, not as slow

launchd will not start the next run of a label while the previous run is still alive. A job
that outlives its own `StartInterval` therefore suppresses every following run.

**Receipt.** `com.estate.costsentinel` had 408 consecutive clean runs behind it and still
scored DARK, because `capability_audit` saw `last=1.8h expected≤15m`. The capability was not
failing. It was being prevented from starting.

**Check.** Before believing a DARK verdict, look for a live process for that job.

```bash
ps -Ao pid,etime,command | grep <script>
launchctl print gui/$UID/<label> | grep -E "state|pid|last exit"
```

**Fix.** Three parts. Give the wrapper a hard ceiling so a stalled run cannot suppress the
next one forever — `launchd_receipt.py --timeout` defaults to 3600s and records exit 124,
which is a receipt the audit can see. Then fix whatever made the run slow, because a timeout
is containment and not a cause.

Third, and added 2026-08-17 because the founder had to be the one who noticed: a job now has
a runtime BUDGET, and blowing it is a failure on its own. `launchd_receipt.py` works the
budget out from the label's own `StartInterval` and halves it, so nothing has to opt in —
`com.estate.costsentinel` at `StartInterval 900` gets 450s. A run over budget writes
`over_budget: true` on its receipt, and `capability_audit.py` scores that **SLOW**, which is
in `FAIL_VERDICTS`. Between "fresh" and "dark" there was nothing; a job could get ten times
slower and stay green until it got slow enough to disappear. Now it goes red while the
diagnosis is still cheap. Override with `--budget-s`; `--budget-s 0` disables.

**Half the interval was not enough, and the founder proved it the same day.** The
complaint-ledger job went from minutes to 1h53m. That is a tenfold regression, and it sat
comfortably inside half of a daily interval, so nothing went red and the founder was the
alarm. Half the interval only catches a job about to suppress its own next run.

So there is a second bar, from 2026-08-17: **three times the median of that job's own recent
clean runs** (`launchd_receipt.py::_history_budget`, and the same function with the same
numbers in `cron/scheduler.py`, so one audit reads both ledgers). The tighter of the two
bars wins, and the receipt records which one under `budget_basis`. Median, not mean, so one
outlier cannot raise the bar it exists to trip. Clean runs only, because a run that crashed
early is fast for the wrong reason. Under five samples there is no budget at all — we do not
know what normal is yet, and a guessed bar is worse than none. A 30s floor stops a job whose
median is 0.2s going red at 0.6s.

Proved: five clean runs of 100s give a 300s budget; five failed 0.1s runs do not lower it; a
0.2s median gives 30s rather than 0.6s; and six 120s runs give 360s, which a 6780s run trips
and a 130s run does not.

**The cron jobs were outside all of this until the same day.** The rail read launchd plists,
and 15 of 22 owned launchd jobs are long-running daemons with no interval to halve, while the
complaint ledger has no plist at all — it runs from `~/.hermes/cron/jobs.json`. Its receipts
recorded `duration_s` and compared it to nothing. The history bar needs no plist, which is
what let the same rule cover both.

---

## Q3 — `StartCalendarInterval` is skipped outright if the machine is asleep

A calendar-scheduled job does not run late. If the machine is asleep at that minute, that run
simply does not happen, and the next one is a whole period away.

**Receipt.** `ai.hermes.submodule-backup` was set to 04:10 daily and the capability read
`last=3.5d`. The script was fine. The machine was asleep at 04:10.

**Check.** `pmset -g log | grep -E "Sleep|Wake"` around the scheduled minute.

**Fix.** Use `StartInterval` for anything that must happen once a period rather than at a
specific clock time. `StartInterval` fires on wake once the interval has elapsed.
`ai.hermes.submodule-backup` is now `StartInterval 86400`.

---

## Q4 — The launchd plists have no tracked source

`~/Library/LaunchAgents/*.plist` are not in any repository. Every scheduler definition on this
estate exists on exactly one disk, and so does every fix applied to one.

**Receipt.** The Q1 throttle fix and the Q3 interval change are both live and both untracked.
Nothing would show they had reverted.

**Check.** `ls ~/Library/LaunchAgents/*.plist | wc -l` against any tracked copy. There is none.

**Fix.** Closed 2026-08-17. `scripts/launchd_plists.py` snapshots every owned job to
`ops/launchd/*.json` and reports drift against it.

```bash
python3 scripts/launchd_plists.py --check      # exit 0 match, 1 drift, 2 no snapshot yet
python3 scripts/launchd_plists.py --snapshot   # accept what is installed now
```

29 jobs tracked. Vendor agents (Adobe, ExpressVPN, Steam and the like) are excluded, because
drift on a job we did not install trains the reader to ignore the output.

**Secrets.** Plists carry real credentials — `CONTROL_CENTER_PASSWORD` in two of them and
`DEEPSEEK_API_KEY` in a third. Any value under a credential-shaped key name is written as
`<REDACTED>`, and two redacted values compare equal. Drift in a secret's value is therefore
invisible to this tool by design. It tracks job definitions, not the secret store.

Proven on both paths: `--check` before any snapshot exits 2; after `--snapshot` it exits 0 with
29 matches; reverting the tracked copy of `com.estate.costsentinel` to its pre-fix state
printed exactly the three keys that make up the fix and exited 1.

---

## Q5 — Spotlight is permanent background IO, and excluding a tree needs no sudo

Spotlight's crawlers (`mds`, `mds_stores`, `mdworker`, `mdbulkimport`) walk every file on the
disk continuously. That is the competing IO that makes Q1's throttle bite.

**Receipt, 2026-08-17.** `mds` had used 198 minutes of CPU and `mds_stores` 294 minutes.

**Fix.** Turning Spotlight off entirely costs ⌘-Space, Finder search and Mail search, and it
needs root. A `.metadata_never_index` file inside a directory makes Spotlight skip that whole
tree, needs no sudo, and is reversed by deleting the file. Placed in `~/.claude/projects`
(16,615 entries), `~/.claude/state/toolguard`, `~/.hermes/state`, `~/.hermes/backups`,
`prospector/store`, `prospector/graphify-out`, `prospector/.backfill-logs`.

---

## Q6 — `plutil -extract` writes its error message to stdout

A missing key does not produce an empty string. It produces a sentence, on stdout, which a
shell loop then captures as if it were the value.

**Receipt, 2026-08-17.** A sweep of every plist printed
`LowPriorityIO=ai.hermes.cockpit.plist: Could not extract value, error: No value at that key
path` as the value of `LowPriorityIO`, for every plist that did not have the key. Every row
looked like a hit.

**Fix.** Redirect stderr and test the exit status, or read the plist in Python with
`plistlib`, which returns `None` for a missing key.

---

## Q7 — A Python heredoc inside `bash -c` breaks on f-strings containing quotes

The shell processes backslashes before Python ever sees the text, so `f"{d.get(\"key\")}"`
arrives as a syntax error.

**Receipt, 2026-08-17.** The same construct failed three times in one session. On the third
failure the plist patch silently did not apply, and the job was reloaded in the band it was
supposed to have left.

**Fix.** Write the script to a file and run the file. Do not inline Python that contains
quotes inside braces.

---

## Q8 — A substring filter over a shared ledger mixes two jobs together

`capability_receipts.jsonl` holds every job's receipts in one file. Filtering it with a
substring match picks up any job whose name contains that substring.

**Receipt, 2026-08-17.** Filtering for `sentinel` also matched
`com.chidionyema.graphify-sweep`, because its receipts carry `graphify_sweep.py`. Interleaving
the two produced out-of-order start times, which read as overlapping runs of one job. The
conclusion drawn from that — that multiple schedulers were launching the sentinel — was wrong,
and was only caught by grouping on the `label` field.

**Fix.** Filter on the `label` or `script` field exactly. Never on a substring of the whole
line.

---

## Q9 — `duration_s` on a launchd receipt includes the wrapper's own work

`launchd_receipt.py` stamps `started` before the subprocess and computes `duration_s` when it
writes the receipt, which is after the `--artifact-dir` scan. A receipt's duration is the
wrapper's wall time, not the child's.

**Check.** It only matters when `--artifact-dir` is passed at a large tree. The scan is
bounded at 5,000 files, so it degrades to slow rather than unbounded.

---

## Q10 — A recursive glob over `~/.claude` does not return

`~/.claude/projects` holds roughly 89,000 JSONL files across 4 GB. Any `**` glob or `find`
rooted above it walks all of them.

**Receipt, 2026-08-17.** A fallback `glob.glob("~/.claude/**/*spend*history*", recursive=True)`
hung past a 120-second timeout, in a script whose actual job took under a second.

**Fix.** Name the directory. Never glob recursively from a home directory or above.

---

## Q11 — `cmd | tail` reports tail's exit status

A failing build piped through `tail` reads as exit 0.

**Fix.** Capture the real status before the pipe, or use `PIPESTATUS`.

---

## Q12 — In a worktree, `.git` is a file

Anything that reads `<root>/.git/...` as a directory is a bug in a linked worktree, where
`.git` is a file containing a `gitdir:` line. Ask git instead: `git rev-parse --git-path
hooks`, `git rev-parse --git-common-dir`. Those also honour `core.hooksPath`, which a direct
path read does not.

**Receipt.** `tests/unit/test_popdd_gate_lanes.py` had exactly this defect and reported the
POPDD gate uninstalled in a checkout where it was installed and working.
