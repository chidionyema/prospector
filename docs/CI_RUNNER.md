# Where CI runs

CI runs on our own Mac, not on GitHub's runners. This file says why, how to move it back, and how
to fix it when it stops.

## The live answer is a command, not this file

```bash
gh variable get CI_RUNS_ON                                   # self-hosted => our Mac; unset => GitHub
gh api repos/chidionyema/prospector/actions/runners \
  -q '.runners[] | "\(.name) \(.status) busy=\(.busy)"'      # online => it can take jobs
```

Anything below that disagrees with those two commands is out of date. Fix this file.

## Why

On 2026-08-16 GitHub stopped starting jobs. Every job on every open PR came back `failure` with
zero steps and no logs. `gh run view --log-failed` returned nothing, which reads like a passing
run rather than a refused one. The reason is only visible on the check-run annotation:

```bash
gh api repos/:owner/:repo/check-runs/<job_id>/annotations
# "The job was not started because recent account payments have failed or your
#  spending limit needs to be increased."
```

Four PRs went red at once for a reason that had nothing to do with their code.

Hosted runner minutes are metered and billed. Self-hosted runner minutes are not metered at all,
including on a private repo. So our own machine is the free path, and we took it.

## How it is wired

Every job in every workflow reads a repo variable:

```yaml
runs-on: ${{ vars.CI_RUNS_ON || 'ubuntu-latest' }}
```

Set the variable and all jobs move to our Mac. Unset it and they go straight back to GitHub. That
is one command, no commit and no review:

```bash
gh variable set CI_RUNS_ON --body self-hosted   # our Mac
gh variable unset CI_RUNS_ON                    # back to GitHub's hosted runners
```

Four workflows carry it: `ci.yml` (5 jobs), `deploy-web.yml` (2), `deploy-api.yml` (2) and
`e2e-live-smoke.yml` (1). The deploys are included on purpose. Leaving them on the metered runners
would mean CI passes and nothing can ship, which is the same outage wearing a different hat.

No job needed porting. None of them uses `apt-get`, `sudo`, `docker` or a service container, and
`checkout`, `setup-python`, `setup-uv`, `setup-node`, `setup-dotnet` and `cache` all support macOS.

## The runners

Four of them, at `~/actions-runner` through `~/actions-runner-4`, registered as `mumchimp-mac`,
`mumchimp-mac-2`, `mumchimp-mac-3` and `mumchimp-mac-4` with labels `self-hosted,macOS,X64`,
each running under launchd as `actions.runner.chidionyema-prospector.<name>`.

**One runner instance runs one job at a time.** A CI run is five jobs, so a single runner turns a
run into a five-deep queue, and five open PRs into a 25-deep one. Four instances is how five PRs
finish in an afternoon rather than overnight. Add a fifth the same way if the queue is still the
bottleneck.

```bash
gh api repos/chidionyema/prospector/actions/runners \
  -q '.runners[] | "\(.name) \(.status) busy=\(.busy)"'   # the live answer
cd ~/actions-runner && ./svc.sh status                     # is one service up
./svc.sh stop ; ./svc.sh start                             # restart it
tail -f ~/Library/Logs/actions.runner.chidionyema-prospector.mumchimp-mac/stdout.log
```

**Never copy `svc.sh` or `.service` from one runner directory into another.** They name the launchd
job they were generated for, so a copied `svc.sh` in `~/actions-runner-2` stops and starts
`mumchimp-mac`. `config.sh` regenerates both; copy the package without them and let it.

### The tool cache must be told where to live

`actions/setup-python` defaults its tool cache to `/Users/runner`, the path a GitHub-hosted macOS
runner uses. The login user here is `chidionyema`, so that directory cannot be created and every
`Set up Python` step dies:

```
mkdir: /Users/runner: Permission denied
The process '/usr/local/bin/bash' failed with exit code 1
```

