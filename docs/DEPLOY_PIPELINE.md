# How code reaches production

Every deployable part of this system ships by itself when `main` goes green. No one types
`fly deploy`. This page says which parts, by what route, and which machine refuses a change that
would break the arrangement.

Founder directive, 2026-08-19: "the ops console needs autodeploy on main passing, same with other
parts of system / all parts of system need to work this way. document it."

## The route

```
PR opened  ->  CI runs  ->  CI green
                              |
                              v
                 .github/workflows/automerge.yml
                   squash-merges the PR
                   dispatches CI on main
                   dispatches every deploy workflow whose watched paths the merge touched
                              |
              +---------------+----------------+
              v               v                v
      deploy-engine.yml  deploy-api.yml   deploy-web.yml
      prospector-engine  prospector-      prospector-
      (engine + ops      store-api        store-web
       console)
```

## What ships where

| Part | Fly app | Deploy workflow | Watched paths |
| --- | --- | --- | --- |
| Engine (scheduler, consumer, watchdog) | `prospector-engine` | `deploy-engine.yml` | `prospector/**`, `scripts/**`, `deploy/engine/**`, `requirements.txt`, `config.yaml` |
| Ops console | `prospector-engine` | `deploy-engine.yml` | `store_platform/src/Ops.Console/**` |
| Store API | `prospector-store-api` | `deploy-api.yml` | `store_platform/src/Store.Api/**`, `store_platform/src/Store.Catalog/**` |
| Storefront | `prospector-store-web` | `deploy-web.yml` | `store_platform/src/Store.Web/**` |

The ops console has no deploy of its own. It is built into the engine image
(`deploy/engine/Dockerfile` copies both), so shipping the console means shipping the engine, and
one restart covers both.

## Why a merge is not enough on its own

A push made with the default `GITHUB_TOKEN` starts no workflow runs. GitHub documents two
exceptions: `workflow_dispatch` and `repository_dispatch`. So `automerge.yml` merges the PR and
then explicitly dispatches what the merge push could not start.

That is also how this broke. Until 2026-08-19 automerge dispatched exactly one deploy, the
engine's. Merges that changed the API or the storefront went green, landed on `main`, and never
deployed. `deploy-api.yml` last ran at 05:01Z on 2026-08-18 while #358 and #342 changed
`Store.Api` and merged that evening. `deploy-web.yml` last ran from a push at 13:33Z on 2026-08-18
while #349, #363 and #365 changed `Store.Web` after it. Nothing was red. The symptom of a missing
dispatch is a run that does not happen, and nothing looks at those.

Record: `incidents/INC-2026-08-19-automerge-shipped-only-the-engine.json`.

## The machine that keeps this true

`tests/unit/test_every_deploy_ships_on_green_main.py` compares `automerge.yml`'s dispatch list
against each deploy workflow's own `on.push.paths`. It fails when:

- a `deploy-*.yml` exists that automerge does not dispatch (so a new deployable part cannot be
  added half-wired),
- the path lists drift in either direction,
- a deploy workflow has no `workflow_dispatch` trigger, so automerge could not start it,
- a required dispatch input is not supplied, or automerge sends one the workflow does not declare,
- automerge stops being gated on a **successful** CI run.

Adding a new deployable component therefore means three edits, and the suite names the two you
forgot: the workflow, the entry in automerge's `DEPLOYS`, and a row in the table above.

## What this does not cover

- **A direct push to `main`.** Each deploy workflow also has a `push: branches: [main]` trigger
  with the same path filter. That path does not wait for CI, because a push trigger fires at the
  same time CI does. It is kept as the fallback for when automerge is off, and it is the only
  route here that can ship un-graded code. Merge through a PR.
- **Proving the deploy landed.** `deploy-engine.yml` ends with three requests against the running
  console and fails if the old image is still answering. The other two do not have an equivalent
  yet.
- **The live checkout on the laptop.** `prospector-live` is rolled forward by
  `scripts/live_checkout.py --update`, not by CI. It is a standby, not the running engine.

## Checking it by hand

The live answer is a command, never this page:

```bash
gh run list --workflow deploy-engine.yml --limit 5
gh run list --workflow deploy-api.yml --limit 5
gh run list --workflow deploy-web.yml --limit 5
.venv/bin/python -m pytest tests/unit/test_every_deploy_ships_on_green_main.py -q
```
