"""The launchd jobs behind the engine: are they loaded, and start or restart them.

WHY THIS EXISTS, with the incident that produced it.

`run_scheduled._kill_stale_daemon` SIGKILLs a hung daemon and logs "launchd KeepAlive will
relaunch". Every one of its three exits says some version of that sentence. The sentence is only
true while the job is bootstrapped into the user's launchd domain.

On 2026-08-16 `com.prospector.scheduler` was not. The plist sat on disk with `KeepAlive=1` and
`RunAtLoad=1`, `launchctl print gui/501/com.prospector.scheduler` answered "Could not find service
com.prospector.scheduler in domain for user gui: 501", and the daemon was dead from 12:52 UTC
until a human ran `launchctl bootstrap` by hand. Nothing in the estate checked the claim the kill
path was making. A watchdog that kills a process and hands it to a supervisor that does not exist
is not a watchdog.

Same shape as `pause.py`: ONE writer for this actuator. The watchdog, the console API and the
Streamlit page all call through here, and every call lands a receipt in `store/ops/intents.jsonl`,
so "who restarted the daemon and when" has an answer.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

# The intent log is shared with the pause actuator on purpose — one append-only record of every
# operator action against the engine, whichever surface asked for it.
from .pause import _now_iso, _record

#: The producer. Generates candidates on the tick cadence; this is "the daemon" in every alert.
PRODUCER = "com.prospector.scheduler"
#: The consumer. Drains the backlog (`vet --resume`); a separate process since the producer split.
CONSUMER = "com.prospector.consumer"

#: The jobs this actuator will touch, by launchd label. Nothing outside this map can be started or
#: restarted from a console — a label typed by an operator must not become an arbitrary
#: `launchctl bootstrap` of any plist on the box.
JOBS: dict[str, dict] = {
    PRODUCER: {"role": "producer",
               "what": "generates candidates on the tick cadence (run_scheduled --daemon)"},
    CONSUMER: {"role": "consumer",
               "what": "drains the backlog (prospector.run consume --publish)"},
}

#: `launchctl` is not instant under load but it is never slow-and-correct: a call that has not
#: answered by now is wedged, and a wedged probe must fail rather than hold the watchdog.
_PROBE_TIMEOUT_S = 15
_ACT_TIMEOUT_S = 30


def plist_path(label: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def domain() -> str:
    """The per-user launchd domain. `gui/<uid>` is where LaunchAgents live for a logged-in user."""
    return f"gui/{os.getuid()}"


def _launchctl(*args: str, timeout: int = _PROBE_TIMEOUT_S) -> tuple[int | None, str]:
    """Run launchctl. Returns (returncode, combined output); returncode is None if it could not run.

    None is NOT a failure code — it means the question was never asked (no launchctl on this box,
    a timeout, a broken PATH). Collapsing that into "not loaded" would make a Linux CI box try to
    bootstrap a job that does not apply to it.
    """
    try:
        proc = subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.SubprocessError, OSError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()


def job_state(label: str) -> dict:
    """Whether launchd holds this job, and its pid if it is running.

    `loaded` is tri-state on purpose: True, False, or None for "could not ask". A caller that
    treats None as False will bootstrap on every pass on a box that has no launchctl.
    """
    plist = plist_path(label)
    meta = JOBS.get(label, {})
    rc, out = _launchctl("print", f"{domain()}/{label}")

    if rc is None:
        loaded: bool | None = None
        reason = out
    elif rc == 0:
        loaded, reason = True, "loaded"
    else:
        loaded = False
        reason = out.splitlines()[0].strip() if out else f"launchctl print rc={rc}"

    pid = None
    if loaded:
        match = re.search(r"^\s*pid\s*=\s*(\d+)", out, re.MULTILINE)
        if match:
            pid = int(match.group(1))

    return {"label": label, "loaded": loaded, "pid": pid, "reason": reason,
            "plist": str(plist), "plist_exists": plist.exists(), "domain": domain(),
            "role": meta.get("role", "unknown"), "what": meta.get("what", "")}


def _receipt(actuator: str, state: dict, actor: str, *,
             ok: bool, changed: bool, message: str) -> dict:
    return {"ts": _now_iso(), "mono": time.monotonic(), "actuator": actuator,
            "label": state["label"], "role": state["role"], "actor": actor,
            "ok": ok, "changed": changed, "message": message,
            "loaded": state["loaded"], "pid": state["pid"],
            "plist": state["plist"], "plist_exists": state["plist_exists"]}


def _bootstrap(state: dict) -> tuple[bool, str]:
    """Load the job from its plist. RunAtLoad in every one of these plists then starts it."""
    rc, out = _launchctl("bootstrap", state["domain"], state["plist"], timeout=_ACT_TIMEOUT_S)
    after = job_state(state["label"])
    if after["loaded"]:
        return True, (f"was NOT loaded in launchd — bootstrapped {state['plist']}; "
                      f"RunAtLoad started it (pid {after['pid'] or '—'}) and KeepAlive now holds it up")
    return False, f"bootstrap failed (rc={rc}): {out[:300] or 'no output'}"


def ensure_loaded(cfg, label: str, *, actor: str = "unknown") -> dict:
    """Bootstrap the job if launchd does not have it. Idempotent; safe to call every watchdog pass.

    This is the automated repair for the 2026-08-16 failure. It deliberately does NOT stop or
    start the process itself — a job that is loaded is left exactly alone, whatever state the
    process is in, because killing a live daemon is `_kill_stale_daemon`'s decision and its
    liveness rules, not this function's.
    """
    if label not in JOBS:
        raise ValueError(f"unknown job {label!r}; expected one of {', '.join(sorted(JOBS))}")
    state = job_state(label)

    if state["loaded"] is None:
        ok, changed, message = False, False, (
            f"could not ask launchctl ({state['reason']}) — leaving the job untouched")
    elif state["loaded"]:
        ok, changed, message = True, False, "already loaded"
    elif not state["plist_exists"]:
        ok, changed, message = False, False, (
            f"not loaded, and there is no plist at {state['plist']} to bootstrap — "
            f"nothing can relaunch this process")
    else:
        ok, message = _bootstrap(state)
        changed = ok

    receipt = _receipt("engine.supervisor.ensure_loaded", state, actor,
                       ok=ok, changed=changed, message=message)
    _record(cfg, receipt)
    return receipt


def restart(cfg, label: str, *, actor: str = "unknown") -> dict:
    """Restart the job, whichever way it is broken.

    Two paths, because "the daemon is down" has two causes and the operator should not have to
    know which one they have:
      * job loaded  -> `launchctl kickstart -k` kills the current process and starts a clean one.
      * not loaded  -> bootstrap it. That IS the restart in the case that actually happened; there
        is no process to kick.
    """
    if label not in JOBS:
        raise ValueError(f"unknown job {label!r}; expected one of {', '.join(sorted(JOBS))}")
    state = job_state(label)

    if state["loaded"] is None:
        ok, changed, message = False, False, (
            f"could not ask launchctl ({state['reason']}) — nothing was restarted")
    elif not state["loaded"]:
        if not state["plist_exists"]:
            ok, changed, message = False, False, (
                f"not loaded, and there is no plist at {state['plist']} to bootstrap")
        else:
            ok, message = _bootstrap(state)
            changed = ok
    else:
        rc, out = _launchctl("kickstart", "-k", f"{state['domain']}/{label}",
                             timeout=_ACT_TIMEOUT_S)
        ok = rc == 0
        changed = ok
        after = job_state(label)
        message = (f"killed and restarted (pid {after['pid'] or '—'})" if ok
                   else f"kickstart failed (rc={rc}): {out[:300] or 'no output'}")

    receipt = _receipt("engine.supervisor.restart", state, actor,
                       ok=ok, changed=changed, message=message)
    _record(cfg, receipt)
    return receipt
