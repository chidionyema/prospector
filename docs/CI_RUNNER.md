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

## The runner

Installed at `~/actions-runner`, registered as `mumchimp-mac` with labels `self-hosted,macOS,X64`,
running under launchd as `actions.runner.chidionyema-prospector.mumchimp-mac`.

```bash
cd ~/actions-runner && ./svc.sh status     # is the service up
./svc.sh stop ; ./svc.sh start             # restart it
tail -f ~/Library/Logs/actions.runner.chidionyema-prospector.mumchimp-mac/stdout.log
```

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
./svc.sh install && ./svc.sh start
```

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
