# A GitHub Actions self-hosted runner, as a container, on Linux.
#
# WHY THIS EXISTS
#
# The four runners that serve this repo are `mumchimp-mac`, `-2`, `-3` and `-4`, and all four
# are launchd jobs on the founder's laptop, sharing its 12 CPUs and 16 GB. Closing the lid
# stops CI for the whole repo. That is the same "business critical work on the laptop" problem
# the engine migration solves, and it gets the same answer: one container, no platform API
# inside it, moved by the adapters in deploy/targets/.
#
# WHAT THIS IS NOT
#
# It is not a move to GitHub-hosted runners. Founder, 2026-08-17: "we have hosted runner and
# github is billig us". Hosted minutes are metered and were cut off on 2026-08-16 when a
# payment failed; self-hosted minutes are not metered. `vars.CI_RUNS_ON` stays `self-hosted`,
# and these runners carry that label, so no workflow changes at all.
#
# WHY UBUNTU AND NOT macOS
#
# `.github/workflows/ci.yml:16-18` records that the jobs are OS-portable: no apt-get, no sudo,
# no docker, no service containers. Every toolchain arrives through an action that fetches its
# own copy — setup-node, setup-dotnet, setup-uv — and the python job deliberately uses
# `uv venv` rather than the system interpreter (ci.yml:190-208), precisely so it does not care
# what the box has installed. So this image installs no language runtimes. It installs what
# those actions need in order to unpack and run what they download.

FROM ubuntu:24.04

# Packages, and why each one is here. Nothing is here "just in case".
#   ca-certificates, curl  - every setup-* action downloads over https
#   git                    - actions/checkout
#   jq                     - the entrypoint parses the registration-token response
#   tar, unzip, zstd       - actions/cache writes .tzst; unzstd comes from zstd
#   libicu74               - the .NET runtime refuses to start without ICU, and the runner
#                            agent itself is .NET. This is the one dependency whose absence
#                            fails as "Couldn't find a valid ICU package" rather than as a
#                            missing command.
#   liblttng-ust1, libssl3 - the rest of the runner agent's .NET dependencies
#   sudo                   - some third-party actions call it; without it they fail late
#   locales, tzdata        - test output that compares formatted dates otherwise differs
#                            between this runner and the Macs
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl git jq tar unzip zstd sudo locales tzdata \
      libicu74 liblttng-ust1 libssl3 gnupg xz-utils \
    && locale-gen en_GB.UTF-8 \
    && rm -rf /var/lib/apt/lists/*

ENV LANG=en_GB.UTF-8 LC_ALL=en_GB.UTF-8 TZ=Europe/London
ENV DEBIAN_FRONTEND=noninteractive
# The runner refuses to start as root and says so plainly. This is not a hardening flourish.
RUN useradd -m -s /bin/bash runner && echo 'runner ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/runner

# Pinned. An unpinned runner tarball means a CI fleet that silently changes version between
# two machines started an hour apart, and the resulting "works on runner 3, fails on runner 1"
# is the most expensive kind of flake to chase.
ARG RUNNER_VERSION=2.328.0
ARG RUNNER_ARCH=x64

WORKDIR /home/runner/actions-runner
RUN curl -fsSL -o runner.tar.gz \
      "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-${RUNNER_ARCH}-${RUNNER_VERSION}.tar.gz" \
    && tar xzf runner.tar.gz && rm runner.tar.gz \
    && chown -R runner:runner /home/runner

# `./bin/installdependencies.sh` is NOT run, on purpose. Runner 2.328.0 ships a script that asks
# apt for `libicu72`, which does not exist on Ubuntu 24.04 - the build dies with
# "E: Unable to locate package libicu72", which reads like a broken base image rather than a
# runner script that has not caught up with the distro. The apt-get above already installs the
# 24.04 equivalents (libicu74, liblttng-ust1, libssl3), which is the whole list that script
# would have installed. Verified rather than assumed: `Runner.Listener` is the .NET binary the
# agent runs, so asking it for its version exercises the runtime, and a missing ICU package fails
# right here with "Couldn't find a valid ICU package" instead of at registration time on Fly.
# It is Runner.Listener and not `config.sh --version`, because the wrapper scripts refuse to run
# as root and exit 1 before reaching any .NET code - a check that proves nothing about ICU.
# The version probe above runs as root, and the only thing it creates is _diag/, owned by root.
# The chown two RUNs up has already happened by then, so `USER runner` gets a runner directory it
# cannot write its own log into. The container then crash-loops with
# "Access to the path '/home/runner/actions-runner/_diag/Runner_*.log' is denied" at config time,
# which reads like a bad PAT and is not. _diag is build junk here, so delete it and re-assert
# ownership rather than leaving a root-owned directory in the image.
RUN ./bin/Runner.Listener --version \
    && rm -rf /home/runner/actions-runner/_diag \
    && chown -R runner:runner /home/runner

COPY deploy/runner/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER runner
ENV RUNNER_ALLOW_RUNASROOT=0
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
