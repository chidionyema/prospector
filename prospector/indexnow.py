"""
IndexNow submission — tell the search engines a URL exists the moment it is published.

WHY THIS EXISTS. The storefront's sitemap is correct and carries real `lastmod` dates, but a
sitemap is a *pull*: the crawler decides when to come back, and for a small site that is measured
in days. The engine publishes several packs a day, so on the pull model a pack's first days —
when it is newest and most linkable — are days it is not in any index. IndexNow is the push
equivalent: one HTTP request naming the changed URLs.

WHO ACTUALLY CONSUMES IT. Bing, Yandex, Seznam and Naver share one IndexNow endpoint; a
submission to any of them is shared with the others. Google does NOT participate — it announced
a 2021 evaluation and has never adopted it, so nothing here should be described as speeding up
Google. It is worth doing anyway because Bing's index is what backs Copilot and, at the time of
writing, ChatGPT's web search — i.e. this is aimed squarely at the AI answer surfaces, which is
the half of discovery a sitemap serves worst.

HOW IT AUTHENTICATES. Ownership is proved by hosting a file containing the key, whose URL is
declared as `keyLocation` in the payload. That file is served by the web app at a fixed path
(`/indexnow-key.txt`, see `Store.Web/src/pages/indexnow-key.txt.tsx`), so BOTH sides must read
the same `INDEXNOW_KEY`. If they disagree the endpoint returns 403 and nothing is indexed — the
failure is silent from the buyer's point of view, which is why `submit` logs the status rather
than swallowing it.

FAILURE POLICY. Publishing a pack must never fail because a search engine was unreachable. Every
path here returns a bool and raises nothing; the caller ignores the result. Unconfigured (no key,
no site URL) is a no-op returning False, not an error — the engine runs on machines that have no
business pinging a production index.
"""

from __future__ import annotations

import logging
import os
from typing import Iterable, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# All participating engines share submissions with each other, so one host is enough and
# api.indexnow.org is the neutral one (using bing.com/indexnow would work identically).
ENDPOINT = "https://api.indexnow.org/IndexNow"

# The protocol's own cap. We submit one or two URLs at a time, so this is a guard against a
# caller looping something unbounded into `urls`, not a limit we expect to reach.
MAX_URLS = 10_000

KEY_PATH = "/indexnow-key.txt"


def _site_url() -> Optional[str]:
    """The public storefront origin: the scheme and host of the live store.

    `STORE_SITE_URL` is read first so the engine can be pointed at a staging storefront without
    disturbing `NEXT_PUBLIC_SITE_URL`, which is the web app's own build-time variable and may be
    present in a shared shell for entirely unrelated reasons.
    """
    raw = os.environ.get("STORE_SITE_URL") or os.environ.get("NEXT_PUBLIC_SITE_URL")
    if not raw:
        return None
    raw = raw.rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        logger.warning("IndexNow: ignoring malformed site URL %r", raw)
        return None
    return raw


def is_configured() -> bool:
    """True when a submission would actually be attempted. Cheap; safe to call anywhere."""
    return bool(os.environ.get("INDEXNOW_KEY")) and _site_url() is not None


def submit(urls: Iterable[str]) -> bool:
    """Announce that `urls` changed. Returns True only on an accepted submission.

    Never raises. An unconfigured engine, an empty list, a URL on another host, an unreachable
    endpoint and a rejected key all return False — the caller is publishing a pack and must not
    care which.
    """
    key = os.environ.get("INDEXNOW_KEY")
    site = _site_url()
    if not key or not site:
        return False

    # Every submitted URL must be on the host that owns the key file; the endpoint rejects the
    # whole batch (422) if one is not. Filtering here means a caller passing a mixed list still
    # gets the valid ones submitted rather than losing all of them.
    wanted: List[str] = []
    for url in urls:
        if url.startswith(site + "/") or url == site:
            wanted.append(url)
        else:
            logger.warning("IndexNow: skipping off-host URL %s (site is %s)", url, site)
    if not wanted:
        return False
    if len(wanted) > MAX_URLS:
        logger.warning("IndexNow: truncating %d URLs to the protocol limit of %d", len(wanted), MAX_URLS)
        wanted = wanted[:MAX_URLS]

    payload = {
        "host": urlparse(site).netloc,
        "key": key,
        "keyLocation": f"{site}{KEY_PATH}",
        "urlList": wanted,
    }

    try:
        import requests  # imported here so the module stays importable without the dependency

        response = requests.post(ENDPOINT, json=payload, timeout=10)
    except Exception as exc:  # network, DNS, TLS, missing dependency — all non-fatal
        logger.warning("IndexNow: submission failed for %d URL(s): %s", len(wanted), exc)
        return False

    # 200 accepted, 202 accepted-pending-key-validation. Both mean we did our part.
    if response.status_code in (200, 202):
        logger.info("IndexNow: submitted %d URL(s) (%s)", len(wanted), response.status_code)
        return True

    # 403 is the one worth reading twice: it means the key file this module points at does not
    # serve the key this module sent, i.e. INDEXNOW_KEY differs between the engine and the web app.
    logger.warning(
        "IndexNow: endpoint returned %s for %d URL(s)%s",
        response.status_code,
        len(wanted),
        " — key file and INDEXNOW_KEY disagree" if response.status_code == 403 else "",
    )
    return False


def submit_pack(pack_id: str) -> bool:
    """Announce one newly published pack, and the catalogue page that now lists it."""
    site = _site_url()
    if not site:
        return False
    return submit([f"{site}/pack/{pack_id}", site])
