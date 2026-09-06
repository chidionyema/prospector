# Onboarding — the vendor ratchet

## What it is for

Leaving a hosting provider is not one decision, it is several hundred small ones spread across
workflows, scripts, config, tests and Dockerfiles. The measurement on 2026-08-24 was 586 Fly.io
references in 130 executable files here.

That set cannot be deleted in a single change. The live shop takes card payments through Fly right
now, and the deploy path that keeps it running is inside the set. Delete it first and the thing
being rescued is what breaks.

The ratchet makes the removal safe by making it one-way. Every change is measured against a
committed baseline. A change that removes references passes and lowers the baseline. A change that
adds one fails. Nobody has to hold the whole migration in their head, no single commit is
dangerous, and the number reaching zero is the definition of done rather than someone's opinion
that it looks finished.

## What it costs

A few seconds in CI. It reads tracked text files and counts regex matches; there is no network
call and no service behind it.

## What it watches or changes

It changes nothing. It reads `git ls-files`, skips documentation, specs and incident records, and
counts matches per file.

Documentation is excluded deliberately. A doc explaining why the estate left Fly is the opposite
of a dependency, and a counter that graded it would push the next agent to delete the history that
explains the migration in order to make a number go down.

## Where it lives

- `scripts/vendor_ratchet.py` — the whole thing, including the vendor table.
- `ops/config/vendor_ratchet.json` — the committed baseline, machine-written. Do not edit it by
  hand; `--update` writes it.
- `.github/workflows/ci.yml`, in the `guard` job, step "No new dependency on a vendor we are
  leaving".

Adding a second vendor is a new entry in the `VENDORS` table: a pattern that finds a call-site and
a pattern for the paths that do not count. It was written that way on purpose, because the next
exit should reuse this rather than produce a second copy of it.

## How to turn it off

Delete the step from `.github/workflows/ci.yml`:

```
      - name: No new dependency on a vendor we are leaving
        run: python3 scripts/vendor_ratchet.py --check
```

For one unavoidable change, do not turn it off. Say in the commit message why the reference is
necessary and raise the baseline:

```
.venv/bin/python scripts/vendor_ratchet.py --update --vendor fly
```

That leaves the decision in the history where the next person can find it, which switching the
gate off does not.

## How to turn it back on

Restore the step. The baseline is already committed, so nothing else is needed.

## What goes wrong

**It fails and you did not add anything.** Check whether you moved or copied a file. The counter
grades occurrences, not intent, so copying an existing Fly script to a new name doubles its
references and reads as growth. That is usually correct behaviour: two copies of a dependency are
worse than one.

**It fails on a merge.** Your branch's baseline is older than main's. Merge main in first, per
LAW 7, then rerun. Merging main is the fix, never `--update`, because `--update` on a stale branch
writes a baseline that quietly re-admits everything main had already removed.

**The count is zero and Fly still runs.** The ratchet grades this repository. Fly apps, Fly
secrets and DNS records live outside it, and a count of zero here means the code no longer needs
Fly, not that the account is closed.
