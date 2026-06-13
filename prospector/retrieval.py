"""Grounding (Part 4 'source-or-die'). Real web evidence via Gemini's built-in
Google Search grounding — returns resolvable URLs + passages.

Layers (Part 9 three-layer cache + graceful degradation):
  - GeminiGroundingProvider: live search+fetch in one call (google_search tool).
  - FixtureProvider: canned passages for tests / golden set (no network).
  - DiskCache: content-addressed cache wrapping any provider.
Any failure returns [] so the caller downgrades that check to `unverifiable`,
never crashing the run.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
import urllib.request

from .errors import ProviderExhaustedError
from .models import Source
from .telemetry import track_latency, logger

CACHE_DIR = Path(__file__).resolve().parent.parent / "store" / "_cache"


class SearchProvider(ABC):
    @abstractmethod
    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        """Return up to k grounded passages. MUST return [] on failure, not raise."""
        ...


def _resolve(url: str, timeout: float = 5.0) -> Optional[str]:
    """Best-effort: follow redirects to a canonical URL. 
    Returns None on any connection failure or non-2xx response."""
    try:
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "Mozilla/5.0 prospector"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if 200 <= r.status < 300:
                return r.url or url
            return None
    except Exception:
        return None


class GeminiGroundingProvider(SearchProvider):
    def __init__(self, model: str = "gemini-2.0-flash", api_key: Optional[str] = None,
                 resolve_urls: bool = True):
        from google import genai
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY not set")
        self._client = genai.Client(api_key=key)
        self.model = model
        self.resolve_urls = resolve_urls

    @track_latency(name="gemini_grounding_search")
    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        logger.info(f"Grounding search started: {query!r}", extra={"query": query, "k": k})
        try:
            from google.genai import types
            resp = self._client.models.generate_content(
                model=self.model,
                contents=(f"Search the web for evidence about: {query}\n"
                          "Summarise the most relevant findings, citing the sources."),
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.0),
            )
        except Exception as e:
            logger.warning(f"Grounding search failed: {e}", extra={"error": str(e)})
            return []

        sources: list[Source] = []
        try:
            cand = resp.candidates[0]
            gm = getattr(cand, "grounding_metadata", None)
            chunks = list(getattr(gm, "grounding_chunks", None) or [])
            summary = (resp.text or "")[:max_chars]
            for ch in chunks[:k]:
                web = getattr(ch, "web", None)
                if not web or not getattr(web, "uri", None):
                    continue
                
                url = web.uri
                if self.resolve_urls:
                    resolved = _resolve(web.uri)
                    if not resolved:
                        logger.warning("Dropping dead grounding URL", extra={"url": web.uri})
                        continue
                    url = resolved
                
                title = getattr(web, "title", "") or ""
                text = (f"{title}. {summary}".strip())[:max_chars]
                sources.append(Source.make(url=url, text=text, query=query))
            # fallback: no chunks but we have grounded text -> single unsourced-ish note
            if not sources and summary:
                # no resolvable URL => not a citable Source; drop (source-or-die).
                logger.info("Search summary found but no resolvable chunks", extra={"query": query})
                return []
        except Exception as e:
            logger.warning(f"Failed to parse search results: {e}", extra={"error": str(e)})
            return []
            
        logger.info(f"Grounding search returned {len(sources)} sources", extra={"count": len(sources)})
        return sources


class FixtureProvider(SearchProvider):
    """Serves canned passages keyed by substring match on the query. For tests and
    the golden set so grounding is deterministic and offline."""
    def __init__(self, fixtures: dict[str, list[dict]] | None = None,
                 path: str | Path | None = None):
        data = fixtures or {}
        if path:
            data = json.loads(Path(path).read_text())
        self._fixtures = data

    @track_latency(name="fixture_search")
    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        q = query.lower()
        for key, items in self._fixtures.items():
            if key.lower() in q or q in key.lower():
                results = [Source.make(url=i["url"], text=i["text"][:max_chars],
                                    published_at=i.get("published_at"), query=query)
                        for i in items[:k]]
                logger.info(f"Fixture search match for {key!r}", extra={"query": query, "count": len(results)})
                return results
        return []


class DiskCache(SearchProvider):
    """Content-addressed cache over any provider (Part 9). Misses delegate; hits
    are served from store/_cache/<sha>.json."""
    def __init__(self, inner: SearchProvider, cache_dir: Path = CACHE_DIR):
        self.inner = inner
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, query: str, k: int, max_chars: int) -> Path:
        h = hashlib.sha1(f"{query}|{k}|{max_chars}".encode()).hexdigest()[:20]
        return self.cache_dir / f"{h}.json"

    @track_latency(name="cached_search")
    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        p = self._path(query, k, max_chars)
        if p.exists():
            try:
                results = [Source(**d) for d in json.loads(p.read_text())]
                logger.info("Search cache hit", extra={"query": query, "count": len(results)})
                return results
            except Exception as e:
                logger.warning(f"Failed to read search cache: {e}", extra={"path": str(p)})
                pass
        
        logger.info("Search cache miss", extra={"query": query})
        results = self.inner.search(query, k, max_chars)
        if results:  # never cache empty/failed results
            p.write_text(json.dumps([s.to_dict() for s in results], ensure_ascii=False))
        return results


class FallbackSearchProvider(SearchProvider):
    """Chain of grounding providers with quota-aware failover (Part 9 resilience).

    A search tries each provider in order. When one fails *persistently* (it already
    did its own internal retries) the provider is RETIRED for the rest of this run and
    the next one takes over — so a mid-run quota/credit exhaustion on one LLM is
    transparently replaced by the next. A legitimate empty result ([]) from a WORKING
    provider is returned as-is (no failover — that's real evidence of nothing).

    Only when EVERY provider is retired does search() raise — which run_check turns
    into a DEFER (re-vet later), never a false kill.
    """
    def __init__(self, providers: list[tuple[str, SearchProvider]]):
        if not providers:
            raise ValueError("FallbackSearchProvider needs at least one provider")
        self.providers = providers
        self._dead: set[str] = set()      # provider names retired for this run
        self._lock = threading.Lock()

    @track_latency(name="fallback_search")
    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        last_err: Optional[Exception] = None
        for name, prov in self.providers:
            with self._lock:
                if name in self._dead:
                    continue
            try:
                return prov.search(query, k=k, max_chars=max_chars)
            except Exception as e:
                last_err = e
                exhausted = isinstance(e, ProviderExhaustedError)
                with self._lock:
                    self._dead.add(name)   # retire on persistent failure (run-scoped)
                logger.warning(
                    f"Grounding provider {name!r} {'exhausted' if exhausted else 'failed'}; "
                    f"failing over to next",
                    extra={"provider": name, "exhausted": exhausted, "error": str(e)[:200]})
        # Every provider is retired — propagate so run_check defers (not a kill).
        raise ProviderExhaustedError(
            f"all grounding providers exhausted/failed: {last_err}",
            provider="+".join(n for n, _ in self.providers))


def _build_search(name: str, cfg, fixtures: dict | None) -> SearchProvider:
    r = cfg.retrieval
    if name == "fixture":
        return FixtureProvider(fixtures=fixtures)
    if name == "gemini_cli":
        from .gemini_cli import GeminiCliGroundingProvider
        # Grounding is a web SEARCH (fetch URLs+passages), not reasoning — use the fast
        # model. gemini-2.5-pro's grounded search is heavy and times out (~240s); flash-lite
        # returns the same passages in seconds. The capable model is reserved for the verdict.
        return GeminiCliGroundingProvider(model=(cfg.model_fast or cfg.model or None),
                                          timeout=r.search_timeout, retries=r.search_retries)
    if name == "claude_cli":
        from .claude_cli import ClaudeCliGroundingProvider
        return ClaudeCliGroundingProvider(timeout=max(r.search_timeout, 120),
                                          retries=r.search_retries)
    if name == "gemini_grounding":
        return GeminiGroundingProvider(model=cfg.model if cfg.operator == "gemini"
                                       else "gemini-2.0-flash")
    raise ValueError(f"unknown retrieval provider: {name!r}")


def make_provider(cfg, fixtures: dict | None = None) -> SearchProvider:
    # provider may be a single name or an ordered fallback chain.
    names = cfg.retrieval.provider
    names = [names] if isinstance(names, str) else list(names)
    built = [(n, _build_search(n, cfg, fixtures)) for n in names]
    base: SearchProvider = (built[0][1] if len(built) == 1
                            else FallbackSearchProvider(built))
    return DiskCache(base) if cfg.retrieval.cache else base
