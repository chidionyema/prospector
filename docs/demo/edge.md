# Demo — the edge

The edge is the Caddy container that terminates TLS and routes `mumchimp.com`, `www.mumchimp.com`
and `api.mumchimp.com` at the storefront and the API. It is the replacement for the last thing
Fly.io was still doing that the compose stack could not do for itself.

This is a real run on 2026-08-24, on a laptop, with Fly out of the request path entirely. The
storefront and the API are both answering through the edge, and the API is reading the real
production `store.db` recovered from Fly on 2026-08-23.

## Bring it up

```
docker compose \
  --env-file .env \
  --env-file deploy/compose/stack.env \
  -f deploy/compose/docker-compose.yml \
  --profile store --profile edge \
  up -d api web edge
```

Two `--env-file` flags, and the order matters. Compose resolves `${VAR}` from the files given on
the command line, not from a service's own `env_file:` key, so the secrets in `.env` are invisible
to interpolation unless `.env` is named here. The later file wins, which is how `stack.env`
overrides a production value with a drill one.

The service names are given explicitly on purpose. `engine` carries no `profiles:` key, so a plain
`up` pulls it in and its build stalls everything behind it.

## What came back

```
$ docker ps --filter name=prospector- --format "{{.Names}}\t{{.Status}}"
prospector-store-api	Up 2 minutes (healthy)
prospector-edge	Up 8 minutes (healthy)
prospector-engine	Up 8 minutes
prospector-store-web	Up 8 minutes (healthy)

$ curl -s -o /dev/null -w "HTTP %{http_code}  bytes=%{size_download}\n" -H "Host: localhost" http://127.0.0.1:8080/
HTTP 200  bytes=30355

$ curl -s -H "Host: api.localhost" http://127.0.0.1:8080/catalog | head -c 200
[{"id":"d6ce3ca2ff304cda","title":"Cold chain audit AI for Georgia poultry processors","oneLine":"An AI auditor that reads temperature logs and finds the hour a cold chain broke, so a Georgia poultry

$ docker exec prospector-store-api sh -c "ls -l /data/store.db"
-rw-r--r-- 1 root root 4632576 Aug 24 00:29 /data/store.db
```

## What that proves, and what it does not

It proves the storefront renders and the catalogue serves with no Fly hostname anywhere in the
path, and that the API is reading the genuine production database — 4,632,576 bytes, the same
byte count and sha256 as the copy extracted from the Fly volume.

It does not prove TLS. The drill runs on a laptop with no public DNS, so `EDGE_SITE` carries an
explicit `http://` scheme, which switches Caddy's certificate management off for that site block.
The certificate path is the one thing this drill cannot exercise, and it is exercised for the first
time on the destination box when a real hostname resolves to it.
