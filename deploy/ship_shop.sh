#!/usr/bin/env bash
# Put the SHOP on any Linux box with Docker and an SSH login. Hetzner, EC2, a Mac mini, a Pi.
#
#   deploy/ship_shop.sh --check                 # everything it can prove with no box at all
#   deploy/ship_shop.sh --dry-run root@1.2.3.4  # print every remote command, run none of them
#   deploy/ship_shop.sh root@1.2.3.4            # do it
#
# WHY THIS FILE EXISTS. deploy/cutover.sh moves the ENGINE between platforms and says so on its
# first line: "engine cutover". deploy/targets/sshdocker.sh runs ONE container, prospector-engine,
# and its health check looks for the engine's ledger. Neither of them has ever moved the shop.
#
# The shop is the half that takes card payments. On 2026-08-24 it had no cutover path of any kind,
# which is the real reason Fly.io was still load-bearing: not because anything technical was
# missing, but because nobody had written the twenty lines that put api + web + edge on a box.
#
# IT SHIPS THE SAME COMPOSE FILE THE DRILL RUNS. That is the whole design. deploy/compose/ is
# proven every time anyone brings the stack up locally, so production and the drill cannot drift
# into two different configurations that are each only half tested. The only thing that differs
# between them is deploy/compose/stack.env, which carries the hostnames and the TLS switch.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DIR="$REPO/deploy/compose"
REMOTE_DIR="${SHOP_REMOTE_DIR:-/srv/mumchimp}"

# The hostnames and the TLS switch. Overridable so the rehearsal box can run the SAME script
# against the SAME compose file with the Caddyfile's local-drill mode, instead of the rehearsal
# being a second code path that proves nothing about the real one.
STACK_ENV="${SHOP_STACK_ENV:-$COMPOSE_DIR/stack.env}"

DRY_RUN=0
CHECK_ONLY=0
HOST=""

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --check)   CHECK_ONLY=1 ;;
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}"; exit 0 ;;
    -*) echo "unknown flag: $1" >&2; exit 2 ;;
    *)  HOST="$1" ;;
  esac
  shift
done

say()  { printf '\n== %s\n' "$*"; }
fail() { printf '!! %s\n' "$*" >&2; exit 1; }

# Extra ssh options, word-split on purpose. A non-standard port, a jump host or a specific key are
# ordinary on a real estate, and a deploy script that cannot express them is one people work around
# by editing it. deploy/rehearse_box.sh sets this to reach the local rehearsal box.
# shellcheck disable=SC2206
SSH_OPTS=( ${SHOP_SSH_OPTS:-} )

# Every remote command goes through here, so --dry-run cannot miss one.
_ssh() {
  if [ "$DRY_RUN" = 1 ]; then printf '   [dry-run] ssh %s %s\n' "$HOST" "$*"; return 0; fi
  ssh -o BatchMode=yes -o ConnectTimeout=15 "${SSH_OPTS[@]}" "$HOST" "$@"
}
_push() {  # _push <local> <remote>
  if [ "$DRY_RUN" = 1 ]; then printf '   [dry-run] push %s -> %s\n' "${1#"$REPO"/}" "$2"; return 0; fi
  ssh -o BatchMode=yes "${SSH_OPTS[@]}" "$HOST" "cat > $2" < "$1"
}

# ---------------------------------------------------------------------------
# 1. What we can prove without a box. Runs on every invocation, including --check,
#    because a missing local file is a failure worth finding before a box is rented.
# ---------------------------------------------------------------------------
say "local preflight"