The step fails, every step after it is skipped, and the job goes red with no test output at all. It
hits every PR equally, including docs-only ones, which is the tell that it is the environment and
not the code — on 2026-08-16 a PR that changed only this file failed its `python` job this way.

The fix is two exported variables, and **they go in `runsvc.sh`, not `.env`**:

```bash
# ~/actions-runner*/runsvc.sh, at the line that says
# "insert anything to setup env when running as a service"
export AGENT_TOOLSDIRECTORY=/Users/chidionyema/hostedtoolcache
export RUNNER_TOOL_CACHE=/Users/chidionyema/hostedtoolcache
```

`runsvc.sh` sources `.path` and nothing else. Putting the variables in `.env` looks right, changes
nothing, and costs a restart cycle to disprove. All four runners share one cache directory on
purpose: a Python or Node toolchain downloaded by any of them is reused by the rest.

`config.sh` regenerates `runsvc.sh`, so **re-registering a runner drops this patch.** Re-apply it
before `./svc.sh install`.

It is a **LaunchAgent**, so it runs as the logged-in user and stops when that user logs out. It
survives a reboot only once someone logs in. If CI must run on a machine nobody is logged into,
this has to move to a LaunchDaemon; that is not done.

### Registering it again from scratch

```bash
cd ~/actions-runner
./config.sh --url https://github.com/chidionyema/prospector \
  --token "$(gh api -X POST repos/chidionyema/prospector/actions/runners/registration-token -q .token)" \
  --name mumchimp-mac --labels self-hosted,macos,x64 \
  --work _work --unattended --replace --disableupdate < /dev/null
# re-apply the tool cache exports here: config.sh has just rewritten runsvc.sh
./svc.sh install && ./svc.sh start
```

For an additional runner, use a new directory and a new `--name` (`~/actions-runner-3`,
`mumchimp-mac-3`). Copy the package from an existing runner with `tar --exclude=.runner
--exclude=.credentials --exclude=.credentials_rsaparams --exclude=_work --exclude=_diag
--exclude=.service --exclude=svc.sh`, then configure it. Registration can take a couple of minutes;
if it times out half way it leaves a directory with no `.runner` file, and the cure is to delete
`.runner .credentials .credentials_rsaparams _work _diag .service svc.sh` and configure again.

Restarting a runner service makes the server hold its old session for a minute or two. The log says
`A session for this runner already exists` and the runner reads `offline` in the API. It retries
every 30 seconds and reconnects on its own. Restarting again does not speed it up.

**`< /dev/null` is the load-bearing part.** Without it `config.sh` hangs with no output and writes
a zero-byte diagnostic log, which looks exactly like a broken download. It is not: `Runner.Listener
configure` waits on stdin. With stdin closed the same command finishes in seconds and prints
`√ Connected to GitHub / √ Runner successfully added / √ Settings Saved`.

Two things that look like the cause and are not:

- **`svc.sh` missing from `~/actions-runner`.** `config.sh` generates it from
  `bin/darwin.svc.sh.template`. It is absent because configuration never finished, not because the
  download was short.
- **A quarantine flag or the wrong architecture.** Check them rather than assuming:
  `file ~/actions-runner/bin/Runner.Listener` against `uname -m`, and
  `~/actions-runner/bin/Runner.Listener --version` — it prints the version and exits 0 when the
  package is fine.

## What this does not fix

The billing problem is still there. This routes around it. Every hosted-runner minute is still
refused, so anything that must run on GitHub's machines cannot run at all until the account is
settled.

Merging with CI red is a separate decision and needs its own evidence. On 2026-08-16 #237 and #238
were merged on local full-suite runs (`4268 passed, 4 skipped` and `4245 passed, 2 skipped`, plus
`Passed! Failed: 0, Passed: 319` for the .NET suite) because the red was provably the billing
refusal. A local run is not the same as CI: it covers the `python` job, not `dotnet` or `nextjs`,
unless you run those too.
