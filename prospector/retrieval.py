"""Grounding (Part 4 'source-or-die'). Real web evidence via Gemini's built-in
Google Search grounding — returns resolvable URLs + passages.

Layers (Part 9 three-layer cache + graceful degradation):
  - GeminiGroundingProvider: live search+fetch in one call (google_search tool).
  - FixtureProvider: canned passages for tests / golden set (no network).
  - DiskCache: content-addressed CROSS-TICK cache wrapping any provider; entries
    persist in store/_cache/, carry their fetch time, and expire on
    `retrieval.cache_ttl_s`. `retrieval.cache: false` bypasses it entirely.
Any failure returns [] so the caller downgrades that check to `unverifiable`,
never crashing the run.
"""
from __future__ import annotations

import contextvars
import datetime
import hashlib
import json
import os
import tempfile
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from nltk.stem import PorterStemmer
import http.client
import re
import urllib.error
import urllib.parse
import urllib.request

from .audit import audit
from .breaker import CircuitBreaker
from .copy_lint import extract_urls
from .errors import FixtureMiss, ProviderExhaustedError, ProviderUnavailable, SearchProviderError
from .models import Source
from .telemetry import logger, record_usage, track_latency

CACHE_DIR = Path(__file__).resolve().parent.parent / "store" / "_cache"

# Cache entry format. v2 is an envelope {"v", "fetched_at", "sources"} so TTL is
# judged on the recorded FETCH time rather than on mtime alone; v1 (a bare JSON
# list) is still read, so the existing on-disk cache stays valid.
_CACHE_ENTRY_VERSION = 2

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

# Globally authoritative sources — the wire services, journals and multilaterals that
# carry weight in any jurisdiction. Per-MARKET authorities (gov.uk, sec.gov, CAC…) are
# NOT listed here; they come from the active market's config and are unioned in below.
_HIGH_AUTHORITY_DOMAINS = {
    "ft.com", "reuters.com", "bloomberg.com", "wsj.com", "economist.com",
    "nytimes.com", "theguardian.com", "bbc.co.uk", "bbc.com", "hbr.org",
    "nature.com", "science.org", "mit.edu", "stanford.edu", "harvard.edu",
    "gov.uk", "europa.eu", "un.org", "worldbank.org", "imf.org", "nih.gov",
    "who.int", "gartner.com", "forrester.com", "mckinsey.com", "deloitte.com",
}

# The active market's authority domains, unioned with the base set above.
#
# A ContextVar rather than a module global on purpose: a plain global would be shared by
# every worker thread, so the moment vetting runs more than one market concurrently
# (vet_workers > 1) one market's authority list would silently apply to another's
# fetches. ContextVar keeps it per-execution-context, so that cannot happen.
_market_authority_domains: ContextVar[frozenset[str]] = ContextVar(
    "market_authority_domains", default=frozenset())


@contextmanager
def market_retrieval(cfg):
    """Scope retrieval to a market's evidence terrain for the duration of the block."""
    domains = frozenset(
        str(d).lower().lstrip(".")
        for d in ((cfg.market_config() or {}).get("authority_domains") or [])
    ) if getattr(cfg, "markets", None) else frozenset()
    token = _market_authority_domains.set(domains)
    try:
        yield
    finally:
        _market_authority_domains.reset(token)


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
            
        # Domain-list authority: global base + the active market's own authorities.
        authorities = _HIGH_AUTHORITY_DOMAINS | _market_authority_domains.get()
        if any(netloc == d or netloc.endswith("." + d) for d in authorities):
            return _HIGH_AUTHORITY_TIMEOUT
    except Exception:
        pass
    return _RESOLVE_TIMEOUT

# A real browser UA, not "Mozilla/5.0 prospector": many CDNs (Cloudflare et al.)
# 403 obviously-bot agents on sight, which dropped legitimate sources.
_RESOLVE_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# The two statuses that mean "this page is GONE", as distinct from "you are being walled".
# Deliberately identical to pack_linter._DEAD_STATUSES: the retrieval-time drop and the
# publish-time lint must agree by construction rather than by coincidence, or a URL passes
# one gate and fails the other after the money rail has already been minted.
_DEAD_STATUSES = frozenset({404, 410})


def _confirm_dead(url: str, timeout: float) -> bool:
    """True when a GET agrees with HEAD that the page is gone.

    Some origins 404 a HEAD they would have served for a GET, and a false drop discards
    real evidence. Only ever runs on the rare 404/410 path, so it costs one extra request
    per dead citation, not per source.
    """
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": _RESOLVE_UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read(1)
            return False
    except urllib.error.HTTPError as e:
        return e.code in _DEAD_STATUSES
    except Exception:
        return False  # no verdict is not a death certificate; keep the source


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
    except urllib.error.HTTPError as e:
        # The server RESPONDED. Two different things hide behind that, and conflating them
        # is what pinned the shelf:
        #
        #   401/403/429/5xx — a bot-wall, paywall or rate limit. The path is unjudgeable
        #   from out here and the source is very likely real, so KEEP (the original rule;
        #   en.wikipedia.org answers a bare HEAD with 403 and a browser GET with 200).
        #
        #   404/410 — NOT a bot-wall. No CDN answers a challenge with "Gone"; 410 is an
        #   explicit permanent removal, and a 404 that survives the browser UA above is a
        #   page that is genuinely missing. Keeping these stranded freshly-passed packs:
        #   the dead URL rode all the way to publish, where pack_linter's identical
        #   _DEAD_STATUSES check failed the whole pack — after the money rail had been
        #   minted. Dropping one source here is cheap; keeping it cost the entire pack.
        if e.code in _DEAD_STATUSES and _confirm_dead(url, to):
            logger.warning("Dropping dead URL (HTTP %s)", e.code, extra={"url": url})
            return None
        return url
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as e:
        # No HTTP response at all (DNS failure, connection refused, timeout, malformed URL):
        # the host is dead/fabricated. results_per_query redundancy covers the
        # rare real-but-slow host we drop here.
        #
        # NARROWED from a bare `except Exception` on 2026-08-15. Every network condition this
        # is meant to catch is one of these four (`socket.timeout` and `ssl.SSLError` are both
        # OSError subclasses). What the bare form ALSO caught was our own bugs: an
        # `AttributeError` or `TypeError` from a refactor anywhere in the try block came back
        # as `None`, which the callers read as "fabricated URL — drop this source". Sources
        # would have gone on vanishing from dossiers, silently, with no error anywhere, and
        # the visible symptom would have been thin grounding — a problem this engine has
        # chased six times. An unexpected exception here is a code defect and must surface.
        logger.debug("URL did not resolve, dropping as dead/fabricated",
                     extra={"url": url, "error": str(e)})
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
    # A ContextVar set in this thread is NOT visible to threads created by .map()/.submit(),
    # so _get_timeout would read the DEFAULT empty authority set and drop the per-market
    # timeout bonus. copy_context() carries the caller's market scope into each worker.
    #
    # ONE COPY PER WORKER, never one shared copy. Context.run() raises
    # RuntimeError("cannot enter context ... is already entered") when the SAME Context
    # object is entered concurrently, and these workers overlap by construction. A single
    # shared ctx made this function raise 20/20 on 3 URLs the moment _resolve took real time
    # (measured 2026-08-13) — i.e. ALWAYS in production, NEVER in a test whose _resolve stub
    # returns instantly. That is why tests/unit/test_resolve_sources.py stayed green from
    # 2026-06-15 (5f95ca7) while the claude_cli grounding backstop raised on every query
    # that returned 2+ URLs. The regression test forces the overlap with a Barrier.
    pairs = [(contextvars.copy_context(), it) for it in cand]
    with ThreadPoolExecutor(max_workers=len(cand)) as ex:
        resolved = list(ex.map(
            lambda p: p[0].run(_resolve, str(p[1].get("url", "")), _RESOLVE_TIMEOUT), pairs))
    out: list[Source] = []
    for it, r in zip(cand, resolved):
        if not r:
            logger.warning("Dropping fabricated/dead URL", extra={"url": it.get("url")})
            continue
        out.append(Source.make(url=r, text=str(it.get("text", ""))[:max_chars],
                               published_at=it.get("published_at"), query=query))
    return out


