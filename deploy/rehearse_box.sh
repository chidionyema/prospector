#!/usr/bin/env bash
# A Linux box with Docker and an SSH login, made on this laptop in about a minute, for free.
#
#   deploy/rehearse_box.sh            # make the box, ship the shop to it, prove it serves
#   deploy/rehearse_box.sh up         # just make the box
#   deploy/rehearse_box.sh down       # destroy it
#   deploy/rehearse_box.sh status     # is it up, and what does it answer
#
# WHY THIS EXISTS. deploy/ship_shop.sh could be proved two ways and no further: --check, which
# reads local files, and --dry-run, which prints the remote commands without running any of them.
# Both passed. Neither says whether the stack COMES UP on a box that has never seen it, and that
# is the only question that matters on the day the founder pays for one. A migration first
# executed on a rented box with the live shop pointed at it is a migration nobody rehearsed.
#
# The box is `docker:28-dind`: a container running its own Docker daemon, with sshd on
# 127.0.0.1:2222. It is a real remote as far as ship_shop.sh is concerned -- its own daemon, its
# own empty image store, its own filesystem, reached only over ssh. Nothing is stubbed and
# ship_shop.sh is not modified for it: `docker save | ssh | docker load` genuinely transfers
# 180MB of images into a daemon that has none, and compose genuinely starts three containers.
#
# WHAT IT CANNOT PROVE, said plainly so nobody reads more into a green run than it carries:
# real network latency, a provider's boot time, a Let's Encrypt issuance (the drill runs the
# Caddyfile's documented local-drill mode, TLS off, because there is no public DNS pointing here),
# and live Stripe. Those need money and a real box. Everything before them is proved here.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DIR="$REPO/deploy/compose"

NAME="${REHEARSAL_BOX_NAME:-prospector-rehearsal-box}"
IMAGE="${REHEARSAL_BOX_IMAGE:-docker:28-dind}"
CACHE="${REHEARSAL_CACHE:-$HOME/.cache/prospector-rehearsal}"
KEY="$CACHE/id_ed25519"
STACK_ENV="$CACHE/stack.env"

# `up` records the ports it actually got, so `ship` and `status` in later shells reach the same
# box instead of the one the defaults describe.
BOX_ENV="$CACHE/box.env"
# shellcheck disable=SC1090
[ -f "$BOX_ENV" ] && . "$BOX_ENV"
SSH_PORT="${REHEARSAL_SSH_PORT:-${BOX_SSH_PORT:-2222}}"
HTTP_PORT="${REHEARSAL_HTTP_PORT:-${BOX_HTTP_PORT:-8080}}"

say()  { printf '\n== %s\n' "$*"; }
fail() { printf '!! %s\n' "$*" >&2; exit 1; }

# The key never leaves this laptop and the box is destroyed with it, so BatchMode plus a throwaway
# known_hosts is the honest setting here rather than a shortcut: there is no host identity to pin
# when the host is recreated from scratch every run.
ssh_opts() {
  printf -- '-p %s -i %s -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR' \
    "$SSH_PORT" "$KEY"
}
_bssh() { eval "ssh $(ssh_opts) -o BatchMode=yes root@127.0.0.1" '"$@"'; }

