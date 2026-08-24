"""The routing control — the ONE writer for the verdict roster (R20).

`moat_primary` is the line that decides what may be SOLD. Everything a brain outside it rules is
stamped `provisional` (`operator.is_provisional_provider`, `operator.py:1509`), and a provisional
PASS never publishes — `run.py:1157` reads
`if publish and dossier.decision == Decision.PASS and not dossier.provisional:`. So the roster is
not a preference knob: **narrow it wrongly and the engine keeps working, keeps spending and stops
selling**, with no error anywhere. That is why this is the one config edit that gets its own
actuator instead of a text box.

THE FENCE IS IN THE WRITER (§6). `routing_problems()` is called by this module's `set_moat_primary`
AND by `config_editor.validate_config`, so the Streamlit Parameters page, this CLI (which is what
the Telegram surface calls) and a hand-edited save all hit the same refusal. A fence in a keyboard
is a fence in ONE keyboard.

WHAT IT REFUSES, and why each one is a way to stop publication without noticing:

  1. an empty roster                  → `moat_primary()` falls back to `{claude_cli}` and the
                                        declared chain head silently loses trust.
  2. a tier no adapter can build      → `_build_operator` raises at startup (`cursor_cli`,
                                        `standardcompute`, `claude` are all in that state now).
  3. a head outside the roster        → THE R20 fence. Every verdict the daemon rules is
                                        provisional; the catalogue stops growing and every rail
                                        stays green.

WHY THE READER MUST LOAD CONFIG FIRST (§14.5.1). `operator.moat_primary()` reads a process global
installed by `config.load_config` (`config.py:1141-1142`). A cold import answers
`MOAT_PRIMARY_DEFAULT` = `{claude_cli}` while the daemon rules on `[minimax, claude_cli]` — so a
panel built on a bare import would report the LEADING brain as untrusted while it is publishing.
`routing_view` refuses to answer in that state (`StaleProcessGlobal`) rather than report the
default as if it were the truth. `readmodel.load_cfg` is the supported entry point.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Iterable, Optional

from prospector import operator as _op

from .pause import _record as _record_intent
from .pause import _seen_nonce as _seen_intent


class StaleProcessGlobal(RuntimeError):
    """The installed trusted set disagrees with the config that was just read.

    Raised rather than papered over: the two answers differ by exactly the amount that makes a
    routing panel wrong (`{claude_cli}` vs `[minimax, claude_cli]`), and a control that shows the
    wrong roster is how an operator "fixes" a roster that was never broken.
    """


def _chain(raw: Any) -> list[str]:
    """Normalise `operator:`/`moat_primary:` — a bare string, a list, or nothing."""
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    return [str(t).strip() for t in raw if str(t).strip()]


def _cfg_get(cfg, key: str) -> list[str]:
    if isinstance(cfg, dict):
        return _chain(cfg.get(key))
    return _chain(getattr(cfg, key, None))


# --------------------------------------------------------------------------- #
# The fence
# --------------------------------------------------------------------------- #
def routing_problems(operator_chain: Iterable[str], moat_primary: Iterable[str]) -> list[str]:
    """Reasons this roster must not be written. Empty list ⇒ safe to save.

    Pure, so both surfaces and the tests can call it without a config on disk.
    """
    chain = _chain(operator_chain)
    trusted = _chain(moat_primary)
    problems: list[str] = []

    if not trusted:
        problems.append(
            "moat_primary is empty — `operator.moat_primary()` would fall back to "
            f"{sorted(_op.MOAT_PRIMARY_DEFAULT)} (operator.py:1405), which is not what this "
            "config says. Name the brains that may rule finally.")
    # Built-ins PLUS declared, for the same reason as config_editor: a name this refuses is a
    # name the engine can build, so the refusal would be wrong and would read as a typo.
    # Being SETTABLE here is not being trusted — it is the operator choosing, which is the same
    # choice `openrouter` and `ollama` have always been offered.
    from prospector.providers import buildable_tiers, declared_now
    _buildable = buildable_tiers(declared_now())
    unknown = [t for t in trusted if t not in _buildable]
    if unknown:
        problems.append(
            f"moat_primary names {unknown}, which no adapter can build "
            f"(buildable: {', '.join(_buildable)}). A tier that cannot be constructed "
            "cannot rule, so trusting it trusts nothing.")

    if chain and trusted and chain[0] not in trusted:
        problems.append(
            f"the verdict chain head is {chain[0]!r}, which is not in moat_primary "
            f"({trusted}). Everything it rules would be stamped provisional "
            "(operator.py:1509) and no PASS would publish (run.py:1157) — the engine would keep "
            "running, keep spending and stop selling. Add it to moat_primary, or put a trusted "
            "tier at the head of `operator`.")

    return problems


def routing_advisories(operator_chain: Iterable[str], moat_primary: Iterable[str]) -> list[str]:
    """Facts worth showing that are NOT grounds to refuse."""
    chain, trusted = _chain(operator_chain), _chain(moat_primary)
    out = []
    inert = [t for t in trusted if t not in chain]
    if chain and inert:
        out.append(f"trusted but never called: {inert} — in moat_primary, absent from `operator`.")
    tail = [t for t in chain[1:] if t not in trusted]
    if tail:
        out.append(f"provisional fallbacks: {tail} — they rule when the head is down, and every "
                   "row they produce is re-vetted rather than published.")
    return out


# --------------------------------------------------------------------------- #
# The read (R20's reader half + R23: no second derivation)
# --------------------------------------------------------------------------- #
def routing_view(cfg) -> dict:
    """The roster as the RUNNING PROCESS sees it. `cfg` must come from `readmodel.load_cfg`.

    `trusted` is `operator.moat_primary()` — the same call `is_provisional_provider` makes — never
    a re-read of the YAML key. The two are cross-checked, and a disagreement raises.
    """
    declared = _cfg_get(cfg, "moat_primary")
    live = sorted(_op.moat_primary())
    env_override = os.environ.get(_op.MOAT_PRIMARY_ENV, "").strip()

    if declared and not env_override and set(declared) != set(live):
        raise StaleProcessGlobal(
            f"config.yaml declares moat_primary={declared} but the process global answers {live}. "
            "This is what a cold `import prospector.operator` looks like (§14.5.1): call "
            "`prospector.ops.readmodel.load_cfg()` before reading the roster.")

    chain = _cfg_get(cfg, "operator")
    noncritical = _cfg_get(cfg, "noncritical_operator")
    head = chain[0] if chain else None
    problems = routing_problems(chain, live)

    return {
        "operator": chain,
        "noncritical_operator": noncritical,
        "moat_primary_declared": declared,
        "trusted": live,
        "trusted_source": (f"${_op.MOAT_PRIMARY_ENV}" if env_override
                           else ("config.yaml moat_primary" if declared
                                 else "operator.MOAT_PRIMARY_DEFAULT")),
        "head": head,
        "head_trusted": bool(head) and head in live,
        # The only sentence an operator needs: can a PASS reach the shelf right now?
        "publishes": bool(head) and head in live and not problems,
        "provisional_tiers": [t for t in chain if t not in live],
        "buildable": list(_op.BUILDABLE_TIERS),
        "problems": problems,
        "advisories": routing_advisories(chain, live),
    }


# --------------------------------------------------------------------------- #
# The write
# --------------------------------------------------------------------------- #
def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def set_moat_primary(cfg, tiers: Iterable[str], *, actor: str = "unknown",
                     reason: str = "", nonce: str = "") -> dict:
    """Write `moat_primary:` and return a receipt. Refuses rather than guesses.

    The receipt is appended to the same `store/ops/intents.jsonl` the pause control writes, so a
    roster changed from the phone is inspectable at the desk (§4.1). `applied` is the field to
    read: a refusal is a receipt too, and a control that logs only its successes cannot answer
    "why did nobody publish yesterday".

    A replayed `nonce` returns the first receipt unchanged — a Telegram tap that arrives twice
    must not re-write a config a human has since edited (`idempotency-keys-expire-…`).
    """
    prior = _seen_intent(cfg, nonce) if nonce else None
    if prior is not None:
        return {**prior, "replayed": True}

    from prospector.ops import config_editor as _ce

    requested = _chain(list(tiers))
    raw, readable = _ce._read_config_raw()
    if not readable or not raw:
        receipt = _refusal(cfg, requested, actor, reason, nonce,
                           ["config.yaml could not be parsed — refusing to write on top of a "
                            "failed read (that is what an empty config looks like)."])
        return receipt

    chain = _chain(raw.get("operator"))
    problems = routing_problems(chain, requested)
    if problems:
        return _refusal(cfg, requested, actor, reason, nonce, problems)

    before = _chain(raw.get("moat_primary"))
    if before == requested:
        receipt = {"ts": _now_iso(), "mono": time.monotonic(),
                   "actuator": "engine.routing.moat_primary", "actor": actor, "reason": reason,
                   "nonce": nonce, "applied": True, "changed": False,
                   "before": before, "after": requested,
                   "message": "moat_primary already reads that; nothing written."}
        _record_intent(cfg, receipt)
        return receipt

    new_cfg = dict(raw)
    new_cfg["moat_primary"] = requested
    ok, message = _ce.write_config(new_cfg, moat_affecting=True,
                                   orig_mtime=_ce.get_config_mtime())
    receipt = {"ts": _now_iso(), "mono": time.monotonic(),
               "actuator": "engine.routing.moat_primary", "actor": actor, "reason": reason,
               "nonce": nonce, "applied": bool(ok), "changed": bool(ok),
               "before": before, "after": requested if ok else before,
               "message": message,
               # The daemon re-reads config.yaml at its next tick, and config.yaml is inside
               # `code_fingerprint` — so this ships without a human step. Said out loud in the
               # receipt because the operator pressing the button is the last check there is.
               "takes_effect": "next scheduler tick (config.yaml is inside code_fingerprint)"}
    _record_intent(cfg, receipt)
    return receipt


def _refusal(cfg, requested, actor, reason, nonce, problems) -> dict:
    receipt = {"ts": _now_iso(), "mono": time.monotonic(),
               "actuator": "engine.routing.moat_primary", "actor": actor, "reason": reason,
               "nonce": nonce, "applied": False, "changed": False,
               "after": requested, "problems": problems}
    _record_intent(cfg, receipt)
    return receipt


def main(argv: Optional[list[str]] = None) -> int:
    """`python -m prospector.ops.routing show`
    `python -m prospector.ops.routing set minimax,claude_cli --actor chidi --reason "…"`."""
    import argparse

    ap = argparse.ArgumentParser(description="Verdict-roster control (R20)")
    ap.add_argument("action", choices=["show", "set"])
    ap.add_argument("tiers", nargs="?", default="",
                    help="comma or space separated, in priority order")
    ap.add_argument("--actor", default=os.environ.get("USER") or "cli")
    ap.add_argument("--reason", default="")
    ap.add_argument("--nonce", default="")
    ap.add_argument("--config", default=os.environ.get("PROSPECTOR_CONFIG") or None)
    args = ap.parse_args(argv)

    from .readmodel import load_cfg

    cfg = load_cfg(args.config)
    if args.action == "show":
        print(json.dumps(routing_view(cfg), indent=2))
        return 0
    if not args.tiers.strip():
        ap.error("set needs at least one tier")
    tiers = [t for t in args.tiers.replace(",", " ").split() if t]
    receipt = set_moat_primary(cfg, tiers, actor=args.actor, reason=args.reason,
                               nonce=args.nonce)
    print(json.dumps(receipt, indent=2))
    return 0 if receipt.get("applied") else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
