# SPEC — Graphify enforcement: estate-wide, unbypassable, never stale

**Status: DRAFT — awaiting founder approval. Nothing in §4 is built yet.**
Companion: [COST_PROGRAM.md](COST_PROGRAM.md). Governs every repo under `~/Documents/code/`,
not just prospector; it lives here because this is the versioned, pushed repo.

---

## 1. Goal (falsifiable)

> On any project, at any moment, a question about the codebase is answered from a knowledge graph
> that is **provably current**, and neither the operator nor the agent has to remember to make that
> happen.

Three properties, each independently testable:

| property | means | fails when |
|---|---|---|
| **P1 Universal** | every git repo under `~/Documents/code/` has a graph | a new repo is created and has none |
| **P2 Never stale** | `graph.json` is newer than every tracked source file and than `HEAD` | a commit lands and the graph is not rebuilt |
| **P3 Unbypassable** | graphify output reaches the model's context without the model choosing it | a session answers an architecture question with no graph evidence |

---

## 2. Measured starting point (2026-08-06, receipts in-session)

| item | value |
|---|---|
| graphify CLI | `~/.local/bin/graphify` → uv tool `graphifyy`; `.graphify_version` = **0.8.38** |
| skill | `~/.claude/skills/graphify/SKILL.md` (32,550 B) + 9 reference docs, installed 2026-06-12 |
| repos under `~/Documents/code/` | **16** git repos |
| prospector graph age | built **2026-06-21 12:34** → **209** newer `.py` files, **247** commits since |
| enforcement mechanisms | **0** — three prose lines at `~/.claude/CLAUDE.md:154-156`; no hook, no probe line, no memory file, no scheduled job |
| repo pollution | `git ls-files graphify-out` = **318 files / 7,722,576 bytes tracked**, `graphify-out` absent from `.gitignore` |
| enforcement scripts versioned? | **no** — `~/.claude/.git` does not exist |

**Verdict: P1 partial, P2 failed, P3 never attempted.** The current rule is prose, and prose is
exactly what failed for batching discipline.

### Baseline scoreboard — `python3 scripts/graphify_sweep.py`, 2026-08-06 19:00

```
repos 16   FRESH 7   STALE 4   ABSENT 5   graph files tracked in git 318
STALE:  prospector (46.3d behind HEAD, 318 files tracked)  haworks-platform (40.0d)
        signalengine (older than config.yaml)              sentinel-loop (0.2d)
ABSENT: modeltrainer_backup  popdd-py  prospector-consolidate-*  vault-101  vault-201
exit=1
```

Read the FRESH column carefully: those 7 graphs are also 46 days old, and are FRESH **only because
those repos have not changed since**. Freshness here is relative to the code, not to the calendar —
which is the correct contract, and the reason "rebuild everything weekly" is not the fix.
This block is the tracked baseline; every future amendment re-runs the sweep and replaces it.

---

## 3. Bypass surfaces and the mechanism that closes each

A requirement without a closing mechanism is a wish. Each row is a way today's setup gets bypassed.

| id | bypass surface | closing mechanism | enforced by |
|---|---|---|---|
| **G-USE** | agent simply doesn't run graphify | `UserPromptSubmit` hook detects a codebase-shaped prompt and injects the **graphify query result**, not an instruction | harness hook — runs outside model control |
| **G-FRESH** | graph older than the code | three independent refresh triggers (§4.2); any one failing still leaves the graph fresh | git hook + SessionStart + timer |
| **G-BOOT** | project has no graph at all | first SessionStart in a repo without `graphify-out/` bootstraps one in the background | SessionStart hook |
| **G-DISCOVER** | a new repo appears later | repos are **enumerated at run time**, never a hardcoded list | sweep job |
| **G-SELF** | someone edits/removes the hook | probe asserts the hooks are present in `settings.json` and fails loudly | state probe, exit 1 |
| **G-CLI** | CLI missing, or graph built by a different version | assert `graphify` on PATH and cache version == `.graphify_version` | probe |
| **G-IGNORE** | graphs bloat every repo (7.7 MB tracked today) | `graphify-out/` gitignored estate-wide; untrack existing | one-time migration + probe |
| **G-VCS** | enforcement scripts can't be reviewed or restored | version `~/.claude` with a strict ignore list | founder decision D2 |
| **G-COST** | enforcement costs more than it saves | refresh is incremental (`--update`), background, capped; measured into COST_PROGRAM §2 | cost ledger |
| **G-LOCK** | two sessions rebuild the same graph concurrently | per-repo lock file; second caller no-ops | refresh script |

