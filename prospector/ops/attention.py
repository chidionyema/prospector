"""Which nav group has a problem, so "is anything wrong" costs no navigation.

The console has seven groups and twenty-four screens. Until this view existed, the only way to
answer "is anything wrong" was to open all seven: every screen derived its own trouble in its own
TSX, and nothing above a screen carried a signal. Measured 2026-08-20: twenty-two of the
thirty-one pages render a `<Problem>`, and no two of them share a definition of one.

Two rules hold this view honest, and both were chosen against a specific way it could lie.

**It derives nothing of its own.** Every verdict below is read out of `read status`, which is the
same payload the Now page renders. It cannot drift from that page, because it is that page's data.
A second definition of "the queue is stalled" is worse than no badge at all — the badge would go
green while the screen went red, and the operator would trust the badge.

**A group nobody measured is `unmeasured`, never `ok`.** Money and Shop are served by the store
API over the network, and `status` does not call it. A dot that is absent must mean "no problem
found"; if absence could also mean "not asked", the absence stops meaning anything. So those
groups say so out loud and the Now page prints the sentence.
"""

from __future__ import annotations

from typing import Any

#: Group labels, exactly as `Ops.Console/src/lib/nav.ts` spells them. A test asserts the two
#: lists match: a badge keyed to a group that no longer exists is a badge that never renders,
#: and it fails silently, which is the only kind of failure a nav badge can have.
GROUPS = ("Now", "Engine", "Shelf", "Shop", "Money", "Data", "Control")

#: Worst first. `unmeasured` sits below `ok` on purpose — it is not a fault, so it must never
#: outrank one, and it is not health either, so it must never be reported as one.
_RANK = {"bad": 3, "warn": 2, "ok": 1, "unmeasured": 0}


def _worst(findings: list[dict]) -> str:
    if not findings:
        return "ok"
    return max((f["state"] for f in findings), key=lambda s: _RANK.get(s, 0))


def _g(obj: Any, *path, default=None):
    """Walk a path of dict keys, returning `default` the moment anything is not a mapping.

    `status` is composed from a dozen views and any one of them may return an `error` record
    instead of its usual shape — `_incident_headline` does exactly that by design. A badge must
    survive that: a view that failed makes its group unmeasured, never green and never a crash.
    """
    cur = obj
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur if cur is not None else default


def _now_group(s: dict) -> list[dict]:
    out: list[dict] = []

    alerts = _g(s, "alerts", default={})
    for rec in _g(alerts, "active", default=[]) or []:
        sev = str(_g(rec, "severity", default="") or "")
        out.append({
            "state": "bad" if sev == "critical" else "warn",
            "what": str(_g(rec, "key", default="alert")),
            "where": "/",
        })
    if _g(alerts, "banner"):
        out.append({"state": "bad", "what": "an alert banner is posted", "where": "/"})
    if _g(alerts, "note"):
        out.append({"state": "unmeasured", "what": str(alerts["note"]), "where": "/"})

    for role in ("producer", "consumer"):
        hb = _g(s, "heartbeats", role, default={})
        if not hb:
            out.append({"state": "unmeasured", "what": f"no {role} heartbeat reading",
                        "where": "/"})
            continue
        if not _g(hb, "alive", default=False):
            out.append({"state": "bad", "what": f"{role}: {_g(hb, 'why', default='not alive')}",
                        "where": "/"})
        elif _g(hb, "stale", default=False):
            out.append({"state": "warn", "what": f"{role} beat is stale", "where": "/"})

    for job in _g(s, "supervisor", "jobs", default=[]) or []:
        loaded = _g(job, "loaded")
        label = str(_g(job, "label", default="a job"))
        if loaded is None:
            # Tri-state, and it stays that way. "could not ask launchctl" is not "not loaded".
            out.append({"state": "unmeasured", "what": f"{label}: could not ask launchctl",
                        "where": "/"})
        elif loaded is False:
            out.append({"state": "bad", "what": f"{label} is not held by launchd", "where": "/"})

    if _g(s, "pause", "any_armed", default=False):
        armed = [str(_g(sc, "scope", default="?"))
                 for sc in _g(s, "pause", "scopes", default=[]) or []
                 if _g(sc, "armed", default=False)]
        out.append({"state": "warn", "what": f"paused: {', '.join(armed) or 'a scope is armed'}",
                    "where": "/"})
    return out


