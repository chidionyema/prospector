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
| R9 | Enforcement scripts are committed and pushed | `git -C ~/.claude status` succeeds and is clean |
| R10 | The refresh never blocks a session | refresh runs detached; SessionStart hook returns in < 500 ms |
| R11 | Concurrent sessions cannot corrupt a graph | two simultaneous refreshes on one repo → one runs, one no-ops |
| R12 | Enforcement cost is known and capped | a row in COST_PROGRAM §2 attributing daily tokens/seconds to refresh |

### 4.2b Proven so far (receipts, 2026-08-06)

| req | evidence | result |
|---|---|---|
| **R1** | CLI warned `skill is from graphify 0.8.38, package is 0.8.49`; ran `graphify install --platform claude` | ✅ closed — `.graphify_version` now `0.8.49`, SKILL.md 32,550 → 37,070 B, warning gone. Old skill backed up before overwrite |
| **R3/R4 mechanism** | `graphify_sweep.py --root <one repo> --fix` on `sentinel-loop`: STALE(41.6d) → **FRESH in 46.5s** | ✅ refresh works and re-assessment confirms it |
| **G-COST** | that run executed under `env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY` and still succeeded | ✅ **the refresh path spends zero tokens** — proven by execution, not by the help text |
| **R11** | held the repo's lock externally → `SKIPPED — another sweep holds the lock`, repo stayed STALE; released it → same command refreshed → FRESH | ✅ red-then-green, no race |

**R10 (never blocks a session) is NOT yet proven.** Refresh took 46.5s on a small repo, so the
SessionStart hook must spawn it detached; that is PH2 work and is not claimed until measured.

**Refreshing prospector itself is BLOCKED on R8.** Its `graphify-out` is tracked (318 files), so a
rebuild would drop a 318-file diff into a branch shared with other live sessions. Untrack first,
then refresh — in that order, or the refresh becomes an accidental mass commit.

### 4.3 Refresh triggers (R4 — three, so no single failure causes staleness)

1. **git `post-commit` hook** (per repo, installed by the sweep) — refresh immediately on the change
   that caused staleness. Primary.
2. **SessionStart** — refresh if stale when a session opens. Catches commits made outside the hook
   (rebases, `--no-verify`, other machines).
3. **Periodic sweep** (launchd, interval TBD) — backstop that also satisfies R2/G-DISCOVER for new
   repos. Catches everything the first two miss.

---

## 5. Deliverables and phases

(Phases are `PH*` so they cannot be confused with the properties `P1–P3` in §1.)

| phase | deliverable | satisfies | status |
|---|---|---|---|
| **PH0** | `scripts/graphify_sweep.py` — read-only status of every repo (`FRESH/STALE/ABSENT`, tracked-file count). Ships first so the spec has a scoreboard from day one. | R2, R3, R8 evidence | ✅ **DONE 2026-08-06**, exit 1 |
| **PH1** | `--fix` mode: incremental `--update`, bootstrap, lock file | R4, R10, R11 | ✅ **DONE 2026-08-06** |
| **PH2** | Hook wiring: SessionStart line, `UserPromptSubmit` injection, `post-commit` install | R5, R6, R4 | not started |
| **PH3** | Self-check in the state probe; `.gitignore` migration; `~/.claude` versioning | R7, R8, R9 | not started |
| **PH4** | Cost attribution row in COST_PROGRAM §2 | R12 | not started |

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

*Created 2026-08-06 by Claude (Opus 5). All §2 figures measured in-session; no figure carried from
memory. Amendments append and date their evidence.*