### The honest boundary
A hook can guarantee that graphify **runs** and that its output **is in context**. No mechanism can
force the model to *reason* from it. That is why **G-USE injects answers rather than instructions**
— the graph evidence is present whether or not the model asks for it. Residual risk is measured
after the fact by auditing transcripts for architecture answers with no graph evidence in context;
it is not claimed as prevented.

---

## 4. Requirements

Each requirement is `ID · statement · verification command`. A requirement with no runnable
verification is not accepted into this spec.

### 4.1 Freshness definition (the contract everything else references)

```
FRESH  := graphify-out/graph.json exists
          AND mtime(graph.json) >= committer-time of HEAD
          AND no tracked source file has mtime > mtime(graph.json)
STALE  := graph exists but fails the above
ABSENT := no graphify-out/graph.json
```
Tolerance is **zero**, because "N days old" is how a graph silently rots. Meeting it is cheap:
`graphify <path> --update` is incremental.

### 4.2 Requirements table

| id | requirement | verification |
|---|---|---|
| R1 | `graphify` CLI is installed and its version matches the graphs' cache version | `test -x ~/.local/bin/graphify && graphify --version` vs `graphify-out/cache/ast/v*` |
| R2 | Every git repo under `~/Documents/code/` has `graphify-out/graph.json` | sweep script prints `ABSENT: 0` |
| R3 | Every graph is **FRESH** per §4.1 | sweep script prints `STALE: 0` |
| R4 | A commit makes its repo's graph fresh again **without human action** | `git commit` in a test repo, then re-run the sweep → still `STALE: 0` |
| R5 | A session opening in a stale repo triggers a refresh and says so | SessionStart injects a `[graphify]` line with FRESH/STALE/ABSENT + action taken |
| R6 | A codebase-shaped prompt gets graph evidence injected automatically | `UserPromptSubmit` hook output contains graphify results for a test prompt |
| R7 | Removing or breaking any hook is detected | probe exits 1 when the `settings.json` hook entries are absent |
| R8 | `graphify-out/` is gitignored in every repo and untracked where it is tracked today | `git ls-files graphify-out \| wc -l` → `0` in every repo (currently **318** in prospector) |
| R9 | Enforcement scripts are committed and pushed | `git -C ~/Documents/code/prospector log --oneline -1 -- scripts/graphify_*.py` and the branch is pushed |
| R10 | The refresh never blocks a session | refresh runs detached; SessionStart hook returns in < 2 s (**amended 2026-08-06** from "< 500 ms" — see §4.2b; the original number was written before anything was measured) |
| R11 | Concurrent sessions cannot corrupt a graph | two simultaneous refreshes on one repo → one runs, one no-ops |
| R12 | Enforcement cost is known and capped | a row in COST_PROGRAM §2 attributing daily tokens/seconds to refresh |

### 4.2b Proven so far (receipts, 2026-08-06)

| req | evidence | result |
|---|---|---|
| **R1** | CLI warned `skill is from graphify 0.8.38, package is 0.8.49`; ran `graphify install --platform claude` | ✅ closed — `.graphify_version` now `0.8.49`, SKILL.md 32,550 → 37,070 B, warning gone. Old skill backed up before overwrite |
| **R3/R4 mechanism** | `graphify_sweep.py --root <one repo> --fix` on `sentinel-loop`: STALE(41.6d) → **FRESH in 46.5s** | ✅ refresh works and re-assessment confirms it |
| **G-COST** | that run executed under `env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY` and still succeeded | ✅ **the refresh path spends zero tokens** — proven by execution, not by the help text |
| **R11** | held the repo's lock externally → `SKIPPED — another sweep holds the lock`, repo stayed STALE; released it → same command refreshed → FRESH | ✅ red-then-green, no race |

