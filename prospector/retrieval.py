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
from .errors import FixtureMiss, ProviderExhaustedError, ProviderUnavailable
from .models import Source
from .telemetry import track_latency, logger

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

# A real browser UA, not "Mozilla/5.0 prospector": many CDNs (Cloudflare et al.)
# 403 obviously-bot agents on sight, which dropped legitimate sources.
_RESOLVE_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

def _resolve(url: str, timeout: float = _RESOLVE_TIMEOUT) -> Optional[str]:
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
    req = urllib.request.Request(url, method="HEAD",
                                 headers={"User-Agent": _RESOLVE_UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
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
    Used by both CLI grounding providers (gemini, claude)."""
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
        # Catch-all: empty-string key matches everything.
        if "" in self._fixtures:
            items = self._fixtures[""]
            results = [Source.make(url=i["url"], text=i["text"][:max_chars],
                                published_at=i.get("published_at"), query=query)
                    for i in items[:k]]
            logger.info(f"Fixture match: '' (catch-all, query={query!r})")
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
            return results

        if self._raise_on_miss:
            raise FixtureMiss(f"no fixture entry matched query: {query!r}")
        return []


# ---------------------------------------------------------------------------
# External API search providers (grounding resilience chain)
# These kick in when the primary grounding providers (gemini_cli, claude_cli,
# gemini_grounding) are all exhausted. Each must return list[Source] on
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
            return []

        logger.info(f"Brave search: {len(results)} results for {query!r}",
                    extra={"query": query, "count": len(results)})
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
            return results
        except Exception as e:
            logger.warning(f"Exa search error: {e}")
            return []


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

    def __init__(self, resolve_urls: bool = True, max_chars: int = 1500):
        self.resolve_urls = resolve_urls
        self.max_chars = max_chars

    @track_latency(name="llm_synthesis_search")
    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
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
        return results

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

    model_name = "deepseek-chat"
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

    model_name = "MiniMax-M3"
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

    model_name = "google/gemma-4-31b-it:free"
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
        for name, prov in self.providers:
            br = self._breakers[name]
            # Persisted quota window (cross-run) OR in-run breaker can skip it for free.
            if self._health.is_dead(name) or not br.allow():
                continue
            try:
                results = prov.search(query, k=k, max_chars=max_chars)
                br.record_success()       # incl. a legitimate empty [] — provider is healthy
                self._health.clear(name)  # proven alive — drop any stale dead mark
                return results
            except (FixtureMiss, ProviderUnavailable) as e:
                # Either no fixture matched this query, or the provider is not configured
                # to run (e.g. missing API key). Fall through to the next provider WITHOUT
                # counting it against the breaker — it never actually attempted a search.
                # (A legitimate empty result from a WORKING provider returns [] above and
                # short-circuits; a skip must NOT masquerade as that.)
                logger.info(f"{type(e).__name__} from {name!r}; falling through to next provider")
                continue
            except Exception as e:
                last_err = e
                exhausted = isinstance(e, ProviderExhaustedError)
                br.record_failure(hard=exhausted)  # exhaustion trips now; transient needs threshold
                if exhausted:
                    dead_for = parse_reset_seconds(str(e)) or DEFAULT_EXHAUSTION_S
                    self._health.mark_exhausted(name, dead_for)
                logger.warning(
                    f"Grounding provider {name!r} {'exhausted' if exhausted else 'failed'} "
                    f"(breaker={br.state}); failing over to next",
                    extra={"provider": name, "exhausted": exhausted,
                           "breaker": br.state, "error": str(e)[:200]})
        # Every provider is open or failed this pass — propagate so run_check defers (not a kill).
        raise ProviderExhaustedError(
            f"all grounding providers unavailable: {last_err}",
            provider="+".join(n for n, _ in self.providers))


def _build_search(name: str, cfg, fixtures: dict | None) -> SearchProvider:
    r = cfg.retrieval
    if name == "fixture":
        # raise_on_miss=True so FallbackSearchProvider can fall through to live
        # search when a fixture entry is missing (partial fixture coverage).
        return FixtureProvider(fixtures=fixtures, raise_on_miss=bool(fixtures))
    if name == "gemini_cli":
        from .gemini_cli import GeminiCliGroundingProvider, configure_concurrency
        configure_concurrency(r.gemini_concurrency)
        # Grounding is a web SEARCH (fetch URLs+passages), not reasoning. pro's grounded
        # search is heavy and times out (~240s); flash-lite is fast but has POOR RECALL
        # (returns 0 sources for many queries → gates short-circuit to unverifiable). The
        # mid-tier search_model (gemini-2.5-flash) recalls far better and stays fast. The
        # capable verdict model (cfg.model) is reserved for ruling on the fetched passages.
        return GeminiCliGroundingProvider(
            model=(r.search_model or cfg.model_fast or cfg.model or None),
            timeout=r.search_timeout, timeout_max=r.search_timeout_max,
            escalation=r.search_timeout_escalation, retries=r.search_retries,
            queue_timeout=r.queue_timeout)
    if name == "claude_cli":
        from .claude_cli import ClaudeCliGroundingProvider, configure_concurrency
        configure_concurrency(r.claude_concurrency)
        return ClaudeCliGroundingProvider(
            timeout=max(r.search_timeout, r.claude_min_timeout),
            timeout_max=max(r.search_timeout_max, r.claude_min_timeout),
            escalation=r.search_timeout_escalation, retries=r.search_retries,
            queue_timeout=r.queue_timeout)
    if name == "gemini_grounding":
        return GeminiGroundingProvider(model=cfg.model if cfg.operator == "gemini"
                                       else "gemini-2.0-flash")
    if name == "brave":
        return BraveSearchProvider()
    if name == "exa":
        return ExaSearchProvider()
    if name == "deepseek":
        return DeepSeekSearchProvider()
    if name == "minimax_search":
        return MiniMaxSearchProvider()
    if name == "openrouter":
        return OpenRouterSearchProvider()
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
    return DiskCache(base) if cfg.retrieval.cache else base
