# Onboarding — ship the shop to a box

## What it is for

This is how mumchimp.com stops being a Fly.io application and becomes a thing that runs anywhere.

The estate already had `deploy/cutover.sh` and `deploy/targets/sshdocker.sh`, and both of them move
the *engine* — the research process that produces dossiers. Neither has ever touched the shop.
`sshdocker.sh` runs one container, `prospector-engine`, and health-checks the engine's ledger at
`/data/store/prospector.jsonl`.

The shop is the half that takes card payments: the Next.js storefront, the .NET API, the SQLite
database holding orders, and the TLS edge in front of them. On 2026-08-24 it had no cutover path of
any kind. That is the actual reason Fly.io was still load-bearing — not a missing feature, not a
technical dependency, just nobody having written the script that puts three containers on a box.

`deploy/ship_shop.sh` is that script. It ships the same compose file the local drill runs, so
production and the drill cannot quietly become two different configurations that are each only half
tested. The only thing that differs between them is `deploy/compose/stack.env`, which carries the
hostnames and the TLS switch.

## What it costs

Nothing to own. It is a shell script that uses ssh and docker, both of which are already here.

It costs a box, and that is the only recurring bill: any Linux machine with Docker and an SSH login
will do. The images are built on this laptop and piped over the SSH connection, so there is no
container registry account, no registry login and no second vendor in the path.

Transferring the two images takes a few minutes on a normal connection. The database is 4.6 MB.

## What it watches or changes

It changes a directory on the box you name, `/srv/mumchimp` by default, and nothing else. It does
not touch DNS, it does not touch Fly, and it does not stop anything that is currently serving.
After a successful run, the shop is running on the new box and the public is still being served by
Fly, which is exactly what makes the whole thing reversible: if the new box is wrong, you have lost
a few minutes and no orders.

There is one irreversible thing in the script and it is fenced. If the box already holds a
`store.db`, that box has been taking money, and copying over it destroys every order placed since
this laptop's copy was made. The default is to keep the box's own database and say so. Replacing it
has to be typed deliberately:

```
SHOP_OVERWRITE_DB=1 deploy/ship_shop.sh user@host
```

and even then the existing file is copied aside first.

## Where it lives

- `deploy/ship_shop.sh` — the whole thing.
- `deploy/compose/docker-compose.yml` and `deploy/compose/Caddyfile` — what gets shipped.
- `deploy/compose/stack.env` — the hostnames and TLS mode. Gitignored, because it is per-target.
- `deploy/compose/data-api/store.db` and `.../keys/` — the orders and the data-protection keyring.
- On the box: `/srv/mumchimp`, mode 700, with `.env` and `stack.env` at 0600.

Override the remote directory with `SHOP_REMOTE_DIR=/somewhere/else`.

## How to turn it off

There is nothing running to turn off — the script does its work and exits. To stop the shop on a
box it has shipped to:

```
ssh user@host 'cd /srv/mumchimp && docker compose -f compose/docker-compose.yml down'
```

Fly is untouched by all of this, so while DNS still points at Fly, stopping the new box has no
effect on anybody buying anything.

## How to turn it back on

```
ssh user@host 'cd /srv/mumchimp && docker compose --env-file .env --env-file compose/stack.env \
    -f compose/docker-compose.yml --profile store --profile edge up -d api web edge'
```

The service names are explicit on purpose. The `engine` service in that compose file carries no
`profiles:` key, so a bare `up` pulls it in and blocks on a build the shop does not need.

## What goes wrong

**It refuses with "no store.db".** The database is not in the working tree — it is gitignored,
because it holds real customer orders. Recover it from the running production volume before
shipping anything.

**It refuses with "store.db is not a readable SQLite database".** The copy is truncated. That
usually means an extraction was interrupted. Re-extract; do not ship it. A truncated SQLite file
copies without complaint and fails at the first checkout, in front of a buyer.

**It refuses with "no keyring".** `deploy/compose/data-api/keys/` is missing. Without it every
existing session cookie and every encrypted column becomes unreadable, which looks exactly like a
database that lost its rows. It is a separate file from the database and it is easy to forget.

**It refuses with "image not built locally".** Build first:

```
docker compose -f deploy/compose/docker-compose.yml --profile store build
```

**The proof step reports HTTP 000.** Caddy is trying to get a real certificate for a hostname that
does not resolve to this box yet. That is expected before the DNS cutover and is not a failure of
the shipment; the containers behind the edge are still the thing to check.

**Everything worked and the site is unchanged.** Correct. This ships the shop; it does not move
traffic. The cutover is changing the A records for `mumchimp.com`, `www` and `api` to the new box.
There is no script for that yet — `scripts/dns_zone.py` reads DNS and deliberately never writes it.
