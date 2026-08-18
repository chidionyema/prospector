# The platform for ops

Your job is to know the state and to change it without a terminal. The founder's standing rule is
that **everything that can change is changed by the operator, from the console** — not by editing a
file and redeploying.

## Where you work

- **The ops console**: `https://prospector-engine.fly.dev/`. A Next.js app served by the engine
  process itself. Screens: `/` (queue, pause and provider state), `/engine`, `/queue`, `/runs`,
  `/metrics`, `/spend`, `/money`, `/catalogue`, `/shelf`, `/tools`.
- **Hermes on Telegram**: the front door. The gateway is the door, the cockpit is behind it.
- **The command line**, when the console cannot answer.

**Check the badge in the header before you touch anything.** It reads
`prospector-engine · 80d34d · lhr` when the console is production, and `this laptop — NOT production`
in red anywhere else. A production console and a laptop dev server look identical and are one
bookmark apart, which is a real way to arm a pause on the wrong machine.

## The three questions, and the commands that answer them

```bash
.venv/bin/python scripts/estate_map.py            # everything: apps, URLs, laptop jobs, volumes
.venv/bin/python scripts/ops_status.py            # the ops programme's own grading
.venv/bin/python scripts/live_checkout.py         # which code production is actually running
```

`live_checkout.py` matters more than it looks. **Production does not run from the developer
checkout.** It runs from `/Users/chidionyema/Documents/code/prospector-live`, kept detached at
`origin/main`. On 2026-08-17 that distinction cost real time: the daemon was executing 17-hour-old
code from a branch a session had left behind, and the only way to see it was to run `lsof` on the
pid. `live_checkout.py --update` rolls production forward and restarts. It refuses to update a live
checkout with local code changes, on purpose — a fix reaches production through a pull request, not
through an edit on the box.

## The controls you have

**Stopping things.** Three levers, deliberately different:

| Lever | What it stops |
|---|---|
| `store/scheduler/PAUSE` | The **entire** tick: generation and the re-vet drain together |
| `store/scheduler/PAUSE_GENERATION` | Generation only. The drain keeps running |
| `schedule.backlog_cap` | Automatic. Above the cap, ticks drain only, then release themselves |

`PAUSE` is the liability rail, and it is total on purpose: a rail with exceptions is not a rail. The
half-stops exist because the drain is the only thing that pays the backlog down, and stopping the
treadmill also stopped the thing paying for it once already.

**Running tools.** The console can run any catalogued tool. The catalogue is a hand-kept table at
`prospector/ops/console_api.py:2206`, not a directory scan, because a scan can list a file but cannot
say whether it reaches off this machine. Each entry carries a risk level:

- `read` — writes nothing.
- `local` — writes only `store/`, and `prospector.ops.undo` rolls it back in full.
- `external` — reaches Stripe, the live shelf, R2 or public sources. A snapshot is still taken but
  **cannot undo the external half**, and the preview says so.
- `shell` — not a tool at all; the refusal names why.

Every action goes through a preview and a confirmation token. That, plus undo, is the fence — not
hiding the button. The founder's words: "we just need rollback to be safe not to hide actions".

A test refuses to let a tool be invisible: `tests/unit/test_console_tools_run.py` fails by name if a
file in `scripts/` or `tools/` is in neither the button list nor the named-exclusion list.

**Refused actions.** Some things the console will not do and tells you why.
`catalogue.set_price` is refused because a direct catalogue write would drift from Stripe. Run
`tools/set_live_pack_price.py` instead, which does both halves.

## What runs where

Six Fly apps: `prospector-engine`, `prospector-store-api`, `prospector-store-web`,
`prospector-searxng`, `prospector-hermes`, and `prospector-ci` (suspended — the runners have not
moved yet). Five `tie-*` apps belong to a separate older product and are kept on purpose.

On the laptop, as last probed: **9 of 18 declared launchd jobs have a pid, and 4 of 4 GitHub Actions
runners are online.** Run the probe for the current number.

launchd is macOS only. Since the engine moved into a container, the console shows
`not supervised by launchd on this machine` for the engine's own jobs. That is correct, not broken —
the Fly machine restarts the process, not a plist.

## Probes that lie, and how

This is the part of the job that catches people out.

| The probe | The lie |
|---|---|
| `GET /health` on the store API | **There is no such route.** The Fly health check is `GET /catalog`. A 404 at `/health` comes from a perfectly healthy machine |
| `DEPLOY_RC=0` plus HTTP 200 | Does not prove the deploy carries your change. Grep the built chunk |
| A deploy of `main` | Silently reverts a hand-deploy. One was live at 09:45 and gone by 10:12 |
| `fly auth whoami` | Passes on a dead token |
| macOS `ps` and `launchctl` probes | Report a false pass |
| `cmd 2>&1 \| tail` | Reports **tail's** exit status. A failed build reads as exit 0 |
| A green check on a pull request | Verify the run actually ran; `runner_name == ""` means it never did |
| "Could not ask" | **Is not "fine".** `estate_map.py` prints `?` for it, distinct from `ok` |

## Two things you personally have to do

1. **`~/.config/prospector/age-key.txt` is not backed up off this laptop.** Nothing automated will
   fix that.
2. **Never merge a pull request while a check is queued or in progress.**

## What to read next

- [sre-on-call.md](sre-on-call.md) — what to do when something is actually red.
- [ESTATE_MAP.md](../ESTATE_MAP.md) — §4 operating, §10 probes that lie.
- `docs/RUNBOOKS.md`, `docs/OPS_AUTOMATION_PRINCIPLES.md`, `docs/LAUNCH_OPS_PROGRAM.md`.
