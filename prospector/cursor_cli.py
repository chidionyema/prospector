"""Cursor Agent CLI adapter — use the locally-installed `agent` binary on the
Cursor subscription, no Anthropic/Claude Code dependency.

Headless: `agent -p <prompt> --mode ask --output-format text --trust --workspace <neutral>`.

`--mode ask` is deliberate: plain `-p` grants write/shell tools by default, which is
wrong for a completion brain that must only return text/JSON. Ask mode is read-only Q&A.

Auth: `agent login` (browser OAuth) or `CURSOR_API_KEY` / `CURSOR_AUTH_TOKEN` in the
environment. We do not invent credentials here.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Optional

from .errors import ProviderExhaustedError, looks_exhausted
from .operator import Operator
from .telemetry import logger, track_latency
from .cli_governor import make_governor

# Prefer `agent` (what the official installer symlinks); allow override / legacy name.
CURSOR_BIN = os.environ.get("CURSOR_BIN") or os.environ.get("AGENT_BIN") or "agent"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Same reason as claude_cli: never run inside the prospector tree. Project AGENTS.md /
# CLAUDE.md would hijack a generation/verdict prompt into meta commentary about the daemon.
_NEUTRAL_CWD = os.path.join(tempfile.gettempdir(), "prospector_cursor_cli_cwd")
os.makedirs(_NEUTRAL_CWD, exist_ok=True)

_MAX_CLI = max(1, int(os.environ.get("PROSPECTOR_CURSOR_CONCURRENCY", "2") or "2"))
# Machine-wide, not per-process: several prospector pipelines (daemon, backfill, manual
# generate) run concurrently, and a threading.Semaphore in each of them multiplied the real
# ceiling by the number of processes. See prospector/cli_governor.py for the measurements.
_CLI_SEM = make_governor(_MAX_CLI, "cursor")
_SEM_LOCK = threading.Lock()
_BACKOFFS = (2, 5, 10)


def configure_concurrency(n: int) -> None:
    """Resize the Cursor CLI subprocess governor from config."""
    global _CLI_SEM, _MAX_CLI
    if os.environ.get("PROSPECTOR_CURSOR_CONCURRENCY"):
        return
    n = max(1, int(n))
    with _SEM_LOCK:
        if n != _MAX_CLI:
            _MAX_CLI = n
            _CLI_SEM = make_governor(n, "cursor")


def _resolve_bin() -> str:
    bin_name = CURSOR_BIN
    path = shutil.which(bin_name)
    if path:
        return path
    # Installer default when PATH hasn't picked up ~/.local/bin yet.
    for candidate in (
        os.path.expanduser("~/.local/bin/agent"),
        os.path.expanduser("~/.local/bin/cursor-agent"),
    ):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError(
        f"Cursor agent CLI not found ({bin_name!r}). Install with: "
        f"curl https://cursor.com/install -fsS | bash  then: agent login"
    )


def _attempt_cursor_cli(cmd: list[str], timeout: int,
                        queue_timeout: Optional[float] = None) -> str:
    if not _CLI_SEM.acquire(timeout=queue_timeout):
        raise RuntimeError(
            f"cursor cli slot acquire timed out after {queue_timeout}s")
    # Unique workspace per call so parallel sessions don't collide; outside the
    # repo so project instruction files are not loaded.
    call_cwd = tempfile.mkdtemp(prefix="cur_", dir=_NEUTRAL_CWD)
    try:
        # Ensure PATH includes the installer bin even if the parent shell missed it.
        child_env = dict(os.environ)
        local_bin = os.path.expanduser("~/.local/bin")
        child_env["PATH"] = local_bin + os.pathsep + child_env.get("PATH", "")
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=call_cwd, timeout=timeout, stdin=subprocess.DEVNULL,
            env=child_env)
    finally:
        _CLI_SEM.release()
        shutil.rmtree(call_cwd, ignore_errors=True)

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "")[-400:]
        raise RuntimeError(f"cursor cli exit {proc.returncode}: {err}")

    out = (proc.stdout or "").strip()
    if not out:
        raise RuntimeError("cursor cli empty response")

    # --output-format json may wrap the answer; text is the model reply itself.
    if out.startswith("{") or out.startswith("["):
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return out
        if isinstance(data, dict):
            if data.get("is_error") or data.get("error"):
                raise RuntimeError(f"cursor cli error result: {str(data)[:200]}")
            for key in ("result", "text", "response", "content", "message"):
                if data.get(key):
                    return str(data[key])
        return out
    return out


@track_latency(name="run_cursor_cli")
def run_cursor_cli(prompt: str, *, model: Optional[str] = None,
                   timeout: int = 180, timeout_max: Optional[int] = None,
                   escalation: float = 1.0, retries: int = 1,
                   queue_timeout: Optional[float] = None) -> str:
    """Run the Cursor agent CLI headless and return response text."""
    bin_path = _resolve_bin()
    # ask = read-only Q&A (no write/shell). trust skips the workspace prompt.
    # text format: we parse JSON ourselves via Operator._extract_json — more reliable
    # than depending on the CLI's json envelope shape across versions.
    cmd = [
        bin_path, "-p", prompt,
        "--mode", "ask",
        "--output-format", "text",
        "--trust",
        "--workspace", _NEUTRAL_CWD,
    ]
    if model:
        cmd += ["--model", model]

    logger.info("Invoking Cursor CLI", extra={"model": model or "default"})

    ceiling = timeout_max or timeout
    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        attempt_timeout = min(ceiling, int(round(timeout * (escalation ** attempt))))
        try:
            return _attempt_cursor_cli(cmd, attempt_timeout, queue_timeout)
        except (subprocess.TimeoutExpired, RuntimeError) as e:
            last_err = e
            if looks_exhausted(str(e)) or "Authentication required" in str(e):
                # Auth failure is persistent until the operator logs in — don't retry-burn.
                logger.warning("Cursor CLI auth/exhaustion; skipping remaining retries",
                               extra={"error": str(e)[:200]})
                break
            if attempt < retries:
                backoff = _BACKOFFS[min(attempt, len(_BACKOFFS) - 1)]
                logger.warning(
                    f"Cursor CLI attempt {attempt + 1}/{retries + 1} failed; "
                    f"retrying in {backoff}s",
                    extra={"attempt": attempt + 1, "error": str(e)[:200]})
                time.sleep(backoff)

    logger.error("Cursor CLI failed after retries",
                 extra={"attempts": retries + 1, "error": str(last_err)[:300]})
    err_s = str(last_err)
    if looks_exhausted(err_s) or "Authentication required" in err_s:
        raise ProviderExhaustedError(
            f"cursor cli exhausted after {retries + 1} attempts: {last_err}",
            provider=f"cursor_cli/{model or 'default'}")
    raise RuntimeError(f"cursor cli failed after {retries + 1} attempts: {last_err}")


class CursorCliOperator(Operator):
    """Verification / generation brain via the Cursor agent CLI. No tools, no web."""

    def __init__(self, model: Optional[str] = None,
                 timeout: int = 120, timeout_max: Optional[int] = None,
                 escalation: float = 1.0, retries: int = 1,
                 queue_timeout: Optional[float] = None):
        self.model = model
        self.name = f"cursor-cli/{model or 'default'}"
        self.timeout = int(timeout)
        self.timeout_max = int(timeout_max if timeout_max is not None else timeout)
        self.escalation = float(escalation)
        self.retries = int(retries)
        self.queue_timeout = queue_timeout

    @track_latency(name="cursor_cli_raw")
    def _raw(self, system: str, user: str, temperature: float) -> str:
        # temperature is unused — the CLI has no temperature flag; kept for Operator parity.
        _ = temperature
        return run_cursor_cli(
            f"{system}\n\n{user}", model=self.model,
            timeout=self.timeout, timeout_max=self.timeout_max,
            escalation=self.escalation, retries=self.retries,
            queue_timeout=self.queue_timeout,
        )
