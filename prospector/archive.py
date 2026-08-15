"""Snapshot every citation at publish time, so link rot degrades a convenience, not a claim.

The problem this exists for
---------------------------
A pack is generated once and sold indefinitely, so its cost is one-time while the quality of
its evidence decays monotonically: the URLs it cites keep dying after the sale. Measured
2026-08-09 on the packs blocked by `pack_linter.check_urls`: of 14 dead citations, 12 were
genuinely 404 on a GET. That is not a bug to fix, it is the weather.

Two facts make it survivable, and both were already true before this module existed:

  * the full retrieved passage is stored (`models.Source.text`, written to disk with the
    dossier), and
  * the buyer already reads that passage, quoted, in the pack's QA report
    (`dossier.py:428-434`).

So the CLAIM is durable and only the POINTER rots. What was missing was a second pointer.
This module mints one: a Wayback memento captured at publish, stored beside the live URL, so
"follow any of them and check us" stays true in five years.

Measured on those same 14 dead citations, lookup only: 6 already had a usable Wayback capture
that nothing in this codebase was asking for. Those 6 are repairable today at zero cost. The
other 8 are the argument for capturing AT PUBLISH rather than on demand — nobody archived them
while they were alive, and now nobody can.

Design rules, each of which is a failure mode avoided
-----------------------------------------------------
**It can never block a publish.** Archiving is strictly additive: every function here returns
None or a partial result rather than raising, and `archive_sources` swallows everything. The
Internet Archive being slow, rate-limited or down is our convenience failing, not the pack's
quality failing, and the engine-wide rule that an exception is never evidence applies here as
much as on the verdict path.

**Look before you save.** Save Page Now is slow (tens of seconds) and aggressively rate-limits
anonymous callers. Most cited pages, especially the government and Wikipedia pages this
catalogue leans on, are already archived. So the cheap availability API runs first and the
expensive save runs only for URLs with no snapshot at all.

**A 429 stops the batch, not just the request.** Continuing to hammer Save Page Now after it
has asked us to stop earns a longer block, and the next publish inherits it. One 429 disables
saving for the rest of the call.

**The availability API is metered too, and a 429 from it is not an answer.** This module
originally exempted lookups from that rule, on the stated premise that they hit "a different,
unmetered endpoint". Measured 2026-08-09, that premise is false: a plain
`curl 'https://archive.org/wayback/available?url=...'` returned `HTTP 429 Too Many Requests`
during a backfill sweep. Because `_lookup` collapsed every non-200 to None, the 429 was
indistinguishable from "this URL was never archived", and three things compounded:
`existing_snapshot` retried the alternate slash form (a SECOND request, at the exact moment we
were being told to stop), the caller recorded a negative, and that false negative was cached
for `_FAILURE_TTL_S`. The visible symptom was a sweep reporting 0 of 18 dead citations
recoverable, in the same repo whose measured figure is 6 of 14 — with `bbc.co.uk` and
`gov.uk` among the "unarchived". A rate-limited lookup is now propagated as a distinct state,
never cached, and stops further lookups for the batch, exactly as a save-side 429 does.

**Successes are cached forever, failures briefly.** A memento URL does not rot, so re-deriving
it is pure waste and the cache entry never expires. A failure is a statement about today's
network, so it expires quickly and we try again on the next publish. The cache is keyed by
citation URL and shared across packs, which matters because the same statute page is cited by
many of them.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence

import requests

from .telemetry import logger

AVAILABILITY_API = "https://archive.org/wayback/available"
#: The CDX index — same captures, independent throttle. Leads the lookup since 2026-08-13; see
#: `_lookup` for the head-to-head that put it there.
CDX_API = "https://web.archive.org/cdx/search/cdx"
SAVE_API = "https://web.archive.org/save/"

#: A real browser UA, matching retrieval._RESOLVE_UA and pack_linter._PROBE_UA.
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

#: A memento never rots, so a hit is cached without expiry. A miss is a statement about the
#: network today, so it is retried on the next publish rather than remembered for a week —
#: the mistake `pack_linter`'s 7-day URL cache made with a wrong dead verdict.
_FAILURE_TTL_S = 6 * 3600

#: Minimum gap between availability requests, process-wide. A publish batch fires up to 30 of
#: them back to back and archive.org answers a burst with 429; measured 2026-08-13, three
#: unspaced requests were refused and the same three spaced 3s apart all returned 200. This is
#: politeness that buys throughput, not a throttle we are forced to accept.
_MIN_INTERVAL_S = 1.5

#: The 429 retry ladder. Bounded on purpose: `archive_citations` runs inside `publish_pass`,
#: upstream of the money rail, so the worst case must stay in the tens of seconds per URL.
_BACKOFF_S = (4.0, 12.0, 30.0)

#: CDX is an index SCAN, not a key lookup, so it is legitimately slower than the availability
#: API. Measured 2026-08-13: a 30s read timeout fired on a long `.pdf` URL that CDX had answered
#: with a capture minutes earlier. The old 10s budget turned "slow" into "never archived".
_CDX_TIMEOUT_S = 40.0

#: Monotonic stamp of the last availability call, so pacing spans URLs and packs in one process.
_last_call = 0.0

#: Set once the availability API has exhausted the retry ladder in this process. It is the
#: FALLBACK, so paying 46s of backoff for it on every CDX miss is a cost with no upside — one
#: 42-citation pack ran past twenty minutes inside `publish_pass` before this fuse existed.
#: Deliberately per-process, not persisted: a fresh publish run is entitled to try again.
_avail_blocked = False

#: Consecutive Save Page Now timeouts that end saving for a batch, and the running count.
_SAVE_TIMEOUT_FUSE = 2
_save_timeouts = 0


def _cache_load(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return {}
    try:
        data = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {}                         # first run: an empty cache is the correct answer
    except (OSError, ValueError) as exc:
        # A cache file that exists and will not load re-queries the Internet Archive for every
        # URL on every publish, forever, and pays the rate limit for it. Best-effort is the right
        # behaviour; being silent about it is what makes it permanent.
        logger.error("archive: citation cache at %s is unreadable, re-querying every URL: %s",
                     path, exc)
        return {}
    if not isinstance(data, dict):
        logger.error("archive: citation cache at %s is a %s, not an object; ignoring it",
                     path, type(data).__name__)
        return {}
    return data


def _cache_save(path: Optional[Path], cache: Dict[str, Any]) -> None:
    if path is None:
        return
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(cache, indent=2, sort_keys=True))
    except OSError:
        pass  # the cache is an optimisation; never let it break a publish


def existing_snapshot(url: str, timeout_s: float = 10.0) -> Optional[str]:
    """The closest existing Wayback capture of `url`, or None.

    Only a snapshot the API reports as `available` counts. A capture whose own status was a
    4xx/5xx is worse than nothing: it would put a memento of an error page next to the quote
    it is supposed to corroborate, which reads as evidence and is not.

    The availability API matches the URL as a near-literal key, so it answers differently for
    forms a browser treats as identical. Measured 2026-08-09: `https://example.com` returns a
    capture and `https://example.com/` returns nothing, on the same site archived thousands of
    times. Trying the other form is the difference between "no snapshot" and "not asked
    correctly" — the same distinction `pack_linter._probe_url` draws for the live URL.
    """
    return _snapshot(url, timeout_s)[0]


def _snapshot(url: str, timeout_s: float) -> tuple[Optional[str], bool]:
    """`existing_snapshot` plus the rate-limit state the caller must not discard.

    Returns (memento_or_None, rate_limited). The two are NOT interchangeable: None with
    `rate_limited=False` means the Internet Archive answered and has no capture, which is a
    fact worth caching; None with `rate_limited=True` means it declined to answer, which is a
    fact about today's traffic and must never be recorded as a property of the URL.
    """
    hit, limited = _lookup(url, timeout_s)
    if hit:
        return hit, False
    # Asking again while being rate-limited is what earns a longer block, and the alt form is
    # a guess at best. Stop here and let the caller retry the whole URL on a later run.
    if limited:
        return None, True
    alt = url[:-1] if url.endswith("/") else url + "/"
    if alt.count("/") < 3:          # never degrade "https://host/" to the bare scheme
        return None, False
    return _lookup(alt, timeout_s)


def _lookup(url: str, timeout_s: float) -> tuple[Optional[str], bool]:
    """The most recent successful capture of `url`. Returns (memento, rate_limited).

    2026-08-13 — WE WERE ASKING THE WRONG SERVICE, and that is why published packs sit unlisted.
    `/wayback/available` is throttled to near-uselessness for a publish batch: a run logged
    `archived 0/22 citation(s)` and `archived 0/46` because the FIRST 429 sets `rate_limited`
    and `archive_citations` then skips every remaining URL. The lint blocks a definitive 404/410
    unless a memento corroborates it, so the escape hatch existed and never once fired.

    Backing off does not fix it. Measured head-to-head the same day, on the dead citations of
    the stranded packs, after a full `_BACKOFF_S` ladder (4s/12s/30s) had already been spent:

        availability=429  cdx=200 captures=1  20260218062023  aol.com/news/2013-01-29-security…
        availability=429  cdx=200 captures=1  20260103025511  oconnors.law/people/kathryn-howard/
        availability=429  cdx=200 captures=1  20260609174442  scanbaby.co.uk/is-the-nhs-wait-too…
        availability=429  cdx=200 captures=1  20241203032333  ulh.nhs.uk/wp-content/…IRMER-2017.pdf

    4 for 4, identical timestamps to what the availability API returns when it deigns to answer.
    The CDX index is a different service on a different limit, so it leads now and the
    availability API is the fallback. `filter=statuscode:[23]..` reproduces the invariant this
    function has always enforced — never hand a buyer a memento OF an error page — and
    `limit=-1` takes the most recent capture, which is what "closest" meant.

    Calls are still paced (`_MIN_INTERVAL_S`) and still climb `_BACKOFF_S` on a 429, because
    politeness is what keeps CDX answering. `rate_limited=True` is reserved for BOTH services
    declining the whole ladder — the only state that justifies abandoning a batch.
    """
    global _avail_blocked
    memento, cdx_unanswered = _paced_get(_cdx_memento, CDX_API, url, timeout_s)
    if memento:
        return memento, False
    # Fall through on a miss, not only on a refusal: the two endpoints index the same captures
    # but disagree at the edges (the availability API's near-literal URL key is why `_snapshot`
    # tries the trailing-slash form at all), and a second request is cheap next to a pack that
    # cannot be sold.
    #
    # Cheap ONLY while that endpoint is answering. Timed on a real 42-citation pack: the
    # availability API 429s on essentially every call right now, so each miss cost the whole
    # 4s+12s+30s ladder and one pack's archiving ran past twenty minutes — inside `publish_pass`,
    # upstream of the money rail. So the fallback is fused: once the ladder has been exhausted
    # against it, this process stops asking for the rest of the batch. CDX is unaffected.
    if not _avail_blocked:
        memento, avail_unanswered = _paced_get(_availability_memento, AVAILABILITY_API, url,
                                               timeout_s)
        if memento:
            return memento, False
        if avail_unanswered:
            _avail_blocked = True
            logger.warning("archive: availability API fused off for this run; CDX only")
    else:
        avail_unanswered = True
    # `unanswered` is True only if NEITHER service answered — a definitive "no captures" from
    # either one is a fact about the URL and may be cached.
    return None, cdx_unanswered and avail_unanswered


def _cdx_memento(resp: "requests.Response") -> Optional[str]:
    """Parse a CDX reply into a memento URL. The body is `[[header], [ts, original], …]`, or
    empty (not `[]`) when nothing was ever captured."""
    body = resp.text.strip()
    if not body:
        return None
    rows = resp.json()
    if not isinstance(rows, list) or len(rows) < 2 or len(rows[-1]) < 2:
        return None
    ts, original = str(rows[-1][0]), str(rows[-1][1])
    if not ts.isdigit() or not original.startswith("http"):
        return None
    return f"https://web.archive.org/web/{ts}/{original}"


def _availability_memento(resp: "requests.Response") -> Optional[str]:
    """Parse an availability-API reply into a memento URL."""
    closest = (resp.json().get("archived_snapshots") or {}).get("closest") or {}
    if not closest.get("available"):
        return None
    status = str(closest.get("status") or "200")
    if not status.startswith("2") and not status.startswith("3"):
        return None
    memento = closest.get("url")
    if not isinstance(memento, str) or not memento.startswith("http"):
        return None
    # The API answers in http:// for historical reasons; the storefront is https-only and a
    # mixed-content link is one a browser may refuse to open.
    return memento.replace("http://web.archive.org/", "https://web.archive.org/", 1)


def _paced_get(parse, endpoint: str, url: str, timeout_s: float) -> tuple[Optional[str], bool]:
    """One paced, 429-retried GET against `endpoint`, parsed by `parse`. Never raises.

    Returns (memento_or_None, unanswered). The two are NOT interchangeable: None with
    `unanswered=False` means the service answered and has no capture, which is a fact worth
    caching; None with `unanswered=True` means we never got an answer, which is a fact about
    today's traffic and must never be recorded as a property of the URL.

    **A read timeout is an unanswered call, not a "no".** Before 2026-08-13 a `RequestException`
    returned `(None, False)`, so the caller wrote `{"memento": None}` and every later publish
    read it back as "already checked, not archived". Measured that day: CDX read-timed out at
    30s on `ulh.nhs.uk/...IRMER-2017.pdf`, a URL CDX had answered with a capture minutes
    earlier — the index is a scan and long/rare URLs are genuinely slow, which is why CDX gets
    `_CDX_TIMEOUT_S` rather than the availability API's budget. Timeouts now climb the same
    ladder as a 429 and end in `unanswered=True`.
    """
    global _last_call
    is_cdx = endpoint == CDX_API
    params = ({"url": url, "output": "json", "limit": "-1", "fl": "timestamp,original",
               "filter": "statuscode:[23].."} if is_cdx else {"url": url})
    timeout_s = max(timeout_s, _CDX_TIMEOUT_S) if is_cdx else timeout_s
    name = "cdx" if is_cdx else "availability"
    for attempt, backoff in enumerate((*_BACKOFF_S, None)):
        gap = _MIN_INTERVAL_S - (time.monotonic() - _last_call)
        if gap > 0:
            time.sleep(gap)
        try:
            _last_call = time.monotonic()
            resp = requests.get(endpoint, params=params, timeout=timeout_s,
                                headers={"User-Agent": _UA})
            if resp.status_code == 429:
                if backoff is None:                      # the ladder is spent; give up honestly
                    logger.warning("archive: %s API rate-limited after %d retries", name,
                                   attempt, extra={"url": url})
                    return None, True
                # A server-stated Retry-After outranks our guess, but never by more than a
                # minute — a publish must not park on the money rail waiting for archive.org.
                try:
                    wait = min(60.0, max(float(resp.headers.get("Retry-After", 0) or 0), backoff))
                except (TypeError, ValueError):
                    wait = backoff
                logger.info("archive: %s API 429; retrying in %.0fs", name, wait,
                            extra={"url": url})
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                return None, False
            return parse(resp), False
        except (requests.Timeout, requests.ConnectionError) as exc:
            # Never reached us / never came back. Retry, then admit we do not know.
            if backoff is None:
                logger.warning("archive: %s API unreachable after %d retries (%s)", name,
                               attempt, type(exc).__name__, extra={"url": url})
                return None, True
            time.sleep(backoff)
            continue
        except (requests.RequestException, ValueError, IndexError):
            return None, False                           # a real, malformed answer: that IS a no
    return None, True                                    # the ladder ends in None; unreachable


def save_snapshot(url: str, timeout_s: float = 30.0) -> tuple[Optional[str], bool]:
    """Ask Save Page Now to capture `url`. Returns (memento_or_None, rate_limited).

    `rate_limited` is the signal the caller uses to stop saving for the rest of the batch.
    """
    global _save_timeouts
    try:
        resp = requests.get(SAVE_API + url, timeout=timeout_s, allow_redirects=True,
                            headers={"User-Agent": _UA})
    except (requests.Timeout, requests.ConnectionError) as exc:
        # Save Page Now is either taking captures right now or it is not; a read timeout is the
        # slow way it says no. Each one costs the full `save_timeout_s`, and a 30-URL batch of
        # them is fifteen minutes inside `publish_pass`. Two in a row and this batch stops
        # asking — measured 2026-08-13, that is exactly how it fails when it fails.
        _save_timeouts += 1
        logger.warning("archive: save failed", extra={"url": url, "err": type(exc).__name__})
        if _save_timeouts >= _SAVE_TIMEOUT_FUSE:
            logger.warning("archive: Save Page Now unresponsive; skipping saves for this batch")
            return None, True
        return None, False
    except requests.RequestException as exc:
        logger.warning("archive: save failed", extra={"url": url, "err": type(exc).__name__})
        return None, False
    _save_timeouts = 0                                   # it answered; the streak is broken

    if resp.status_code == 429:
        logger.warning("archive: Save Page Now rate-limited; skipping saves for this batch")
        return None, True
    if resp.status_code >= 400:
        return None, False

    # SPN reports the capture in Content-Location as a site-relative path; the final URL
    # after redirects is the fallback.
    loc = resp.headers.get("Content-Location") or ""
    if loc.startswith("/web/"):
        return "https://web.archive.org" + loc, False
    final = str(resp.url or "")
    if "/web/" in final and final.startswith("http"):
        return final.replace("http://web.archive.org/", "https://web.archive.org/", 1), False
    return None, False


def archive_urls(urls: Iterable[str], *, cache_path: Optional[Path] = None,
                 save_new: bool = True, timeout_s: float = 10.0,
                 save_timeout_s: float = 30.0, save_budget_s: float = 60.0,
                 max_urls: int = 30) -> Dict[str, str]:
    """{url: memento} for as many of `urls` as can be archived. Never raises.

    Bounded by `max_urls` so a pack with a long bibliography cannot stall a publish. What is
    dropped is LOGGED — a silent cap reads as "we archived everything" when it did not.
    """
    global _save_timeouts
    _save_timeouts = 0          # the SPN fuse is per batch, so each pack gets its own two tries
    cache = _cache_load(cache_path)
    now = time.time()
    out: Dict[str, str] = {}

    unique: list[str] = []
    for url in urls:
        if isinstance(url, str) and url.startswith("http") and url not in unique:
            unique.append(url)
    if len(unique) > max_urls:
        logger.warning("archive: capping at %d of %d citation URLs; %d not archived",
                       max_urls, len(unique), len(unique) - max_urls)
        unique = unique[:max_urls]

    rate_limited = False        # Save Page Now has asked us to stop
    lookup_limited = False      # the availability API has asked us to stop
    deferred = 0
    dirty = False

    # Two passes, and the order is load-bearing. Only a LOOKUP can list a pack today: the lint's
    # escape hatch needs a capture that already exists, and a dead 404 URL cannot be captured
    # now in any case. Saving is durability for the NEXT publish, and Save Page Now takes tens
    # of seconds per URL because it really fetches the page. Interleaved (the shape until
    # 2026-08-13) one slow save delayed every lookup behind it, and a 30-URL pack spent a
    # quarter of an hour inside `publish_pass`, upstream of the money rail.
    misses: list[str] = []
    for url in unique:
        entry = cache.get(url) or {}
        memento = entry.get("memento")
        if isinstance(memento, str) and memento:
            out[url] = memento
            continue
        if entry and now - float(entry.get("ts") or 0) < _FAILURE_TTL_S:
            continue  # recently failed; do not re-spend the request on this publish
        if lookup_limited:
            deferred += 1
            continue  # see below: an unasked URL is not an unarchived one

        memento, lookup_limited = _snapshot(url, timeout_s)

        # A 429 means we never got an answer, so there is nothing here worth remembering.
        # Writing `{"memento": None}` would pin our own throttling onto the URL for
        # `_FAILURE_TTL_S`, and every later run would read it back as "already checked, not
        # archived" without ever asking again.
        if memento is None and lookup_limited:
            deferred += 1
            continue
        if memento:
            out[url] = memento
            cache[url] = {"memento": memento, "ts": now}
            dirty = True
        else:
            misses.append(url)

    # Pass 2: best-effort, and hard-stopped by the clock. What the budget drops is LOGGED, and
    # a URL we never tried to save is left OUT of the cache so a later run still tries it.
    started = time.monotonic()
    for url in misses:
        out_of_budget = time.monotonic() - started >= save_budget_s
        if save_new and not rate_limited and not out_of_budget:
            memento, rate_limited = save_snapshot(url, save_timeout_s)
        elif save_new:
            # We meant to save and were stopped by the clock or a 429, so we do not know whether
            # this URL is archivable. Caching it as missing would pin our own budget onto it.
            deferred += 1
            continue
        else:
            memento = None      # caller never wanted a save: the lookup miss IS the answer
        cache[url] = {"memento": memento, "ts": now}
        dirty = True
        if memento:
            out[url] = memento

    if deferred:
        logger.warning("archive: %d URL(s) left unchecked (rate limit or save budget) and NOT "
                       "cached as missing; retry on a later run", deferred)

    if dirty:
        _cache_save(cache_path, cache)
    return out


def archive_sources(sources: Sequence[Any], *, cache_path: Optional[Path] = None,
                    save_new: bool = True, timeout_s: float = 10.0,
                    save_timeout_s: float = 30.0, save_budget_s: float = 60.0,
                    max_urls: int = 30) -> int:
    """Populate `source.archived_url` in place for each `models.Source`. Returns how many.

    Wrapped in a blanket except on purpose. This runs inside `publish_pass`, upstream of the
    money rail; a `requests` edge case here must never be the reason a paid-for pack fails to
    ship. The worst outcome of a total failure is a pack with no mementos, which is exactly
    what every pack published before today has.

    The blanket therefore STAYS, but it is split in two. `requests.RequestException` subclasses
    `OSError`, so the remote failures this is built to absorb are nameable; anything outside that
    set is a bug in THIS function, not the Internet Archive being slow, and one `logger.warning`
    with no traceback made a refactor's `TypeError` read exactly like a socket timeout. Both
    still return 0 — the caller (`store.py:192`, `bridge.py:968`) only ever logs the count — so
    the log is the only place the distinction can live.
    """
    try:
        by_url = archive_urls((getattr(s, "url", "") for s in sources),
                              cache_path=cache_path, save_new=save_new,
                              timeout_s=timeout_s, save_timeout_s=save_timeout_s,
                              save_budget_s=save_budget_s,
                              max_urls=max_urls)
        n = 0
        for src in sources:
            memento = by_url.get(getattr(src, "url", ""))
            if memento:
                try:
                    src.archived_url = memento
                    n += 1
                except AttributeError:
                    pass
        return n
    except (OSError, ValueError) as exc:
        logger.error("archive: skipped entirely (remote or I/O failure)",
                     extra={"err": f"{type(exc).__name__}: {exc}"})
        return 0
    except Exception as exc:  # noqa: BLE001 — see the docstring; archiving is never fatal
        logger.exception(
            "archive: skipped entirely on an UNEXPECTED %s — this is a bug in archive_sources, "
            "not a remote failure", type(exc).__name__,
            extra={"err": f"{type(exc).__name__}: {exc}"})
        return 0
