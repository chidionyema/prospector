# The escape hatch drill

## What it is for

It answers one question, every Sunday, without anyone asking it: if we had to leave Fly, could
we get our data out and would it be intact. That is the only leverage a company with no funds
has over a platform. A provider who knows you cannot leave prices you accordingly.

The drill proves the half that can be proved for free. It packs the live store off the Fly VM,
pulls it down, restores it, verifies it against its manifest, and counts the rows against the
live ledger. It does not prove that a second machine is running the engine today, and it says so
in its own output, because renting a box for a rehearsal was refused and a drill that never runs
proves nothing.

## What it costs

Nothing in money. It runs on a GitHub Actions runner on the free tier, once a week, and it
rents nothing. It reads the store on the Fly VM and writes one temporary archive there, which it
deletes on every exit path including the failing ones. The bandwidth is one copy of the store
per week.

## What it watches and what it changes

It reads `/data/store` on the Fly engine VM and writes `/data/handover.tar.gz` plus its split
parts, then removes them. `store_migrate.py pack` only reads the store. The engine keeps
serving throughout — this is a rehearsal, not a cutover, and production is never taken down.

## Where it lives

- `.github/workflows/escape-hatch-drill.yml` — the schedule and the checks
- `deploy/targets/fly.sh`, the `t_pack` function — the transfer itself
- `scripts/store_migrate.py` — packs on the VM and verifies on the far side
- `tests/unit/test_fly_pack_refuses_a_truncated_export.py` — the regression test that keeps the
  transfer honest

## How to turn it off

```
gh workflow disable "Escape hatch drill" --repo chidionyema/prospector
```

## How to turn it back on

```
gh workflow enable "Escape hatch drill" --repo chidionyema/prospector
```

To run it now rather than waiting for Sunday:

```
gh workflow run "Escape hatch drill" --repo chidionyema/prospector
```

## What goes wrong

**The transfer arrives short and says it succeeded.** This is the one that has actually bitten.
On 2026-08-23, `fly ssh sftp get` delivered 12,779,520 of 112,474,776 bytes, printed
"12779520 bytes written", and exited 0. It is intermittent, not a size limit: two 100 MB control
transfers the same day were byte-exact. The drill's old check was a one-megabyte floor, which an
11% payload passes. The transfer is now split into parts, every part is checksummed on the VM
and re-fetched if it does not match, and a transfer that cannot be completed produces no file at
all rather than a partial one.

**The drill says it proved something it did not.** Until 2026-08-23 the "Say what was proved"
step ran under `if: always()`, so it printed its sentence even on runs where the pack had failed
and the verify had been skipped. It now runs only on success, and a separate step says
`NOT PROVED` on failure.

**The archive is complete-looking but short.** An export can open, match its manifest and re-hash
50 sampled rows while holding a fraction of the store, if it was packed from a partial volume.
The manifest cannot catch it, because its census is computed at pack time on the VM. The drill
now counts the live ledger separately and fails if the restored copy is more than 1% short, or
if it has more rows than the live store.

**The drill needs a running Fly machine.** It reads the store over `fly ssh`. If the engine
machine is stopped, the drill cannot run and the exit is undrilled until it can.
