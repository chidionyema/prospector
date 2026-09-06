"""The research engine's evidence, turned into a signal this factory can generate from.

WHY THIS EXISTS. The unattended tick calls ``run_signal("")`` (scheduler/run_scheduled.py) --
an empty signal, which `generate.py` records as ``seed_kind: blue_sky``. Every batch the
scheduler has produced started from nothing but the model's own priors. That is the mechanical
form of the complaint on crew#659: the factory runs, the store front fills with ideas nobody
researched, and the research lane's own ledger held one idea in a month.

The research engine (chidionyema/research-engine) already does the other half. It runs hourly
against a lane -- `market-demand` asks who pays for a thing today, what they pay, and what
evidence says the demand is falling -- and every claim it keeps has survived a provenance gate:
the source resolved, the snapshot exists, the locator points at the sentence, and a verifier
from a different provider than the producer agreed the source entails the claim. Rejected
claims are kept with the reason, so what this module reads is the admitted set only.

So this module is the join: it reads admitted claims out of the engine's ledger and renders
them as the signal text the generator already knows how to consume. Nothing about prospector is
in the engine, and nothing about the engine's schema leaks past this file -- that boundary is
the engine's own invariant I2, and it is why the adapter lives in this repository rather than
in that one (research-engine SPEC-v1 section 8).

WHAT IT REFUSES TO DO. It never blocks a tick. A database that is unreachable, a query that
fails, a lane with nothing new: every one of those returns an empty signal and the batch runs
blue-sky exactly as it does today. A factory that stops because its research feed is down is a
worse failure than a factory that generates without one. Every degraded return logs at ERROR
with the reason, because a silent empty string is how this would rot back to blue-sky without
anyone noticing.

CREDENTIAL. `RESEARCH_PG_PASSWORD` arrives as a file in the mounted secret directory and
`prospector/file_secrets.py` puts it in the environment before this module is imported. The
role behind it (`research_reader`) can read the ledger and cannot write it: its privileges come
entirely from membership of the engine's NOLOGIN `research_consumer` role. Nothing here holds a
host, a user or a password as a literal (LAW 46).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from prospector import paths

logger = logging.getLogger(__name__)

# The lane whose questions are commercial. The engine holds the questions; this names which of
# its lanes this factory buys from, and it is an environment override rather than a constant
# because a second commercial lane is a config change, not a release.
DEFAULT_LANE = "market-demand"

# How many claims one signal carries. The generator's prompt has a budget and forty claims
# crowd out the market and the question; ten is about what signals/example.txt -- the signal
# the best batch on record came from -- is worth in claims.
DEFAULT_CLAIM_LIMIT = 10

# How old a research request may be and still be worth generating from. A market read three
# weeks ago has the wrong prices in it, and the engine re-asks every lane within the day, so
# refusing an old one costs nothing.
DEFAULT_MAX_AGE_DAYS = 14


def _consumed_path() -> Path:
    """Which research requests this factory has already generated from.

    Prospector's state, in prospector's store -- not a column in the engine's ledger. A
    consumer that writes to the system of record is a consumer that can corrupt it, and the
    read-only role would refuse the write anyway.
    """
    return paths.store_path("research", "consumed.json")


def consumed_keys() -> set[str]:
    p = _consumed_path()
    if not p.exists():
        return set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {str(k) for k in data.get("request_ids", [])}
    except (OSError, ValueError, AttributeError) as e:
        # Losing this file means generating twice from one market: wasteful, not wrong.
        # Refusing to generate because a bookkeeping file is corrupt would be wrong.
        logger.error("research intake: consumed ledger unreadable, treating as empty: %s", e)
        return set()


def mark_consumed(request_id: str, *, keep: int = 500) -> None:
    p = _consumed_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    ids = [i for i in sorted(consumed_keys()) if i != str(request_id)]
    ids.append(str(request_id))
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"request_ids": ids[-keep:]}), encoding="utf-8")
    tmp.replace(p)


def dsn() -> str | None:
    """The engine's ledger, addressed from the environment or not at all.

    Returns None when this deployment has not been given the read side, which is the state of
    every laptop. None means blue-sky, not an exception.
    """
    host = os.environ.get("RESEARCH_PG_HOST")
    password = os.environ.get("RESEARCH_PG_PASSWORD")
    if not host or not password:
        return None
    user = os.environ.get("RESEARCH_PG_USER", "research_reader")
    db = os.environ.get("RESEARCH_PG_DB", "research")
    port = os.environ.get("RESEARCH_PG_PORT", "5432")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


# Admitted claims only, newest request first, and one request per signal: a signal that mixes
# two markets asks the generator to hold two shocks at once and the batch comes back hedged.
# `sources` is the engine's own JSONB and carries the locked URL and the snapshot reference.
_LATEST_SQL = """
SELECT r.id::text, r.subject->>'ref', c.statement, c.sources, c.confidence
  FROM claims c
  JOIN questions q ON q.id = c.question_id
  JOIN requests  r ON r.id = q.request_id
 WHERE c.status = 'admitted'
   AND r.profile_id = %(lane)s
   AND r.created_at > now() - (%(max_age_days)s || ' days')::interval
 ORDER BY r.created_at DESC, c.created_at ASC
