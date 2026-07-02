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
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
import re
import urllib.error
import urllib.parse
import urllib.request

from .breaker import CircuitBreaker
from .errors import FixtureMiss, ProviderExhaustedError, ProviderUnavailable, SearchProviderError
from .models import Source
from .telemetry import track_latency, logger, record_usage
from .audit import audit

CACHE_DIR = Path(__file__).resolve().parent.parent / "store" / "_cache"

# Minimum word-overlap ratio for FixtureProvider word-level matching.
# Set to 0 to always pick the best-overlap key (useful when fixture keys are short
# and queries include idea-title + check-keywords where overlap is low).
_FIXTURE_MIN_MATCH_RATIO = 0.0

# Stopwords stripped from fixture keys before scoring (reduces noise from "OR", "AND" etc.)
_FIXTURE_STOP = {"or", "and", "the", "a", "an", "of", "in", "for", "to", "with", "on", "by"}

# Stemmer for fixture word-level matching. Lazily initialised on first use.
_stemmer: "PorterStemmer" | None = None


def _stem(word: str) -> str:
    """Porter-stem a word for fixture key matching. Handles "incumbency"→"incumb",
    "competitors"→"competitor", etc."""
    global _stemmer
    if _stemmer is None:
        try:
            from nltk.stem import PorterStemmer
            _stemmer = PorterStemmer()
        except Exception:
            _stemmer = False  # type: ignore[assignment] — no stemming available
    if _stemmer:
        return _stemmer.stem(word.lower())
    return word.lower()


class SearchProvider(ABC):
    @abstractmethod
    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        """Return up to k grounded passages. MUST return [] on failure, not raise."""
        ...


# FIX #9: 4s timeout. Sites that don't respond to HEAD in 4s are typically
# genuinely unresponsive — we shouldn't wait longer. (Was 2s, but real journalism
# sites behind a CDN sometimes need a beat to answer even a fast bot-reject.)
_RESOLVE_TIMEOUT = 4.0

# Tiered timeout for high-authority sources (Part 16 principal upgrade).
# Authoritative sites often have heavy CDNs or bot-mitigation that can take
# longer to answer a HEAD request. We give them 15s to ensure we don't drop
# the best evidence due to transient latency.
_HIGH_AUTHORITY_TIMEOUT = 15.0

_HIGH_AUTHORITY_DOMAINS = {
    "ft.com", "reuters.com", "bloomberg.com", "wsj.com", "economist.com",
    "nytimes.com", "theguardian.com", "bbc.co.uk", "bbc.com", "hbr.org",
    "nature.com", "science.org", "mit.edu", "stanford.edu", "harvard.edu",
    "gov.uk", "europa.eu", "un.org", "worldbank.org", "imf.org", "nih.gov",
    "who.int", "gartner.com", "forrester.com", "mckinsey.com", "deloitte.com",
}

def _get_timeout(url: str) -> float:
    """Determine timeout based on domain authority (Domain-Aware Patience)."""
    try:
        parsed = urllib.parse.urlparse(url.lower())
        netloc = parsed.netloc
        if netloc.startswith("www."):
            netloc = netloc[4:]
        
        # TLD-based authority
        if netloc.endswith(".gov") or netloc.endswith(".edu") or netloc.endswith(".int"):
            return _HIGH_AUTHORITY_TIMEOUT
            
        # Domain-list authority
        if any(netloc == d or netloc.endswith("." + d) for d in _HIGH_AUTHORITY_DOMAINS):
            return _HIGH_AUTHORITY_TIMEOUT
    except Exception:
        pass
    return _RESOLVE_TIMEOUT

# A real browser UA, not "Mozilla/5.0 prospector": many CDNs (Cloudflare et al.)
# 403 obviously-bot agents on sight, which dropped legitimate sources.
_RESOLVE_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

def _resolve(url: str, timeout: Optional[float] = None) -> Optional[str]:
    """Confirm a grounding URL is REAL (not fabricated). Under web=True the CLI
    grounds on a live Google Search, so URLs come from Google's index, not model
    hallucination — the real fabrication signal is a made-up HOST (DNS failure),
    not a bad path. Authoritative sites (Reuters/Nature/FT) bot-wall a HEAD with a
    404/401/403 for REAL and fake paths alike, so exact-path HTTP validation
    cannot tell them apart and only ever false-drops real evidence. So: any HTTP
    response (2xx/3xx/4xx/5xx) proves the host is real → KEEP; only a host that
    gives NO response at all (DNS failure, refused, timeout) or a malformed URL is
    treated as fabricated/dead → DROP. Returns the canonical URL or None."""
    if not url.lower().startswith(("http://", "https://")):
        return None
    
    # Use tiered timeout if none provided (Domain-Aware Patience)
    to = timeout if timeout is not None else _get_timeout(url)
    
    req = urllib.request.Request(url, method="HEAD",
                                 headers={"User-Agent": _RESOLVE_UA})
    try:
        with urllib.request.urlopen(req, timeout=to) as r:
            return r.url or url
    except urllib.error.HTTPError:
        # The server RESPONDED with an error code — the host is real (bot-wall,
        # paywall, moved path). Under live grounding this is a real source; keep it.
        return url
    except Exception:
        # No HTTP response at all (DNS failure, connection refused, timeout):
        # the host is dead/fabricated. results_per_query redundancy covers the
        # rare real-but-slow host we drop here.
        return None


def resolve_sources(items: list[dict], query: str, max_chars: int, k: int) -> list[Source]:
    """Validate up to k grounding-result URLs IN PARALLEL and build Sources,
    dropping dead/fabricated URLs (source-or-die). Each _resolve() is an independent,
    side-effect-free HEAD request, so running them concurrently is pure latency — the
    drop-dead-URL outcome and the result ORDER are identical to resolving serially.
    Used by the CLI grounding provider (claude)."""
    cand = [it for it in (items or [])[:k] if str(it.get("url", ""))]
    if not cand:
        return []
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=len(cand)) as ex:
        resolved = list(ex.map(
            lambda it: _resolve(str(it.get("url", "")), timeout=_RESOLVE_TIMEOUT), cand))
    out: list[Source] = []
    for it, r in zip(cand, resolved):
        if not r:
            logger.warning("Dropping fabricated/dead URL", extra={"url": it.get("url")})
            continue
        out.append(Source.make(url=r, text=str(it.get("text", ""))[:max_chars],
                               published_at=it.get("published_at"), query=query))
    return out