# ---------------------------------------------------------------------------
# RELEVANCE — rank what search returned; do not just take the first k.
# ---------------------------------------------------------------------------
_RELEVANCE_STOP = frozenset("""
a an and are as at be been by for from how in is it its of on or that the their them
they this to was were what when where which who why will with you your site
""".split())


def _relevance_terms(text: str) -> set[str]:
    """Content words of a query or a passage. Deliberately crude — this ranks candidates
    against EACH OTHER; it never rules on anything and never drops a source."""
    return {w for w in re.findall(r"[a-z0-9']+", (text or "").lower())
            if len(w) > 3 and w not in _RELEVANCE_STOP}


def relevance_score(query: str, text: str) -> float:
    """Fraction of the QUERY's content words that appear in `text` (0.0-1.0)."""
    q = _relevance_terms(query)
    if not q:
        return 0.0
    return len(q & _relevance_terms(text)) / len(q)


def _mean_coverage(query: str, sources: list) -> float:
    return (sum(relevance_score(query, s.text) for s in sources) / len(sources)
            if sources else 0.0)


#: The verdict prompt reads only the first `VERDICT_PASSAGE_TRUNCATE` chars of each passage
#: (`verify.py`). Anchoring the stored passage on a window of exactly that size is what makes
#: the selection pay: optimising the 1500-char window instead and slicing its head made what
#: the verdict reads WORSE by 3.5 points (measured 2026-08-14, n=26 live pages).
#: `tests/unit/test_relevance_ranking.py` pins this against verify's constant — one
#: discipline, one number.
PASSAGE_ANCHOR_CHARS = 600


def _best_window_start(query: str, lowered: str, anchor: int) -> int:
    """Start offset of the `anchor`-char window containing the most DISTINCT query terms.

    Scans term OCCURRENCES rather than every offset: a 400,000-char page has 4,000 candidate
    offsets and re-tokenising a 600-char slice at each is seconds of CPU on the grounding
    path. Two pointers over the match list is milliseconds. Ties take the EARLIEST window,
    so a page whose terms are evenly spread keeps today's head slice.
    """
    terms = _relevance_terms(query)
    if not terms:
        return 0
    hits: list[tuple[int, str]] = []
    for t in terms:
        hits.extend((m.start(), t) for m in re.finditer(r"\b" + re.escape(t), lowered))
    if not hits:
        return 0
    hits.sort()
    best_start, best_n = 0, 0
    counts: dict[str, int] = {}
    lo = 0
    for hi in range(len(hits)):
        counts[hits[hi][1]] = counts.get(hits[hi][1], 0) + 1
        while hits[hi][0] - hits[lo][0] >= anchor:
            counts[hits[lo][1]] -= 1
            if not counts[hits[lo][1]]:
                del counts[hits[lo][1]]
            lo += 1
        if len(counts) > best_n:
            best_n, best_start = len(counts), hits[lo][0]
    return best_start


def select_passage(text: str, max_chars: int, *, query: Optional[str] = None,
                   anchor: int = PASSAGE_ANCHOR_CHARS) -> str:
    """Return the `max_chars` of `text` most likely to answer `query`.

    THE DEFECT THIS CLOSES. `fetch_page_text` returned `text[:max_chars]` — the TOP of the
    page — and the verdict then read the first `VERDICT_PASSAGE_TRUNCATE` chars of that. On a
    median 6,334-char page that is the masthead and the cookie banner, and it is why the
    page-fetch fix bought real page text and no yield.

    MEASURED 2026-08-14 over 61 live pages sampled from post-fix dossier citations, scoring
    what the VERDICT reads (the first 600 chars of the stored passage):
        head slice   26.9%  of the query's content words
        anchored     40.3%  (+13.5 points)
    1 page of 61 was made worse; 9 pages whose head slice had ZERO query overlap gained some.
    Anchors on `anchor`, not on `max_chars`, and the window start is snapped back to a word
    boundary so a passage never opens mid-word.
    """
    if len(text) <= max_chars or not query:
        return text[:max_chars]
    start = _best_window_start(query, text.lower(), anchor)
    start = min(start, max(0, len(text) - max_chars))
    if start:
        # Snap back to a word boundary; a passage opening "...ation of the Act" reads as
        # corrupt evidence to a verdict brain and to a buyer reading the dossier.
        space = text.rfind(" ", max(0, start - 60), start)
        start = space + 1 if space != -1 else start
    return text[start:start + max_chars]


def _resolve_urls(urls: list[str], timeout: Optional[float] = None) -> list[Optional[str]]:
    """Resolve many URLs CONCURRENTLY, preserving order and the per-domain tiered timeout.

    Over-fetching multiplies the HEAD probes a provider makes per query, and DuckDuckGo
    and Exa both resolved theirs in a serial `for` loop — ten unresponsive hosts at the
    4s timeout would have added ~40s to one check. `timeout=None` keeps `_get_timeout`'s
    authority-domain patience, which a fixed timeout would silently discard.

    ONE `copy_context()` PER WORKER, never one shared: `Context.run()` raises when the
    same Context is entered concurrently. That is the defect that made `resolve_sources`
    raise 20/20 on 3 URLs from 2026-06-15 (5f95ca7) until 2026-08-13.
    """
    if not urls:
        return []
    from concurrent.futures import ThreadPoolExecutor
    pairs = [(contextvars.copy_context(), u) for u in urls]
    with ThreadPoolExecutor(max_workers=min(len(urls), 10)) as ex:
        return list(ex.map(lambda pr: pr[0].run(_resolve, pr[1], timeout), pairs))


class ProviderStamped(SearchProvider):
    """Records which search provider supplied each passage (`Source.retrieved_by`).

    THE DEFECT THIS CLOSES. Until 2026-08-14 a stored source was
    `{source_id, url, text, published_at, query, fetched_at}` — nothing said which engine
    returned it. So "is DuckDuckGo the reason 8.9% of our 13,479 citations are primary
    sources, and 970 of them Wikipedia?" was not answerable from our own dossiers; it had
    to be re-derived by replaying queries live. A grounding engine that cannot attribute
    its own evidence cannot improve it. `docs/RETRIEVAL_PROGRAM.md` §D8.

    WHY HERE AND NOT AT `Source.make`. There are ~11 construction sites across the provider
    classes, and the next provider added would silently miss one — reintroducing exactly
    this blind spot, in the one field whose job is to eliminate it. Wrapping each provider
    as the chain is built (`make_provider`) is structural: a provider is stamped because of
    how it is COMPOSED, not because its author remembered to.

    Correct under every wrapper above it. `RelevanceRankedProvider` filters and reorders the
    same objects and `PageTextEnricher` mutates `s.text` in place, so neither rebuilds a
    Source and neither can drop the stamp. `DiskCache` round-trips through
    `to_dict()`/`Source(**d)`, which carries the field.

    NEVER OVERWRITES an existing stamp. A cached passage really was retrieved by whichever
    provider first returned it; re-stamping it with today's chain head would manufacture a
    provider attribution that never happened — the precise class of invention this field
    exists to stop.
    """

    def __init__(self, name: str, inner: SearchProvider):
        self.name = str(name)
        self._inner = inner

    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        results = self._inner.search(query, k=k, max_chars=max_chars)
        for s in results:
            if getattr(s, "retrieved_by", None) is None:
                try:
                    s.retrieved_by = self.name
                except AttributeError:
                    # A frozen/slotted stand-in in a test double must not break grounding.
                    # Attribution is an audit field; losing it costs a measurement, while
                    # raising here would cost a verdict.
                    logger.debug("could not stamp retrieved_by on %r", type(s).__name__)
        return results

    def __getattr__(self, item):
        # Transparent to anything that reaches past `.search` (breaker bookkeeping, probes,
        # `close()`). A wrapper that hides the wrapped provider's surface would fail far from
        # here and read as a provider outage.
        return getattr(self._inner, item)


