# Demo — the rehearsal box, and the defect it found on its first run

This is the actual output of the first real execution, on 2026-08-24. It is not a tidied version.
The run **failed**, which is the point of showing it: the failure it found would otherwise have been
found on a rented box with the live shop's database on it and mumchimp.com pointed at it an hour
later.

## The command

```
deploy/rehearse_box.sh
```

## What came back

```
== box
   ok  throwaway key at ~/.cache/prospector-rehearsal/id_ed25519
   -   8080 was busy, the box's port 80 is on 8081
   ok  prospector-rehearsal-box started from docker:28-dind
   waiting for the box's own docker daemon ... up
   ok  ssh root@127.0.0.1:2222 -> docker 28.5.2, compose 2.40.3
   ok  the box publishes port 80 on 127.0.0.1:8081

== shipping the shop to the rehearsal box with the REAL deploy/ship_shop.sh

== local preflight
   ok  deploy/compose/docker-compose.yml
   ok  deploy/compose/Caddyfile
   ok  .env
   ok  /Users/chidionyema/.cache/prospector-rehearsal/stack.env
   ok  store.db  4632576 bytes
   ok  store.db integrity_check: ok
   ok  keyring  1 file(s)
   ok  compose file parses with these env files

== remote preflight: root@127.0.0.1
   ok  docker and the compose plugin are present

== provision /srv/mumchimp

== database
   no database on the box yet; shipping the 4632576 byte copy
   keyring shipped and locked to 700

== configuration
   config and secrets in place, 0600

== images
   transferring prospector-store-api:local ... done
   transferring prospector-store-web:local ... done

== start
 Container prospector-store-api  Started
 Container prospector-store-web  Started
 Container prospector-edge  Started

== proof
   angle 1, container health:
Connection timed out during banner exchange
   angle 2, through the edge:
      storefront  HTTP 000   (Host: localhost, port 80)
      api/catalog HTTP 000   (Host: api.localhost, port 80)

!! THE SHOP IS ON THE BOX BUT IT IS NOT SERVING. Nothing has been cut over, so
!! nothing is broken for customers -- Fly still holds the DNS.
EXIT=1
```

The compose start section is trimmed here to the three `Started` lines. The full run printed about
110 lines of Docker layer-pull progress for the edge image, which carries no information and is not
worth the page.

## What this proves, and what it does not

**Every step up to `== proof` is a step nobody had ever run.** `deploy/ship_shop.sh` could be checked
two ways before this and no further: `--check` reads local files and confirms the database is intact
and the compose file parses, and `--dry-run` prints every remote command and executes none of them.
Both passed for weeks. Neither starts a container.

The run above transferred a 4.6MB SQLite database, a keyring, a config file and two container images
into a machine that had never seen any of them, over SSH, and started three containers. That whole
path is now evidence rather than a plan.

**Then it failed honestly, and that is the deliverable.** Both proof angles disagreed with the
containers: Docker reported three containers `Started` while the storefront and the API both returned
`HTTP 000`, which is curl saying it never got a response at all rather than a server saying no.

`Started` is a fact about a process existing. It is not a fact about anything serving. A migration
script that had only checked container state would have printed green here and the next step would
have been DNS.

## The two defects behind it

**The API exits when a setting is missing, and the box's `.env` was short one.** That is the money
rail gate doing its job: the application refuses to run half-configured rather than accept a card
with a webhook signature it cannot verify. The gate is at `MoneyRailConfigGate.cs:150`.

**`Connection timed out during banner exchange` is a second, separate failure**, and it is about this
laptop rather than about the shop. Measured the same day: running the pytest suite and the rehearsal
at once took the load average to **113 on 12 cores**, and Docker's own daemon stopped answering SSH.
The drill needs the machine to itself.

## Why the exit code matters more than the output

The run exits **1**. An earlier version of this script printed the same failure text and exited 0,
because the last command in its `all` branch was an `echo`. A drill that reports a failure in prose
and succeeds in its exit status cannot gate anything: no CI job, no pre-push hook and no scheduler
would ever see the problem. `cmd_status` now returns non-zero when any probe is not 200, and the
`all` branch branches on it.

That correction is the single most valuable line in the script and it came from reading the exit
code of a run that had already told the truth on screen.
