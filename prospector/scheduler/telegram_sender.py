"""Send an operator alert to Telegram from inside this repo, with no estate installed.

WHY THIS EXISTS (issue #355). The alert rail's off-machine sink was a local import of
`~/.hermes/scripts/estate_alert.py`. That worked while the engine ran on the founder's Mac. Since
the Fly cutover on 2026-08-18 the engine runs in a container with no `$HOME/.hermes`, so
`_load_hermes_sender()` returns None and every founder-actionable alert stays in a file nobody
reads. Measured 2026-08-20 on `prospector-engine`: 18 `moat_blind` criticals in
`store/scheduler/alerts.jsonl`, none delivered, while the moat had been blind for hours.

THE CONTRACT IS HERMES', DELIBERATELY. Same name, same signature, same never-raises promise, so
`alerts.py` can fall back to this without a second code path:

    send_operator_alert(text, *, debounce_key=None, debounce_s=300.0, dry_run=False) -> bool

Credentials come from the environment — `TELEGRAM_BOT_TOKEN` and `TELEGRAM_HOME_CHANNEL` — which
is how a container gets them (`fly secrets`). Nothing is read from a file in `$HOME`, because a
path under `$HOME` is exactly what broke.

THE DEBOUNCE STATE GOES IN THE STORE, NOT IN `$HOME`. `config.store_root()` is the one resolver.
A debounce file derived from `__file__` follows the CODE rather than the store, which is how a
daemon and a probe end up reading different copies and neither can see the other's state.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

#: Telegram refuses a longer message outright, so a too-long alert is a silently dropped alert.
TELEGRAM_MAX_CHARS = 4096

_TIMEOUT_S = 10.0


def _debounce_path() -> Path:
    from prospector import config

    return Path(config.store_root()) / "scheduler" / ".telegram-debounce.json"


def _fit(text: str, limit: int = TELEGRAM_MAX_CHARS) -> str:
    """Trim to the limit on a LINE boundary, so a trimmed alert is never a half sentence.

    An alert cut mid-word reads as corruption and costs the reader a trip to the log to find out
    what it said. Cutting at the last newline keeps every line that survives readable, and the
    marker says the message was longer rather than leaving the reader to guess.
    """
    if len(text) <= limit:
        return text
    marker = "\n[trimmed]"
    head = text[: limit - len(marker)]
    cut = head.rfind("\n")
    # A single line longer than the limit has no newline to cut at; take the hard slice rather
    # than returning just the marker.
    if cut > 0:
        head = head[:cut]
    return head + marker


def _debounced(key: str, window_s: float) -> bool:
    """True when this key was sent inside the window. An unusable state file answers False.

    Failing OPEN is deliberate. A debounce file that cannot be read must never be the reason a
    critical alert is withheld: the worst case of failing open is a duplicate message, and the
    worst case of failing closed is silence during the outage the rail exists for.

    Only OSError and ValueError are absorbed, and both are logged at ERROR. Anything else is our
    bug and belongs in `send_operator_alert`'s handler, which is where the never-raises promise
    to the caller is actually kept.
    """
    if not key or window_s <= 0:
        return False
    path = _debounce_path()
    now = time.time()
    try:
        state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(state, dict):
            raise ValueError(f"debounce state is {type(state).__name__}, not a dict")
    except (OSError, ValueError) as exc:
        # NARROW and LOUD, both deliberately. Narrow, because an unreadable file and a malformed
        # one are the only failures this can legitimately absorb; anything else is our bug and
        # should reach the caller's own handler. Loud, because a debounce that silently resets
        # sends every alert twice, and a silent reset leaves no trace that it happened.
        logger.error("Telegram debounce state at %s unusable (%s) — treating every key as unsent, "
                     "so alerts may repeat until this is fixed", path, exc)
        state = {}
    last = state.get(key)
    if isinstance(last, (int, float)) and (now - last) < window_s:
        return True
    state[key] = now
    # Keep the file from growing without bound: drop anything older than a day.
    state = {k: v for k, v in state.items() if isinstance(v, (int, float)) and (now - v) < 86400.0}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        tmp.replace(path)
    except Exception:  # noqa: BLE001 — best effort; a lost stamp costs a duplicate, never silence
        pass
    return False


def credentials() -> tuple[str, str]:
    """The bot token and channel from the environment. Empty strings when unset.

    Returned rather than logged. The token is a secret and must never reach a log line, an
    exception message or a URL that gets printed.
    """
    return (
        os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
        os.environ.get("TELEGRAM_HOME_CHANNEL", "").strip(),
    )


def configured() -> bool:
    """True when both credentials are present. Lets a probe grade the rail without sending."""
    token, channel = credentials()
    return bool(token and channel)


def send_operator_alert(
    text: str, *, debounce_key: str | None = None, debounce_s: float = 300.0, dry_run: bool = False
) -> bool:
    """Send `text` to the founder's Telegram channel. Returns True when a message left the box.

    NEVER RAISES. An alert rail that can throw takes down the thing it was watching, and the
    caller is usually already handling a failure when it gets here.

    The debounce is checked BEFORE `dry_run`, matching Hermes, so a dry run consumes the window
    exactly as a real send does and a test cannot report a different debounce state than
    production would have.
    """
    try:
        body = _fit((text or "").strip())
        if not body:
            return False
        if debounce_key and _debounced(debounce_key, debounce_s):
            logger.info("Telegram alert debounced key=%s", debounce_key)
            return False
        if dry_run:
            logger.info("Telegram alert dry_run key=%s chars=%d", debounce_key, len(body))
            return False
        token, channel = credentials()
        if not token or not channel:
            # Named, not silent. This is the exact state issue #355 was opened for, and it is
            # invisible unless something says which half is missing.
            logger.warning(
                "Telegram alert NOT sent: %s unset. The alert stayed in the local sinks only.",
                " and ".join(
                    n
                    for n, v in (("TELEGRAM_BOT_TOKEN", token), ("TELEGRAM_HOME_CHANNEL", channel))
                    if not v
                ),
            )
            return False
        data = urllib.parse.urlencode({"chat_id": channel, "text": body}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:  # noqa: S310 — fixed host
            ok = 200 <= resp.status < 300
        logger.info("Telegram alert key=%s sent=%s chars=%d", debounce_key, ok, len(body))
        return ok
    except Exception as exc:  # noqa: BLE001 — documented never-raises
        # The token can appear in the URL inside a urllib exception, so log the TYPE and never
        # the exception text.
        logger.warning("Telegram alert push failed: %s", type(exc).__name__)
        return False