class RelevanceRankedProvider(SearchProvider):
    """Over-fetch, then hand the verdict the k passages that actually answer the query.

    THE DEFECT THIS CLOSES. Every provider in this file asks the search engine for
    exactly `k` results and keeps them in the engine's own order (`raw[:k]`). Relevance
    was therefore something this engine MEASURED at the verdict — as `unverifiable` —
    and never once enforced where the sources are produced.

    MEASURED 2026-08-14 over the 450 grounding passages written since the page-fetch fix
    went live (`store/dossiers/*.json` -> `checks[].sources[]`): a source under a
    `supported` verdict contains 42.8% of its own query's content words; under
    `unverifiable`, 25.1% — and 47.2% of those contain under 20%. Half the pages we
    fetched were off-topic outright (a `distribution` check grounded on vk.com and
    fire.ca.gov; an `AATF WEEE resale` query grounded on gamblingcommission.gov.uk).
    Re-running ten of those exact queries with `max_results=10`: the first 3 average
    25.9% coverage, the BEST 3 average 36.8% (+10.8 points). The relevant pages were
    already in the result list and were being discarded unread.

    Ranks on the SNIPPET, which search returned for free, and is wrapped INSIDE
    PageTextEnricher so only the surviving k are ever fetched. Cost: one wider search
    call per query. No extra page fetch, no LLM call, no change to any verdict rule.

    CANNOT STARVE A CHECK. It returns the same COUNT it was asked for — only a different
    choice of which — so `retrieval_failed`, the DEFER gate and every downstream count
    are untouched. Ties keep the provider's own order (`sorted` is stable), so at
    `overfetch=1` this is a byte-for-byte no-op.
    """

    def __init__(self, inner: SearchProvider, *, overfetch: int = 3,
                 max_k: int = 10) -> None:
        self._inner = inner
        self.overfetch = max(1, int(overfetch))
        self.max_k = max_k

    @track_latency(name="relevance_rank")
    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        if self.overfetch <= 1:
            return self._inner.search(query, k=k, max_chars=max_chars)
        # `max_k` mirrors the `min(k, 10)` cap every provider already applies, so asking
        # for more than a provider will ever return cannot look like a shortfall.
        want = min(max(k, 1) * self.overfetch, self.max_k)
        results = self._inner.search(query, k=want, max_chars=max_chars)
        if len(results) <= k:
            return results
        before = results[:k]
        kept = sorted(results, key=lambda s: -relevance_score(query, s.text))[:k]
        cov_before, cov_after = _mean_coverage(query, before), _mean_coverage(query, kept)
        logger.info("Relevance rank: kept %d of %d for %r (query coverage %.0f%% -> %.0f%%)",
                    len(kept), len(results), query[:80], 100 * cov_before, 100 * cov_after)
        audit("search_rank", query=query[:200], asked_k=k, fetched_n=len(results),
              kept_n=len(kept), cov_before=round(cov_before, 3),
              cov_after=round(cov_after, 3),
              swapped_n=sum(1 for s in kept if s not in before))
        return kept


_ISO_DATE_RE = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})")
_SLASH_DATE_RE = re.compile(r"^\s*(\d{4})/(\d{2})/(\d{2})")


