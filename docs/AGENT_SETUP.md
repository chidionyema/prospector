# How agents are briefed on this estate

Every Claude Code session opens with a set of instructions it did not choose. This document says
where each kind of fact lives, and why. It is short on purpose. If you are adding something an
agent must know, the table below tells you where to put it, and the last section says what happens
when you put it in the wrong place.

## The rule

**A fact that can change without anyone editing a file does not go in a markdown file.**

Anthropic's own guidance says it plainly: build status, deployment info and live state belong in a
SessionStart hook or an MCP tool, not in `CLAUDE.md`, because context loaded at launch is stale by
turn two. This estate learned it the expensive way on 2026-08-19 — see the last section.

## Where each kind of fact lives

| Kind of fact | Where it goes | This estate |
| --- | --- | --- |
| Live state: what is deployed, what is running, how stale this checkout is | SessionStart hook | `ops/state_probe.sh`, installed to `~/.claude/state-probe/prospector.sh`, run by `~/.claude/scripts/memory-loop.py` and injected as VERIFIED LIVE STATE |
| Standing rules that apply to every turn | `CLAUDE.md` | `~/.claude/CLAUDE.md` (all projects) and `./CLAUDE.md` (this repo) |
| Rules that only matter when certain files are open | `.claude/rules/*.md` with `paths:` frontmatter | not yet used — see Open below |
| A repeatable procedure with steps | `.claude/skills/<name>/SKILL.md` | `~/.claude/skills/graphify/` |
| A narrow job with restricted tools | `.claude/agents/<name>.md` | subagents are spawned inline today |
| What happened, and what to do next | `~/.claude/projects/<slug>/checkpoints/LATEST.md` | written at every safe point, re-injected by the same hook as LEADS, not state |
| An incident and the trap it revealed | `~/.claude/projects/<slug>/memory/` one file per fact | indexed by `MEMORY.md` |

Load order for instructions: managed policy, then `~/.claude/CLAUDE.md`, then `./CLAUDE.md`, then
`./CLAUDE.local.md`. They concatenate — nothing overrides anything, so a contradiction between two
files is a contradiction the agent has to guess its way out of. Root `CLAUDE.md` is re-read after
`/compact`; nested files and path-scoped rules are not.

## What the probe prints, and why each line is there

`ops/state_probe.sh` runs before every session in a prospector checkout. It prints where production
is (Fly, not this Mac), the command that returns the live process table, a warning not to read the
laptop's leftover launchd jobs as production, and how many commits behind `origin/main` each
developer checkout is. No network calls: it runs before every session and must stay fast.

It is installed rather than run from the repo, because a checkout can be stale and the brief must
not be. That installed copy is itself graded: `scripts/process_audit.py` compares its hash against
`ops/state_probe.sh` and fails the audit on drift, and fails again if any project directory has
lost its `.state-probe` pointer. Sessions started somewhere with no pointer open blind, which is
the failure this whole mechanism exists to prevent, so it is graded rather than assumed.

Re-install after changing it:

```bash
bash ops/state_probe.sh --install
```

## The ethos problem, measured

This estate writes rules faster than it writes checks. Counted across
`docs/WAYS_OF_WORKING.md`, `docs/PLATFORM_MANIFESTO.md` and the programme docs on 2026-08-19:
about thirty distinct founder complaints have produced a written rule, and roughly one in three
has a machine standing behind it. The other two thirds rest on an agent remembering a sentence.

That ratio is the ethos problem, and it is not fixed by writing better sentences. The tenets
already say "self-healing first, guard second, memory file last", and the estate keeps reaching
for the third option because it is the cheapest to produce and the only one that never fails
loudly. A rule with no check does not fail. It just stops being followed, quietly, and the next
incident reads as a new problem.

**The rule about rules: a new rule ships with the check that catches its violation, or it ships
labelled PROSE-ONLY with the reason no machine can check it.** Three legal answers, same as for a
defect: make the system fix it, make a machine refuse it, or write it down and say plainly that
writing it down is all you did.

## Which Claude Code mechanism closes which rule

The hook events are the lever, and the estate already uses twelve of them. These are the rules
that are still prose and the event that would close each one. Every "not wired" below is a
morning's work that `docs/WAYS_OF_WORKING.md` Part 7 already asked for.

| Rule, and what it last cost | Event | Wired? |
| --- | --- | --- |
| W20 verify in production, after prod ran 17-hour-old code | SessionStart | partly: `ops/state_probe.sh` prints where production is, but not whether the live image matches `origin/main` |
| W21 never leave work uncommitted, which the founder called irresponsible | SessionEnd | no. `scripts/session_check.py` exists and nothing fires it |
| W7 claim before starting, after two sessions duplicated work | SessionStart | no |
| W22 close browser sessions when UI work ends | SessionEnd | no |
| W23 branch hygiene: 34 worktrees behind main, worst 719 commits | SessionStart or scheduled | measured by `scripts/worktree_gc.py`, graded by `scripts/process_audit.py`, not yet run on a schedule |
| W6 check what exists before building, with 219 files referenced by nothing | UserPromptSubmit | partly: `graphify_query_hook.py` injects evidence, nothing refuses a duplicate |
| W11 timebox at thirty minutes, against "5 hours sometimes" | Stop | no. No hook models elapsed time on one unchanged failure |
| Recon delegation and batching | PreToolUse | yes: `tool-drip-guard.py` exits 2 on the third consecutive read-only call |
| W18 push implies a pull request | PreToolUse and Stop | yes: `push-pr-fence.py` refuses the push, `branch-pr-guard.py` blocks the turn end |
| Commits that stage runtime state or skip the gate | PreToolUse | yes: `rule-guard.py`, eight refusing rules |

Two mechanisms this estate has never used at all, both of which would help:

- **`.claude/agents/<name>.md`.** Subagent definitions with a pinned model and restricted tools.
  The delegation rule, "before the second exploratory search, spawn a haiku recon agent", is
  prose every session has to remember. As an agent definition it becomes configuration.
- **`.claude/rules/<name>.md` with `paths:` frontmatter.** Rules that load only when matching
  files are in context. `CLAUDE.md` is 239 lines here and 305 globally, against Anthropic's
  200-line guidance, and every line is resident on every turn of every session.

**One caveat worth stating plainly.** All twelve hooks live in `~/.claude/scripts/`. None is in a
git repository, none goes through a pull request, and none has a test. The machines enforcing this
estate's engineering standards are the only code here held to none of them.

## The incident this came from

On 2026-08-19 an agent reported "production engine is down" while the engine was ruling verdicts in
`lhr`. It was not careless. The `CLAUDE.md` the harness injected came from the checkout the session
started in, that checkout was 59 commits behind `origin/main`, and its "Where production runs"
section still described a local engine started by launchd. The agent read the file, graded this
Mac's `com.prospector.*` jobs as the production process table, found them unloaded, and drew the
only conclusion those instructions supported.

Stale instructions are indistinguishable from correct ones from the inside. That is why the fix is
a probe and a grader, not a better paragraph.

## Open

- `CLAUDE.md` is 239 lines here and 305 lines globally, against Anthropic's 200-line guidance. The
  worktree and pre-commit-gate sections are the obvious candidates to move to `.claude/rules/` with
  `paths:` frontmatter, so they load only when git or hook files are in context.
- Both developer checkouts are 60 commits behind `origin/main` and the iCloud one holds 132
  uncommitted paths. Until that is resolved the probe warns about it every session, which is the
  correct behaviour but not a fix. Deciding it is a founder call: bring it current, or stop starting
  sessions there.
