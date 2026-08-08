"""Incumbent-landscape seed (G2).

The generator has been structurally blind to who already serves a space, so it proposes
ideas that die at the `incumbency` gate for reasons that were knowable BEFORE the idea was
written. This module spends ONE bounded, cached retrieval per (topic, market) and injects
the result as generation CONTEXT.

It is explicitly NOT evidence: it is never cited, never scored, never stored as a Source,
and can never kill anything. claude_cli is deliberately excluded from the provider list
because the moat's grounding queue runs on it and a generation-side query must never queue
ahead of a verdict (job 20260730T212901866 died at 1731s on exactly that saturation).
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from typing import Any
from urllib.parse import urlparse

from .diversity import generation_artifact_dir
from .telemetry import logger

# ddg+exa only — NEVER claude_cli. See the module docstring for the saturation argument
# that pinned this; a generation-side query must not consume moat grounding slots.
_DEFAULT_PROVIDERS = ("ddg", "exa")

_DEFAULT_TEMPLATES = (
    "{topic} existing providers",
    "{topic} software vendors pricing",
)

# generate_multilane runs its lanes CONCURRENTLY (generate.py:683), so without this lock four
# lanes sharing one topic would all miss the cache, all fetch, and all write it — 4x the queries
# and a torn JSON file. One thread fetches; the rest read the cache it just wrote.
_FETCH_LOCK = threading.Lock()


def _topic(signal_text: str = "", sector: str = "", audience: str = "") -> str:
    """Derive the topic string fed into the retrieval query templates.

    Precedence, strongest signal first:

    1. `sector` — already a clean noun phrase the operator typed or the active market
       supplied.
    2. the first 12 words of `signal_text` — a long free-form signal can be 100+ words
       and the templates only ever replace `{topic}` with the literal string, so
       unbounded text would mint queries like "veterinary invoicing small animal
       practice surgery recovery plan existing providers" and return nothing relevant.
       Twelve words is the same order as the query-gen budget elsewhere and keeps the
       query inside what a search engine will actually match on.
    3. the AUDIENCE PERSONA slug, underscores expanded to spaces.

    Rung 3 exists because without it this whole feature would have had no authority over
    the path that produces most of the catalogue. The daemon generates blue-sky:
    `scheduler/run_scheduled.py:724` calls `run_signal("", cfg=cfg, k=batch_size,
    publish=True, lanes=lanes)` — empty signal, and no sector is threaded through — so
    rungs 1 and 2 are both empty on every unattended tick and the brief would never fire.
    Be honest about what rung 3 buys: a BUYER-level landscape ("who already sells to
    ecommerce sellers"), not an idea-level one. It is weaker than a signal-derived brief,
    and the receipts in store/generation_metrics.jsonl are what decide whether it earns
    its place. It is not a guessed topic — the persona is a real field the run owns.

    Returns "" when all three are empty, so the call site no-ops without any retrieval.
    """
    s = str(sector or "").strip()
    if s:
        return s
    text = str(signal_text or "").strip()
    if text:
        return " ".join(text.split()[:12])
    aud = str(audience or "").strip().replace("_", " ")
    return " ".join(aud.split())


def _cache_key(topic: str, market: str) -> str:
    """A stable cache key for (topic, market). Lowercased so casing never splits the cache."""
    return hashlib.sha1(f"{topic.lower()}|{market.lower()}".encode("utf-8")).hexdigest()


def _providers(icfg: dict) -> list[str]:
    """Resolve the generation-side provider list, dropping claude_cli with a loud warning.

    claude_cli is the moat's grounding backstop (retrieval.provider chain position 3); a
    generation-side query that landed on it would queue behind every live verdict and could
    starve the moat. Empty / non-string entries are silently stripped; an entry equal to
    "claude_cli" (case-insensitive) is stripped WITH a warning so the operator can see why
    their config is being partially ignored. Empty result falls back to the default chain
    so the directive never silently disappears."""
    raw = icfg.get("providers") or _DEFAULT_PROVIDERS
    out: list[str] = []
    for p in raw:
        s = str(p or "").strip()
        if not s:
            continue
        if s.lower() == "claude_cli":
            logger.warning(
                "incumbent_seed.providers drops 'claude_cli': generation-side retrieval "
                "must not consume moat grounding slots."
            )
            continue
        out.append(s)
    return out or list(_DEFAULT_PROVIDERS)


def _format_brief(sources: list, max_entries: int = 8, max_chars: int = 220) -> str:
    """Render the sources list into a single directive string for the model.

    PURE function — no I/O, no cfg — so the unit tests exercise this directly and any
    format regression is caught before the retrieval layer even runs. Deduplicates on URL
    (first wins) so the same vendor page hit twice across queries contributes one line;
    truncates each passage to `max_chars` so the prompt budget is bounded regardless of
    how long a fetched passage was. Empty output when nothing survives — the caller treats
    that as "no brief" and skips the directive, byte-for-byte today's prompt."""
    lines: list[str] = []
    seen_urls: set[str] = set()
    for s in sources:
        url = (getattr(s, "url", "") or "").strip()
        text = (getattr(s, "text", "") or "").strip()
        if not url or not text:
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        snippet = " ".join(text.split())
        if len(snippet) > max_chars:
            snippet = snippet[:max_chars].rstrip()
        lines.append(f"- {host}: {snippet}")
        if len(lines) >= max_entries:
            break
    if not lines:
        return ""
    return (
        "INCUMBENT LANDSCAPE (retrieved live for this signal — who and what ALREADY serves this "
        "space). This is CONTEXT, not evidence: it is never cited, never scored, and never kills "
        "anything. Use it to design against reality rather than around it:\n"
        + "\n".join(lines) + "\n"
        "Every idea you propose must do ONE of these: (a) name the specific structural reason an "
        "incumbent above CANNOT capture the value you are going after, or (b) serve a buyer or a "
        "job that none of them serves at all. A thinner, cheaper or AI-flavoured version of "
        "anything listed is not an idea — it is the incumbency gate's next kill."
    )


def _fetch_brief(cfg: Any, icfg: dict, topic: str) -> str:
    """Run the configured provider chain ONCE and return a rendered brief.

    Deferred imports inside the function mirror run.py:640 — keep import cost off the hot
    path AND avoid an import cycle (retrieval imports diversity-adjacent things and the
    reverse direction is not safe at module load). A shallow copy of cfg is built so the
    restricted provider list cannot leak into the moat's own config object, which is
    shared across concurrently-running lanes (the exact failure that produced the 1731s
    saturation: a generation-side provider slipping into a vet's grounding chain).

    No outer wall-clock timeout is imposed here, on purpose. The providers carry their own
    request timeouts and FallbackSearchProvider carries the circuit breaker; wrapping this
    in a thread purely to time it out would leak a non-daemon worker on a genuinely hung
    socket, which is strictly worse than the bounded wait the provider already gives us."""
    import copy

    from .retrieval import make_provider

    shim = copy.copy(cfg)
    shim.retrieval = copy.copy(cfg.retrieval)
    shim.retrieval.provider = _providers(icfg)

    provider = make_provider(shim)

    templates = list(icfg.get("query_templates") or _DEFAULT_TEMPLATES)
    max_queries = int(icfg.get("max_queries", 2))
    queries = [str(t).replace("{topic}", topic) for t in templates[:max_queries]]
    k = int(icfg.get("results_per_query", 3))
    max_chars = int(icfg.get("max_chars", 700))

    sources: list = []
    for q in queries:
        try:
            sources.extend(provider.search(q, k, max_chars))
        except Exception as e:
            # One dead query must not cost the others — log and keep going.
            logger.info(f"incumbent_seed query failed, continuing: {e}",
                        extra={"query": q})

    return _format_brief(
        sources,
        max_entries=int(icfg.get("max_entries", 8)),
    )


def incumbent_brief(cfg: Any, signal_text: str = "", sector: str = "",
                     market: str = "", audience: str = "") -> str:
    """Return a cached incumbent-landscape directive, or "" if the gate is off / topic empty /
    anything raises.

    Order of operations:
        1. gate check — returns "" without any I/O when the feature is off (default-off,
           so absent flags mean byte-identical behaviour to today).
        2. topic derivation — see `_topic` for the three-rung precedence. An empty topic
           means no retrieval call at all.
        3. cache lookup under `_FETCH_LOCK` — the lock is held across read-fetch-write
           so four concurrent lanes that share a topic all read the freshly-written cache
           instead of racing four fetches. The cache is keyed on (topic, market), so the
           blue-sky path costs one fetch per DISTINCT AUDIENCE (~13 of them) per ttl
           window, not one per call.
        4. cache write is atomic via a `.tmp` sibling + `os.replace`, so a concurrently-
           starting lane never observes a torn JSON file.
        5. every step is wrapped — a corrupt cache is a cold cache, never an error; a
           failing fetch is logged and treated as no brief; an unwritable cache is logged
           and the fresh brief is still returned."""
    icfg = (getattr(cfg, "generation", {}) or {}).get("incumbent_seed", {}) or {}
    if not icfg.get("enabled", False):
        return ""
    try:
        topic = _topic(signal_text, sector, audience)
        if not topic:
            logger.info("incumbent_seed: no topic (empty signal and sector), skipping")
            return ""
        path = generation_artifact_dir(cfg) / "incumbent_cache.json"
        key = _cache_key(topic, market)
        ttl = float(icfg.get("cache_ttl_s", 604800))
        now = time.time()

        with _FETCH_LOCK:
            cache: dict = {}
            if path.exists():
                try:
                    cache = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    cache = {}  # a corrupt cache is a cold cache, never an error
            entry = cache.get(key)
            if entry and (now - float(entry.get("fetched_at", 0))) < ttl:
                return str(entry.get("brief", "") or "")

            brief = _fetch_brief(cfg, icfg, topic)
            cache[key] = {"fetched_at": now, "topic": topic, "brief": brief}

            # Prune to the freshest 200 — protects against an unbounded file under long-tail
            # topics. Cheaper than an LRU and good enough: a stale entry just re-fetches on
            # the next hit, which the ttl already bounds.
            if len(cache) > 200:
                keep = sorted(cache.items(),
                              key=lambda kv: float(kv[1].get("fetched_at", 0)),
                              reverse=True)[:200]
                cache = dict(keep)

            # Atomic write — a plain write_text here would be a torn read for a concurrently-
            # starting lane. .tmp sibling + os.replace gives POSIX-atomic rename.
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(cache), encoding="utf-8")
                os.replace(tmp, path)
            except Exception as e:
                # Cache write is best-effort; we still return the fresh brief.
                logger.warning(f"incumbent_seed cache write failed, returning brief anyway: {e}")

            return brief
    except Exception as e:
        logger.warning(f"incumbent_seed failed, skipping: {e}")
        return ""
