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
saving for the rest of the call; availability lookups continue, because they are a different,
unmetered endpoint.

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
SAVE_API = "https://web.archive.org/save/"

#: A real browser UA, matching retrieval._RESOLVE_UA and pack_linter._PROBE_UA.
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

#: A memento never rots, so a hit is cached without expiry. A miss is a statement about the
#: network today, so it is retried on the next publish rather than remembered for a week —
#: the mistake `pack_linter`'s 7-day URL cache made with a wrong dead verdict.
_FAILURE_TTL_S = 6 * 3600


def _cache_load(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return {}
    try:
        data = json.loads(Path(path).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


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
    hit = _lookup(url, timeout_s)
    if hit:
        return hit
    alt = url[:-1] if url.endswith("/") else url + "/"
    if alt.count("/") < 3:          # never degrade "https://host/" to the bare scheme
        return None
    return _lookup(alt, timeout_s)


def _lookup(url: str, timeout_s: float) -> Optional[str]:
    """One cheap, unmetered availability request. Never raises."""
    try:
        resp = requests.get(AVAILABILITY_API, params={"url": url}, timeout=timeout_s,
                            headers={"User-Agent": _UA})
        if resp.status_code != 200:
            return None
        closest = (resp.json().get("archived_snapshots") or {}).get("closest") or {}
    except (requests.RequestException, ValueError):
        return None
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


def save_snapshot(url: str, timeout_s: float = 30.0) -> tuple[Optional[str], bool]:
    """Ask Save Page Now to capture `url`. Returns (memento_or_None, rate_limited).

    `rate_limited` is the signal the caller uses to stop saving for the rest of the batch.
    """
    try:
        resp = requests.get(SAVE_API + url, timeout=timeout_s, allow_redirects=True,
                            headers={"User-Agent": _UA})
    except requests.RequestException as exc:
        logger.warning("archive: save failed", extra={"url": url, "err": type(exc).__name__})
        return None, False

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
                 save_timeout_s: float = 30.0, max_urls: int = 30) -> Dict[str, str]:
    """{url: memento} for as many of `urls` as can be archived. Never raises.

    Bounded by `max_urls` so a pack with a long bibliography cannot stall a publish. What is
    dropped is LOGGED — a silent cap reads as "we archived everything" when it did not.
    """
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

    rate_limited = False
    dirty = False
    for url in unique:
        entry = cache.get(url) or {}
        memento = entry.get("memento")
        if isinstance(memento, str) and memento:
            out[url] = memento
            continue
        if entry and now - float(entry.get("ts") or 0) < _FAILURE_TTL_S:
            continue  # recently failed; do not re-spend the request on this publish

        memento = existing_snapshot(url, timeout_s)
        if memento is None and save_new and not rate_limited:
            memento, rate_limited = save_snapshot(url, save_timeout_s)

        cache[url] = {"memento": memento, "ts": now}
        dirty = True
        if memento:
            out[url] = memento

    if dirty:
        _cache_save(cache_path, cache)
    return out


def archive_sources(sources: Sequence[Any], *, cache_path: Optional[Path] = None,
                    save_new: bool = True, timeout_s: float = 10.0,
                    save_timeout_s: float = 30.0, max_urls: int = 30) -> int:
    """Populate `source.archived_url` in place for each `models.Source`. Returns how many.

    Wrapped in a blanket except on purpose. This runs inside `publish_pass`, upstream of the
    money rail; a `requests` edge case here must never be the reason a paid-for pack fails to
    ship. The worst outcome of a total failure is a pack with no mementos, which is exactly
    what every pack published before today has.
    """
    try:
        by_url = archive_urls((getattr(s, "url", "") for s in sources),
                              cache_path=cache_path, save_new=save_new,
                              timeout_s=timeout_s, save_timeout_s=save_timeout_s,
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
    except Exception as exc:  # noqa: BLE001 — see the docstring; archiving is never fatal
        logger.warning("archive: skipped entirely", extra={"err": f"{type(exc).__name__}: {exc}"})
        return 0
