# The engine must be able to leave any platform the same day it arrives

Founder directive, 2026-08-18: *"we cant be tied down and moving from fly needs to be seamless and
pre-planned"*, alongside *"nothing business critical can run off this laptop"*.

Both at once. We go to Fly now. Leaving Fly is a pre-built, tested path, not a future project.

## The contract

There is **one artifact**: the container image built from `deploy/engine/Dockerfile`. It contains
the scheduler, the consumer, the watchdog, the backup jobs and both admin dashboards.

A platform has to give the engine exactly six things. Nothing else.

| # | What | How the engine sees it |
|---|---|---|
| 1 | Run one container, and only one | the platform's own single-instance setting |
| 2 | A writable directory that survives a restart | mounted at `/data` |
| 3 | Environment variables | injected at start, never baked into the image |
| 4 | Outbound HTTPS | normal internet |
| 5 | A way to run a command inside the container | used by the cutover and by `verify` |
| 6 | A private way to reach two ports | 8601 and 8611, private network only, no public IP |

That is the whole list. There is no Fly API call anywhere in the engine's code. `fly.toml` is
configuration for the adapter, not for the application.

**The single-container rule is a money fence, not a preference.** Two engines running at once
keep two spend ledgers and can spend twice the $100 daily cap (EDGE-1 in
`docs/ENGINE_MIGRATION_PROGRAM.md`). Any platform that cannot promise one instance is not a
candidate.

## The adapters

`deploy/targets/<name>.sh` implements eight shell functions. Each is a handful of lines.

```
t_preflight            the platform CLI is installed and logged in
t_provision            the app and the persistent volume exist
t_secrets FILE         push a KEY=VALUE file as the container's environment
t_release              build and deploy the image
t_start / t_stop       run exactly one container, or none
t_exec CMD...          run a command inside the running container
t_put LOCAL REMOTE     copy one file from here into the container's volume
t_logs                 stream the container's logs
```

Shipped today:

- `deploy/targets/fly.sh` — Fly.io. Where the engine runs from tonight.
- `deploy/targets/sshdocker.sh` — any Linux box with Docker and an SSH login. This is the escape
  hatch, and it exists **now**, not later. Hetzner, a Mac mini in an office, an EC2 instance and a
  Raspberry Pi are all the same target.

Writing a third adapter is the whole cost of changing platform.

## Leaving a platform

`deploy/cutover.sh` does not know where it is moving from or to. Both sides are adapters.

```bash
# what we run tonight: this laptop -> Fly
deploy/cutover.sh --from laptop --to fly

# what leaving Fly looks like, whenever we want it
deploy/cutover.sh --from fly --to sshdocker

# and it is reversible, which is the same command with the ends swapped
deploy/cutover.sh --from fly --to laptop
```

The state itself is a plain `tar.gz` with a sha256 manifest inside it
(`scripts/store_migrate.py`). It has no platform in it at all. The same file unpacks on a Mac, on
Fly and on a rented Linux box, and `store_migrate.py verify` proves the copy is complete on
whichever end it lands.

## The four things that would tie us down, and what we did instead

| Lock-in we refused | What we did |
|---|---|
| Fly Postgres / Upstash / any managed database | SQLite and append-only JSONL on the mounted volume. The data is files. |
| Fly Machines API called from application code | The engine never calls a platform API. Only the adapter does. |
| A public hostname baked into the engine | Both dashboards bind to loopback. Access is `fly proxy` here, an SSH tunnel there. |
| Secrets held only in the platform's secret store | `.env` on this laptop stays the source of truth, encrypted in the backup. `t_secrets` pushes it. Any platform can be filled from it in one command. |

## What is deliberately still Fly-shaped

`api.mumchimp.com` and `mumchimp.com` already run on Fly and are **not** part of this migration.
They are a separate app with its own deploy path, and moving them is a different job.
