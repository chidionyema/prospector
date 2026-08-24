"""Is each brain actually answering? One probe, every model the platform can build.

Founder directive 2026-08-21, verbatim: "also when enabeld fron ops, should be able to test
fron ops console and cconfirn nodel is active", "need heatbeat", "for all nodels in platforn".

WHAT COUNTS AS ALIVE HERE, AND WHY IT IS NOT "THE SOCKET OPENED". A provider that answers 200
with an upsell body, a provider that answers with a different model than the one pinned, and a
provider whose key was revoked all look identical to a connectivity check. So a probe asks for
one specific word and grades the ANSWER. `state` is `alive` only when the configured model
returned the word it was asked for. Everything else gets its own state, because the repair is
different in each case: a missing key is a config edit, a permanent exhaustion is money, a
transient one is a wait.

WHY THIS NEVER WRITES A DEAD MARK. It calls the adapter's `_raw` directly rather than going
through `make_operator`, so nothing here marks a provider exhausted and nothing here consumes
the half-open re-probe slot in `health.py`. A monitor that benches brains is a monitor that can
take the engine down, and a heartbeat that eats the recovery probe is why a recovered brain
would look dead until the next real call. This module only ever REPORTS.

WHAT IT COSTS, WHICH IS THE REASON FOR THE TWO CADENCES. A probe is a real call and a metered
tier bills for it. Measured 2026-08-21: one claude_cli probe logged `cost_usd 0.0490218`. At the
free-tier cadence of 15 minutes that is $4.70 a day to learn something nothing was waiting on.
So `metered_interval_s` (6h by default) governs the tiers in `METERED_TIERS` and
`interval_s` (15m) governs the rest. The on-demand console test ignores both: the founder
clicking Test is a person deciding to spend, which is the one case where the spend is wanted.
"""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ..config import store_root
from ..errors import PERMANENT, TRANSIENT, classify_exhaustion

#: What the probe asks for. Short on purpose: the answer is graded, and a long answer costs
#: tokens on tiers that reserve `max_tokens` against a per-minute budget (see the groq note in
#: config.yaml). One word in, one word out.
_log = logging.getLogger(__name__)

PROBE_SYSTEM = "Answer with one word and nothing else."
PROBE_USER = "Reply with the single word ALIVE."
PROBE_EXPECT = "alive"

#: Tiers that bill per call, or that spend an allowance a person is relying on. They are probed
#: on the LONG cadence. This is a list of what costs money, not a list of what is slow.
METERED_TIERS = frozenset({"claude_cli", "minimax", "minimax_m27", "openrouter", "deepseek"})

#: Concurrency. The founder's standing rule is "i dont want consurreny onclaude code", so
#: claude_cli is probed ALONE, after everything else has finished. Distinct HTTP providers are
#: independent accounts on independent hosts and are probed together — that ban is about the
#: Claude Code CLI, not about parallelism in general.
SERIAL_TIERS = frozenset({"claude_cli"})
MAX_PARALLEL_PROBES = 6

#: A probe that has not answered by here is reported as `timeout`, not waited on. A benched
#: MiniMax runs a 5/10/20/40s retry ladder before it raises — measured at 77.2s on 2026-08-21 —
#: and a heartbeat must not be hostage to the slowest dead tier.
DEFAULT_PROBE_TIMEOUT_S = 30.0

DEFAULT_INTERVAL_S = 900.0
DEFAULT_METERED_INTERVAL_S = 21600.0


def heartbeat_path() -> Path:
    """Where the last round is kept. Under `store_root()`, never derived from `__file__` —
    a store path that follows the CODE is the 2026-08-18 trap that split the health file."""
    return store_root() / "health" / "heartbeat.json"


def platform_tiers(cfg) -> tuple[str, ...]:
    """Every model the platform can build: the built-ins plus everything declared in
    `config.yaml providers:`. Founder: "for all nodels in platforn".

    Generated, never hand-listed. A hand-written roster is how a provider gets added to config
    and stays invisible on the console for six weeks.
    """
    from ..providers import buildable_tiers

    declared = getattr(cfg, "providers", {}) or {}
    out = []
    for name in buildable_tiers(declared):
        if name in _NOT_PROBEABLE:
            continue
        out.append(name)
    return tuple(out)


