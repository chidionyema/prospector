# A GitHub Actions runner that runs on Fly, so CI stops competing with the founder's laptop.
#
# Measured 2026-08-18 on the Mac that hosted all four runners: load average 317 on six physical
# cores, with CI accounting for 19% of 600% and the agent tooling for the rest. A CI job on that
# box is not slow because CI is slow; it is slow because it is queued behind everything else.
#
# The image preinstalls the three toolchains ci.yml asks for, so setup-node and setup-dotnet find
# what they need already present instead of downloading it per job:
#   Node 22    (ci.yml nextjs, ops-console)
#   .NET 9.0   (ci.yml DOTNET_VERSION)
#   uv         (ci.yml installs Python 3.14 through uv, which fetches its own interpreter)
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    RUNNER_ALLOW_RUNASROOT=0 \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_NOLOGO=1 \
    DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1

# libicu and libssl are dotnet's runtime dependencies; without them `dotnet` exits 132 with no
# message. git-lfs, jq and unzip are what actions/checkout and the workflow steps shell out to.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl git git-lfs jq unzip zip tar xz-utils sudo gnupg \
      build-essential libicu74 libssl3 zlib1g \
    && rm -rf /var/lib/apt/lists/*

# Node 22. NodeSource rather than apt's node, which is 18 on 24.04 and below the >=22 that
# store_platform/src/Store.Web/package.json declares in engines.node.
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# .NET 9 SDK via the install script. The apt feed lags and pins a patch we do not choose.
RUN curl -fsSL https://dot.net/v1/dotnet-install.sh -o /tmp/dotnet-install.sh \
    && bash /tmp/dotnet-install.sh --channel 9.0 --install-dir /usr/share/dotnet \
    && ln -s /usr/share/dotnet/dotnet /usr/local/bin/dotnet \
    && rm /tmp/dotnet-install.sh

# The runner refuses to execute as root, so it gets its own user. Passwordless sudo because
# actions/setup-* write outside $HOME.
RUN useradd -m -s /bin/bash runner \
    && echo "runner ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/runner

USER runner
WORKDIR /home/runner

ARG RUNNER_VERSION=2.336.0
RUN curl -fsSL -o actions-runner.tar.gz \
      "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz" \
    && tar xzf actions-runner.tar.gz \
    && rm actions-runner.tar.gz

# uv installs to ~/.local/bin. Preinstalled so `astral-sh/setup-uv` is a no-op rather than a
# download on every python job.
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/home/runner/.local/bin:${PATH}"

COPY --chown=runner:runner entrypoint.sh /home/runner/entrypoint.sh
ENTRYPOINT ["/home/runner/entrypoint.sh"]