# A shop the public cannot reach on 80 is not shipped, and Caddy cannot answer an ACME
# challenge on any other port, so a certificate never issues either. deploy/compose/stack.env
# carried EDGE_HTTP_PORT=8080 from laptop use, measured 2026-08-24, and this script would
# happily have shipped that to a rented box.
EDGE_HTTP_PORT="$(grep -E '^EDGE_HTTP_PORT=' "$STACK_ENV" 2>/dev/null | cut -d= -f2 || echo 80)"
EDGE_HTTPS_PORT="$(grep -E '^EDGE_HTTPS_PORT=' "$STACK_ENV" 2>/dev/null | cut -d= -f2 || echo 443)"
: "${EDGE_HTTP_PORT:=80}" "${EDGE_HTTPS_PORT:=443}"
# The compose file publishes the edge on 127.0.0.1 unless EDGE_BIND says otherwise (a laptop
# is dev; only a public box may listen on every interface). A public box must say so.
EDGE_BIND="$(grep -E '^EDGE_BIND=' "$STACK_ENV" 2>/dev/null | cut -d= -f2 || true)"
if [ "${EDGE_BIND:-}" != "0.0.0.0" ]; then
  fail "$STACK_ENV does not set EDGE_BIND=0.0.0.0. The edge binds 127.0.0.1 by default, which no
   customer can reach. Add EDGE_BIND=0.0.0.0 to that file for a public box."
fi
if [ "$EDGE_HTTP_PORT" != 80 ] || [ "$EDGE_HTTPS_PORT" != 443 ]; then
  fail "$STACK_ENV publishes the edge on ${EDGE_HTTP_PORT}/${EDGE_HTTPS_PORT}. A public box must
   be 80/443: nothing else is reachable without a port in the URL, and Let's Encrypt answers
   its challenge on 80. Set EDGE_HTTP_PORT=80 and EDGE_HTTPS_PORT=443 in that file."
fi


for f in "$COMPOSE_DIR/docker-compose.yml" "$COMPOSE_DIR/Caddyfile" "$REPO/.env"; do
  [ -f "$f" ] || fail "missing: ${f#"$REPO"/}"
  printf '   ok  %s\n' "${f#"$REPO"/}"
done

# stack.env is gitignored and holds the hostnames. Without it the compose defaults apply, which
# are the production ones, so its absence is survivable -- but say so rather than silently
# shipping a config nobody chose.
if [ -f "$STACK_ENV" ]; then
  printf '   ok  %s\n' "${STACK_ENV#"$REPO"/}"
else
  printf '   -   deploy/compose/stack.env absent; compose defaults (built from ESTATE_ZONE) apply\n'
fi

# THE DATABASE IS THE BUSINESS. Everything else here is replaceable in ten minutes.
DB="$COMPOSE_DIR/data-api/store.db"
KEYS="$COMPOSE_DIR/data-api/keys"
[ -f "$DB" ] || fail "no store.db at deploy/compose/data-api/store.db -- nothing to ship"
DB_BYTES=$(wc -c < "$DB" | tr -d ' ')
printf '   ok  store.db  %s bytes\n' "$DB_BYTES"

# A truncated SQLite file copies without complaint and fails at the first checkout. Ask SQLite.
if command -v sqlite3 >/dev/null 2>&1; then
  # `|| true` is load-bearing. sqlite3 exits 26 on a file that is not a database, and under
  # `set -e` a failing command substitution in an assignment kills the script on that line --
  # before the message below ever runs. Measured 2026-08-24 against a deliberately corrupted
  # copy: it refused correctly with exit 26 and printed nothing at all, which tells whoever
  # meets it nothing about what is wrong or what to do. A guard's error message is the only
  # documentation anybody reads.
  INTEG=$(sqlite3 "$DB" 'PRAGMA integrity_check;' 2>&1 | head -1 || true)
  [ "$INTEG" = "ok" ] || fail "store.db is not a readable SQLite database. PRAGMA integrity_check said: ${INTEG:-<no output>}. Shipping it would put a broken database in front of buyers; re-extract it before going further."
  printf '   ok  store.db integrity_check: ok\n'
else
  printf '   -   sqlite3 not installed locally; integrity unchecked\n'
fi

# The data-protection keyring. Without it every existing session cookie and every encrypted
# column becomes unreadable, which looks exactly like a database that lost its rows.
if [ -d "$KEYS" ] && [ -n "$(ls -A "$KEYS" 2>/dev/null)" ]; then
  printf '   ok  keyring  %s file(s)\n' "$(ls -1 "$KEYS" | wc -l | tr -d ' ')"
