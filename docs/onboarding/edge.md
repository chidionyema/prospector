# Onboarding — the edge

## What it is for

mumchimp.com takes card details. An escape hatch that serves the shop over plain HTTP is not an
escape hatch you can actually use, so for as long as the compose stack had no certificate, Fly.io
was load-bearing whatever the portability doc claimed. `force_https = true` and the two issued
certificates were the last thing Fly was doing for us.

The edge is a Caddy container that does the same job with no vendor in the path. It requests
certificates from Let's Encrypt on the first request for a hostname and renews them on its own.
Nothing has to be bought, no account has to be held, and moving the stack to a different box moves
the certificates with it.

## What it costs

Nothing in money. Caddy is Apache-2.0 and Let's Encrypt is free. It costs one container, roughly
40 MB of memory, and ports 80 and 443 on whatever box the stack runs on. Port 80 is not optional:
it is where the ACME HTTP challenge arrives, so closing it stops certificate renewal and the shop
goes dark 90 days later.

## What it watches or changes

It terminates TLS and reverse-proxies two upstreams by hostname: the storefront at `web:3000` and
the API at `api:8080`. It reaches them by compose service name on the compose network, not by
published host port, which is what keeps an un-TLS'd storefront off the box's public interface.

It adds one header, `X-Forwarded-Proto`. Without it ASP.NET and Next.js believe they are serving
plain HTTP and build `http://` links into verification emails while the browser is on `https`,
which shows the buyer a mixed-content warning at the exact moment they are typing a card number.

Its admin API is switched off. On a public box that endpoint is a config-write API, and nothing
here uses it.

## Where it lives

`deploy/compose/Caddyfile` is the whole configuration. The `edge` service in
`deploy/compose/docker-compose.yml` mounts it read-only. The two variables that decide what it
serves are `EDGE_SITE` and `EDGE_API` in `deploy/compose/stack.env`, and their production values
are in `stack.env.example`.

A bare hostname in those variables makes Caddy manage the certificate. An explicit `http://`
scheme turns TLS off for that site block, which is how the local drill runs on a laptop that has
no public DNS and cannot answer an ACME challenge.

## How to turn it off

```
docker compose -f deploy/compose/docker-compose.yml stop edge
```

The storefront and the API keep running and stay reachable on their published ports, 3000 and
5291. What stops is TLS, so do not do this while a real hostname points at the box.

## How to turn it back on

```
docker compose --env-file .env --env-file deploy/compose/stack.env \
  -f deploy/compose/docker-compose.yml --profile edge up -d edge
```

Certificates survive a restart because they are stored in the `caddy_data` volume. Deleting that
volume makes Caddy request fresh certificates, and Let's Encrypt rate-limits a hostname to five
duplicate certificates a week, so do not delete it to fix an unrelated problem.

## What goes wrong

**The container restart-loops with exit 1.** Read the log. If it says "wrong argument count or
unexpected line ending after 'email'", `ACME_EMAIL` is defined but empty. Caddy's `{$VAR:default}`
only fires when a variable is unset, not when it is set to nothing, so an empty value reaches the
`email` directive as no argument at all, which is a parse error rather than an omission. Both the
Caddyfile and the compose file now carry a default for this, and it took a restart loop on
2026-08-24 to find it.

**A hostname returns a certificate error.** Caddy could not complete the ACME challenge. Either
port 80 is closed on the box, or DNS for that hostname does not yet point at it, or the hostname
is being served through a proxy that terminates TLS itself. Cloudflare's orange-cloud proxy is the
usual third case, and mumchimp.com's records are deliberately DNS-only for that reason.

**Everything returns 502.** The upstream containers are not on the compose network or are not
running. `docker compose ps` first, before touching anything in the Caddyfile.
