"""The pause control — the ONE writer for all three pause scopes (R17).

Arming a pause is the cheapest actuator in the estate and the one most likely to be reached for
in an incident, which is why it is the first to get the spine's actuation shape (§4.1):

    intent {scope, action, actor, nonce} -> fence -> write -> receipt -> store/ops/intents.jsonl

THE FENCE IS IN THE WRITER, NEVER IN THE KEYBOARD (§6). A Streamlit button, a Telegram tap and a
`python -m prospector.ops.pause` call all land here, so a scope that does not exist is refused
once, in the one place, rather than in three UIs that each have to remember.

WHY THE FILE CARRIES A BODY. Every reader decides on `.exists()` alone — `guard.is_paused`,
`run_scheduled`'s generation check and `consumer._blocked_reason` — so the JSON inside is
provenance, not semantics: an operator who armed a pause by hand with `touch` gets identical
behaviour and a `null` actor. That asymmetry is deliberate. A control that changed the MEANING of
the file would make the documented `touch store/scheduler/PAUSE` in every runbook subtly wrong.

WHY ARMING IS IDEMPOTENT. Re-arming an already-armed scope does not rewrite the file: the first
armer's name, reason and timestamp are the ones worth keeping, and a refresh loop that re-posted
the intent would otherwise erase who stopped the engine and when.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .readmodel import PAUSE_SCOPES

#: Append-only intent + receipt log, shared by both surfaces (§4.1). A run started on the phone is
#: inspectable at the desk because there is one log, not one per UI.
INTENTS_FILENAME = "intents.jsonl"


class UnknownScope(ValueError):
    """Raised for a scope outside `PAUSE_SCOPES`. Loud, because the alternative is a pause file
    with a typo'd name that no reader ever consults — a control that reports success and stops
    nothing."""


def _scope_meta(scope: str) -> dict:
    meta = PAUSE_SCOPES.get(str(scope))
    if meta is None:
        raise UnknownScope(
            f"unknown pause scope {scope!r}; expected one of {', '.join(sorted(PAUSE_SCOPES))}")
    return meta


def pause_path(cfg, scope: str) -> Path:
    from prospector.scheduler import paths as _paths

    return _paths.scheduler_dir(cfg) / _scope_meta(scope)["filename"]


def intents_path(cfg) -> Path:
    from prospector.scheduler import paths as _paths

    d = _paths.store_dir(cfg) / "ops"
    d.mkdir(parents=True, exist_ok=True)
    return d / INTENTS_FILENAME


def _record(cfg, receipt: dict) -> None:
    """Append one receipt. NEVER raises: an unwritable audit log must not leave the operator
    unable to stop the engine. The receipt's absence is visible in the log; a refused PAUSE is a
    liability."""
    try:
        from prospector.jsonl_atomic import append_jsonl

        append_jsonl(intents_path(cfg), receipt)
    except Exception:  # noqa: BLE001
        pass


def _seen_nonce(cfg, nonce: str) -> Optional[dict]:
    """The receipt already recorded for `nonce`, if any.

    Idempotency by STORED nonce, not by a cache with a TTL (memory:
    `idempotency-keys-expire-they-are-not-dedup`). A double-tap on a phone keyboard is the case
    this exists for.
    """
    if not nonce:
        return None
    try:
        raw = intents_path(cfg).read_text(errors="replace")
    except OSError:
        return None
    for line in raw.splitlines():
        line = line.strip()
        if not line or nonce not in line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("nonce") == nonce:
            return rec
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def arm(cfg, scope: str, *, actor: str = "unknown", reason: str = "",
        nonce: str = "") -> dict:
    """Arm one pause scope. Returns the receipt.

    `changed` is False when the scope was already armed — the caller renders "already paused",
    and the original armer survives.
    """
    meta = _scope_meta(scope)
    prior = _seen_nonce(cfg, nonce)
    if prior is not None:
        return {**prior, "replayed": True}

    path = pause_path(cfg, scope)
    existed = path.exists()
    if not existed:
        body = {"scope": scope, "armed_at": _now_iso(), "actor": actor,
                "reason": reason, "pid": os.getpid(),
                "stops": meta["stops"], "keeps_running": meta["keeps_running"]}
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(body, indent=2))
        os.replace(tmp, path)

    receipt = {"ts": _now_iso(), "mono": time.monotonic(), "actuator": "engine.pause.arm",
               "scope": scope, "path": str(path), "actor": actor, "reason": reason,
               "nonce": nonce, "changed": not existed, "armed": True,
               "stops": meta["stops"], "keeps_running": meta["keeps_running"]}
    _record(cfg, receipt)
    return receipt


def disarm(cfg, scope: str, *, actor: str = "unknown", nonce: str = "") -> dict:
    """Clear one pause scope. Returns the receipt; `changed` is False if it was not armed."""
    meta = _scope_meta(scope)
    prior = _seen_nonce(cfg, nonce)
    if prior is not None:
        return {**prior, "replayed": True}

    path = pause_path(cfg, scope)
    existed = path.exists()
    if existed:
        try:
            path.unlink()
        except FileNotFoundError:
            existed = False

    receipt = {"ts": _now_iso(), "mono": time.monotonic(), "actuator": "engine.pause.disarm",
               "scope": scope, "path": str(path), "actor": actor, "nonce": nonce,
               "changed": existed, "armed": False,
               "resumes": meta["stops"]}
    _record(cfg, receipt)
    return receipt


def main(argv: Optional[list[str]] = None) -> int:
    """`python -m prospector.ops.pause arm consumer --actor chidi --reason "…"`."""
    import argparse

    ap = argparse.ArgumentParser(description="Pause control (R17)")
    ap.add_argument("action", choices=["arm", "disarm", "show"])
    ap.add_argument("scope", nargs="?", choices=sorted(PAUSE_SCOPES) + [None], default=None)
    ap.add_argument("--actor", default=os.environ.get("USER") or "cli")
    ap.add_argument("--reason", default="")
    ap.add_argument("--nonce", default="")
    ap.add_argument("--config", default=os.environ.get("PROSPECTOR_CONFIG") or None)
    args = ap.parse_args(argv)

    from .readmodel import load_cfg, pause_view

    cfg = load_cfg(args.config)
    if args.action == "show":
        print(json.dumps(pause_view(cfg), indent=2))
        return 0
    if not args.scope:
        ap.error("arm/disarm need a scope")
    fn = arm if args.action == "arm" else disarm
    kwargs = {"actor": args.actor, "nonce": args.nonce}
    if args.action == "arm":
        kwargs["reason"] = args.reason
    print(json.dumps(fn(cfg, args.scope, **kwargs), indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