else
  fail "no keyring at deploy/compose/data-api/keys -- buyers would be logged out and encrypted columns unreadable"
fi

# The compose file has to actually parse with the env files it will be given. This catches a
# missing variable before anything is copied anywhere.
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  ENVARGS=(--env-file "$REPO/.env")
  [ -f "$STACK_ENV" ] && ENVARGS+=(--env-file "$STACK_ENV")
  # NEVER print the output. `docker compose config` expands every env_file value inline, so its
  # stdout is the estate's entire secret set. Measured 2026-08-24, the hard way: one unredacted
  # run put the live Stripe key into a transcript. --quiet is not a preference here.
  if docker compose "${ENVARGS[@]}" -f "$COMPOSE_DIR/docker-compose.yml" config --quiet 2>/dev/null; then
    printf '   ok  compose file parses with these env files\n'
  else
    fail "compose file does not parse with .env + stack.env"
  fi
else
  printf '   -   no local docker daemon; compose file not parsed\n'
fi

if [ "$CHECK_ONLY" = 1 ]; then
  say "check only -- everything provable without a box passed"
  echo "   next: deploy/ship_shop.sh --dry-run user@host"
  exit 0
fi

[ -n "$HOST" ] || fail "no host given. usage: deploy/ship_shop.sh [--dry-run] user@host"

# ---------------------------------------------------------------------------
# 2. The box
# ---------------------------------------------------------------------------
say "remote preflight: $HOST"
if [ "$DRY_RUN" = 0 ]; then
  _ssh "docker version >/dev/null" || fail "no docker over ssh at $HOST"
  _ssh "docker compose version >/dev/null" || fail "docker has no compose plugin at $HOST"
  printf '   ok  docker and the compose plugin are present\n'
else
  _ssh "docker version && docker compose version"
fi

say "provision $REMOTE_DIR"
_ssh "mkdir -p $REMOTE_DIR/compose $REMOTE_DIR/data-api/keys && chmod 700 $REMOTE_DIR"

# ---------------------------------------------------------------------------
# 3. Data, and the one irreversible thing in this script.
#
# A box that already holds a store.db is a box that has been taking money. Copying over it
# destroys every order placed since this laptop's copy was made, and no amount of care
# afterwards gets them back. So the default is to refuse, and the override has to be typed.
# ---------------------------------------------------------------------------
say "database"
REMOTE_DB="$REMOTE_DIR/data-api/store.db"
EXISTING=""
[ "$DRY_RUN" = 0 ] && EXISTING="$(_ssh "test -f $REMOTE_DB && wc -c < $REMOTE_DB || true" 2>/dev/null | tr -d ' ')"

if [ -n "$EXISTING" ]; then
  if [ "${SHOP_OVERWRITE_DB:-0}" = 1 ]; then
    printf '   !!  %s already has a store.db of %s bytes; SHOP_OVERWRITE_DB=1 given, overwriting\n' "$HOST" "$EXISTING"
    _ssh "cp $REMOTE_DB $REMOTE_DB.replaced-$(date -u +%Y%m%dT%H%M%SZ)"
    _push "$DB" "$REMOTE_DB"
  else
    printf '   keeping the box'\''s own store.db (%s bytes). It may hold orders this laptop has never seen.\n' "$EXISTING"
    printf '   To replace it deliberately: SHOP_OVERWRITE_DB=1 deploy/ship_shop.sh %s\n' "$HOST"
  fi
else
  printf '   no database on the box yet; shipping the %s byte copy\n' "$DB_BYTES"
  _push "$DB" "$REMOTE_DB"
fi

