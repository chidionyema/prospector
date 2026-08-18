# SearXNG, the engine's only working grounding provider once it left the laptop.
#
# WHY THIS EXISTS. Measured from prospector-engine on 2026-08-18, every other provider in
# `config.yaml retrieval.provider` is dead from a Fly datacenter IP:
#
#   html.duckduckgo.com   000 after 12s   (lite. too, and over both IPv4 and IPv6)
#   api.exa.ai            402             {"tag":"NO_MORE_CREDITS"}
#   claude_cli            exit 1          "Not logged in - Please run /login"
#   searx.be              200 but HTML    "Verifying your browser..." anti-bot captcha
#
# while `https://example.com` answered 200 in 0.08s from the same shell, so this is those
# hosts refusing datacenter traffic, not broken egress. The engine had produced nothing since
# the 03:09 cutover, and the log line for it - "ALL grounding providers dead" - reads as an
# outage rather than as a permanent property of the new host.
#
# Of the free engines probed from that machine, exactly two answered 200: bing and wikipedia.
# SearXNG drives both, keylessly. mojeek 403, brave 429, duckduckgo 000 - they stay declared
# in settings.yml because they cost nothing when they fail fast and they work from a laptop.
FROM docker.io/searxng/searxng:latest

# The same settings the laptop container used, so grounding behaves identically wherever it
# runs. limiter:false is safe here because this app has no public IP at all - see fly.toml.
COPY searxng/settings.yml /etc/searxng/settings.yml
