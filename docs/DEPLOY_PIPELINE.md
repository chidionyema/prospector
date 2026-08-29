# How code reaches production

Every deployable part of this system ships by itself when `main` goes green. No one types
`fly deploy`. This page says which parts, by what route, and which machine refuses a change that
would break the arrangement.

Founder directive, 2026-08-19: "the ops console needs autodeploy on main passing, same with other
parts of system / all parts of system need to work this way. document it."

## The route

```
PR opened  ->  CI runs  ->  CI green  ->  the AUTHOR merges it
                                              |
                                  the merge is a push to main
                                              |
              +-------------------------------+----------------+
              v               v                                v
      deploy-engine.yml  deploy-api.yml                  deploy-web.yml
      prospector-engine  prospector-                     prospector-
      (engine + ops      store-api                       store-web
       console)

      each one triggered by its OWN `on: push: {branches: [main], paths: [...]}`
```

Changed 2026-08-20. Until then a workflow called automerge.yml did the merging and then dispatched
each deploy by hand. It was deleted on founder decision -- *"no autonerge goee autodeploy stays"* --
because the `pulls.updateBranch` call it made to keep branches fresh pushed a merge commit onto
every open pull request whenever main moved, which moved fifteen heads out of the batch branches
cut to close them and jammed the board for thirty hours.

Deleting it did not break the deploys, and the reason is the next section.

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

## Why a robot merge was not enough on its own

A push made with the default `GITHUB_TOKEN` starts no workflow runs. GitHub documents two
exceptions: `workflow_dispatch` and `repository_dispatch`. A robot merge is such a push, so the
automerge workflow had to dispatch by hand everything its own merge could not start.

**A human merge is not.** `gh pr merge` pushes as you, so the merge commit starts the deploy
workflows the ordinary way, off the `push:` triggers they already carried. That is why the deploys
survived automerge's deletion untouched.

One push in this estate is still a `GITHUB_TOKEN` push: the merge that
`.github/workflows/merge-when-green.yml` makes when a pull request goes green. It therefore
dispatches the deploys itself with `gh workflow run` -- otherwise a merge it performed would ship
nothing, which is the failure that left production on old code before.

That map is the thing that broke before. Until 2026-08-19 the dispatch list covered exactly one
deploy, the engine's. Merges that changed the API or the storefront went green, landed on `main`,
and never deployed. `deploy-api.yml` last ran at 05:01Z on 2026-08-18 while #358 and #342 changed
`Store.Api` and merged that evening. `deploy-web.yml` last ran from a push at 13:33Z on 2026-08-18
while #349, #363 and #365 changed `Store.Web` after it. Nothing was red. The symptom of a missing
dispatch is a run that does not happen, and nothing looks at those.

Record: `incidents/INC-2026-08-19-automerge-shipped-only-the-engine.json`.

## The machine that keeps this true

`test_every_deploy_ships_on_green_main.py (deleted 2026-08-26, crew#203)` compares the admission guard's dispatch list
against each deploy workflow's own `on.push.paths`. It fails when:

- a `deploy-*.yml` has no `push:` trigger at all, or fires on a branch other than `main`, or
  watches no paths (the primary route, gone or pointed at the wrong branch),
- a `deploy-*.yml` exists that the admission guard does not dispatch (so a new deployable part
  cannot be added half-wired, and a revert would leave it in production),
- the path lists drift in either direction,
- a deploy workflow has no `workflow_dispatch` trigger, so the guard could not start it,
- a required dispatch input is not supplied, or the guard sends one the workflow does not declare,
- the admission guard stops watching pushes to `main`, or stops re-deploying after a revert.

Adding a new deployable component therefore means four edits, and the suite names the ones you
forgot: the workflow (with its own `push:` trigger), its entry in the admission guard's `DEPLOY`
map, its entry in that guard's `INPUTS` map, and a row in the table above.

## Where the jobs run

Three labels, and they are not three pools. Every runner carries `self-hosted`, so a job that
asks for `self-hosted` can land on any machine that is online.

| Repo variable | Value | Which machines that reaches |
| --- | --- | --- |
| `CI_RUNS_ON` | `self-hosted` | every online runner |
| `CI_LIGHT_RUNS_ON` | `self-hosted` | every online runner |
| `CI_HEAVY_RUNS_ON` | `heavy` | the two Linux containers on Fly |

The live list is a command:

```bash
gh api /repos/chidionyema/prospector/actions/runners \
  --jq '.runners[] | "\(.name)\t\(.os)\t\(.status)\t\([.labels[].name]|join(","))"'
```

**The pool is not homogeneous, and that is the trap.** On 2026-08-19 the three macOS runners
`mumchimp-mac`, `mumchimp-mac-2` and `mumchimp-mac-3` were stopped at the founder's instruction,
which left `heavy` meaning "a Linux container" and `self-hosted` meaning "a Linux container or
`mumchimp-mac-4`". A step that works on one operating system and not the other now decides its own
outcome by which machine happened to be free.

That is not hypothetical. `actions/setup-dotnet` installs to `/usr/share/dotnet` on Linux, which
our containers cannot create, and `deploy-api.yml` could not run at all until it was told to
install under `$HOME` instead
(`docs/incidents/INC-2026-08-19-deploy-api-could-not-install-dotnet.json`).
`tests/unit/test_dotnet_installs_where_it_can_write.py` refuses the next instance.

Write every job so it does not care which of the six it gets. Do not install into a system
directory, and do not assume a tool the image happens to carry.

To bring a stopped Mac runner back:

```bash
launchctl enable gui/501/actions.runner.chidionyema-prospector.mumchimp-mac
(cd ~/actions-runner && ./svc.sh start)
```

## What this does not cover

- **CI finishing before the deploy does.** The `push: branches: [main]` trigger fires at the same
  moment CI on main does, not after it, so a deploy can be in flight while main is still being
  graded. Nothing here waits. This is the accepted cost of the 2026-08-20 change, and the
  compensating control is no longer a revert robot. Ruleset `strict` (id 20109556, active on
  `~DEFAULT_BRANCH`, no bypass actors) requires `guard`, `python`, `dotnet`, `nextjs` and `ci-ok`
  to pass before anything reaches main, so a merge with no green run at its head cannot land and
  there is nothing to take back out. Merge through a PR whose CI is already green and the window
  is empty.
- **A direct push to `main`.** Same trigger, same lack of a wait, and no pull request was ever
  graded. `scripts/guard_main_push.py` is the local pre-push hook that refuses it; ruleset `strict`
  is the server-side half, because no local hook can see a merge clicked in the web UI. Its
  `pull_request` rule means a direct push to main is refused by GitHub outright.
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
.venv/bin/python -m pytest test_every_deploy_ships_on_green_main.py (deleted 2026-08-26, crew#203) -q
```