for k in "$KEYS"/*; do
  [ -f "$k" ] || continue
  _push "$k" "$REMOTE_DIR/data-api/keys/$(basename "$k")"
done
_ssh "chmod -R 700 $REMOTE_DIR/data-api"
printf '   keyring shipped and locked to 700\n'

# ---------------------------------------------------------------------------
# 4. Configuration and secrets. 0600 before the content arrives, never after: a file created
#    world-readable and chmod'ed a moment later was world-readable for that moment.
# ---------------------------------------------------------------------------
say "configuration"
_push "$COMPOSE_DIR/docker-compose.yml" "$REMOTE_DIR/compose/docker-compose.yml"
_push "$COMPOSE_DIR/Caddyfile"          "$REMOTE_DIR/compose/Caddyfile"

_ssh "install -m 600 /dev/null $REMOTE_DIR/.env"
_push "$REPO/.env" "$REMOTE_DIR/.env"
if [ -f "$STACK_ENV" ]; then
  _ssh "install -m 600 /dev/null $REMOTE_DIR/compose/stack.env"
  _push "$STACK_ENV" "$REMOTE_DIR/compose/stack.env"
fi
printf '   config and secrets in place, 0600\n'

# ---------------------------------------------------------------------------
# 5. Images. Built here and piped over, so the box needs no registry account and no login,
#    which is one less vendor in the path.
# ---------------------------------------------------------------------------
say "images"
for img in prospector-store-api:local prospector-store-web:local; do
  if [ "$DRY_RUN" = 1 ]; then
    printf '   [dry-run] docker save %s | gzip | ssh %s "gunzip | docker load"\n' "$img" "$HOST"
    continue
  fi
  docker image inspect "$img" >/dev/null 2>&1 || fail "image $img not built locally. Build it first: docker compose -f deploy/compose/docker-compose.yml --profile store build"
  printf '   transferring %s ... ' "$img"
  docker save "$img" | gzip -1 | ssh -o BatchMode=yes "${SSH_OPTS[@]}" "$HOST" "gunzip | docker load" >/dev/null
  printf 'done\n'
done
# caddy comes from a public registry, so the box pulls it itself.
_ssh "docker pull caddy:2-alpine >/dev/null"

# ---------------------------------------------------------------------------
# 6. Start
# ---------------------------------------------------------------------------
say "start"
# The service names are explicit on purpose. The `engine` service carries no `profiles:` key, so
# a bare `up` pulls it in and blocks on a build the shop does not need.
_ssh "cd $REMOTE_DIR && docker compose --env-file .env --env-file compose/stack.env \
        -f compose/docker-compose.yml --profile store --profile edge \
        up -d api web edge"

if [ "$DRY_RUN" = 1 ]; then
  say "dry run complete -- nothing was changed on $HOST"
  exit 0
fi

# ---------------------------------------------------------------------------
# 7. Prove it, from two angles (LAW 15). Compose's own health verdict is one instrument and it
#    can be wrong: the api healthcheck ran `wget` in an image with no wget for weeks and reported
#    unhealthy the whole time while the API served perfectly. So ask the containers, and then
#    ask the edge, which is the path a buyer actually takes.
# ---------------------------------------------------------------------------
say "proof"
sleep 20
printf '   angle 1, container health:\n'
_ssh "cd $REMOTE_DIR && docker compose -f compose/docker-compose.yml ps --format '      {{.Name}}\t{{.Status}}'" || true

printf '   angle 2, through the edge:\n'
# stack.env spells every hostname as <label>.${ESTATE_ZONE} and declares the zone once on its own
# ESTATE_ZONE line (crew#796): read the zone first, then expand it in the two hostnames. The file
# is read, not sourced, because its edge lines hold comma-separated lists a shell would run.
stack_env_value() { grep -E "^$1=" "$STACK_ENV" 2>/dev/null | head -1 | cut -d= -f2-; }
ESTATE_ZONE="${ESTATE_ZONE:-$(stack_env_value ESTATE_ZONE)}"
: "${ESTATE_ZONE:?set ESTATE_ZONE, the estate zone, in deploy/compose/stack.env or the environment}"
SITE_HOST="$(stack_env_value SITE_DOMAIN | sed "s/\${ESTATE_ZONE}/$ESTATE_ZONE/g")"
SITE_HOST="${SITE_HOST:-$ESTATE_ZONE}"
API_HOST="$(stack_env_value API_DOMAIN | sed "s/\${ESTATE_ZONE}/$ESTATE_ZONE/g")"
API_HOST="${API_HOST:-api.$ESTATE_ZONE}"

# THIS BLOCK USED TO END IN `|| true` AND THE BANNER BELOW PRINTED REGARDLESS.
# Measured 2026-08-24 on the rehearsal box: both probes returned HTTP 000 -- the API was in a
# restart loop and the edge was bound to a port nothing was asking on -- and this script
# printed "the shop answered through the edge" and exited 0. A deploy tool that cannot report
# a dead deploy is not a deploy tool, it is a log with a success message at the end.
#
# The port matters as much as the code. `curl http://127.0.0.1/` was hardcoded while the edge
# publishes ${EDGE_HTTP_PORT}, so on a box where those two disagree the probe asks a port the
# stack never bound and reports 000 for a shop that is actually fine -- or, worse, the reverse.
probe() {  # probe <label> <host header> <path>
  # ssh failing and the shop failing are different facts and they must not print the same word.
  # The first version of this swallowed stderr and turned every failure into `HTTP 000`, so a
  # loaded laptop timing out during the ssh banner exchange was reported as a dead storefront --
  # measured 2026-08-24. curl always prints exactly three digits, so anything else on stdout
  # means the question never reached curl at all.
  local out
  out="$(_ssh "curl -s -o /dev/null -m 15 -w '%{http_code}' -H 'Host: $2' http://127.0.0.1:${EDGE_HTTP_PORT}$3" 2>&1)" || true
  out="$(printf '%s' "$out" | tr -d '[:space:]')"
  case "$out" in
    [0-9][0-9][0-9])
      printf '      %-11s HTTP %s   (Host: %s, port %s)\n' "$1" "$out" "$2" "$EDGE_HTTP_PORT"
      [ "$out" = 200 ] ;;
    *)
      printf '      %-11s NOT ASKED -- the box could not be reached: %s\n' "$1" "${out:-no output}"
      return 1 ;;
  esac
}

PROOF_OK=1
probe storefront  "$SITE_HOST" "/"         || PROOF_OK=0
probe api/catalog "$API_HOST"  "/catalog"  || PROOF_OK=0

if [ "$PROOF_OK" != 1 ] && [ "$DRY_RUN" != 1 ]; then
  printf '\n!! THE SHOP IS ON THE BOX BUT IT IS NOT SERVING. Nothing has been cut over, so\n'
  printf '!! nothing is broken for customers -- Fly still holds the DNS. What to read, in order:\n\n'
  printf '     ssh %s "cd %s && docker compose -f compose/docker-compose.yml ps"\n' "$HOST" "$REMOTE_DIR"
  printf '     ssh %s "cd %s && docker compose -f compose/docker-compose.yml logs --tail 40 api"\n\n' "$HOST" "$REMOTE_DIR"
  printf '   The API refuses to start when a setting is missing and names the one it wants, so\n'
  printf '   that log usually says exactly what the box was not given.\n'
  exit 1
fi

say "shipped to $HOST"
cat <<EOF
   The shop is running on the box. It is NOT yet serving the public: DNS still points at Fly,
   and Fly stays up and untouched, which is what keeps this reversible.

   What the world resolves right now:
       .venv/bin/python scripts/dns_zone.py --check

   The cutover itself is changing the A records for the estate zone's apex, www and api to this box.
   That script now exists, in the survival-stack repo, because that is where the Cloudflare
   credential and the zone tooling already live:

       node ~/dev/code/survival-stack/scripts/cutover.mjs --show
       node ~/dev/code/survival-stack/scripts/cutover.mjs --to <this box's IP> --dry-run
       node ~/dev/code/survival-stack/scripts/cutover.mjs --to <this box's IP>
       node ~/dev/code/survival-stack/scripts/cutover.mjs --rollback

   It refuses a box that is not answering, deletes the apex AAAA so no v6 client is left on the
   old host, and never touches mail. scripts/dns_zone.py still only READS.
EOF