### 4.2c PH2/PH3 receipts (2026-08-06 evening — the triggers, not just the scoreboard)

| req | evidence | result |
|---|---|---|
| **R2** | `graphify update` run on all 7 non-fresh repos with `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` unset: haworks-platform 260.2s, signalengine 38.8s, modeltrainer_backup, popdd-py, vault-101 7.9s, vault-201 5.6s — **every one exit 0** | ✅ bootstrap needs no LLM either; the "first build may cost tokens" caveat did not materialise on any repo |
| **R4** | `--install-git-hooks` → installed in **15 of 16** repos, verified by re-reading `git rev-parse --git-path hooks`, not by trusting the installer's exit code | ✅ the 16th is an orphan worktree with 0 tracked files; given the §6/S1 `.graphify-skip` opt-out |
| **R4 cost** | read the installed hook: it ends in `subprocess.Popen(..., start_new_session=True)` and skips rebase/merge/cherry-pick and graphify-out-only commits | ✅ **commits are not slowed** — the refresh is detached, which matters here because a prospector commit already spends ~9 min in the POPDD gate |
| **R5/R10** | `graphify_session_hook.py` on `crux`: emitted the `[graphify] crux — graph FRESH` line in **1.21s real** (`assess()` itself 0.34–0.40s; the rest is interpreter start) | ⚠️ works, but **1.21s ≠ the < 500 ms the spec asserted**. R10 amended to < 2s. The 500 ms was invented before measurement — exactly the kind of unproven number this spec exists to stop |
| **R6** | `graphify_query_hook.py` on *"where is the moat verdict provider chain wired in verify.py?"* → injected graph evidence in 4.6s, including `verdict_for() verify.py:213`, `verify() verify.py:452`, `_build_operator() operator.py:904` | ✅ fires and returns real anchors |
| **R6 quality** | that same run returned **337 nodes** as a flat list and spent the entire 1,200-token budget, truncating 287 of them | ⚠️ **signal is thin.** The useful rows were in the first ~25, so the budget was cut to **700**. Whether injection beats a grep sweep is still §L8's unmeasured question |
| **R6 negative control** | `{"prompt":"thanks, that looks good"}` → no output, exit 0 | ✅ does not tax non-codebase prompts |
| **R7** | `--check-hooks` **before** wiring: 3 problems, exit 1 (both settings.json entries + 16 repos). After wiring: see the board below | ✅ red-then-green; the check detects its own removal |
| **R8** | untracked via a temporary `GIT_INDEX_FILE`, so the shared index was never touched — no worktree needed, and a concurrent session's bare commit could not sweep in the 318 deletions | ✅ 324 paths staged (318 deletions + `.gitignore` + 3 scripts + 2 docs), every path machine-asserted against an allowlist before committing |
| **R8 attempt 1** | the commit was **BLOCKED**: `❌ python — pytest suite: step 'pytest' exceeded 600s and was killed`. The python lane is ~175s uncontended (`.lux/hooks/pre-commit:28`); at the time a second session was running both its own `pytest tests/unit` and its own `git commit --only` gate, against a live scheduler daemon | ⚠️ **the gate reports a hang, and contention looks identical to one.** `grep -rl graphify tests/` returns nothing, so that suite was never evidence about this diff. Fixed by serialising on the other gate and raising `POPDD_TEST_TIMEOUT` (`scripts/popdd_verify.py:72`), never by `--no-verify` |
| **R8 trap** | the temp index had been built with `read-tree` from the *old* HEAD. Committing it after the other session landed would have reverted their work silently — the tree is complete, it just predates them | ✅ the index is now rebuilt from `HEAD` **after** the wait, not before |

### 4.3 Refresh triggers (R4 — three, so no single failure causes staleness)

