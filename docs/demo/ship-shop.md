# Demo — shipping the shop to a box

`deploy/ship_shop.sh` puts the storefront, the API and the TLS edge on any Linux box with Docker
and an SSH login. Before it existed, `deploy/cutover.sh` moved the engine and
`deploy/targets/sshdocker.sh` ran a single engine container. Nothing moved the half that takes card
payments, which is the real reason Fly.io was still load-bearing.

Run on 2026-08-24.

## What it can prove with no box at all

```
$ deploy/ship_shop.sh --check

== local preflight
   ok  deploy/compose/docker-compose.yml
   ok  deploy/compose/Caddyfile
   ok  .env
   ok  deploy/compose/stack.env
   ok  store.db  4632576 bytes
   ok  store.db integrity_check: ok
   ok  keyring  1 file(s)
   ok  compose file parses with these env files

== check only -- everything provable without a box passed
   next: deploy/ship_shop.sh --dry-run user@host
exit=0
```

That is the real production database, the one recovered from the Fly volume, being verified before
anything is rented.

## Every remote command, with none of them run

```
$ deploy/ship_shop.sh --dry-run root@198.51.100.7

== provision /srv/mumchimp
   [dry-run] ssh root@198.51.100.7 mkdir -p /srv/mumchimp/compose /srv/mumchimp/data-api/keys && chmod 700 /srv/mumchimp

== database
   no database on the box yet; shipping the 4632576 byte copy
   [dry-run] push deploy/compose/data-api/store.db -> /srv/mumchimp/data-api/store.db
   [dry-run] push deploy/compose/data-api/keys/key-578f92e1-...xml -> /srv/mumchimp/data-api/keys/...

== configuration
   [dry-run] push deploy/compose/docker-compose.yml -> /srv/mumchimp/compose/docker-compose.yml
   [dry-run] push deploy/compose/Caddyfile -> /srv/mumchimp/compose/Caddyfile
   [dry-run] ssh root@198.51.100.7 install -m 600 /dev/null /srv/mumchimp/.env

== images
   [dry-run] docker save prospector-store-api:local | gzip | ssh root@198.51.100.7 "gunzip | docker load"
   [dry-run] docker save prospector-store-web:local | gzip | ssh root@198.51.100.7 "gunzip | docker load"

== start
   [dry-run] ssh root@198.51.100.7 cd /srv/mumchimp && docker compose --env-file .env
             --env-file compose/stack.env -f compose/docker-compose.yml
             --profile store --profile edge up -d api web edge

== dry run complete -- nothing was changed on root@198.51.100.7
exit=0
```

Every remote call goes through one function, so `--dry-run` cannot miss one.

## It says no, and says why

Four runs against deliberately broken inputs, in a scratch tree so the real database was never
touched:

```
REFUSE: no store.db          exit=1  !! no store.db at deploy/compose/data-api/store.db -- nothing to ship
REFUSE: corrupt store.db     exit=1  !! store.db is not a readable SQLite database. PRAGMA integrity_check
                                        said: Error: in prepare, file is not a database (26). Shipping it
                                        would put a broken database in front of buyers; re-extract it
                                        before going further.
REFUSE: no keyring           exit=1  !! no keyring at deploy/compose/data-api/keys -- buyers would be
                                        logged out and encrypted columns unreadable
ALLOW:  real repo            exit=0
```

The corrupt case originally refused with a bare `exit=26` and no message at all, because `set -e`
killed the script on sqlite3's own exit code before the explanation could run. A guard that
refuses without saying why is most of the way to being an outage.