"""


def _rows(conn: Any, lane: str, max_age_days: int) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(_LATEST_SQL, {"lane": lane, "max_age_days": str(max_age_days)})
        return list(cur.fetchall())


def _source_urls(sources: Any) -> list[str]:
    """The locked URLs behind one claim, whatever shape the engine stored them in.

    Read defensively: a claim whose sources cannot be parsed still has a statement worth
    generating from, and guessing one shape would drop every source silently -- which is the
    unsourced idea crew#659 objects to, arrived at from the other direction.
    """
    urls: list[str] = []
    if isinstance(sources, str):
        try:
            sources = json.loads(sources)
        except ValueError:
            return []
    if isinstance(sources, dict):
        sources = [sources]
    if not isinstance(sources, list):
        return []
    for s in sources:
        if isinstance(s, dict):
            u = s.get("url") or s.get("uri") or s.get("source_url")
            if u:
                urls.append(str(u))
        elif isinstance(s, str):
            urls.append(s)
    return urls


def render(subject: str, claims: list[tuple[str, list[str], Any]]) -> str:
    """The signal text: a market, what the evidence says about it, and the question.

    The shape follows signals/example.txt, which is the signal the best batch on record came
    from: what changed, then one question asking where the opportunity is. Claims are numbered
    and carry their sources inline so the generator can cite them and a reader can check them.
    An idea whose evidence is a URL is the thing being sold here.
    """
    lines = [
        f"Researched market: {subject}.",
        "",
        "Every statement below was produced by the estate's research engine and survived its "
        "provenance gate: the source resolved, a snapshot was taken, and a verifier from a "
        "different provider than the producer agreed the source entails the statement. "
        "Statements the gate rejected are not here.",
        "",
    ]
    for i, (statement, urls, confidence) in enumerate(claims, start=1):
        tag = f" [{confidence}]" if confidence else ""
        src = f" Sources: {', '.join(urls)}" if urls else " Sources: none recorded."
        lines.append(f"{i}. {statement}{tag}.{src}")
    lines += [
        "",
        "What opportunities exist in this market for a small, evidence-cited product a buyer "
        "would pay for today? Ground every claim you make in the evidence above, or in "
        "evidence you can cite yourself.",
    ]
    return "\n".join(lines)


def next_signal(
    conn: Any,
    *,
    lane: str | None = None,
    claim_limit: int | None = None,
    max_age_days: int | None = None,
    already: set[str] | None = None,
) -> tuple[str, str] | None:
    """The newest researched market this factory has not generated from yet.

    Returns (request_id, signal_text), or None when there is nothing new. The caller marks it
    consumed rather than this function, so a signal is never burned by a tick that then failed
    to use it.
    """
    lane = lane or os.environ.get("RESEARCH_LANE", DEFAULT_LANE)
    claim_limit = claim_limit or int(os.environ.get("RESEARCH_CLAIM_LIMIT", DEFAULT_CLAIM_LIMIT))
    max_age_days = max_age_days or int(
        os.environ.get("RESEARCH_MAX_AGE_DAYS", DEFAULT_MAX_AGE_DAYS)
    )
    already = consumed_keys() if already is None else already

    grouped: dict[str, tuple[str, list[tuple[str, list[str], Any]]]] = {}
    order: list[str] = []
    for request_id, subject, statement, sources, confidence in _rows(conn, lane, max_age_days):
        if request_id in already:
            continue
        if request_id not in grouped:
            grouped[request_id] = (subject or "an unnamed market", [])
            order.append(request_id)
        grouped[request_id][1].append((statement, _source_urls(sources), confidence))

    for request_id in order:
        subject, claims = grouped[request_id]
        if not claims:
            continue
        return request_id, render(subject, claims[:claim_limit])
    return None


def signal_text_or_empty() -> str:
    """What the scheduler calls. Never raises, never blocks a tick.

    An empty string is the factory's current behaviour, so every failure here degrades to what
    it does today and says why at ERROR -- visible in the log the alerter reads, rather than
    indistinguishable from "no new research".
    """
    address = dsn()
    if not address:
        logger.info("research intake: no read side configured, generating blue-sky")
        return ""
    try:
        import psycopg
    except ImportError:
        logger.error("research intake: psycopg is not installed, generating blue-sky")
        return ""
    try:
        with psycopg.connect(address, connect_timeout=10) as conn:
            found = next_signal(conn)
    except Exception as e:  # noqa: BLE001
        # The driver's failure modes are open-ended and not one of them may take a tick down.
        # The type and message are logged; the password is in the DSN and the DSN is not.
        logger.error(
            "research intake: ledger unreadable (%s), generating blue-sky: %s", type(e).__name__, e
        )
        return ""
    if found is None:
        logger.info("research intake: no unused researched market, generating blue-sky")
        return ""
    request_id, text = found
    mark_consumed(request_id)
    logger.critical(
        "research intake: generating from researched market, request %s, %d chars",
        request_id,
        len(text),
        extra={"research_request_id": request_id},
    )
    return text