class GeminiGroundingProvider(SearchProvider):
    """DEPRECATED — replaced by AgyCliGroundingProvider.
    Google grounding via google-genai SDK. Kept for reference; not wired in the
    grounding provider factory."""
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
    the golden set so grounding is deterministic and offline.

    Args:
        fixtures: Dict of claim-key → list of fixture items (url, text, published_at).
        path: Alternative to fixtures — load from a JSON file.
        raise_on_miss: When True (default), raises FixtureMiss if no entry matches.
            FallbackSearchProvider catches FixtureMiss and falls through to the next tier.
            When False (standalone mode), returns [] on miss — suitable for tests
            where FixtureProvider is the only provider and [] is a valid result.
    """
    def __init__(self, fixtures: dict[str, list[dict]] | None = None,
                 path: str | Path | None = None,
                 raise_on_miss: bool = False):
        data = fixtures or {}
        if path:
            data = json.loads(Path(path).read_text())
        self._fixtures = data
        self._raise_on_miss = raise_on_miss

    @track_latency(name="fixture_search")
    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        """Match using stemmed word-level similarity: split query and key into
        stemmed words, require that ≥MIN_MATCH_RATIO of the key's words appear in
        the query (post-stemming).

        Handles word variations robustly:
          - "incumbency" / "incumbent" both stem to "incumb"
          - "competitors" / "competitor" both stem to "competitor"
          - Hyphens/spaces normalised (re-split on non-alphanumeric)
          - Empty-string key acts as catch-all fallback (matches any query).
        """
        record_usage(web=True, provider="fixture")
        start = time.monotonic()
        try:
            # Catch-all: empty-string key matches everything.
            if "" in self._fixtures:
                items = self._fixtures[""]
                results = [Source.make(url=i["url"], text=i["text"][:max_chars],
                                    published_at=i.get("published_at"), query=query)
                        for i in items[:k]]
                logger.info(f"Fixture match: '' (catch-all, query={query!r})")
                audit("search", provider="fixture", query=query[:200], k=k,
                      max_chars=max_chars, returned_n=len(results),
                      latency_ms=int((time.monotonic() - start) * 1000),
                      status="ok" if results else "empty")
                return results

            q_words = {_stem(w) for w in re.split(r'[^\w]+', query) if w}
            best_key: str | None = None
            best_score = 0.0

            for key, items in self._fixtures.items():
                k_words = [_stem(w) for w in re.split(r'[^\w]+', key)
                            if w and w.lower() not in _FIXTURE_STOP]
                if not k_words:
                    continue
                overlap = sum(1 for w in k_words if w in q_words)
                score = overlap / len(k_words)
                if score >= _FIXTURE_MIN_MATCH_RATIO and score > best_score:
                    best_score = score
                    best_key = key

            if best_key is not None:
                items = self._fixtures[best_key]
                results = [Source.make(url=i["url"], text=i["text"][:max_chars],
                                    published_at=i.get("published_at"), query=query)
                        for i in items[:k]]
                logger.info(f"Fixture match: {best_key!r} (score={best_score:.0%}, query={query!r})")
                audit("search", provider="fixture", query=query[:200], k=k,
                      max_chars=max_chars, returned_n=len(results),
                      latency_ms=int((time.monotonic() - start) * 1000),
                      status="ok" if results else "empty")
                return results

            if self._raise_on_miss:
                raise FixtureMiss(f"no fixture entry matched query: {query!r}")
            audit("search", provider="fixture", query=query[:200], k=k,
                  max_chars=max_chars, returned_n=0,
                  latency_ms=int((time.monotonic() - start) * 1000),
                  status="empty")
            return []
        except Exception as e:
            audit("search", provider="fixture", query=query[:200], k=k,
                  max_chars=max_chars, returned_n=0,
                  latency_ms=int((time.monotonic() - start) * 1000),
                  status="error", error=str(e)[:200])
            raise


# ---------------------------------------------------------------------------
# External API search providers (grounding resilience chain)
# These kick in when the primary grounding providers (claude_cli) are all exhausted. Each must return list[Source] on
# success, [] on failure — never raise, so the FallbackSearchProvider can
# continue to the next tier.
# ---------------------------------------------------------------------------

class BraveSearchProvider(SearchProvider):
    """Brave Search API — 2,000 queries/month on the free tier.

    Real web search results, no model hallucination risk. Configure with:
      BRAVE_API_KEY=<your-key>  (free key at https://api.search.brave.com/)

    The provider is skipped (returns []) if BRAVE_API_KEY is not set, so it
    integrates cleanly into the FallbackSearchProvider chain as a no-op when
    unconfigured rather than a hard failure.
    """

    _BASE_URL = "https://api.search.brave.com/res/v1/web/search"
    _UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

    def __init__(self, api_key: str | None = None, resolve_urls: bool = True):
        self._key = api_key or os.environ.get("BRAVE_API_KEY", "")
        self.resolve_urls = resolve_urls
        self._configured = bool(self._key)

    @track_latency(name="brave_search")
    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        if not self._configured:
            logger.debug("BraveSearchProvider: BRAVE_API_KEY not set, skipping")
            raise ProviderUnavailable("BRAVE_API_KEY not set")
        record_usage(web=True, provider="brave")
        start = time.monotonic()
        try:
            url = (f"{self._BASE_URL}"
                   f"?q={urllib.parse.quote(query)}&count={min(k, 10)}"
                   f"&safesearch=Off&extra_http_params=accept_language%3Den-US")
            req = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": self._UA,
                    "X-Subscriber-Key": self._key,
                })
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
        except Exception as e:
            logger.warning(f"Brave search failed: {e}")
            audit("search", provider="brave", query=query[:200], k=k,
                  max_chars=max_chars, returned_n=0,
                  latency_ms=int((time.monotonic() - start) * 1000),
                  status="error", error=str(e)[:200])
            return []

        results: list[Source] = []
        try:
            raw = (data.get("web", {}) or {}).get("results", [])
            for item in raw[:k]:
                url = str(item.get("url", ""))
                if not url:
                    continue
                if self.resolve_urls:
                    resolved = _resolve(url)
                    if not resolved:
                        logger.warning("Brave: dropping dead URL", extra={"url": url})
                        continue
                    url = resolved
                title = str(item.get("title", ""))[:200]
                desc = str(item.get("description", ""))[:max_chars]
                snippet = (f"{title}. {desc}".strip())[:max_chars]
                results.append(Source.make(url=url, text=snippet, query=query))
        except Exception as e:
            logger.warning(f"Brave parse error: {e}")
            audit("search", provider="brave", query=query[:200], k=k,
                  max_chars=max_chars, returned_n=0,
                  latency_ms=int((time.monotonic() - start) * 1000),
                  status="error", error=str(e)[:200])
            return []

        logger.info(f"Brave search: {len(results)} results for {query!r}",
                    extra={"query": query, "count": len(results)})
        audit("search", provider="brave", query=query[:200], k=k,
              max_chars=max_chars, returned_n=len(results),
              latency_ms=int((time.monotonic() - start) * 1000),
              status="ok" if results else "empty")
        return results


class ExaSearchProvider(SearchProvider):
    """Exa Search API — free tier (1,000–20,000 queries/month, no credit card).

    Real web search with highlights/snippets returned directly — no URL hallucination
    risk of LLM synthesis. Configure with:
      EXA_API_KEY=<your-key>  (free key at https://dashboard.exa.ai/api-keys)

    The provider is skipped (returns []) if EXA_API_KEY is not set, so it
    integrates cleanly into the FallbackSearchProvider chain as a no-op when
    unconfigured rather than a hard failure.
    """
    @track_latency(name="exa_search")
    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        key = os.environ.get("EXA_API_KEY", "")
        if not key:
            logger.debug("ExaSearchProvider: EXA_API_KEY not set, skipping")
            raise ProviderUnavailable("EXA_API_KEY not set")
        record_usage(web=True, provider="exa")
        start = time.monotonic()
        try:
            from exa_py import Exa
            exa = Exa(api_key=key)
            result = exa.search(query, num_results=min(k, 10))
            results: list[Source] = []
            for item in (result.results or []):
                url = getattr(item, "url", None) or ""
                if not url:
                    continue
                resolved = _resolve(url)
                if not resolved:
                    continue
                # Use full page text (exceeds max_chars, caller/truncate handles it)
                text = (getattr(item, "text", None) or "").strip()[:max_chars]
                if text:
                    results.append(Source.make(url=resolved, text=text, query=query))
            logger.info(f"Exa search: {len(results)} results for {query!r}",
                        extra={"query": query, "count": len(results)})
            audit("search", provider="exa", query=query[:200], k=k,
                  max_chars=max_chars, returned_n=len(results),
                  latency_ms=int((time.monotonic() - start) * 1000),
                  status="ok" if results else "empty")
            return results
        except Exception as e:
            # A transport/auth/API error is NOT "zero evidence". Swallowing it into [] makes the
            # FallbackSearchProvider read a dead provider as a successful empty result and STOP —
            # never failing over to brave/claude_cli. That is exactly how a bad
            # EXA_API_KEY silently zeroed grounding (every check -> unverifiable, conf ~0.40).
            # Propagate so the chain fails over, and if every provider is down it DEFERs (+alerts).
            logger.warning(f"Exa search error: {e}; failing over to next provider")
            audit("search", provider="exa", query=query[:200], k=k,
                  max_chars=max_chars, returned_n=0,
                  latency_ms=int((time.monotonic() - start) * 1000),
                  status="error", error=str(e)[:200])
            raise




class TavilySearchProvider(SearchProvider):
    """Tavily Search API — real web search, simple REST API.

    Free tier: 1,000 queries/month. Configure with:
      TAVILY_API_KEY=<your-key>  (free key at https://app.tavily.com)

    Returns real URLs with content snippets — no URL hallucination risk.
    HTTP 402/401/429 errors re-raise so the FallbackSearchProvider fails over.
    """
    @track_latency(name="tavily_search")
    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        key = os.environ.get("TAVILY_API_KEY", "")
        if not key:
            logger.debug("TavilySearchProvider: TAVILY_API_KEY not set, skipping")
            raise ProviderUnavailable("TAVILY_API_KEY not set")
        record_usage(web=True, provider="tavily")
        start = time.monotonic()
        try:
            payload = json.dumps({
                "query": query,
                "search_depth": "basic",
                "max_results": min(k, 10),
                "include_answer": False,
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.tavily.com/search",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {key}",
                },
            )
            resp = urllib.request.urlopen(req, timeout=30)
            data = json.loads(resp.read().decode("utf-8"))
            results: list[Source] = []
            for item in (data.get("results") or []):
                url = item.get("url", "")
                if not url:
                    continue
                resolved = _resolve(url)
                if not resolved:
                    continue
                text = (item.get("content") or "").strip()[:max_chars]
                if text:
                    results.append(Source.make(url=resolved, text=text, query=query))
            logger.info(f"Tavily search: {len(results)} results for {query!r}",
                        extra={"query": query, "count": len(results)})
            audit("search", provider="tavily", query=query[:200], k=k,
                  max_chars=max_chars, returned_n=len(results),
                  latency_ms=int((time.monotonic() - start) * 1000),
                  status="ok" if results else "empty")
            return results
        except Exception as e:
            logger.warning(f"Tavily search error: {e}; failing over to next provider")
            audit("search", provider="tavily", query=query[:200], k=k,
                  max_chars=max_chars, returned_n=0,
                  latency_ms=int((time.monotonic() - start) * 1000),
                  status="error", error=str(e)[:200])
            raise



class SearXNGSearcher(SearchProvider):
    """SearXNG — self-hosted metasearch, keyless, unlimited.

    Queries the local SearXNG container at SEARXNG_URL (default localhost:8080).
    Aggregates results from DuckDuckGo, Bing, Brave etc. with no API key,
    no credits, no quota. This is the load-bearing primary provider.

    Docker: docker compose -f searxng/docker-compose.yml up -d
    Must have format=json enabled in settings.yml and limiter: false.
    """
    def __init__(self, base_url: str | None = None, timeout: float = 6.0):
        # timeout is a HARD ceiling on the whole HTTP round-trip. Kept tight (6s) so a
        # SearXNG whose upstream engines are hanging fails over fast instead of stalling
        # every check on a dead metasearch. Per-engine patience is set separately in
        # searxng/settings.yml (outgoing.request_timeout) so SearXNG itself gives up on
        # blocked engines in ~2.5s and returns.
        self.base = (base_url or os.environ.get("SEARXNG_URL", "http://localhost:8080")).rstrip("/")
        self.timeout = timeout

    @track_latency(name="searxng_search")
    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        record_usage(web=True, provider="searxng")
        start = time.monotonic()
        try:
            import urllib.request
            url = f"{self.base}/search?q={urllib.parse.quote(query)}&format=json"
            req = urllib.request.Request(url)
            resp = urllib.request.urlopen(req, timeout=self.timeout)
            data = json.loads(resp.read().decode("utf-8"))
            results: list[Source] = []
            for item in (data.get("results") or [])[:k]:
                result_url = item.get("url", "")
                if not result_url:
                    continue
                resolved = _resolve(result_url)
                if not resolved:
                    continue
                text = (item.get("content", "") or item.get("snippet", "") or "").strip()[:max_chars]
                if text:
                    results.append(Source.make(url=resolved, text=text, query=query))
            # Distinguish a WORKING-but-empty response (engines ran, found nothing — real
            # evidence of nothing) from a BROKEN-empty one (HTTP 200, but every upstream
            # engine timed out / was blocked). The latter is an infrastructure failure
            # masquerading as "found nothing"; returning [] would make FallbackSearchProvider
            # short-circuit and NEVER consult the next provider (ddg). Raise instead so the
            # fall-over-on-exception path fires AND the circuit breaker eventually retires a
            # persistently-dead SearXNG (so we stop paying its latency on every check).
            unresponsive = data.get("unresponsive_engines") or []
            if not results and unresponsive:
                msg = (f"SearXNG returned 0 results with {len(unresponsive)} unresponsive "
                       f"engine(s) {unresponsive[:4]} — treating as provider failure, not empty")
                logger.warning(f"{msg}; failing over to next provider")
                audit("search", provider="searxng", query=query[:200], k=k,
                      max_chars=max_chars, returned_n=0,
                      latency_ms=int((time.monotonic() - start) * 1000),
                      status="error", error=msg[:200])
                raise SearchProviderError(msg)
            logger.info(f"SearXNG search: {len(results)} results for {query!r}",
                        extra={"query": query, "count": len(results)})
            audit("search", provider="searxng", query=query[:200], k=k,
                  max_chars=max_chars, returned_n=len(results),
                  latency_ms=int((time.monotonic() - start) * 1000),
                  status="ok" if results else "empty")
            return results
        except Exception as e:
            logger.warning(f"SearXNG search error: {e}; failing over to next provider")
            audit("search", provider="searxng", query=query[:200], k=k,
                  max_chars=max_chars, returned_n=0,
                  latency_ms=int((time.monotonic() - start) * 1000),
                  status="error", error=str(e)[:200])
            raise

class DuckDuckGoSearchProvider(SearchProvider):
    """DuckDuckGo search via ddgs library — free, keyless, no account needed.

    Uses the duckduckgo-search Python library which scrapes DuckDuckGo's HTML
    (not an official API). Rate-limited by DuckDuckGo if abused, but as a
    bottom-rung fallback for a personal daemon this is acceptable.

    Returns real URLs with snippets. No API key, no credits, no expiration.
    """
    @track_latency(name="ddg_search")
    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        record_usage(web=True, provider="ddg")
        start = time.monotonic()
        try:
            from ddgs import DDGS
            # ddgs 9.x's underlying primp/impersonation client throws transient
            # FakeUserAgentError / SystemError("...Client...returned a result with an
            # exception set") on its FIRST call in a process with non-trivial frequency;
            # a plain retry succeeds (proven: attempt #2 returns relevant gov.uk pages).
            # Retry up to 3x so a flaky first call doesn't blind the only working free
            # fallback. Real "no results" returns [] on attempt 1 and is kept as-is.
            raw: list = []
            last_exc: Optional[Exception] = None
            for attempt in range(3):
                try:
                    with DDGS() as ddgs:
                        raw = list(ddgs.text(query, max_results=min(k, 10)))
                    last_exc = None
                    break
                except Exception as e:  # noqa: BLE001 — transient primp/UA flakiness
                    last_exc = e
                    logger.info(f"DDG attempt {attempt + 1}/3 transient error: "
                                f"{type(e).__name__}: {str(e)[:120]}")
            if last_exc is not None:
                raise last_exc
            results: list[Source] = []
            for item in raw:
                url = item.get("href", "") or item.get("url", "")
                if not url:
                    continue
                resolved = _resolve(url)
                if not resolved:
                    continue
                text = (item.get("body", "") or item.get("description", "") or "").strip()[:max_chars]
                if text:
                    results.append(Source.make(url=resolved, text=text, query=query))
            logger.info(f"DDG search: {len(results)} results for {query!r}",
                        extra={"query": query, "count": len(results)})
            audit("search", provider="ddg", query=query[:200], k=k,
                  max_chars=max_chars, returned_n=len(results),
                  latency_ms=int((time.monotonic() - start) * 1000),
                  status="ok" if results else "empty")
            return results
        except Exception as e:
            logger.warning(f"DDG search error: {e}; failing over to next provider")
            audit("search", provider="ddg", query=query[:200], k=k,
                  max_chars=max_chars, returned_n=0,
                  latency_ms=int((time.monotonic() - start) * 1000),
                  status="error", error=str(e)[:200])
            raise

class _LLMSearchProvider(SearchProvider):
    """Base class for LLM-backed search providers that synthesize web-grounded
    evidence using model intelligence + citation validation.

    Strategy:
    1. Model decomposes the query into focused sub-queries (function calling)
       and/or synthesises a response with inline citations.
    2. Extracted URLs are validated via _resolve(); dead URLs are dropped.
    3. Synthesised text is returned as a last-resort Source (no URL) so the
       moat at least has something to rule on rather than always returning []
       (which would make every candidate unverifiable).

    Subclasses override _call_search() to use a specific model/API.
    """

    model_name: str = ""
    provider_name: str = ""

    SYSTEM_PROMPT = (
        "You are a research assistant. For the query below, provide a concise "
        "summary (3-5 sentences) citing specific facts. Include URLs to "
        "authoritative sources (government sites, industry reports, news). "
        "Format URLs on their own line like: SOURCE: https://...")

    def __init__(self, model_name: str = "", resolve_urls: bool = True,
                 max_chars: int = 1500):
        # `model_name` is config-driven (passed by the factory from
        # cfg.model_defaults.search.<provider>). The class-level attribute
        # is preserved as a fallback so subclasses can still be constructed
        # without config in tests.
        if model_name:
            self.model_name = model_name
        self.resolve_urls = resolve_urls
        self.max_chars = max_chars

    @track_latency(name="llm_synthesis_search")
    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        record_usage(web=True, provider=self.provider_name or "llm_search")
        start = time.monotonic()
        try:
            text, sources = self._call_search(query)
            results: list[Source] = []

            # Extract and validate URLs from the response
            urls = re.findall(r'https?://[^\s\)\;\,\]\'"\'>]+', text)
            for raw_url in urls[:k]:
                url = raw_url.rstrip(".,;:)")
                if self.resolve_urls:
                    resolved = _resolve(url)
                    if not resolved:
                        logger.warning(f"{self.provider_name}: dropping dead URL", extra={"url": url})
                        continue
                    url = resolved
                # Find the sentence containing this URL
                for line in text.split("\n"):
                    if url in line:
                        snippet = line.strip()[:max_chars]
                        break
                else:
                    snippet = text[:max_chars]
                results.append(Source.make(url=url, text=snippet, query=query))

            # Fallback: if no valid URLs, return the synthesis as an unsourced Source
            # (better than [] — the moat can still rule on the content)
            if not results and text.strip():
                logger.info(f"{self.provider_name}: no valid URLs; returning synthesis as unsourced source",
                            extra={"query": query})
                results.append(Source.make(
                    url=f"synthesized://{self.provider_name}/knowledge",
                    text=text.strip()[:max_chars],
                    query=query))

            logger.info(f"{self.provider_name} synthesis: {len(results)} sources for {query!r}",
                        extra={"query": query, "count": len(results)})
            audit("search", provider=self.provider_name or "llm_search",
                  query=query[:200], k=k, max_chars=max_chars,
                  returned_n=len(results),
                  latency_ms=int((time.monotonic() - start) * 1000),
                  status="ok" if results else "empty")
            return results
        except Exception as e:
            audit("search", provider=self.provider_name or "llm_search",
                  query=query[:200], k=k, max_chars=max_chars,
                  returned_n=0,
                  latency_ms=int((time.monotonic() - start) * 1000),
                  status="error", error=str(e)[:200])
            raise

    def _call_search(self, query: str) -> tuple[str, list[dict]]:
        raise NotImplementedError


class DeepSeekSearchProvider(_LLMSearchProvider):
    """DeepSeek function-calling search for grounding resilience.

    Uses DeepSeek's strict function-calling beta API to decompose the query into
    focused sub-searches, execute them via Brave (if configured) or DDG, then
    synthesise the results into a grounded response.

    Falls back to pure synthesis (no live search) if no external search backend
    is available — still useful because DeepSeek's training covers recent data.
    """

    # The model name is config-driven (cfg.model_defaults.search.deepseek).
    # The factory passes it as a constructor arg. The class-level attribute
    # is left empty as a fallback for tests that don't construct via factory.
    provider_name = "deepseek"
    _BASE_URL = "https://api.deepseek.com/beta"

    SEARCH_TOOL = {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Execute a web search and return structured results (title, URL, snippet).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                    "num_results": {"type": "integer", "description": "Number of results", "default": 5},
                },
                "required": ["query"],
            },
        },
    }

    def __init__(self, api_key: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self._key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self._configured = bool(self._key)
        self._brave_key = os.environ.get("BRAVE_API_KEY", "")

    def _call_search(self, query: str) -> tuple[str, list[dict]]:
        if not self._configured:
            return "", []
        try:
            payload = {
                "model": self.model_name,
                "messages": [
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": (
                        f"Research this query and return your findings with specific "
                        f"source URLs:\n\nQuery: {query}\n\n"
                        f"Decompose into 2-3 focused sub-searches using the web_search tool, "
                        f"then synthesise a response citing the sources found.")},
                ],
                "tools": [self.SEARCH_TOOL],
                "temperature": 0.0,
                "max_tokens": 1024,
            }
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{self._BASE_URL}/chat/completions",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._key}",
                })
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
                msg = data["choices"][0]["message"]
                tool_calls = msg.get("tool_calls", [])
                synthesis = msg.get("content", "") or ""
                # Execute tool calls and continue
                if tool_calls:
                    cont_messages = payload["messages"] + [msg]
                    for tc in tool_calls:
                        args = json.loads(tc["function"]["arguments"])
                        search_q = args.get("query", query)
                        results_text = self._execute_search(search_q)
                        cont_messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": results_text,
                        })
                    # Second turn: model synthesises with real search results
                    synthesis_payload = {
                        "model": self.model_name,
                        "messages": cont_messages + [{
                            "role": "user",
                            "content": "Based on the search results above, provide your synthesised answer citing specific URLs."
                        }],
                        "temperature": 0.0,
                        "max_tokens": 512,
                    }
                    body2 = json.dumps(synthesis_payload).encode("utf-8")
                    req2 = urllib.request.Request(
                        f"{self._BASE_URL}/chat/completions",
                        data=body2,
                        headers={"Content-Type": "application/json", "Authorization": f"Bearer {self._key}"})
                    with urllib.request.urlopen(req2, timeout=20) as r2:
                        data2 = json.loads(r2.read())
                        synthesis = data2["choices"][0]["message"].get("content", synthesis)
        except Exception as e:
            logger.warning(f"DeepSeek search failed: {e}")
            return "", []
        return synthesis, []

    def _execute_search(self, query: str) -> str:
        """Execute a search using Brave (preferred) or DDG HTML."""
        # Try Brave first
        if self._brave_key:
            try:
                url = (f"https://api.search.brave.com/res/v1/web/search"
                       f"?q={urllib.parse.quote(query)}&count=5")
                req = urllib.request.Request(
                    url,
                    headers={"Accept": "application/json",
                             "User-Agent": "Mozilla/5.0",
                             "X-Subscriber-Key": self._brave_key})
                with urllib.request.urlopen(req, timeout=10) as r:
                    data = json.loads(r.read())
                    results = (data.get("web", {}) or {}).get("results", [])
                    lines = [f"- {it.get('title','')}: {it.get('url','')} — {it.get('description','')[:100]}"
                             for it in results[:3]]
                    return "\n".join(lines) if lines else "(no results)"
            except Exception:
                pass
        # Fallback to DDG
        try:
            url = (f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 prospector/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                html = r.read().decode("utf-8", errors="ignore")
                lines = []
                for line in html.split("\n"):
                    if "<a class=" in line and "href=" in line:
                        import re as _re
                        txt = _re.sub(r"<[^>]+>", " ", line)
                        txt = " ".join(txt.split())
                        if len(txt) > 20:
                            lines.append(txt[:200])
                    if len(lines) >= 3:
                        break
                return "\n".join(lines) if lines else "(no results)"
        except Exception:
            return "(search failed)"


class MiniMaxSearchProvider(_LLMSearchProvider):
    """MiniMax-M3 search for grounding resilience.

    MiniMax-M3 has a built-in web search tool the model is trained to call.
    We use a two-turn function-calling loop: (1) model requests web_search calls,
    (2) we execute them via Brave (if configured) or DDG, (3) model synthesises
    the real results into a grounded response with citations.

    Falls back to pure synthesis if no external search backend is available.
    """

    # The model name is config-driven (cfg.model_defaults.search.minimax).
    # The factory passes it as a constructor arg. The class-level attribute
    # is left empty as a fallback for tests that don't construct via factory.
    provider_name = "minimax"
    _BASE_URL = "https://api.minimax.io/v1"

    SEARCH_TOOL = {
        "type": "function",
        "function": {
            "name": "web_search",
            "strict": True,
            "description": "Search the web for current information about any topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                    "num_results": {"type": "integer", "description": "Number of results", "default": 5},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    }

    def __init__(self, api_key: str | None = None, group_id: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self._key = api_key or os.environ.get("MINIMAX_API_KEY", "")
        self._grp = group_id or os.environ.get("MINIMAX_GROUP_ID", "")
        self._configured = bool(self._key)
        self._brave_key = os.environ.get("BRAVE_API_KEY", "")

    def _call_search(self, query: str) -> tuple[str, list[dict]]:
        if not self._configured:
            return "", []
        try:
            payload = {
                "model": self.model_name,
                "messages": [
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": (
                        f"Research this and return your findings with specific source URLs:\n"
                        f"Query: {query}\n\n"
                        f"Use the web_search tool to find real sources, then synthesise a response.")},
                ],
                "tools": [self.SEARCH_TOOL],
                "tool_choice": {"type": "function", "function": {"name": "web_search"}},
                "temperature": 0.0,
                "max_tokens": 1024,
            }
            body = json.dumps(payload).encode("utf-8")
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self._key}"}
            if self._grp:
                headers["GroupId"] = self._grp
            req = urllib.request.Request(
                f"{self._BASE_URL}/chat/completions",
                data=body,
                headers=headers)
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
                msg = data["choices"][0]["message"]
                tool_calls = msg.get("tool_calls", [])
                synthesis = msg.get("content", "") or ""
                if tool_calls:
                    cont_messages = payload["messages"] + [msg]
                    for tc in tool_calls:
                        args = json.loads(tc["function"]["arguments"])
                        search_q = args.get("query", query)
                        results_text = self._execute_search(search_q)
                        cont_messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": results_text,
                        })
                    synthesis_payload = {
                        "model": self.model_name,
                        "messages": cont_messages + [{
                            "role": "user",
                            "content": "Based on the search results, provide your synthesised answer citing specific URLs."
                        }],
                        "temperature": 0.0,
                        "max_tokens": 512,
                    }
                    body2 = json.dumps(synthesis_payload).encode("utf-8")
                    req2 = urllib.request.Request(
                        f"{self._BASE_URL}/chat/completions",
                        data=body2,
                        headers=headers)
                    with urllib.request.urlopen(req2, timeout=20) as r2:
                        data2 = json.loads(r2.read())
                        synthesis = data2["choices"][0]["message"].get("content", synthesis)
        except Exception as e:
            logger.warning(f"MiniMax search failed: {e}")
            return "", []
        return synthesis, []

    def _execute_search(self, query: str) -> str:
        if self._brave_key:
            try:
                url = (f"https://api.search.brave.com/res/v1/web/search"
                       f"?q={urllib.parse.quote(query)}&count=5")
                req = urllib.request.Request(
                    url,
                    headers={"Accept": "application/json",
                             "User-Agent": "Mozilla/5.0",
                             "X-Subscriber-Key": self._brave_key})
                with urllib.request.urlopen(req, timeout=10) as r:
                    data = json.loads(r.read())
                    results = (data.get("web", {}) or {}).get("results", [])
                    lines = [f"- {it.get('title','')}: {it.get('url','')} — {it.get('description','')[:100]}"
                             for it in results[:3]]
                    return "\n".join(lines) if lines else "(no results)"
            except Exception:
                pass
        try:
            url = (f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 prospector/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                html = r.read().decode("utf-8", errors="ignore")
                lines = []
                for line in html.split("\n"):
                    if "<a class=" in line and "href=" in line:
                        import re as _re
                        txt = _re.sub(r"<[^>]+>", " ", line)
                        txt = " ".join(txt.split())
                        if len(txt) > 20:
                            lines.append(txt[:200])
                    if len(lines) >= 3:
                        break
                return "\n".join(lines) if lines else "(no results)"
        except Exception:
            return "(search failed)"


class OpenRouterSearchProvider(_LLMSearchProvider):
    """OpenRouter search provider — Qwen 80B and Gemma 31B run entirely in
    OpenRouter's cloud, no download to your machine.

    Uses OpenRouter's free-tier models (qwen3-next-80b, gemma-4-31b) to
    synthesise a web-grounded response with citations. No function-calling needed:
    we prompt the model to include real source URLs in its response and validate
    them via _resolve().

    Falls back through OpenRouter's model pool automatically (per-model circuit
    breakers handle rate-limits within OpenRouterOperator itself).
    """

    # The model name is config-driven (cfg.model_defaults.search.openrouter).
    # The factory passes it as a constructor arg. The class-level attribute
    # is left empty as a fallback for tests that don't construct via factory.
    provider_name = "openrouter"
    _BASE_URL = "https://openrouter.ai/api/v1"

    SYSTEM_PROMPT = (
        "You are a research assistant. Provide a concise summary (3-5 sentences) of "
        "what you know about the query. Cite specific facts and include real source URLs "
        "where possible. Format sources as separate lines: SOURCE: https://...")

    def __init__(self, api_key: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self._key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self._configured = bool(self._key)
        self._brave_key = os.environ.get("BRAVE_API_KEY", "")

    def _call_search(self, query: str) -> tuple[str, list[dict]]:
        if not self._configured:
            return "", []
        try:
            payload = {
                "model": self.model_name,
                "messages": [
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": (
                        f"Research this query and provide your answer with specific source URLs:\n\n"
                        f"Query: {query}\n\n"
                        f"Include at least 2-3 specific URLs to authoritative sources.")},
                ],
                "temperature": 0.0,
                "max_tokens": 1024,
            }
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{self._BASE_URL}/chat/completions",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._key}",
                    "HTTP-Referer": "https://prospector.ai",
                    "X-Title": "Prospector",
                })
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
                content = data["choices"][0]["message"].get("content", "") or ""
                # If the model didn't cite URLs, supplement with a DDG search
                if not re.search(r"https?://", content):
                    supp = self._execute_search(query)
                    if supp and supp not in ("(search failed)", "(no results)"):
                        content += f"\n\nSearch results:\n{supp}"
        except Exception as e:
            logger.warning(f"OpenRouter search failed: {e}")
            return "", []
        return content, []

    def _execute_search(self, query: str) -> str:
        """Fallback: Brave (if key) or DDG HTML."""
        if self._brave_key:
            try:
                url = (f"https://api.search.brave.com/res/v1/web/search"
                       f"?q={urllib.parse.quote(query)}&count=5")
                req = urllib.request.Request(
                    url,
                    headers={"Accept": "application/json",
                             "User-Agent": "Mozilla/5.0",
                             "X-Subscriber-Key": self._brave_key})
                with urllib.request.urlopen(req, timeout=10) as r:
                    data = json.loads(r.read())
                    results = (data.get("web", {}) or {}).get("results", [])
                    lines = [f"- {it.get('title','')}: {it.get('url','')}"
                             for it in results[:3]]
                    return "\n".join(lines) if lines else "(no results)"
            except Exception:
                pass
        try:
            url = (f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 prospector/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                html = r.read().decode("utf-8", errors="ignore")
                lines = []
                for line in html.split("\n"):
                    if "<a class=" in line and "href=" in line:
                        txt = re.sub(r"<[^>]+>", " ", line)
                        txt = " ".join(txt.split())
                        if len(txt) > 20:
                            lines.append(txt[:200])
                    if len(lines) >= 3:
                        break
                return "\n".join(lines) if lines else "(no results)"
        except Exception:
            return "(search failed)"


class DiskCache(SearchProvider):
    """Content-addressed cache over any provider (Part 9). Misses delegate; hits
    are served from store/_cache/<sha>.json."""
    def __init__(self, inner: SearchProvider, cache_dir: Path = CACHE_DIR,
                 ttl_s: int = 0):
        self.inner = inner
        self.cache_dir = cache_dir
        # 0 disables expiry; otherwise a cache file older than ttl_s is a miss and
        # the page is re-grounded so a verdict never rules on stale evidence.
        self.ttl_s = ttl_s
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, query: str, k: int, max_chars: int) -> Path:
        h = hashlib.sha1(f"{query}|{k}|{max_chars}".encode()).hexdigest()[:20]
        return self.cache_dir / f"{h}.json"

    def _is_fresh(self, p: Path) -> bool:
        """A cache file is fresh if expiry is disabled or it is younger than ttl_s."""
        if self.ttl_s <= 0:
            return True
        try:
            return (time.time() - p.stat().st_mtime) < self.ttl_s
        except OSError:
            return False

    @track_latency(name="cached_search")
    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        record_usage(web=True, provider="cache")
        start = time.monotonic()
        p = self._path(query, k, max_chars)
        if p.exists() and self._is_fresh(p):
            try:
                results = [Source(**d) for d in json.loads(p.read_text())]
                logger.info("Search cache hit", extra={"query": query, "count": len(results)})
                audit("search", provider="cache", query=query[:200], k=k,
                      max_chars=max_chars, returned_n=len(results),
                      latency_ms=int((time.monotonic() - start) * 1000),
                      status="ok" if results else "empty", cache_hit=True)
                return results
            except Exception as e:
                logger.warning(f"Failed to read search cache: {e}", extra={"path": str(p)})
                pass

        logger.info("Search cache miss", extra={"query": query})
        results = self.inner.search(query, k, max_chars)
        # Cache writes only succeed when inner returned real results; empty
        # results stay uncached so a transient outage does not poison the cache.
        if results:
            try:
                p.write_text(json.dumps([s.to_dict() for s in results], ensure_ascii=False))
            except Exception as e:
                logger.warning(f"Failed to write search cache: {e}", extra={"path": str(p)})
        audit("search", provider="cache", query=query[:200], k=k,
              max_chars=max_chars, returned_n=len(results),
              latency_ms=int((time.monotonic() - start) * 1000),
              status="ok" if results else "empty", cache_hit=False)
        return results


class FallbackSearchProvider(SearchProvider):
    """Chain of grounding providers with circuit-breaker failover (Part 9 resilience).

    A search tries each provider in order, skipping any whose breaker is OPEN. A
    TRANSIENT failure (timeout / bad exit / queue saturation) counts toward the
    breaker's threshold but leaves the provider in service — one slow search no
    longer dead-lists it. A quota/credit EXHAUSTION trips the breaker immediately.
    An OPEN provider half-opens after the cooldown and is retried with a single
    probe, so a provider that recovers mid-run is picked back up.

    A legitimate empty result ([]) from a WORKING provider is returned as-is (no
    failover — that's real evidence of nothing, and counts as breaker success).

    Only when EVERY provider is unavailable (open or failed this pass) does search()
    raise — which run_check turns into a DEFER (re-vet later), never a false kill.
    """
    def __init__(self, providers: list[tuple[str, SearchProvider]],
                 *, failure_threshold: int = 3, cooldown_s: float = 60.0,
                 clock=time.monotonic, health=None):
        if not providers:
            raise ValueError("FallbackSearchProvider needs at least one provider")
        from .health import get_health
        self.providers = providers
        self._breakers = {
            name: CircuitBreaker(name, failure_threshold=failure_threshold,
                                 cooldown_s=cooldown_s, clock=clock)
            for name, _ in providers}
        self._health = health if health is not None else get_health()

    @track_latency(name="fallback_search")
    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        from .errors import parse_reset_seconds
        from .health import DEFAULT_EXHAUSTION_S
        last_err: Optional[Exception] = None
        tried: list[str] = []
        last_status = "empty"
        start = time.monotonic()
        for name, prov in self.providers:
            br = self._breakers[name]
            # Persisted quota window (cross-run) OR in-run breaker can skip it for free.
            if self._health.is_dead(name) or not br.allow():
                tried.append(name)
                continue
            try:
                results = prov.search(query, k=k, max_chars=max_chars)
                br.record_success()       # incl. a legitimate empty [] — provider is healthy
                self._health.clear(name)  # proven alive — drop any stale dead mark
                audit("fallback_resolved", actual_provider=name,
                      tried=tried + [name], query=query[:200], k=k,
                      max_chars=max_chars, returned_n=len(results),
                      latency_ms=int((time.monotonic() - start) * 1000),
                      status="ok" if results else "empty")
                return results
            except (FixtureMiss, ProviderUnavailable) as e:
                # Either no fixture matched this query, or the provider is not configured
                # to run (e.g. missing API key). Fall through to the next provider WITHOUT
                # counting it against the breaker — it never actually attempted a search.
                # (A legitimate empty result from a WORKING provider returns [] above and
                # short-circuits; a skip must NOT masquerade as that.)
                logger.info(f"{type(e).__name__} from {name!r}; falling through to next provider")
                tried.append(name)
                continue
            except Exception as e:
                last_err = e
                exhausted = isinstance(e, ProviderExhaustedError)
                br.record_failure(hard=exhausted)  # exhaustion trips now; transient needs threshold
                if exhausted:
                    dead_for = parse_reset_seconds(str(e)) or DEFAULT_EXHAUSTION_S
                    self._health.mark_exhausted(name, dead_for)
                tried.append(name)
                last_status = "error"
                logger.warning(
                    f"Grounding provider {name!r} {'exhausted' if exhausted else 'failed'} "
                    f"(breaker={br.state}); failing over to next",
                    extra={"provider": name, "exhausted": exhausted,
                           "breaker": br.state, "error": str(e)[:200]})
        audit("fallback_resolved", actual_provider=None,
              tried=tried, query=query[:200], k=k,
              max_chars=max_chars, returned_n=0,
              latency_ms=int((time.monotonic() - start) * 1000),
              status=last_status, error=str(last_err)[:200] if last_err else None)
        # Every provider is down or failed — infrastructure collapse, not a content
        # verdict. GroundingInfrastructureError propagates to the daemon loop which
        # HALTS instead of burning LLM credits on unverifiable candidates.
        from .errors import GroundingInfrastructureError
        raise GroundingInfrastructureError(
            f"ALL grounding providers dead: {[n for n, _ in self.providers]}. "
            f"Last error: {last_err}")


def _build_search(name: str, cfg, fixtures: dict | None) -> SearchProvider:
    r = cfg.retrieval
    if name == "fixture":
        # raise_on_miss=True so FallbackSearchProvider can fall through to live
        # search when a fixture entry is missing (partial fixture coverage).
        return FixtureProvider(fixtures=fixtures, raise_on_miss=bool(fixtures))
    if name == "claude_cli":
        from .claude_cli import ClaudeCliGroundingProvider, configure_concurrency
        configure_concurrency(r.claude_concurrency)
        return ClaudeCliGroundingProvider(
            timeout=max(r.search_timeout, r.claude_min_timeout),
            timeout_max=max(r.search_timeout_max, r.claude_min_timeout),
            escalation=r.search_timeout_escalation, retries=r.search_retries,
            queue_timeout=r.queue_timeout)
    if name == "brave":
        return BraveSearchProvider()
    if name == "searxng":
        return SearXNGSearcher()
    if name == "ddg":
        return DuckDuckGoSearchProvider()
    if name == "tavily":
        return TavilySearchProvider()
    if name == "exa":
        return ExaSearchProvider()
    if name == "deepseek":
        # LLM-search provider — model name comes from cfg.model_defaults.search.deepseek.
        md = getattr(cfg, "model_defaults", None)
        search_model = (md.search.get("deepseek") if md and md.search
                        else "deepseek-chat")
        return DeepSeekSearchProvider(model_name=search_model)
    if name == "minimax_search":
        md = getattr(cfg, "model_defaults", None)
        search_model = (md.search.get("minimax") if md and md.search
                        else "MiniMax-M3")
        return MiniMaxSearchProvider(model_name=search_model)
    raise ValueError(f"unknown retrieval provider: {name!r}")


def make_provider(cfg, fixtures: dict | None = None) -> SearchProvider:
    # provider may be a single name or an ordered fallback chain.
    names = cfg.retrieval.provider
    names = [names] if isinstance(names, str) else list(names)
    # When fixtures are provided (e.g. golden-set harness), pin retrieval to the
    # fixture provider first so that results are deterministic and attributable to
    # the brain, not search variance.
    if fixtures:
        names = ["fixture", *names]
    built = [(n, _build_search(n, cfg, fixtures)) for n in names]
    r = cfg.retrieval
    base: SearchProvider = (
        built[0][1] if len(built) == 1
        else FallbackSearchProvider(built,
                                    failure_threshold=r.breaker_failure_threshold,
                                    cooldown_s=r.breaker_cooldown_s))
    return DiskCache(base, ttl_s=cfg.retrieval.cache_ttl_s) if cfg.retrieval.cache else base
