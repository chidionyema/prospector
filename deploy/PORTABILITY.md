# The engine must be able to leave any platform the same day it arrives

Founder directive, 2026-08-18: *"we cant be tied down and moving from fly needs to be seamless and
pre-planned"*, alongside *"nothing business critical can run off this laptop"*.

Both at once. We go to Fly now. Leaving Fly is a pre-built, tested path, not a future project.

**Siblings.** [`docs/ESTATE_MAP.md`](../docs/ESTATE_MAP.md) maps every component this has to
move. [`docs/personas/ops.md`](../docs/personas/ops.md) and
[`docs/personas/sre-on-call.md`](../docs/personas/sre-on-call.md) say who runs the move and what
they watch while it runs. [`docs/personas/architect.md`](../docs/personas/architect.md) carries
the reasoning for the adapter shape below.

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

`deploy/targets/<name>.sh` implements twelve shell functions, on the eleven lines below —
`t_start` and `t_stop` share a line because they are one decision. Each is a handful of lines.

```
t_name                 what to call this platform in the log
t_preflight            the platform CLI is installed and logged in, AND the local tools exist
t_provision            the app and the persistent volume exist
t_secrets FILE         push a KEY=VALUE file as the container's environment
t_release              build and deploy the image
t_start / t_stop       run exactly one container, or none
t_exec CMD...          run a command inside the running container
t_put LOCAL REMOTE     copy one file from here into the container's volume
t_pack OUT.tar.gz      pack this platform's store, for when it is the SOURCE of a move
t_logs                 stream the container's logs
t_health               is this platform actually carrying the load right now?
```

Three of those carry a rule that cost a cutover attempt each, so they are worth stating
plainly rather than leaving to the reader:

- **`t_start` means started, not created.** `fly scale count 1` returns as soon as the machine
  exists. The next thing the cutover does is `fly ssh`, which then fails with "no started VMs" —
  a message that reads like a broken image. An adapter's `t_start` must not return until the
  container is up.
- **`t_put` must prove the bytes landed.** `fly ssh sftp shell` exits 0 whether or not the file
  transferred. An adapter that trusts the exit status will happily verify whatever was on the
  volume from last time.
- **`t_preflight` checks the LOCAL side too.** Everything after phase 4 runs with the engine
  stopped and customers waiting. A missing script on the operator's machine must fail before that
  window opens, not inside it.

Shipped today:

- `deploy/targets/fly.sh` — Fly.io. Where the engine runs from tonight.
- `deploy/targets/laptop.sh` — the founder's Mac, running launchd rather than Docker. It is an
  adapter like any other, which is what makes the rollback the same command with the ends
  swapped, and what keeps "come back to the laptop" a tested path.
- `deploy/targets/sshdocker.sh` — any Linux box with Docker and an SSH login. This is the escape
  hatch, and it exists **now**, not later. Hetzner, a Mac mini in an office, an EC2 instance and a
  Raspberry Pi are all the same target.
- `deploy/targets/k8s.sh` — Kubernetes and its lighter versions: k3s, k0s, MicroK8s, kind, EKS,
  GKE. Written as an adapter rather than a substrate, because `docs/STACK_AUDIT.md` §5 ruled that
  the contract on this page is what we keep. Choosing Kubernetes later costs one environment
  variable, not a migration.

  It carries one rule the others do not need. **A Deployment defaults to
  `strategy: RollingUpdate`, which starts the replacement pod before terminating the old one** —
  so the default setting of the default workload type breaks rule 1 above on every release: two
  engines, two spend ledgers, twice the daily cap, for as long as the handover takes. `Recreate`
  is what holds it, and it is also the only strategy that works against the ReadWriteOnce volume
  every default StorageClass hands out. Under RollingUpdate the new pod sits Pending on
  "Multi-Attach error for volume" until the rollout times out, which reads like a broken image.
  `tests/unit/test_every_deploy_target_implements_the_contract.py` fails if either goes missing.

Writing a fourth adapter is the whole cost of changing platform. It is now four files of about
ninety lines each, and `tests/unit/test_every_deploy_target_implements_the_contract.py` grades
every one of them against the verb list above — including the fifth, before it is ever used in
anger.

## Leaving a platform

`deploy/cutover.sh` does not know where it is moving from or to. Both sides are adapters.

```bash
# what we run tonight: this laptop -> Fly
deploy/cutover.sh --from laptop --to fly

# what leaving Fly looks like, whenever we want it
deploy/cutover.sh --from fly --to sshdocker

# and it is reversible, which is the same command with the ends swapped
deploy/cutover.sh --from fly --to laptop

# onto a cluster, whether that is k3s on one box or a managed one
PROSPECTOR_K8S_IMAGE=ghcr.io/you/prospector-engine:2026-08-20 \
  deploy/cutover.sh --from fly --to k8s
```

The state itself is a plain `tar.gz` with a sha256 manifest inside it
(`scripts/store_migrate.py`). It has no platform in it at all. The same file unpacks on a Mac, on
Fly and on a rented Linux box, and `store_migrate.py verify` proves the copy is complete on
whichever end it lands.

## The four things that would tie us down, and what we did instead

| Lock-in we refused | What we did |
|---|---|
| Fly Postgres / Upstash / any **managed** database | The engine's data is files: SQLite and append-only JSONL on the mounted volume. The **storefront** moves to Postgres (founder ruling 2026-08-21, `docs/decisions/0003-migration-and-dr-rulings.md` D6) — **self-hosted, never managed**, so it still travels with the cutover. |
| Fly Machines API called from application code | The engine never calls a platform API. Only the adapter does. |
| A public hostname baked into the engine | Both dashboards bind to loopback. Access is `fly proxy` here, an SSH tunnel there. |
| Secrets held only in the platform's secret store | `.env` on this laptop stays the source of truth, encrypted in the backup. `t_secrets` pushes it. Any platform can be filled from it in one command. |

## What is deliberately still Fly-shaped

`api.mumchimp.com` and `mumchimp.com` already run on Fly and are **not** part of this migration.
They are a separate app with its own deploy path, and moving them is a different job.