box_running() { [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null || echo false)" = true ]; }

# A laptop is not a rented box: something else is already on 8080 more often than not. A drill that
# stops because a port is busy is a drill that gets skipped, so walk up until one is free and say
# which one was taken. Measured 2026-08-24: the first run of this script died on exactly this.
free_port() {  # free_port <start>
  local p="$1"
  for _ in $(seq 1 40); do
    if ! nc -z 127.0.0.1 "$p" >/dev/null 2>&1; then echo "$p"; return 0; fi
    p=$((p + 1))
  done
  fail "no free port in ${1}..$((${1} + 40))"
}

# ---------------------------------------------------------------------------

cmd_up() {
  command -v docker >/dev/null || fail "docker is not installed on this laptop"
  docker info >/dev/null 2>&1 || fail "the local docker daemon is not running"

  say "box"
  mkdir -p "$CACHE"; chmod 700 "$CACHE"
  [ -f "$KEY" ] || ssh-keygen -t ed25519 -N '' -C 'prospector-rehearsal' -f "$KEY" >/dev/null
  printf '   ok  throwaway key at %s\n' "${KEY/#$HOME/\~}"

  docker rm -f "$NAME" >/dev/null 2>&1 || true
  local want_ssh="$SSH_PORT" want_http="$HTTP_PORT"
  SSH_PORT="$(free_port "$SSH_PORT")"
  HTTP_PORT="$(free_port "$HTTP_PORT")"
  [ "$SSH_PORT" = "$want_ssh" ]  || printf '   -   %s was busy, ssh is on %s\n' "$want_ssh" "$SSH_PORT"
  [ "$HTTP_PORT" = "$want_http" ] || printf '   -   %s was busy, the box'"'"'s port 80 is on %s\n' "$want_http" "$HTTP_PORT"
  printf 'BOX_SSH_PORT=%s\nBOX_HTTP_PORT=%s\n' "$SSH_PORT" "$HTTP_PORT" > "$BOX_ENV"

  # DOCKER_TLS_CERTDIR empty turns off the inner daemon's TLS. It listens on a unix socket inside
  # one container on a loopback-published port; adding certificates would prove nothing and would
  # be one more thing to go wrong in a drill whose whole point is that it always runs.
  docker run -d --privileged --name "$NAME" \
    -e DOCKER_TLS_CERTDIR= \
    -p "127.0.0.1:${SSH_PORT}:22" \
    -p "127.0.0.1:${HTTP_PORT}:80" \
    "$IMAGE" >/dev/null
  printf '   ok  %s started from %s\n' "$NAME" "$IMAGE"

  printf '   waiting for the box'"'"'s own docker daemon ... '
  for _ in $(seq 1 60); do
    if docker exec "$NAME" docker info >/dev/null 2>&1; then printf 'up\n'; break; fi
    sleep 1
  done
  docker exec "$NAME" docker info >/dev/null 2>&1 \
    || fail "the box's inner docker daemon never came up. docker logs $NAME"

  # openssh so ship_shop.sh can reach it the way it reaches a real box; curl because ship_shop.sh's
  # second proof angle runs curl ON the box, which is the path a buyer actually takes.
  docker exec "$NAME" sh -c 'apk add --no-cache openssh curl >/dev/null 2>&1' \
    || fail "could not install openssh in the box"
  docker exec "$NAME" sh -c 'ssh-keygen -A >/dev/null && mkdir -p /root/.ssh && chmod 700 /root/.ssh'
  docker exec -i "$NAME" sh -c 'cat > /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys' < "$KEY.pub"
  docker exec "$NAME" sh -c \
    'sed -i "s/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/" /etc/ssh/sshd_config; /usr/sbin/sshd'

  # Two angles on "the box is reachable" (LAW 15): sshd answers, and docker answers THROUGH it.
  _bssh 'true' >/dev/null 2>&1 || fail "sshd is up but the key was refused"
  local ver; ver="$(_bssh 'docker version --format "{{.Server.Version}}"' 2>/dev/null || true)"
  [ -n "$ver" ] || fail "ssh works but docker does not answer over it"
  printf '   ok  ssh root@127.0.0.1:%s -> docker %s, compose %s\n' \
    "$SSH_PORT" "$ver" "$(_bssh 'docker compose version --short' 2>/dev/null || echo '?')"
  printf '   ok  the box publishes port 80 on 127.0.0.1:%s\n' "$HTTP_PORT"
}

# The Caddyfile documents two modes and switches on EDGE_SITE/EDGE_API. Production uses bare
# hostnames so Caddy manages certificates; the local drill uses an explicit http:// scheme, which
# turns TLS off for that site block. The rehearsal is the second mode, and it is built by copying
# the real stack.env and replacing exactly those five lines -- so every other value, including the
# signing key, is the production one and a missing variable still fails here.
cmd_stack_env() {
  mkdir -p "$CACHE"; chmod 700 "$CACHE"
  : > "$STACK_ENV"; chmod 600 "$STACK_ENV"
  if [ -f "$COMPOSE_DIR/stack.env" ]; then
    grep -vE '^(SITE_DOMAIN|API_DOMAIN|SITE_SCHEME|EDGE_SITE|EDGE_API|EDGE_HTTP_PORT|EDGE_HTTPS_PORT)=' "$COMPOSE_DIR/stack.env" >> "$STACK_ENV"
  fi
  cat >> "$STACK_ENV" <<'EOF'
SITE_DOMAIN=localhost
API_DOMAIN=api.localhost
SITE_SCHEME=http
EDGE_SITE=http://localhost
EDGE_API=http://api.localhost
EDGE_HTTP_PORT=80
EDGE_HTTPS_PORT=443
EDGE_BIND=0.0.0.0
EOF
}

cmd_ship() {
  box_running || fail "no box. run: deploy/rehearse_box.sh up"
  cmd_stack_env
  say "shipping the shop to the rehearsal box with the REAL deploy/ship_shop.sh"
  SHOP_SSH_OPTS="$(ssh_opts)" SHOP_STACK_ENV="$STACK_ENV" \
    "$REPO/deploy/ship_shop.sh" root@127.0.0.1
}

# ship_shop.sh proves the shop from inside the box. This proves it from OUTSIDE, through the
# box's published port, which is the angle a customer occupies and the only one that can see a
# port the stack forgot to publish.
cmd_status() {
  if ! box_running; then echo "box: down"; return 1; fi
  say "the box, from outside it"
  printf '   containers on the box:\n'
  _bssh "cd /srv/mumchimp && docker compose -f compose/docker-compose.yml ps --format '      {{.Name}}\t{{.Status}}'" 2>/dev/null || printf '      (nothing shipped yet)\n'
  printf '   through 127.0.0.1:%s, the way a customer arrives:\n' "$HTTP_PORT"
  # This loop used to end in `|| printf "no answer"` and cmd_status returned 0 either way, so
  # `all` printed "the shop answered through the edge" over two HTTP 000s. Measured 2026-08-24.
  # A drill that cannot go red has not been run, it has been performed.
  local ok=0
  for pair in "localhost /" "api.localhost /catalog"; do
    set -- $pair
    local code
    code="$(curl -s -m 10 -o /dev/null -w '%{http_code}' -H "Host: $1" "http://127.0.0.1:${HTTP_PORT}$2" || echo 000)"
    printf '      HTTP %s   %s%s\n' "$code" "$1" "$2"
    [ "$code" = 200 ] || ok=1
  done
  return "$ok"
}

cmd_down() {
  docker rm -f "$NAME" >/dev/null 2>&1 && echo "box destroyed: $NAME" || echo "no box to destroy"
  rm -f "$STACK_ENV" "$BOX_ENV"
}

case "${1:-all}" in
  up)     cmd_up ;;
  ship)   cmd_ship ;;
  status) cmd_status ;;
  down)   cmd_down ;;
  all)    cmd_up; cmd_ship
          if cmd_status; then
            say "rehearsal complete"
            echo "   The same script that would run against a rented box ran against this one,"
            echo "   start to finish, and the shop answered 200 through the edge from outside."
            echo "   Destroy it with:"
            echo "       deploy/rehearse_box.sh down"
          else
            say "REHEARSAL FAILED"
            echo "   ship_shop.sh finished but the shop is not answering from outside the box."
            echo "   This is the drill doing its job: the same thing would have happened on a"
            echo "   rented box, with the live database on it. What to read:"
            echo "       docker exec $NAME docker compose -f /srv/mumchimp/compose/docker-compose.yml logs --tail 40 api"
            exit 1
          fi ;;
  -h|--help) sed -n '2,25p' "${BASH_SOURCE[0]}" ;;
  *) fail "unknown command: $1  (up | ship | status | down | all)" ;;
esac
