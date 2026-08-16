# Runbooks — what to do when a line goes red

One entry per automation in `ops/automations/`. Every entry answers the same five questions, in
the same order, so the reader never has to hunt: what it checks, what red means, what to do, how
long it takes, and what to do if the fix fails.

Rules for this file (`docs/OPS_AUTOMATION_PRINCIPLES.md` R5):

- An automation without an entry here is not finished.
- Commands are copy-pasteable, with the directory they run in.
- No entry says "investigate". Say what to look at and what a good answer looks like.
- Every automation exits **0 clean, 1 findings, 2 could not establish**. Exit 2 is not clean; it
  means the check could not run and the real state is unknown.

---

## retired-terms

**What it checks.** Every tracked file, for names that were deliberately removed from the
business. The names and the allowed exceptions are declared in `ops/config/retired_terms.yaml`;
the engine holds no names of its own.

**Run it.**

```bash
cd /Users/chidionyema/Documents/code/prospector
.venv/bin/python -m ops.automations.retired_terms          # human output
.venv/bin/python -m ops.automations.retired_terms --json   # what the console calls
```

**What red means.** A file names something that no longer exists. That is not cosmetic. The last
one, Paddle, was the literal default provider in five places, so a catalogue row with no provider
sent a buyer to a payment rail nobody could bill. Legal pages named it as a sub-processor when it
processed nothing, which is a false statement in a UK GDPR notice.

**What to do.** Read each finding and put it in one of two buckets.

1. **A live leftover.** Remove it. Replace the name with what actually happens now. If it is a
   default (`?? "name"`, `or "name"`, `|| 'name'`), the replacement is the real current default,
   never an empty string — an empty default is how a row silently routes nowhere.
2. **History.** A dated audit, an applied database migration, a spec with a superseded banner, a
   test that pins the removal. Add its path prefix to the `allow:` list in
   `ops/config/retired_terms.yaml` **with a written reason on the line above it.** A prefix with
   no reason is how this check quietly stops checking.

Then re-run. Exit 0 is the receipt.

**How long.** Minutes for a handful of findings. The Paddle removal itself took a working session
and touched 34 files across C#, TypeScript, Python, config and legal copy.

**If it exits 2 (could not establish).** The check could not run, and the state is unknown.

- `declaration not found` — you are in the wrong directory, or the YAML was moved. Pass
  `--config <path>`.
- `not a git repository` — the automation lists files through `git ls-files`. Run it inside the
  repo or a worktree of it.
- `PyYAML is not installed` — use the project virtualenv (`.venv/bin/python`), not system python.

**When it should run.** On every CI run, and on the console's scheduled sweep. It is pure CPU over
tracked files (about 1,200 files, under a second), so there is no reason to run it rarely.

**Adding a new retired name.** Add a `terms:` entry to `ops/config/retired_terms.yaml` with the
name and one sentence saying why it must not come back. Run the check, and allow-list the history
it finds. No code change.