def _engine_group(s: dict) -> list[dict]:
    out: list[dict] = []

    providers = _g(s, "providers", default={})
    for reason_key, label in (("moat_blind", "no brain can rule a verdict"),
                              ("drain_blind", "the drain has no trusted brain")):
        why = _g(providers, reason_key)
        if why:
            out.append({"state": "bad", "what": f"{label}: {why}", "where": "/engine"})
    for tier in _g(providers, "tiers", default=[]) or []:
        if str(_g(tier, "state", default="")) == "dead":
            out.append({"state": "warn",
                        "what": f"{_g(tier, 'name', default='a tier')} is benched",
                        "where": "/engine"})

    for problem in _g(s, "routing", "problems", default=[]) or []:
        out.append({"state": "bad", "what": str(problem), "where": "/engine"})
    if _g(s, "routing", "error"):
        out.append({"state": "unmeasured", "what": f"routing: {s['routing']['error']}",
                    "where": "/engine"})

    backlog = _g(s, "queue", "backlog", default={})
    for key, label in (("stalled", "stalled"), ("orphaned", "orphaned"),
                       ("unpublishable", "unpublishable")):
        n = _g(backlog, key, default=0) or 0
        if isinstance(n, int) and n > 0:
            out.append({"state": "warn", "what": f"{n} {label} in the queue", "where": "/queue"})
    expired = _g(s, "queue", "leases", "expired", default=0) or 0
    if isinstance(expired, int) and expired > 0:
        out.append({"state": "warn", "what": f"{expired} expired leases", "where": "/queue"})

    stuck = _g(s, "stuck")
    if stuck is None:
        # The Fly engine's `status` returns no `stuck` key at all. Saying so is the point.
        out.append({"state": "unmeasured", "what": "this engine does not report stuck work",
                    "where": "/queue"})
    else:
        n = _g(stuck, "needs_attention")
        if n is None:
            out.append({"state": "unmeasured",
                        "what": str(_g(stuck, "needs_attention_null_reason",
                                       default="stuck count unreadable")),
                        "where": "/queue"})
        elif n > 0:
            out.append({"state": "warn", "what": f"{n} runs need attention", "where": "/queue"})
    return out


def _money_group(s: dict) -> list[dict]:
    out: list[dict] = []
    spend = _g(s, "spend", default={})
    for w in _g(spend, "warnings", default=[]) or []:
        out.append({"state": "warn", "what": str(w), "where": "/spend"})
    # `cap_armed` ABSENT is not `cap_armed` false. A view that did not report cannot be evidence
    # that the cap is off — the first probe of this module printed exactly that on an empty
    # payload, which is the same lie as reporting an unchecked group green.
    if "cap_armed" not in spend:
        out.append({"state": "unmeasured", "what": "the spend cap was not reported",
                    "where": "/spend"})
    elif not spend["cap_armed"]:
        out.append({"state": "warn", "what": "the daily spend cap is disarmed", "where": "/spend"})
    # The rail itself is a network call the `status` view never makes. Absence of a dot here
    # would otherwise read as "the shop can take money", which this view has not checked.
    out.append({"state": "unmeasured",
                "what": "the payment rail is not checked here — open Rail",
                "where": "/money"})
    return out


def _data_group(s: dict) -> list[dict]:
    out: list[dict] = []
    inc = _g(s, "incidents", default={})
    if _g(inc, "error"):
        return [{"state": "unmeasured", "what": f"incidents: {inc['error']}",
                 "where": "/incidents"}]
    for key, label in (("blocked", "blocked"), ("overdue_grades", "overdue for a grade"),
                       ("unguarded", "closed with no guard")):
        n = _g(inc, key, default=0) or 0
        if isinstance(n, int) and n > 0:
            out.append({"state": "warn", "what": f"{n} incidents {label}", "where": "/incidents"})
    out.append({"state": "unmeasured",
                "what": "backups are not checked here — open Backups", "where": "/data"})
    return out


def _unmeasured(what: str, where: str) -> list[dict]:
    return [{"state": "unmeasured", "what": what, "where": where}]


def attention_view(status: dict) -> dict:
    """Group verdicts, derived from a `status` payload and from nothing else.

    Takes the payload rather than a config so it can be tested without an engine, and so there is
    no second way to fetch it.
    """
    groups = {
        "Now": _now_group(status),
        "Engine": _engine_group(status),
        "Shelf": _unmeasured("the shelf is not checked here — open Catalogue", "/catalogue"),
        "Shop": _unmeasured("orders and delivery are not checked here — open Orders", "/orders"),
        "Money": _money_group(status),
        "Data": _data_group(status),
        "Control": _unmeasured("settings are not checked here — open Settings", "/config"),
    }
    rows = []
    for label in GROUPS:
        findings = groups[label]
        rows.append({
            "group": label,
            "state": _worst(findings),
            "count": sum(1 for f in findings if f["state"] in ("bad", "warn")),
            "findings": findings,
        })
    faults = sum(r["count"] for r in rows)
    return {
        "groups": rows,
        "worst": _worst([{"state": r["state"]} for r in rows]),
        "faults": faults,
        "headline": ("nothing found wrong" if faults == 0
                     else f"{faults} thing needs attention" if faults == 1
                     else f"{faults} things need attention"),
        "not_checked": [r["group"] for r in rows if r["state"] == "unmeasured"],
    }