def _normalise_date(raw) -> Optional[str]:
    """'2024-03-11T09:00:00Z' -> '2024-03-11'. None when it is not a plausible date.

    Deliberately anchored at the START of the string: an unanchored search would pull a
    number out of a query string or an id and hand us a date the page never published.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    m = _ISO_DATE_RE.match(raw) or _SLASH_DATE_RE.match(raw)
    if not m:
        return None
    try:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        datetime.date(y, mo, d)
    except ValueError:
        return None
    if not (1990 <= y <= datetime.date.today().year + 1):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"


def _jsonld_date(obj) -> Optional[str]:
    """First `datePublished` anywhere in a JSON-LD blob, however nested."""
    if isinstance(obj, dict):
        got = _normalise_date(obj.get("datePublished"))
        if got:
            return got
        for v in obj.values():
            got = _jsonld_date(v)
            if got:
                return got
    elif isinstance(obj, list):
        for v in obj:
            got = _jsonld_date(v)
            if got:
                return got
    return None


def _extract_published_at(doc) -> Optional[str]:
    """Read a publication date from a parsed lxml document. NEVER raises.

    MUST be called on the document BEFORE `etree.strip_elements` runs: that call deletes
    `<script>` (where JSON-LD lives) and `<footer>`/`<header>` (where `<time>` usually
    lives), so extracting after stripping silently finds nothing on most real pages.
    """
    try:
        for xp in ('//meta[@property="article:published_time"]/@content',
                   '//meta[@name="date"]/@content'):
            for value in doc.xpath(xp):
                got = _normalise_date(value)
                if got:
                    return got
        for blob in doc.xpath('//script[@type="application/ld+json"]/text()'):
            try:
                got = _jsonld_date(json.loads(blob))
            except (ValueError, TypeError):
                continue
            if got:
                return got
        for value in doc.xpath("//time/@datetime"):
            got = _normalise_date(value)
            if got:
                return got
    except (AttributeError, ValueError, TypeError):
        # Narrow on purpose: these are the shapes malformed markup produces. None already
        # means "this page declares no date", so the caller loses nothing it had, and the
        # date must never cost us the passage we came for.
        return None
    return None


# Below this, an extraction is a page title or an error page, not a passage. Set just under the
# 222-char mean of the search snippets this function exists to REPLACE: returning less than the
# snippet we already hold is a downgrade, and the caller reads None as "keep what you had".
_MIN_PAGE_TEXT = 200


#: Sentences carrying one of these read as a cookie/consent banner and never as evidence.
#: Deliberately phrases, not the bare word "cookie": a page about cookie law, or an ICO ruling
#: on consent, is a legitimate source and says "cookie" constantly.
_CONSENT_PHRASES = [
    r"cookies are small (?:text )?files",
    r"cookies on [a-z0-9.\-]+\.(?:gov\.uk|co\.uk|com|org|net|uk)",
    r"we use (?:some )?(?:essential|necessary|strictly necessary) cookies",
    r"(?:essential|necessary) cookies to make (?:this|our) (?:website|site) work",
    r"(?:we(?:'d| would) like to )?set additional cookies",
    r"we use cookies",
    r"(?:accept|reject|allow|decline) (?:all )?(?:additional |non-essential )?cookies",
    r"cookie (?:settings|preferences|policy|consent|choices|banner)",
    r"manage (?:your )?(?:cookies|cookie preferences)",
    r"your (?:privacy|cookie) choices",
    r"(?:enable|turn on) javascript",
    r"javascript is (?:disabled|required|turned off)",
    r"checking your browser",
    r"verify (?:that )?you are (?:a )?human",
]
_CONSENT_RX = re.compile("|".join(_CONSENT_PHRASES), re.I)

#: Attribute tokens a consent widget announces itself with, including the common vendor CMPs.
#: Used only for the DOM pass, where a short matching container can be dropped outright.
_CONSENT_ATTR_TOKENS = ("cookie", "consent", "gdpr", "onetrust", "cookiebot", "didomi",
                        "usercentrics", "quantcast", "klaro", "osano", "trustarc")
_LOWER = "translate(@{attr},'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')"
_CONSENT_XPATH = "//*[" + " or ".join(
    f"contains({_LOWER.format(attr=attr)},'{tok}')"
    for attr in ("id", "class") for tok in _CONSENT_ATTR_TOKENS
) + "]"

#: A consent container is SHORT. Above this many characters the element is the page's actual
#: subject (iubenda's home page, an ICO guidance note, Google's "manage your cookies" help
#: article), and dropping it would delete the evidence rather than the furniture.
CONSENT_CONTAINER_MAX_CHARS = 2_000

#: If removing consent sentences would take more than this share of a passage, the page really
#: is a consent wall or really is about cookies. Leave it whole either way: a wall must stay
#: visibly empty so the check rules `unverifiable` honestly, and a page about cookie law must
#: keep the sentences that make it a source.
CONSENT_MAX_REMOVED_SHARE = 0.6


def strip_consent_sentences(text: str) -> str:
    """Drop the sentences of `text` that are cookie/consent banner boilerplate.

    THE DEFECT THIS CLOSES. `select_passage` anchors the stored passage on the window holding
    the most query terms, but a consent banner contains none of them, so on a page whose banner
    survives extraction the anchor finds nothing and falls back to the head slice -- which IS
    the banner. The verdict brain then reads 600 chars of cookie notice and rules the check
    `unverifiable`, correctly, on evidence we never actually gave it.

    MEASURED 2026-08-16 over 43,673 stored passages in `store/dossiers/`: 76 open with a banner
    inside the 600 chars the verdict reads, 62 of them within the first 200 chars. In aggregate
    that is 0.2%, which is why this is a small fix -- but it is not spread evenly. It is 8 of 65
    passages from ons.gov.uk (12.3%) and 5 of 225 from legislation.gov.uk (2.2%), which are
    precisely the authoritative sources the payer-solvency and legality checks depend on. One of
    them reached the storefront: the live landing page spent a day telling buyers that the ASHE
    earnings tables "contain only cookie consent screens with no actual wage data".

    WHY SENTENCES AND NOT A BLOCK. There is no reliable marker for where a banner ENDS once the
    markup is gone. A sentence carrying "we use some essential cookies" is never evidence no
    matter where it sits, so removing the sentences is both simpler and safer than guessing a
    boundary. The share guard above is what keeps a page ABOUT cookies intact.
    """
    if not text:
        return text
    # Split on sentence ends and on the blank-line boundaries that survive extraction; a banner
    # is often a heading plus two sentences with no full stop between them.
    parts = re.split(r"(?<=[.!?])\s+|\n{2,}", text)
    kept = [p for p in parts if not _CONSENT_RX.search(p)]
    if not kept:
        return text
    out = " ".join(" ".join(p.split()) for p in kept if p.strip())
    if not out:
        return text
    removed_share = 1.0 - (len(out) / max(1, len(text)))
    if removed_share > CONSENT_MAX_REMOVED_SHARE:
        return text
    return out


def _strip_consent_elements(doc, etree) -> None:
    """Remove consent widgets from a parsed document, in place, before any text is read.

    Runs BEFORE `strip_consent_sentences` because it is the precise pass: a banner in a
    `<div id="global-cookie-message">` is identified by what it IS, not by what it says, so it
    goes without any phrase matching and without any risk to prose. Only SHORT containers are
    dropped (`CONSENT_CONTAINER_MAX_CHARS`), which is what stops this deleting the body of a
    page whose subject happens to be cookies.
    """
    try:
        nodes = doc.xpath(_CONSENT_XPATH)
    except (etree.XPathError, ValueError):
        return
    for node in nodes:
        parent = node.getparent()
        if parent is None:                      # never drop the root
            continue
        try:
            if len(node.text_content()) > CONSENT_CONTAINER_MAX_CHARS:
                continue
            parent.remove(node)
        except (ValueError, AttributeError):
            continue


def fetch_page(url: str, *, timeout_s: float = 8.0, max_chars: int = 1500,
               max_bytes: int = 400_000, query: Optional[str] = None,
               strip_consent: bool = False
               ) -> tuple[Optional[str], Optional[str]]:
    """GET a grounding URL and return its readable text, or None.

    THE DEFECT THIS CLOSES. `_resolve()` above sends a HEAD: it proves the host is real and
    deliberately never reads the body. Every provider then stored the SEARCH ENGINE'S SNIPPET
    as the passage — `DuckDuckGoSearchProvider` does exactly this at the `item.get("body")`
    line below. Measured over 11,857 passages from 2026-08-08 onward: mean 222 chars, median
    217, p90 281, 94.7% under 300. The engine has never read a web page; it ruled every verdict
    on a search blurb, which is why 67.5% of checks came back `unverifiable` and why we cite
    pages nobody opened (a URL that 404s is only discovered by the linter months later).

    NEVER RAISES and never returns a worse passage than it was given — the caller keeps the
    snippet whenever this returns None. A grounding fetch failing is our convenience failing;
    it must not cost a source, and it must not turn into a false `unverifiable` (this repo has
    already paid once for an outage that presented as a reasoned kill).

    It also returns the page's publication date as `(text, published_at)` whenever the page
    declares one, and None for that second element when it does not.
    """
    try:
        import requests
        from lxml import etree
        from lxml import html as lxml_html
    except ImportError:                     # no requests/lxml installed => keep snippets
        return None, None

    resp = None
    published: Optional[str] = None
    try:
        resp = requests.get(url, timeout=timeout_s, allow_redirects=True, stream=True,
                            headers={"User-Agent": _RESOLVE_UA})
        if resp.status_code >= 400:
            return None, published
        # A PDF/image/zip is not something lxml can turn into prose. An absent Content-Type
        # is treated as HTML rather than skipped: the parse below is the real gate, and
        # dropping a page for a missing header would re-introduce the false-drop that the
        # HEAD-based `_resolve` docstring above spent so long getting rid of.
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if ctype and not ("html" in ctype or "xml" in ctype or "text/plain" in ctype):
            return None, published
        buf = bytearray()
        for chunk in resp.iter_content(8192):
            if not chunk:
                continue
            buf.extend(chunk)
            if len(buf) >= max_bytes:
                break
        if not buf:
            return None, published
        raw = bytes(buf).decode(resp.encoding or "utf-8", errors="replace")
    except (requests.RequestException, OSError, UnicodeDecodeError, ValueError):
        # network / decode: keep the snippet. NARROWED from `except Exception` 2026-08-15 —
        # the bare form also caught our own bugs in the streaming loop above and returned the
        # same `None` that a dead host returns, so a refactor could silently stop the engine
        # ever reading a page and the only symptom would be thin grounding.
        return None, published
    finally:
        if resp is not None:
            try:
                resp.close()
            except (requests.RequestException, OSError):
                pass

    try:
        doc = lxml_html.fromstring(raw)
        published = _extract_published_at(doc)
        # Strip the page furniture BEFORE reading any text. Script/style bodies are not prose,
        # and neither is the nav bar. Leaving either in feeds the verdict brain boilerplate
        # that dilutes the passage AND inflates the question/passage word overlap that
        # `verify.py:138` scores confidence on — i.e. it makes grounding look better while
        # making it worse, which is the one outcome worse than the snippet we started with.
        # Proven necessary on the first live run: a bare `text_content()` returned
        # "Skip Navigation Personal Business Find a store Ver en español Shop Deals ..." as
        # the single longest "upgraded" passage of the batch.
        etree.strip_elements(doc, "script", "style", "noscript", "nav", "header", "footer",
                             "aside", "form", "svg", "iframe", "button", "select", "template",
                             with_tail=False)
        # The consent widget is furniture too, but it is named rather than tagged, so it
        # survives the call above. Dropped here, while the DOM still says which element
        # it is -- after `text_content()` there is nothing left to identify it by.
        if strip_consent:
            _strip_consent_elements(doc, etree)
        # Prefer the region the page itself declares as its content. Falling back to the whole
        # document is deliberate — plenty of real pages (gov.uk guidance among them) use none
        # of these landmarks, and refusing those would re-create the false-drop problem.
        text = ""
        for xp in ("//main", "//article", "//*[@role='main']", "//*[@id='content']"):
            nodes = doc.xpath(xp)
            if not nodes:
                continue
            candidate = " ".join(nodes[0].text_content().split())
            if len(candidate) >= 200:
                text = candidate
                break
        if not text:
            text = " ".join(doc.text_content().split())
    except (etree.ParserError, etree.XMLSyntaxError, ValueError, UnicodeDecodeError):
        # unparseable markup. Narrowed for the same reason as the fetch above: an
        # AttributeError from changing the xpath list read exactly like a broken page.
        #
        # MERGE 2026-08-15: origin/main narrowed this handler and this branch changed its
        # BODY from `return None` to `text = ""`. Both, not either — the narrowing is about
        # which exceptions may be swallowed, the body is about what happens after one is.
        # Falling through rather than returning is what gives the fallback below its turn:
        # trafilatura is a different parser and routinely reads a page lxml could not.
        text = ""

    # TRAFILATURA IS THE FALLBACK, NOT THE PRIMARY (2026-08-15, and the sizing is measured).
    #
    # The ladder above returns the page TITLE and nothing else on a page that carries its body
    # outside every landmark it knows: measured on the 12 fetchable URLs cited by pack
    # e698149e137fc164, it produced 15 chars for isbe.net/Pages/SOPPA-Contracts.aspx ("SOPPA
    # Contracts"), 182 for edprivacy.com/state-guides/illinois and 96 for a geekwire article —
    # 3 of 12 pages where the enrichment silently did nothing.
    #
    # It is a FALLBACK because the honest measurement of what it buys is small. `PageTextEnricher`
    # (:630) only replaces a snippet on a gain of `min_gain_chars`, and 10 of those 12 passages
    # were already at the 1500-char cap, so there was no headroom to win: swapping extractors
    # upgrades ONE passage of twelve. Running it first would also cost ~0.55s/page of CPU on the
    # 9 pages the cheap path already handles, for nothing. So it runs only where the cheap path
    # came back with something too short to be a passage at all, which is the case it fixes.
    #
    # A page that yields under _MIN_PAGE_TEXT after both is NO PASSAGE, not a short one. The
    # caller keeps the search snippet, which averages 222 chars — strictly more than a title.
    # This is also what stops a 404 body ("Page not found – GeekWire", 25 chars) being handed
    # to a verdict brain as the evidence for a check.
    if len(text) < _MIN_PAGE_TEXT:
        # Two handlers, not one, on origin/main's rule (2026-08-15): the absent optional
        # dependency and a parser failure are different facts, and a bare `except Exception`
        # over both would also swallow an AttributeError or NameError from a refactor of this
        # very block — which would present as "no page on the open web has a passage", in
        # silence, forever. That is the failure mode main's narrowing pass exists to end.
        try:
            import trafilatura  # declared in requirements.txt; lazy, same as requests above
        except ImportError:     # not installed: keep whatever the ladder found
            trafilatura = None  # type: ignore[assignment]
        if trafilatura is not None:
            try:
                better = trafilatura.extract(raw, include_comments=False, include_tables=True,
                                             favor_precision=True) or ""
            except (etree.ParserError, etree.XMLSyntaxError, ValueError, TypeError,
                    UnicodeDecodeError):
                better = ""     # a third-party parser on hostile markup: keep what we have
            better = " ".join(better.split())
            if len(better) > len(text):
                text = better
    if len(text) < _MIN_PAGE_TEXT:
        return None, published
    # Select the passage that answers the query rather than the top of the page. `query=None`
    # (any caller predating 2026-08-14) still gets the head slice, byte for byte.
    if strip_consent:
        # Second pass, on the text: a banner whose container carried no telltale id or
        # class reaches this line intact, and it is the head of the string -- exactly
        # where `select_passage` falls back to when the query matches nothing.
        text = strip_consent_sentences(text)
    return (select_passage(text, max_chars, query=query) or None), published


def fetch_page_text(url: str, *, timeout_s: float = 8.0, max_chars: int = 1500,
                    max_bytes: int = 400_000, query: Optional[str] = None,
                    strip_consent: bool = False) -> Optional[str]:
    """Text-only view of `fetch_page`, kept for callers that do not want the date."""
    return fetch_page(url, timeout_s=timeout_s, max_chars=max_chars,
                      max_bytes=max_bytes, query=query,
                      strip_consent=strip_consent)[0]


class PageTextEnricher(SearchProvider):
    """Replaces search-result snippets with the actual page text, in place.

    Sits between the provider chain and the DiskCache (see `make_provider`), for two reasons.
    It must wrap the SINGLE-provider case as well as `FallbackSearchProvider` — `make_provider`
    skips the fallback wrapper entirely when only one provider is configured, so wiring this
    into the fallback would have silently done nothing on a one-provider config. And sitting
    INSIDE the cache means the fetched text is what gets cached, so the page is fetched once
    per grounding key rather than on every repeat vet.

    A fetch that fails leaves the original snippet untouched: this layer can only ever add.
    """
    def __init__(self, inner: SearchProvider, *, timeout_s: float = 8.0,
                 max_workers: int = 8, min_gain_chars: int = 400,
                 max_bytes: int = 400_000, strip_consent: bool = False) -> None:
        self._inner = inner
        self._timeout_s = timeout_s
        self._max_workers = max(1, int(max_workers))
        self._min_gain = max(0, int(min_gain_chars))
        self._max_bytes = max_bytes
        self._strip_consent = bool(strip_consent)

    @track_latency(name="page_fetch")
    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        sources = self._inner.search(query, k=k, max_chars=max_chars)
        if not sources:
            return sources
        start = time.monotonic()
        from concurrent.futures import ThreadPoolExecutor
        # The per-market timeout scope lives in a ContextVar that worker threads do not
        # inherit, so the caller's context has to be carried in explicitly.
        #
        # ONE COPY PER WORKER, not one shared copy. `Context.run()` raises
        # RuntimeError("cannot enter context ... already entered") when the SAME Context
        # object is entered concurrently, so a single `copy_context()` shared across the pool
        # fails every fetch the moment two run at once. Proven live 2026-08-13: the first
        # real-web run logged `page fetch pool failed (RuntimeError); keeping snippets` and
        # upgraded 0 of 3 passages — the enrichment silently degraded to exactly the snippet
        # behaviour it exists to replace, while still reporting success.
        pairs = [(contextvars.copy_context(), s) for s in sources]

        def _one(pair) -> tuple[Optional[str], Optional[str]]:
            ctx, s = pair
            return ctx.run(fetch_page, s.url, timeout_s=self._timeout_s,
                           max_chars=max_chars, max_bytes=self._max_bytes, query=query,
                           strip_consent=self._strip_consent)

        try:
            with ThreadPoolExecutor(max_workers=min(self._max_workers, len(sources))) as ex:
                pages = list(ex.map(_one, pairs))
        except Exception as e:              # noqa: BLE001 — enrichment is strictly optional
            logger.warning(f"page fetch pool failed ({type(e).__name__}); keeping snippets")
            return sources

        upgraded = 0
        dated = 0
        for s, (page, published) in zip(sources, pages):
            if page and len(page) >= len(s.text or "") + self._min_gain:
                s.text = page
                upgraded += 1
            if published and not s.published_at:
                s.published_at = published
                dated += 1
        audit("page_fetch", query=query[:200], n_sources=len(sources),
              upgraded=upgraded, dated=dated,
              latency_ms=int((time.monotonic() - start) * 1000),
              status="ok" if upgraded else "no_gain")
        logger.info(f"page fetch: upgraded {upgraded}/{len(sources)} passages",
                    extra={"upgraded": upgraded, "n_sources": len(sources), "dated": dated})
        return sources


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
            # The API call itself failed — a transport error, a bad key, a quota. Returning
            # `[]` told the chain "this provider is healthy and the web is empty", which is
            # a lie in both halves: it books a breaker SUCCESS and clears the dead mark
            # (FallbackSearchProvider.search, ~:1860), so a provider that is down stays in
            # rotation and its outage is indistinguishable from a null result. Raise, and
            # the chain fails over exactly as it was built to.
            logger.error(f"Grounding search failed, failing over: {e}", extra={"error": str(e)})
            raise

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
            # Same rule as the transport failure above, and the same reason. We received a
            # response and could not read it; that is our problem, not the web's. `[]` here
            # is the value a real "nothing found" returns, so no caller could ever tell them
            # apart. Note this handler also catches OUR OWN bugs in the loop above — a
            # `TypeError` after a refactor of `Source.make` looked identical to a null
            # result, forever, in silence.
            logger.error(f"Failed to parse search results, failing over: {e}",
                         extra={"error": str(e)})
            raise

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
            # Not "zero evidence" — see ExaSearchProvider.search: a swallowed transport error reads
            # as a successful empty result and stops the fallback chain.
            logger.warning(f"Brave search failed: {e}")
            audit("search", provider="brave", query=query[:200], k=k,
                  max_chars=max_chars, returned_n=0,
                  latency_ms=int((time.monotonic() - start) * 1000),
                  status="error", error=str(e)[:200])
            raise

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
            pairs = [(it, getattr(it, "url", None) or "") for it in (result.results or [])]
            pairs = [(it, u) for it, u in pairs if u]
            results: list[Source] = []
            for (item, _), resolved in zip(pairs, _resolve_urls([u for _, u in pairs])):
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

    `region` selects the locale ddgs searches in ("uk-en", "us-en", …). Note that ddgs
    DEFAULTS to "us-en" when the argument is omitted, which is what this provider did
    for its whole life — so a UK-only engine has been grounding on US-biased results.
    The uk market therefore pins "us-en" to preserve that behaviour exactly; changing it
    is a measured yield decision that must move the market's cache_salt with it.
    """
    def __init__(self, region: Optional[str] = None) -> None:
        self.region = region or None

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
                    kw = {"max_results": min(k, 10)}
                    if self.region:
                        kw["region"] = self.region
                    with DDGS() as ddgs:
                        raw = list(ddgs.text(query, **kw))
                    last_exc = None
                    break
                except Exception as e:  # noqa: BLE001 — transient primp/UA flakiness
                    last_exc = e
                    logger.info(f"DDG attempt {attempt + 1}/3 transient error: "
                                f"{type(e).__name__}: {str(e)[:120]}")
            if last_exc is not None:
                raise last_exc
            # Resolve CONCURRENTLY: over-fetching for relevance ranking multiplies these
            # HEAD probes, and a serial loop would spend the saving on latency.
            pairs = [(it, it.get("href", "") or it.get("url", "")) for it in raw]
            pairs = [(it, u) for it, u in pairs if u]
            results: list[Source] = []
            for (item, _), resolved in zip(pairs, _resolve_urls([u for _, u in pairs])):
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

            # Extract and validate URLs from the response. Shared with pack_linter via
            # copy_lint.extract_urls — two private copies of this regex is how a URL got
            # STORED truncated at a literal '(' and then flagged as a dead citation by the
            # publish gate, with both halves of the engine agreeing on the wrong string.
            for url in extract_urls(text)[:k]:
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
            # Not "zero evidence" — see ExaSearchProvider.search: a swallowed transport error reads
            # as a successful empty result and stops the fallback chain.
            logger.warning(f"DeepSeek search failed: {e}")
            raise
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
            # Not "zero evidence" — see ExaSearchProvider.search: a swallowed transport error reads
            # as a successful empty result and stops the fallback chain.
            logger.warning(f"MiniMax search failed: {e}")
            raise
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
    """Content-addressed CROSS-TICK cache over any provider (Part 9 / S5).

    Entries live in `store/_cache/<sha>.json` and outlive the process, so a query
    repeated in a later tick — or by a different run entirely — is served from disk
    instead of re-hitting ddg/exa/claude_cli. Misses delegate to `inner`.

    Concurrency: the scheduler daemon and interactive runs share this directory.
    Writes are tmp+rename (atomic on POSIX) so a reader never observes half a file,
    and ANY unreadable entry — torn, truncated, wrong shape — is a MISS that gets
    re-fetched. This sits on the grounding path, where a raised exception would fail
    a verdict that one re-fetch answers.
    """
    def __init__(self, inner: SearchProvider, cache_dir: Path | None = None,
                 ttl_s: int = 0, key_salt: str = ""):
        self.inner = inner
        # Resolved at construction, NOT bound as a default argument at import time:
        # a module-level default freezes the path before a test can redirect it, which
        # is how production store/ has been polluted by test runs before.
        self.cache_dir = Path(cache_dir) if cache_dir is not None else CACHE_DIR
        # 0 disables expiry; otherwise a cache file older than ttl_s is a miss and
        # the page is re-grounded so a verdict never rules on stale evidence.
        self.ttl_s = ttl_s
        # Per-market salt. Without it, the identical query text run under two different
        # search regions collides on one cache file, so a US check would be served the
        # UK's cached evidence — a silent grounding corruption no test would notice.
        # The default market's salt is "" so the existing cache stays valid.
        self.key_salt = key_salt or ""
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, query: str, k: int, max_chars: int) -> Path:
        base = f"{query}|{k}|{max_chars}"
        if self.key_salt:
            base = f"{base}|{self.key_salt}"
        h = hashlib.sha1(base.encode()).hexdigest()[:20]
        return self.cache_dir / f"{h}.json"

    def _age_s(self, p: Path, fetched_at: float | None) -> float | None:
        """Seconds since this entry was fetched, or None when age is unknowable.

        The OLDEST available evidence of age wins. `fetched_at` is stamped into the
        entry at write time; mtime is the only signal a v1 entry carries, but mtime
        alone is forgeable — any copy, rsync or restore of the store/ tree
        (`scripts/backup_store.py`) resets it to now and would silently revive
        months-old grounding as "fresh". Taking the minimum can only ever re-fetch.
        """
        stamps: list[float] = []
        if fetched_at is not None:
            stamps.append(fetched_at)
        try:
            stamps.append(p.stat().st_mtime)
        except OSError:
            pass
        if not stamps:
            return None
        return time.time() - min(stamps)

    def _is_fresh(self, p: Path, fetched_at: float | None = None) -> bool:
        """A cache entry is fresh if expiry is disabled or it is younger than ttl_s."""
        if self.ttl_s <= 0:
            return True
        age = self._age_s(p, fetched_at)
        return age is not None and age < self.ttl_s

    def _read_entry(self, p: Path) -> tuple[list[Source], float | None] | None:
        """Parse a cache file into (sources, fetched_at), or None meaning MISS.

        Every failure mode — unreadable file, torn/partial JSON, an envelope of the
        wrong shape, a source dict with unexpected keys — returns None rather than
        raising, so a damaged entry costs one re-fetch and never a failed verdict.
        """
        try:
            raw = json.loads(p.read_text())
        except (OSError, ValueError) as e:   # unreadable file / torn JSON -> one re-fetch
            logger.warning(f"Unreadable search cache entry, treating as miss: {e}",
                           extra={"path": str(p)})
            return None
        fetched_at: float | None = None
        if isinstance(raw, dict):
            payload = raw.get("sources")
            ts = raw.get("fetched_at")
            if isinstance(ts, (int, float)) and not isinstance(ts, bool):
                fetched_at = float(ts)
        else:
            payload = raw               # v1 entry: a bare list, aged by mtime alone.
        if not isinstance(payload, list):
            logger.warning("Malformed search cache entry, treating as miss",
                           extra={"path": str(p)})
            return None
        try:
            sources = [Source(**d) for d in payload]
        except (TypeError, ValueError) as e:   # entry written by an older Source schema
            logger.warning(f"Malformed search cache entry, treating as miss: {e}",
                           extra={"path": str(p)})
            return None
        return sources, fetched_at

    def _write_entry(self, p: Path, results: list[Source]) -> None:
        """Publish an entry atomically: unique temp file in the same dir, then rename.

        `os.replace` is atomic on POSIX, so a concurrent reader sees either the old
        entry or the new one, never a prefix of the new one. A plain write left a
        window in which the daemon could read a truncated file — the torn-write
        defect class this store has hit before.
        """
        payload = json.dumps({"v": _CACHE_ENTRY_VERSION, "fetched_at": time.time(),
                              "sources": [s.to_dict() for s in results]},
                             ensure_ascii=False)
        fd, tmp = tempfile.mkstemp(dir=str(self.cache_dir), prefix=f".{p.stem}.",
                                   suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(payload)
            os.replace(tmp, p)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @track_latency(name="cached_search")
    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        # STAGE TIMING (added 2026-08-16). This wrapper's own audit line reported a mean of
        # 71.4s per search while the web calls underneath it summed to 4.1s — 94% of the
        # grounding time was inside the chain and attributed to nothing. `start` used to sit
        # AFTER `record_usage`, so the ledger write was outside every number we had. Time
        # each stage from the outside: whatever is slow now names itself in the audit line.
        t_enter = time.monotonic()
        record_usage(web=True, provider="cache")
        start = time.monotonic()
        usage_ms = int((start - t_enter) * 1000)
        p = self._path(query, k, max_chars)
        # mtime is a cheap prefilter: because freshness takes the OLDER of mtime and
        # the stamped fetch time, an mtime-stale entry is stale whatever it contains.
        if p.exists() and self._is_fresh(p):
            entry = self._read_entry(p)
            if entry is not None and self._is_fresh(p, entry[1]):
                results = entry[0]
                logger.info("Search cache hit", extra={"query": query, "count": len(results)})
                audit("search", provider="cache", query=query[:200], k=k,
                      max_chars=max_chars, returned_n=len(results),
                      latency_ms=int((time.monotonic() - start) * 1000),
                      usage_ms=usage_ms,
                      status="ok" if results else "empty", cache_hit=True)
                return results

        logger.info("Search cache miss", extra={"query": query})
        t_inner = time.monotonic()
        results = self.inner.search(query, k, max_chars)
        inner_ms = int((time.monotonic() - t_inner) * 1000)
        # Cache writes only succeed when inner returned real results; empty
        # results stay uncached so a transient outage does not poison the cache.
        if results:
            try:
                self._write_entry(p, results)
            except Exception as e:
                logger.warning(f"Failed to write search cache: {e}", extra={"path": str(p)})
        audit("search", provider="cache", query=query[:200], k=k,
              max_chars=max_chars, returned_n=len(results),
              latency_ms=int((time.monotonic() - start) * 1000),
              usage_ms=usage_ms, inner_ms=inner_ms,
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
                 clock=time.monotonic, health=None, min_relevance: float = 0.0,
                 backstop_only: Optional[list[str]] = None):
        if not providers:
            raise ValueError("FallbackSearchProvider needs at least one provider")
        from .health import get_health
        self.providers = providers
        # See `config.Retrieval.backstop_only_providers`. These answer an OUTAGE, not a
        # low-relevance result: they are skipped unless an earlier provider actually failed.
        self.backstop_only = set(backstop_only or ())
        # See `config.Retrieval.min_relevance`. 0.0 keeps the pre-2026-08-14 behaviour
        # exactly: the first provider that answers wins, however off-topic its answer.
        self.min_relevance = float(min_relevance or 0.0)
        self._breakers = {
            name: CircuitBreaker(name, failure_threshold=failure_threshold,
                                 cooldown_s=cooldown_s, clock=clock)
            for name, _ in providers}
        self._health = health if health is not None else get_health()

    def _usable_after(self, idx: int) -> bool:
        """Is there a provider AFTER `idx` that could actually be asked right now?

        Escalating on low relevance is only worth the latency if someone is left to
        escalate TO — a dead-marked or breaker-open tail is not a second opinion. A
        backstop-only provider is not one either: it will refuse the escalation below,
        so counting it here would escalate off a perfectly good result set into nothing.
        """
        return any(n not in self.backstop_only
                   and not self._health.is_dead(n) and self._breakers[n].allow()
                   for n, _ in self.providers[idx + 1:])

    @track_latency(name="fallback_search")
    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        from .health import DEFAULT_EXHAUSTION_S
        last_err: Optional[Exception] = None
        tried: list[str] = []
        last_status = "empty"
        start = time.monotonic()
        # Best (coverage, provider, results) seen this call. Only ever WRITTEN by a
        # provider that answered, so returning it cannot invent sources.
        best: Optional[tuple[float, str, list[Source]]] = None
        # STAGE TIMING (added 2026-08-16). Each provider adapter already audits its own
        # latency, but it starts its clock INSIDE itself. Timing the same call from out
        # here catches everything the adapter's own number cannot see — import, ledger
        # write, whatever blocks before it looks at the clock. `prov_ms` is the outside
        # measure, so `latency_ms - prov_ms - cov_ms` is genuinely unattributed time.
        prov_ms = 0
        cov_ms = 0
        per_provider_ms: dict[str, int] = {}
        # How many providers actually ANSWERED this call (any result, on-topic or not).
        # A backstop-only provider runs only while this is 0 — that is the exact definition
        # of "everyone before me is down", and it is the only condition it was built for.
        answered = 0
        for idx, (name, prov) in enumerate(self.providers):
            br = self._breakers[name]
            # Persisted quota window (cross-run) OR in-run breaker can skip it for free.
            if self._health.is_dead(name) or not br.allow():
                tried.append(name)
                continue
            if name in self.backstop_only and answered:
                # Someone upstream answered. Their set may be off-topic, and this provider
                # might beat it — but see `config.Retrieval.backstop_only_providers` for the
                # measurement: it wins that coin flip about half the time and costs ~196s.
                audit("search_backstop_skipped", provider=name, query=query[:200],
                      answered_by=tried[:], reason="upstream_answered")
                tried.append(name)
                continue
            try:
                _t0 = time.monotonic()
                try:
                    results = prov.search(query, k=k, max_chars=max_chars)
                finally:
                    _took = int((time.monotonic() - _t0) * 1000)
                    prov_ms += _took
                    per_provider_ms[name] = per_provider_ms.get(name, 0) + _took
                br.record_success()       # incl. a legitimate empty [] — provider is healthy
                self._health.clear(name)  # proven alive — drop any stale dead mark
                answered += 1
                # RELEVANCE FAILOVER. A result set that shares almost no content words with
                # the query is not evidence, and no downstream stage can repair it: ranking
                # picks the best of what arrived, the page fetch reads the wrong page in
                # full, and the verdict correctly rules `unverifiable`. Treat it as a SOFT
                # failure — the provider is healthy (breaker success is already recorded
                # above and is NOT reversed), it just answered a different question.
                _t0 = time.monotonic()
                cov = _mean_coverage(query, results)
                cov_ms += int((time.monotonic() - _t0) * 1000)
                if best is None or cov > best[0]:
                    best = (cov, name, results)
                if (results and self.min_relevance > 0.0 and cov < self.min_relevance
                        and self._usable_after(idx)):
                    logger.info(
                        "Grounding provider %r answered %r at %.0f%% query coverage "
                        "(floor %.0f%%); escalating to the next provider",
                        name, query[:80], 100 * cov, 100 * self.min_relevance)
                    audit("search_relevance_escalate", provider=name, query=query[:200],
                          coverage=round(cov, 3), floor=self.min_relevance,
                          returned_n=len(results))
                    tried.append(name)
                    last_status = "low_relevance"
                    continue
                # This provider ends the chain — but an EARLIER one it escalated off may
                # still cover the query better (the tail is a second opinion, not an
                # authority). `best` holds the earliest strict maximum, so a tie keeps the
                # earlier provider's order, exactly as the ranker does.
                chosen_name, chosen = name, results
                if self.min_relevance > 0.0 and best is not None and best[1] != name:
                    chosen_name, chosen = best[1], best[2]
                _total = int((time.monotonic() - start) * 1000)
                audit("fallback_resolved", actual_provider=chosen_name,
                      tried=tried + [name], query=query[:200], k=k,
                      max_chars=max_chars, returned_n=len(chosen),
                      latency_ms=_total, prov_ms=prov_ms, cov_ms=cov_ms,
                      unattributed_ms=_total - prov_ms - cov_ms,
                      per_provider_ms=per_provider_ms,
                      status="ok" if chosen else "empty")
                return chosen
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
                    # Classify, exactly as the moat chain does (operator.py:~975). This matters
                    # more here than there: this chain shares the MOAT's health store
                    # (get_health() above, not the non-critical file), and `retrieval.provider`
                    # includes claude_cli — the SAME key the verdict chain looks up. So a flat
                    # 3600s mark on a grounding hiccup benched the verdict brain for an hour.
                    # Backpressure gets the 60s floor; only a spent allowance gets the hour.
                    from .errors import PERMANENT, classify_exhaustion, limit_window_seconds
                    from .health import TRANSIENT_EXHAUSTION_S
                    kind = classify_exhaustion(str(e))
                    # See the twin call site in `operator.py::FallbackOperator._raw`, and keep
                    # the precedence IDENTICAL to it. A window the raiser knows exactly
                    # (`retry_after_s`, set by the usage-wall preflight) beats any window read
                    # back out of the rendered message; `limit_window_seconds` keeps the
                    # stated-reset precedence and adds absolute resets plus per-class defaults.
                    # This chain shares the MOAT's health store, so an over-long window here
                    # benches the verdict brain — which is exactly what happened on 2026-08-08.
                    dead_for = (getattr(e, "retry_after_s", None)
                                or limit_window_seconds(str(e))
                                or (DEFAULT_EXHAUSTION_S if kind == PERMANENT
                                    else TRANSIENT_EXHAUSTION_S))
                    self._health.mark_exhausted(name, dead_for, error=str(e))
                tried.append(name)
                last_status = "error"
                logger.warning(
                    f"Grounding provider {name!r} {'exhausted' if exhausted else 'failed'} "
                    f"(breaker={br.state}); failing over to next",
                    extra={"provider": name, "exhausted": exhausted,
                           "breaker": br.state, "error": str(e)[:200]})
        if best is not None:
            # Every provider was tried and none cleared the floor (or the ones after the
            # best one failed outright). Return the best coverage seen rather than nothing:
            # low-relevance evidence still beats a GroundingInfrastructureError, which the
            # daemon reads as an outage and turns into a DEFER.
            cov, name, results = best
            logger.info("No provider cleared the %.0f%% relevance floor for %r; "
                        "keeping %r at %.0f%%",
                        100 * self.min_relevance, query[:80], name, 100 * cov)
            _total = int((time.monotonic() - start) * 1000)
            audit("fallback_resolved", actual_provider=name,
                  tried=tried, query=query[:200], k=k, max_chars=max_chars,
                  returned_n=len(results),
                  latency_ms=_total, prov_ms=prov_ms, cov_ms=cov_ms,
                  unattributed_ms=_total - prov_ms - cov_ms,
                  per_provider_ms=per_provider_ms,
                  status="best_effort", coverage=round(cov, 3))
            return results
        _total = int((time.monotonic() - start) * 1000)
        audit("fallback_resolved", actual_provider=None,
              tried=tried, query=query[:200], k=k,
              max_chars=max_chars, returned_n=0,
              latency_ms=_total, prov_ms=prov_ms, cov_ms=cov_ms,
              unattributed_ms=_total - prov_ms - cov_ms,
              per_provider_ms=per_provider_ms,
              status=last_status, error=str(last_err)[:200] if last_err else None)
        # Every provider is down or failed — infrastructure collapse, not a content
        # verdict. GroundingInfrastructureError propagates to the daemon loop which
        # HALTS instead of burning LLM credits on unverifiable candidates.
        from .errors import GroundingInfrastructureError
        raise GroundingInfrastructureError(
            f"ALL grounding providers dead: {[n for n, _ in self.providers]}. "
            f"Last error: {last_err}")


def _market_block(cfg) -> dict:
    """The active market's config block, or {} for a config predating Epic D."""
    try:
        return cfg.market_config() or {}
    except (AttributeError, TypeError):
        # A stubbed cfg in a test, or a config predating Epic D, must never break search.
        # Narrowed from `except Exception`: those two are the shapes a stub actually raises,
        # and anything else here is a real config defect that must not present as "this
        # market has no block" — which is a completely ordinary, unremarkable state.
        return {}


def _build_search(name: str, cfg, fixtures: dict | None) -> SearchProvider:
    r = cfg.retrieval
    if name == "fixture":
        # raise_on_miss=False. It was `bool(fixtures)`, which existed so
        # FallbackSearchProvider could catch FixtureMiss and fall through to live search on
        # partial fixture coverage. `make_provider` no longer builds that fallback — under
        # fixtures the chain is the fixture provider ALONE — so there is nothing left to
        # catch the exception and a missing entry would abort the check instead of grounding
        # it. `[]` is the honest answer: no passage, so `verdict.md` rules `unverifiable`.
        # A silent `[]` is its own trap, which is why the golden audit now records
        # `sources: []` per check and `run_golden_set` prints a NO EVIDENCE line — the miss
        # is visible without being fatal.
        return FixtureProvider(fixtures=fixtures, raise_on_miss=False)
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
        return DuckDuckGoSearchProvider(region=_market_block(cfg).get("search_region"))
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
    # When fixtures are provided (e.g. golden-set harness), retrieval is pinned to the
    # fixture provider ALONE so results are deterministic and attributable to the brain,
    # not search variance.
    #
    # THIS USED TO PREPEND, NOT REPLACE (`names = ["fixture", *names]`), and that made the
    # promotion gate unmeasurable. The live providers stayed in the chain behind the
    # fixtures, and `FallbackSearchProvider`'s relevance failover (see `min_relevance` below,
    # ~line 1868) escalates off ANY provider whose result set scores under the floor. A
    # one-passage fixture scores ~0% query coverage against a 35% floor, so every golden-set
    # query escalated straight past the fixture into live DDG/Exa. Measured 2026-08-15:
    # claude_cli 0.78 and minimax 0.67 on the same nine cases, with ZERO fixture URLs
    # recoverable from either audit — neither number could be attributed to the brain.
    # A single-element chain also skips `FallbackSearchProvider` entirely (see the `built[0]`
    # branch below), so there is no escalation path left to re-open by accident.
    # `is not None`, not truthiness: an EMPTY dict still means fixture mode — same reasoning
    # as `_pinned` below, where truthiness once let a fixture chain reach the real network.
    if fixtures is not None:
        names = ["fixture"]
    # Every provider is stamped AS THE CHAIN IS BUILT, so attribution is a property of the
    # composition rather than of each provider class remembering to set it. This also covers
    # the single-provider config below, where `FallbackSearchProvider` is skipped entirely.
    built = [(n, ProviderStamped(n, _build_search(n, cfg, fixtures))) for n in names]
    r = cfg.retrieval
    base: SearchProvider = (
        built[0][1] if len(built) == 1
        else FallbackSearchProvider(built,
                                    failure_threshold=r.breaker_failure_threshold,
                                    cooldown_s=r.breaker_cooldown_s,
                                    min_relevance=float(getattr(r, "min_relevance", 0.0) or 0.0),
                                    backstop_only=list(
                                        getattr(r, "backstop_only_providers", None) or ())))
    # Fetch the PAGE rather than ruling on the search snippet. Wrapped here, not inside
    # FallbackSearchProvider, because the line above skips that wrapper entirely on a
    # single-provider config. Never wrapped when fixtures are pinned: the golden-set harness
    # exists to attribute results to the BRAIN rather than to search variance, and reaching
    # the live web from it would destroy exactly that property (and make the suite depend on
    # the network).
    # `fixtures is None`, NOT `not fixtures`: an EMPTY dict still means fixture mode, and
    # truthiness let `make_provider(cfg, fixtures={})` wrap a FixtureProvider chain — which
    # would GET the fixtures' fake URLs over the real network from inside the suite.
    # `"fixture" in names` covers a config that names the provider without passing a dict.
    _pinned = fixtures is not None or "fixture" in names
    # Rank BEFORE the page fetch, so only the k survivors are ever fetched. Never under
    # fixtures, for the same reason PageTextEnricher is not: the golden set attributes
    # results to the BRAIN, and re-ordering its passages would move that baseline.
    if not _pinned and int(getattr(r, "relevance_overfetch", 1) or 1) > 1:
        base = RelevanceRankedProvider(base, overfetch=int(r.relevance_overfetch))
    if getattr(r, "fetch_pages", False) and not _pinned:
        base = PageTextEnricher(base,
                                timeout_s=getattr(r, "fetch_timeout_s", 8.0),
                                max_workers=getattr(r, "fetch_max_workers", 8),
                                min_gain_chars=getattr(r, "fetch_min_gain_chars", 400),
                                max_bytes=getattr(r, "fetch_max_bytes", 400_000),
                                strip_consent=bool(
                                    getattr(r, "strip_consent_banners", False)))
    # `_pinned` bypasses the cross-tick DiskCache. Golden-set queries are stable strings,
    # and store/_cache is full of entries written by earlier UNPINNED runs against live DDG
    # and Exa — so a pinned run would be served yesterday's live web under a fixture chain,
    # silently undoing the pin for exactly the queries the gate cares about most.
    if not cfg.retrieval.cache or _pinned:
        return base
    return DiskCache(base, ttl_s=cfg.retrieval.cache_ttl_s,
                     key_salt=str(_market_block(cfg).get("cache_salt", "") or ""))