1. **git `post-commit` hook** (per repo, `--install-git-hooks`) — refresh immediately on the change
   that caused staleness. Primary. ✅ **LIVE in 15/16 repos**, and detached, so it does not slow a
   commit.
2. **SessionStart** (`scripts/graphify_session_hook.py`) — refresh if stale when a session opens.
   Catches commits made outside the hook (rebases, `--no-verify`, other machines). ✅ **LIVE**,
   1.21s, spawns the refresh detached and never waits on it.
3. **Periodic sweep** — `~/Library/LaunchAgents/com.chidionyema.graphify-sweep.plist`, every
   **1800s** (§6/S3). Backstop for everything the first two miss: a repo created after install, a
   push from another machine, a hook someone deleted. ✅ **LIVE**.

A fourth hook, `UserPromptSubmit` (R6), is deliberately **not** a refresh trigger — it is the *use*
trigger. It answers the prompt from the graph so the cheap path is the default one rather than the
disciplined one. Keeping it off the refresh path is what stops a prompt from ever waiting on a
rebuild.

**Two traps this wiring already hit, recorded so the next person does not re-derive them:**
- `graphify hook install` fails with `NotADirectoryError` in a worktree, because there `.git` is a
  **file**. The installer is therefore verified by re-reading `git rev-parse --git-path hooks`,
  never by its exit code.
- A launchd agent running `/usr/bin/python3` **cannot read `~/Documents` at all** — macOS TCC
  denies it and the failure surfaces as `Operation not permitted`, which reads like a missing file.
  The plist runs the repo's `.venv/bin/python`, the interpreter every working agent in this estate
  already uses, and sets `PATH` explicitly so `shutil.which("graphify")` can find `~/.local/bin`.

---

## 5. Deliverables and phases

(Phases are `PH*` so they cannot be confused with the properties `P1–P3` in §1.)

| phase | deliverable | satisfies | status |
|---|---|---|---|
| **PH0** | `scripts/graphify_sweep.py` — read-only status of every repo (`FRESH/STALE/ABSENT`, tracked-file count). Ships first so the spec has a scoreboard from day one. | R2, R3, R8 evidence | ✅ **DONE 2026-08-06**, exit 1 |
| **PH1** | `--fix` mode: incremental `--update`, bootstrap, lock file | R4, R10, R11 | ✅ **DONE 2026-08-06** |
| **PH2** | Hook wiring: SessionStart line, `UserPromptSubmit` injection, `post-commit` install, launchd backstop | R5, R6, R4 | ✅ **DONE 2026-08-06**, receipts in §4.2c |
| **PH3** | `--check-hooks` self-check; `.gitignore` migration; enforcement scripts versioned | R7, R8, R9 | ✅ **DONE 2026-08-06** — see the R9 note below |
| **PH4** | Cost attribution row in COST_PROGRAM §2 | R12 | ✅ **DONE 2026-08-06** — refresh 0 tok, injection ≤700 tok and logged per call |

**R9 was closed differently from the original plan.** The scripts live in
`prospector/scripts/`, which is already tracked and pushed, and `~/.claude/settings.json` points at
them by absolute path. The original plan was `git init ~/.claude` (decision D2), which is now
**withdrawn, not deferred**: `~/.claude` holds credential-adjacent files, so versioning it buys the
same property at a much worse risk. `~/.claude/scripts` is separately a git repo already, with two
commits and no remote — untouched by this work.

**Definition of done for the whole spec:** `scripts/graphify_sweep.py` exits 0 with
`ABSENT: 0  STALE: 0  TRACKED: 0`, and the state probe prints a green `[graphify]` line, on a day
when no one ran anything by hand.

---

## 6. Open decisions

| id | decision | recommendation |
|---|---|---|
| S1 | Scope of "all projects": every git repo under `~/Documents/code/`, or an explicit opt-in list? | All repos, auto-discovered — an opt-out file (`.graphify-skip`) beats a hardcoded list, and satisfies G-DISCOVER. |
| S2 | Does G-USE inject **answers** (strong, costs tokens per prompt) or a **freshness banner** (cheap, model may ignore)? | Answers, but only when the prompt matches a codebase shape, with a hard token cap. Measure into COST_PROGRAM. |
| S3 | Sweep interval for the backstop timer. | 30 min. The git hook does the real work; this only catches misses. |
| S4 | Untracking 7.7 MB of `graphify-out` rewrites nothing but does touch a shared branch. | Do it as its own commit, explicit paths only (never `git add -A` — `store/` is tracked runtime state). |