#: `mock` answers instantly from a fixture and proves nothing about the world. The two removed
#: tiers raise ValueError by design. Probing any of them is noise, not evidence.
_NOT_PROBEABLE = frozenset({"mock", "claude", "cursor_cli", "standardcompute"})


def _model_of(op: Any) -> str:
    for attr in ("_model", "model", "default_model"):
        v = getattr(op, attr, None)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def probe_one(cfg, tier: str, *, component: str | None = None,
              timeout_s: float = DEFAULT_PROBE_TIMEOUT_S) -> dict:
    """Call one tier once and grade the answer. Never raises, never marks anything dead."""
    from ..operator import _build_operator, is_provisional_provider

    started = time.time()
    row: dict[str, Any] = {
        "tier": tier,
        "model": "",
        "ok": False,
        "state": "error",
        "latency_ms": 0.0,
        "reply": "",
        "error": "",
        "trusted": not is_provisional_provider(tier),
        "ts": started,
    }
    try:
        op = _build_operator(tier, cfg, False, component=component)
        row["model"] = _model_of(op)
    except Exception as exc:  # construction failed: no key, removed tier, bad declaration
        row["error"] = f"{type(exc).__name__}: {exc}"[:400]
        low = row["error"].lower()
        row["state"] = "no_key" if ("api_key" in low or "credential" in low
                                    or "unset" in low or "not set" in low) else "not_buildable"
        row["latency_ms"] = round((time.time() - started) * 1000, 1)
        return row

    try:
        reply = op._raw(PROBE_SYSTEM, PROBE_USER, 0.0)
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        row["error"] = detail[:400]
        kind = classify_exhaustion(detail)
        row["state"] = ("exhausted_permanent" if kind == PERMANENT else
                        "exhausted_transient" if kind == TRANSIENT else "error")
        row["latency_ms"] = round((time.time() - started) * 1000, 1)
        return row

    text = (reply or "").strip()
    row["reply"] = text[:200]
    row["latency_ms"] = round((time.time() - started) * 1000, 1)
    if PROBE_EXPECT in text.lower():
        row["ok"] = True
        row["state"] = "alive"
    else:
        # It answered, so the credential and the endpoint are fine — but it did not answer the
        # question. That is the upsell-body shape (`errors._USED_UP_RE`) and the wrong-model
        # shape, and reporting it as alive is how both stayed invisible for a day each.
        row["state"] = "answered_wrong"
        row["error"] = "the model answered but not with the word it was asked for"
    return row


def probe_all(cfg, tiers: tuple[str, ...] | None = None, *,
              timeout_s: float = DEFAULT_PROBE_TIMEOUT_S) -> list[dict]:
    """Probe every named tier. Parallel for HTTP providers, serial for the Claude CLI."""
    names = tuple(tiers) if tiers is not None else platform_tiers(cfg)
    parallel = [n for n in names if n not in SERIAL_TIERS]
    serial = [n for n in names if n in SERIAL_TIERS]
    by_name: dict[str, dict] = {}

    if parallel:
        with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_PROBES, len(parallel)),
                                thread_name_prefix="hb") as pool:
            futures = {pool.submit(probe_one, cfg, n, timeout_s=timeout_s): n for n in parallel}
            deadline = time.time() + timeout_s
            for fut, name in futures.items():
                left = max(0.0, deadline - time.time())
                try:
                    by_name[name] = fut.result(timeout=left)
                except Exception:
                    by_name[name] = {"tier": name, "model": "", "ok": False, "state": "timeout",
                                     "latency_ms": round(timeout_s * 1000, 1), "reply": "",
                                     "error": f"no answer within {timeout_s:.0f}s",
                                     "trusted": False, "ts": time.time()}

    for name in serial:
        by_name[name] = probe_one(cfg, name, timeout_s=timeout_s)

    return [by_name[n] for n in names if n in by_name]


def _interval_for(cfg, tier: str) -> float:
    hb = getattr(cfg, "heartbeat", None) or {}
    if tier in METERED_TIERS:
        return float(hb.get("metered_interval_s", DEFAULT_METERED_INTERVAL_S))
    return float(hb.get("interval_s", DEFAULT_INTERVAL_S))


