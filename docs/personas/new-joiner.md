# The platform for the new joiner

Day one. Read this, then one other document, then run one command. That is the whole of today.

## What this is, in five sentences

A business sells research packs about business ideas. An engine generates candidate ideas, checks each
against sources it fetches from the web, kills most of them with cited reasons, and publishes the
survivors. A storefront at `mumchimp.com` sells them. An ops console and a Telegram bot run the whole
thing. **Making packs can stop for a day and nobody notices; selling cannot stop for a minute** — that
sentence explains most of the design decisions you will meet.

## The one command

```bash
.venv/bin/python scripts/estate_map.py
```

It prints what is running, what a customer can reach, what still runs on the laptop, where the state
lives, and which secrets each app needs — names only, never values. It takes about 20 seconds and it
is the answer to "what is the state of things", which is a **command here, never a paragraph.**

Three states, and the third matters: `ok`, `FAIL`, and `?`. **`?` means "could not ask", and that is
not the same as fine.**

## The one document

[ESTATE_MAP.md](../ESTATE_MAP.md). How every part connects, where every byte of state lives, and §10,
which lists the probes that lie. Read §10 twice.

## Then your own seat

Pick the one that matches what you were hired for. Each is a detailed breakdown of the same platform
from that angle: [founder](founder.md), [analyst](analyst.md), [finance](finance.md), [ops](ops.md),
[developer](developer.md), [senior developer](senior-developer.md),
[principal developer](principal-developer.md), [architect](architect.md),
[ML engineer](machine-learning-engineer.md), [data engineer](data-engineer.md),
[content management](content-management.md), [QA](qa-test-engineer.md), [SRE](sre-on-call.md),
[security](security.md), [legal and privacy](legal-privacy.md),
[product](product-manager.md), [growth](growth-marketing.md), [support](support.md),
[buyer](buyer.md).

## The five rules that will confuse you if nobody says them out loud

**1. State is a probe, never a sentence.** A document once said a feature was live while the process
ran 32-hour-old code. So "is it done, is it deployed, is it working" is answered by running something,
and if a document disagrees with a probe, the probe is right and the document is a bug.

**2. Every claim ships with its proof.** A `file:line`, command output, or a runnable check, in the
same message. If you cannot prove it yet, the honest output is "I cannot prove this yet, here is how I
would verify it" — never a confident verdict. Comparisons count: "faster" and "better" need the
concrete scenario and the test that distinguishes them.

**3. Plain English.** Short sentences, conclusion first, no clever constructions, no dramatic reveals.
This applies to chat, commit messages, pull request bodies, code comments and documentation.

**4. Answer first.** Start with `DONE:`, `BLOCKED:` or `WORKING:` and one sentence. Evidence goes
below the fold.

**5. Never sit and watch a long command.** Anything over about 30 seconds runs in the background while
you do the next thing.

## Setting up

```bash
git worktree add --detach ../my-worktree main
./scripts/setup_worktree.sh ../my-worktree
```

**Always use the script.** A bare `git worktree add` produces a tree that looks complete and is not,
and each missing piece fails by accusing something else — a rejected symlink, a missing signing key, a
missing interpreter. `store/` and `storage/` are tracked runtime state that the test suite writes to,
so never stage every file in a worktree.

**One session, one worktree.** This checkout is shared, and sessions share one git index.

## Five things that are true here and unusual elsewhere

1. **Production does not run from this checkout.** It runs from a separate clone kept at
   `origin/main`. `scripts/live_checkout.py` tells you what production is actually executing.
2. **Test files are named as sentences.** `test_a_failed_call_is_not_an_empty_answer.py`. Reading
   `ls tests/unit/` is the fastest way to learn what has gone wrong here.
3. **`GET /health` does not exist** on the store API. The health check is `GET /catalog`.
4. **The engine runs on Fly, but the canonical data store is still on the laptop**, pinned by
   `PROSPECTOR_STORE_DIR`. That is deliberate and it is temporary.
5. **`cmd | tail` reports tail's exit status.** A failed build reads as success. This has caught
   everyone.

## Where to ask

The root `CLAUDE.md` is the operating contract for the whole estate; the project `CLAUDE.md` in the
repo root carries the rules for this codebase specifically. Both are terse on purpose — each line is
there because something went wrong once.
