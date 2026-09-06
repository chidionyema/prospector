# Onboarding — the rehearsal box

## What it is for

It answers the one question that stood between the estate and leaving Fly.io: **does the shop
actually come up on a box that has never seen it?**

`deploy/ship_shop.sh` could be proved two ways and no further. `--check` reads local files and
says the database is intact and the compose file parses. `--dry-run` prints every remote command
and runs none of them. Both passed, and neither of them starts a container. The first real
execution of that script was going to be against a rented box with the live shop's database on it
and mumchimp.com pointed at it an hour later. That is not a migration plan, it is a first draft
performed in public.

`deploy/rehearse_box.sh` makes a Linux box on this laptop, for free, in about a minute, and runs
the real deploy script against it start to finish.

## What it costs

Nothing. No account, no card, no provider. One container and about 400MB of disk while it runs,
and `down` gives all of it back.

It costs a few minutes of wall clock, most of which is transferring the two images into a daemon
that has none — which is the point, because that transfer is the step nobody had ever run.

## What it watches or changes

Nothing outside the box, and the box is a container. Specifically it does **not** touch DNS, does
not touch Fly, does not touch the live shop, and does not write to `deploy/compose/`.

It reads three things from the repository and copies them: `deploy/compose/docker-compose.yml`,
the `Caddyfile`, and the shop's `store.db` and keyring. The database is copied onto the box, never
the other way round, so nothing the rehearsal does can reach the real one.

The box is `docker:28-dind` — a container running its own Docker daemon, with `sshd` listening on
`127.0.0.1:2222`. As far as `deploy/ship_shop.sh` is concerned it is an ordinary remote: its own
daemon, its own empty image store, its own filesystem, reached only over SSH. Nothing is stubbed
and `ship_shop.sh` is not modified for it.

Two things are deliberately different from a rented box, and both are named in the script:

**TLS is off.** The Caddyfile has always documented two modes and switches on `EDGE_SITE` /
`EDGE_API`. Production uses bare hostnames so Caddy manages certificates; the local drill uses an
explicit `http://` scheme, which turns TLS off for that site block. There is no public DNS
pointing at your laptop, so an ACME challenge could not succeed and a drill that cannot run is a
drill nobody runs. Every other value in `stack.env`, the signing key included, is the production
one — so a variable missing from the real config still fails here.

**The SSH key is a throwaway** in `~/.cache/prospector-rehearsal/`, and host key checking is off.
There is no host identity worth pinning when the host is created from scratch on every run.

## Where it lives

- `deploy/rehearse_box.sh` — the whole thing.
- `deploy/ship_shop.sh` — what it exercises. Unchanged by the rehearsal, and that is the design:
  a rehearsal that runs a second code path proves nothing about the first.
- `~/.cache/prospector-rehearsal/` — the throwaway key and the drill's `stack.env`.

Two environment seams were added to `ship_shop.sh` so the rehearsal could reach a box on a
non-standard port without the script being edited for it. Both are ordinary on a real estate:
`SHOP_SSH_OPTS` (a port, a jump host, a specific key) and `SHOP_STACK_ENV` (which hostname and TLS
config to ship). Unset, both behave exactly as before.

## How to turn it off

```
deploy/rehearse_box.sh down
```

That removes the container and the drill's `stack.env`. There is nothing else running: the script
does its work and exits. Nothing is scheduled, nothing listens after `down`, and nothing on the
estate depends on the box existing.

## How to turn it back on

```
deploy/rehearse_box.sh            # box, ship, prove, in one command
deploy/rehearse_box.sh up         # just the box
deploy/rehearse_box.sh ship       # ship to a box that is already up
deploy/rehearse_box.sh status     # what it answers right now
```

## What goes wrong

**"the local docker daemon is not running".** Start Docker on the laptop. The rehearsal box is a
container, so there has to be a daemon to run it in.

**"the box's inner docker daemon never came up".** The box needs `--privileged` to run a Docker
daemon inside a container. If your Docker setup refuses privileged containers, `docker logs
prospector-rehearsal-box` says so. Some hardened corporate configurations do refuse it, and there
is no way around that other than a real box.

**"image prospector-store-api:local not built locally".** The rehearsal transfers images from this
laptop rather than pulling them from a registry, which is what keeps a registry account out of the
migration path. Build them first:

```
docker compose -f deploy/compose/docker-compose.yml --profile store build
```

**Port 2222 or 8080 is already taken.** It handles this itself now — it walks up until it finds a
free port, prints which one it took, and remembers it in `~/.cache/prospector-rehearsal/box.env` so
`ship` and `status` in a later shell reach the same box. `REHEARSAL_SSH_PORT` and
`REHEARSAL_HTTP_PORT` set the starting point.

**"the box could not be reached" instead of an HTTP code.** The question never got as far as the
shop. Almost always the laptop is loaded: measured 2026-08-24, running the pytest suite and the
rehearsal at the same time took the load average to 113 and Docker's own daemon stopped answering,
which surfaced as `Connection timed out during banner exchange`. Give the rehearsal the machine.

**The edge ports have to be 80 and 443.** `deploy/ship_shop.sh` refuses anything else in preflight
now, before it transfers a single image. A box serving on 8080 is not reachable without a port in
the URL, and Let's Encrypt answers its challenge on 80, so a certificate would never issue.
`deploy/compose/stack.env` carried 8080/8443 from laptop use until 2026-08-24 and the deploy script
would have shipped that to a rented box.

**It all passed and the storefront returned a redirect.** Check `EDGE_SITE` in the drill's
`stack.env` still carries the `http://` scheme. A bare hostname there puts Caddy into
certificate-managing mode, and it will redirect to HTTPS for a name it cannot get a certificate
for.

**The API starts and then exits, naming a setting.** That is the money-rail gate doing its job:
the app refuses to run half-configured rather than take a card with a webhook it cannot verify.
Whatever key it names is missing from the box's `.env`. This is the failure the very first
rehearsal found — see `docs/demo/rehearse-box.md`.

**A green rehearsal is not a green migration.** What it cannot prove: real network latency, a
provider's boot time, Let's Encrypt issuance, and live Stripe. Those need money and a real box.
Everything before them is proved here, which is the difference between a rented box being the
first test and being the last one.