def _load(path: Path) -> dict:
    """The last round, or an empty dict when no round has ever been written.

    A MISSING file and an UNREADABLE one are different facts and the caller must be able to
    tell them apart. Missing means nothing has beaten yet, which is the ordinary state of a
    fresh checkout. Unreadable means the record of which brains are alive has been damaged,
    and returning {} for that would report a quiet, empty, healthy-looking round while the
    engine is flying blind. So: the missing case is checked first and is not an exception at
    all, and the damaged case is narrowed to the two errors a JSON file on disk can actually
    raise, is logged at ERROR, and still returns {} so a damaged file cannot stop the beat.
    """
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        _log.error("Heartbeat record at %s exists but could not be read (%s); "
                   "treating this round as the first one", path, exc)
        return {}


def run_heartbeat(cfg, *, force: bool = False, tiers: tuple[str, ...] | None = None,
                  now: float | None = None) -> dict:
    """One round. Skips any tier probed more recently than its own cadence allows.

    `force` is the console Test button: a person asking is a person choosing to spend.
    """
    now = time.time() if now is None else now
    path = heartbeat_path()
    prev = _load(path)
    prev_rows = {r.get("tier"): r for r in prev.get("providers", []) if isinstance(r, dict)}

    names = tuple(tiers) if tiers is not None else platform_tiers(cfg)
    due, skipped = [], []
    for name in names:
        last = float(prev_rows.get(name, {}).get("ts") or 0.0)
        # `last <= 0` is NEVER PROBED, and it is a separate case from "probed long ago". Without
        # it the arithmetic reads the epoch as the last probe, so a tier is due only once the
        # clock has run for its whole interval — true on a real clock, false the moment anything
        # supplies its own `now`, and false for the case that matters most: a provider added to
        # config five minutes ago, which is exactly the one somebody is waiting to see answer.
        if force or last <= 0.0 or (now - last) >= _interval_for(cfg, name):
            due.append(name)
        else:
            skipped.append(name)

    fresh = {r["tier"]: r for r in probe_all(cfg, tuple(due))} if due else {}
    # ONE ROUND, ONE TIMESTAMP. `probe_one` stamps the wall clock, which is right when it is
    # called on its own, and wrong here: this function decides what is due against `now`, so a
    # row stamped from a different clock lets "age" and "due" disagree. Everything probed in
    # this round is dated to this round.
    for row in fresh.values():
        row["ts"] = now

    rows = []
    for name in names:
        if name in fresh:
            rows.append(fresh[name])
        elif name in prev_rows:
            carried = dict(prev_rows[name])
            carried["stale"] = True
            carried["age_s"] = round(now - float(carried.get("ts") or 0.0), 1)
            rows.append(carried)

    out = {
        "ts": now,
        "probed": sorted(due),
        "skipped_not_due": sorted(skipped),
        "alive": sorted(r["tier"] for r in rows if r.get("ok")),
        "down": sorted(r["tier"] for r in rows if not r.get("ok")),
        "providers": rows,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, indent=2, sort_keys=True))
    os.replace(tmp, path)          # atomic: a reader never sees a half-written round
    return out


def heartbeat_view(cfg) -> dict:
    """What the console shows. READ-ONLY and free — it reads the last round off disk and
    spends nothing. Probing on a page load is how a dashboard becomes a bill."""
    data = _load(heartbeat_path())
    now = time.time()
    rows = data.get("providers") or []
    for r in rows:
        if isinstance(r, dict) and r.get("ts"):
            r["age_s"] = round(now - float(r["ts"]), 1)
    known = {r.get("tier") for r in rows if isinstance(r, dict)}
    never = [t for t in platform_tiers(cfg) if t not in known]
    return {
        "last_round_ts": data.get("ts"),
        "last_round_age_s": round(now - float(data["ts"]), 1) if data.get("ts") else None,
        "alive": data.get("alive") or [],
        "down": data.get("down") or [],
        "never_probed": never,
        "providers": rows,
        "path": str(heartbeat_path()),
        "note": ("Read-only. Nothing here calls a provider — run `providers.test` or the "
                 "heartbeat to refresh." if rows else
                 "No heartbeat has run yet. Run the `providers.test` action to take a round."),
    }