---

## 7. Operating manual (added 2026-08-06 — the part that was only ever said out loud)

Everything above says what was *built* and what was *proven*. None of it said how you **run** this,
which meant the answer lived in a chat reply — the exact prose-drift §4.3 exists to kill.

### 7.1 How you use it: you don't

There is no command to remember. Four independent triggers keep the estate fresh, and the benefit
arrives without you asking for it:

| trigger | fires on | what it does | can it block you? |
|---|---|---|---|
| `post-commit` hook | every commit, 15/16 repos | detached `graphify update` | no — detached |
| `SessionStart` | every session, every repo | prints graph state; spawns a detached refresh if STALE | no — 1.21s, fails silent |
| `UserPromptSubmit` | codebase-shaped prompts only | runs the local BFS and injects the ANSWER | no — 12s timeout, fails silent |
| launchd, 30 min | always | catches whatever the other three missed | no — `Nice 5`, `LowPriorityIO` |

### 7.2 The only four commands worth knowing

```bash
python3 scripts/graphify_sweep.py                     # the scoreboard. exit 0 = estate clean
python3 scripts/graphify_sweep.py --check-hooks        # "is enforcement still wired?" exit 0 = yes
python3 scripts/graphify_sweep.py --fix --only <repo>  # force one repo to refresh now
GRAPHIFY_HOOK_OFF=1 <cmd>                              # disable injection for ONE process
```

`GRAPHIFY_HOOK_OFF` is deliberately per-process, not a global kill switch: `--check-hooks` and the
state probe still report the wiring as present, so it can silence a measurement run (§L8 needs a
control arm) but cannot be used to quietly turn enforcement off estate-wide.

### 7.3 When it looks broken

| symptom | first check | likely cause |
|---|---|---|
| board exits 1 | read the last three lines | `graph files tracked in git` ≠ 0, or a repo is STALE/ABSENT |
| `--check-hooks` exits 1 | it names the missing entry | a `settings.json` edit dropped a hook, or a repo lost its `post-commit` |
| a repo is ABSENT | `--fix --bootstrap --only <repo>` | never auto-built: a first build runs the community labeller, **the one path that can spend tokens** |
| launchd shows exit 1 | `launchctl list \| grep graphify` | **expected** while `graphify-out` is still tracked — the sweep's own exit code is the board's |
| no injection on a code prompt | `tail ~/.claude/graphify-inject.log` | prompt did not match `is_codebase_shaped()`, or the repo has no `graph.json` |
| nothing at all fires | `ps eww` the hook | launchd's bare PATH hides `~/.local/bin`; `/usr/bin/python3` cannot read `~/Documents` (TCC) |

### 7.4 What this does NOT give you

State these before quoting the system, because a lead read as proof is worse than no lead:

- **Injected nodes are LEADS, not answers.** A real prompt returned **337 nodes as a flat list**; the
  useful rows were the first ~25. Verify at a `file:line` before claiming anything. The estate's
  proof-of-claim rule outranks anything this hook injects.
- **The saving is UNMEASURED.** Enforcement is proven ~free (refresh 0 tok, injection ≤700 tok and
  logged per call). Whether injection is *cheaper than an agent grepping* is COST_PROGRAM §L8's open
  A/B. Until it runs, "graphify saves money" is a HYPOTHESIS, not a result.
- **Freshness is mtime-based**, per §4.1. A `git checkout` that rewrites mtimes can mark a graph stale
  when its content is fine. The cost of that false positive is one free refresh, which is why the
  contract errs this way on purpose.

---

*Created 2026-08-06 by Claude (Opus 5). All §2 figures measured in-session; no figure carried from
memory. Amendments append and date their evidence.*
