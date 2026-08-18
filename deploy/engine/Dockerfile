# The engine, as a container.
#
# One image, five processes, one volume. That is not a style choice — the store is a
# single-writer SQLite database plus append-only JSONL ledgers, so every process that
# writes it must share one filesystem and one machine. Splitting the scheduler and the
# consumer across two Fly machines would fork the spend ledger, and the daily cap is
# read from that ledger.
#
# Nothing here is Fly-specific. The same image runs under `docker compose up` on any
# box (deploy/compose/docker-compose.yml), which is what makes the move repeatable to a
# third provider: the provider files carry addresses and secrets, never behaviour.

# ---------------------------------------------------------------------------
# Stage 1: build the ops console.
#
# It comes with the engine because it reads the store as a directory and shells out to
# the repo's Python (`package.json` sets PROSPECTOR_PYTHON from ../../../.venv). Left on
# the laptop it would keep rendering a store that had stopped changing and never say so —
# a dead dashboard that looks alive. Founder, 2026-08-18: "nothing business critical can
# run off this laptop".
# ---------------------------------------------------------------------------
FROM node:22-bookworm-slim AS console
WORKDIR /console
ENV NEXT_TELEMETRY_DISABLED=1
COPY store_platform/src/Ops.Console/package.json store_platform/src/Ops.Console/package-lock.json* ./
RUN npm ci --no-audit --no-fund 2>/dev/null || npm install --no-audit --no-fund
COPY store_platform/src/Ops.Console/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: the engine itself.
# ---------------------------------------------------------------------------
FROM python:3.14-slim-bookworm

# Node is here for two consumers, both of them optional at runtime and both of them
# real: the Claude Code CLI (`claude -p`), which is an npm package and is the fallback
# brain in moat_primary, and the Next.js ops console. Copying the binaries from the
# official image beats apt (bookworm ships Node 18) and beats a tarball fetch (no
# checksum to maintain).
COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-bookworm-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm

# git: several ops scripts shell out to it (scripts/ops_status.py grades against
#   origin/main, graphify reads HEAD). Without it they report a false failure rather
#   than skipping.
# ca-certificates, curl: outbound TLS to the retrieval providers and Stripe.
# tini: PID 1 that reaps children. supervisord's children are long-lived daemons that
#   fork; without a reaper a restarted scheduler leaves zombies until the machine is
#   recycled.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates curl tini \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so a code change does not re-resolve 29 packages.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
 && pip install --no-cache-dir supervisor

# The Claude Code CLI. Installed unconditionally because deciding at runtime whether
# the brain roster includes claude_cli would mean rebuilding the image to change a
# config line, and config lines are supposed to be the cheap knob.
RUN npm install -g @anthropic-ai/claude-code \
 && npm cache clean --force

COPY . /app

# The store lives on the mounted volume, NEVER inside the image. `config.store_root()`
# reads this and it is the only resolver — see the docstring at prospector/config.py:15
# for the 20 minutes in which four `__file__`-anchored constants split live state
# across two directories.
ENV PROSPECTOR_STORE_DIR=/data/store \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PROSPECTOR_CONFIG=/app/config.yaml

# The usage wall marker defaults to ~/.hermes/state/, which does not exist here and is
# not shared with anything. Keep it on the volume so a wall survives a restart: a marker
# in the container filesystem is forgotten on every deploy, and the marker's whole job is
# to stop a hot retry loop against a limit that is still in force.
ENV PROSPECTOR_USAGE_WALL_MARKER=/data/state/claude_usage_limit.json

# Where the `claude` CLI keeps its OAuth credentials. On the volume for the same reason:
# re-authenticating is browser-interactive and cannot be done from a deploy.
ENV CLAUDE_CONFIG_DIR=/data/state/claude

# The built ops console. `.next` and `node_modules` only — the sources already arrived
# with `COPY . /app`, and copying the build output back over them is what makes
# `next start` work without a build step at boot.
COPY --from=console /console/.next /app/store_platform/src/Ops.Console/.next
COPY --from=console /console/node_modules /app/store_platform/src/Ops.Console/node_modules

# The console shells out to Python to read the store. On the laptop that path is resolved
# from the repo's .venv; in the container there is no venv, so name the interpreter.
# PROSPECTOR_ROOT is the name the launchd plist used; keep it identical so the console's
# own code needs no change.
ENV PROSPECTOR_PYTHON=/usr/local/bin/python \
    PROSPECTOR_ROOT=/app

# flyctl, for ONE job: the offsite backup pulls the money database and the ASP.NET key ring
# off prospector-store-api with `fly ssh sftp` (ops/config/offsite_backup.yaml:35-63). That
# backup runs on the laptop today, and the laptop is being switched off. It needs
# FLY_API_TOKEN in the environment; without it the money-db source fails loudly, which is
# the right outcome — a silent gap is what this whole migration is trying to avoid.
RUN curl -sSfL https://fly.io/install.sh | sh
ENV FLYCTL_INSTALL=/root/.fly
ENV PATH=/root/.fly/bin:$PATH

COPY deploy/engine/supervisord.conf /etc/supervisord.conf
COPY deploy/engine/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY deploy/engine/periodic.sh /usr/local/bin/periodic.sh
COPY deploy/engine/receipt.sh /usr/local/bin/receipt.sh
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/periodic.sh /usr/local/bin/receipt.sh

# The commit this image was built from. `COPY . /app` does not bring .git across, so without
# this the running engine cannot say what code it is and neither can anyone else: measured
# 2026-08-18, `fly releases` showed v15 and nothing on this estate could map v15 to a commit.
# That is the failure scripts/live_checkout.py exists to prevent on the laptop, happening again
# on Fly. deploy/targets/fly.sh passes it; a build that does not gets "unknown", which the probe
# reports as a problem rather than hiding.
ARG GIT_SHA=unknown
RUN printf '%s\n' "$GIT_SHA" > /app/GIT_SHA
ENV PROSPECTOR_GIT_SHA=$GIT_SHA

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
CMD ["supervisor"]
