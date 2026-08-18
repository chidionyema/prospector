# CI runners on Fly

CI ran on four self-hosted runners on the founder's MacBook. Measured 2026-08-18 with `top -l 2`,
second pass, on that machine:

```
other (Claude binaries)  109.5%
iCloud (bird/fileprov.)   78.1%
Terminal                  60.1%
sysmond                   39.6%
Chrome                    38.9%
WindowServer              23.9%
CI runners                19.0%
kernel                    10.0%
```

600% is the whole box (six physical cores). Load average was 317. CI had 19% of it, so a CI job
was not slow because CI is slow; it was queued behind everything else on a laptop. The visible
symptoms were a `Set up Node.js` step taking 380s on a runner that already had Node 22.23.2 in
`~/hostedtoolcache`, and a 30s vitest timeout blowing past 37s and turning `main` red.

This directory moves CI off that machine.

## What is here

| file | what it is |
|---|---|
| `Dockerfile` | Ubuntu 24.04, actions runner 2.336.0, Node 22, .NET 9 SDK, uv. The three toolchains `ci.yml` asks for, preinstalled. |
| `entrypoint.sh` | Registers the runner `--ephemeral`, runs one job, exits. Fly restarts it. |
| `fly.toml` | `shared-cpu-4x`, 8 GB, `lhr`, no health check. |

## Why ephemeral

A long-lived runner carries state between jobs. That is how a stale `node_modules` and a
half-written `.venv` survived to poison the next run on the Mac. A container that exits after one
job cannot do it. `--ephemeral` also makes GitHub deregister the runner, so a machine that dies
mid-job cannot leave a phantom `online` runner for the queue to wait on.

## Why no health check

A runner dials out to GitHub and listens on nothing. A health check against a port nobody serves
is how a working machine gets killed and restarted in a loop.

## Deploy

```bash
# durable: the container mints its own registration token at every boot
fly secrets set GH_RUNNER_PAT=<fine-grained PAT, administration:write on this repo> -a prospector-ci

fly deploy --remote-only -c ops/ci-runner/fly.toml -a prospector-ci
fly scale count 2 -a prospector-ci
```

For a trial without committing a PAT, hand in a registration token instead. It expires an hour
after minting, which is enough to prove the image and the job pickup:

```bash
gh api -X POST repos/chidionyema/prospector/actions/runners/registration-token --jq .token \
  | sed 's/^/RUNNER_TOKEN=/' | fly secrets import -a prospector-ci
```

`fly secrets import` reads `KEY=VALUE` from stdin. `xargs` and `fly secrets set` would put the
token in the argument list, where `ps` can read it.

## Cutting over

`ci.yml` reads `runs-on` from repo variables, so the switch is a variable change and no code
change (`ci.yml:18` says so). Today:

```
CI_RUNS_ON=self-hosted   CI_LIGHT_RUNS_ON=self-hosted   CI_HEAVY_RUNS_ON=heavy
```

The Fly runners carry `fly` as well as `self-hosted`, so point the variables at `fly` to move a
lane over and back to `self-hosted` to return it. Move one lane first, not all five.

## What has been proven, and where to check it

| claim | receipt |
|---|---|
| the runner registers and takes jobs | run 32137813966 — guard, changes, ci-ok, all success on `fly-8e4530a7712248` |
| the python suite passes on Linux | run 32138559273, job `python-on-fly` — every step success, golden-set gate included, 9m40s cold with the venv built from scratch |
| the toolchains are there | `shasum sha256sum git curl jq node dotnet uv perl tar` all resolve in the container; `nproc`=4, 8 GB RAM, 7.8 G disk |

`.github/workflows/fly-trial.yml` is what produced those runs. It copies each job out of `ci.yml`
by script and pins it to `runs-on: fly`. It is temporary and must be deleted before this branch
merges.

## The `self-hosted` label cannot be removed

GitHub applies `self-hosted` to every self-hosted runner and there is no way to drop it. A Fly
machine is therefore eligible for every job that says `runs-on: self-hosted` from the moment it
registers — which today is `changes`, `guard`, `ci-ok`, `nextjs` and `ops-console`. Standing up a
runner is not a no-op you can prepare quietly: it starts taking other people's pull requests
immediately. Prove a lane on Fly before a machine is online, not after.
