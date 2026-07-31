"""Claude CLI adapters — use the locally-installed `claude` CLI (Claude Code) on
its subscription, no API key.
free web-search quota is spent, grounding and/or the verdict brain fall over to
Claude here, staying entirely within the Claude Code subscription (no hosted
API-key calls — Prospector's operating rule).

Provides BOTH:
  - ClaudeCliOperator: verification brain (no web; rules from given passages only).
  - ClaudeCliGroundingProvider: real web-search grounding -> resolvable URLs + passages.

Invoked headless: `claude -p <prompt> --output-format json [--allowedTools WebSearch]`.
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
from .models import Source
from .operator import Operator, _extract_json
from .retrieval import SearchProvider
from .telemetry import logger, record_usage, track_latency
from .cli_governor import make_governor

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The headless `claude -p` CLI is a completion endpoint for us, NOT an agent working on this
# repo. Run inside REPO_ROOT it loads the project CLAUDE.md (all about the daemon being broken /
# relaunching) and goes META on generation ("this is a system-level generation prompt … relaunch,
# then …") instead of emitting candidate JSON — PROVEN 2026-07-02: same real prompt yields 0 from
# REPO_ROOT but 3/3 clean candidates from a neutral cwd. It also keeps the daemon's operating rules
# out of VERDICT calls (verdict-from-retrieval-only). Use a stable empty dir OUTSIDE the repo tree
# so Claude Code's upward CLAUDE.md walk finds nothing project-specific (~/.claude global still
# loads — generic, harmless). auth lives in ~/.claude and is cwd-independent.
_NEUTRAL_CWD = os.path.join(tempfile.gettempdir(), "prospector_cli_cwd")
os.makedirs(_NEUTRAL_CWD, exist_ok=True)

# Cap concurrent heavy CLI subprocesses.
_MAX_CLI = max(1, int(os.environ.get("PROSPECTOR_CLAUDE_CONCURRENCY", "2") or "2"))
# Machine-wide, not per-process — see prospector/cli_governor.py. The 45s "grounding queue
# saturated" tail that killed job 20260730T212901866 was oversubscription across pipelines,
# not a too-small limit here.
_CLI_SEM = make_governor(_MAX_CLI, "claude")
_SEM_LOCK = threading.Lock()
_BACKOFFS = (2, 5, 10)


def configure_concurrency(n: int) -> None:
    """Resize the CLI subprocess governor from config (single source of truth).
    PROSPECTOR_CLAUDE_CONCURRENCY env var, if set, pins the value and wins.
    Call at startup (make_provider) before any calls are in flight."""
    global _CLI_SEM, _MAX_CLI
    if os.environ.get("PROSPECTOR_CLAUDE_CONCURRENCY"):
        return
    n = max(1, int(n))
    with _SEM_LOCK:
        if n != _MAX_CLI:
            _MAX_CLI = n
            _CLI_SEM = make_governor(n, "claude")


def _record_claude_usage(data: dict, web: bool) -> None:
    """Log token usage + the CLI's real total_cost_usd against the current phase,
    so `report --costs` accounts for Claude calls too."""
    u = (data or {}).get("usage") or {}
    inp = int(u.get("input_tokens", 0) or 0)
    out = int(u.get("output_tokens", 0) or 0)
    cached = int(u.get("cache_read_input_tokens", 0) or 0)
    total = inp + out + cached + int(u.get("cache_creation_input_tokens", 0) or 0)
    cost = float(data.get("total_cost_usd", 0) or 0)
    record_usage(input_tokens=inp, output_tokens=out, total_tokens=total,
                 cached_tokens=cached, web=web)
    # cost_usd here is the CLI's own billed figure (more accurate than an estimate);
    # costs_report sums it into spend.
    logger.info("Claude CLI usage", extra={"web": web, "input": inp, "output": out,
                                           "total": total, "cached": cached, "cost_usd": cost})


def _attempt_claude_cli(cmd: list[str], timeout: int, web: bool,
                        queue_timeout: Optional[float] = None) -> str:
    """One CLI invocation under the concurrency cap. Raises on transient failure.
    The slot wait is BOUNDED by queue_timeout (None => block) so a saturated provider
    fails fast to failover instead of blocking a vet indefinitely."""
    if not _CLI_SEM.acquire(timeout=queue_timeout):
        raise RuntimeError(
            f"claude cli slot acquire timed out after {queue_timeout}s (grounding queue saturated)")
    # The headless `claude -p` CLI must authenticate via the Claude Code SUBSCRIPTION (OAuth),
    # not a metered API key. We load ANTHROPIC_API_KEY from .env for the HTTP brains, but if it
    # is present in the env the CLI PREFERS it and bills it — and an unfunded key returns
    # api_error 400 "Credit balance is too low" (exit 1), silently killing the trusted moat.
    # Strip the API-key vars from the child env so the CLI falls back to the subscription seat
    # (matches CLAUDE.md: "the entire engine runs within your Claude Code subscription").
    child_env = {k: v for k, v in os.environ.items()
                 if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    # UNIQUE cwd per invocation. Claude Code derives its per-project session slug from the cwd
    # PATH, so concurrent `claude -p` processes in a SHARED dir clobber each other's session
    # state and degrade to non-JSON meta output. PROVEN 2026-07-02: parallel generation
    # (concurrency=2) → 0/3 candidates, but serialized (concurrency=1) → 2/3. A private temp dir
    # per call gives each process a distinct slug, so parallel generation no longer collides.
    # Dir lives under _NEUTRAL_CWD (outside the repo) so no project CLAUDE.md is picked up.
    call_cwd = tempfile.mkdtemp(prefix="c_", dir=_NEUTRAL_CWD)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              cwd=call_cwd, timeout=timeout, stdin=subprocess.DEVNULL,
                              env=child_env)
    finally:
        _CLI_SEM.release()
        shutil.rmtree(call_cwd, ignore_errors=True)
    if proc.returncode != 0:
        raise RuntimeError(f"claude cli exit {proc.returncode}: {proc.stderr[-300:]}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"claude cli non-JSON output: {proc.stdout[:200]!r}") from e
    # Headless JSON shape: {"type":"result","subtype":"success","result":"...","is_error":..}
    if isinstance(data, dict):
        if data.get("is_error") or data.get("subtype") == "error_during_execution":
            raise RuntimeError(f"claude cli error result: {str(data)[:200]}")
        resp = data.get("result")
        if resp:
            _record_claude_usage(data, web)
            return str(resp)
    raise RuntimeError(f"claude cli empty/unexpected response: {str(data)[:200]}")


@track_latency(name="run_claude_cli")
def run_claude_cli(prompt: str, *, web: bool = False, model: Optional[str] = None,
                   timeout: int = 180, timeout_max: Optional[int] = None,
                   escalation: float = 1.0, retries: int = 1,
                   queue_timeout: Optional[float] = None) -> str:
    """Run the claude CLI headless and return the response text.

    Transient failures are retried with backoff; the per-attempt timeout is ADAPTIVE
    (escalates by `escalation` each retry up to `timeout_max` — slow≠dead). A persistent
    failure raises — ProviderExhaustedError if it looks like quota/credit exhaustion (so
    the fallback layer retires this provider), else a plain RuntimeError.
    """
    cmd = [CLAUDE_BIN, "-p", prompt, "--output-format", "json"]
    if web:
        cmd += ["--allowedTools", "WebSearch"]
    if model:
        cmd += ["--model", model]

    logger.info("Invoking Claude CLI", extra={"model": model, "web": web})

    ceiling = timeout_max or timeout
    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        attempt_timeout = min(ceiling, int(round(timeout * (escalation ** attempt))))
        try:
            return _attempt_claude_cli(cmd, attempt_timeout, web, queue_timeout)
        except (subprocess.TimeoutExpired, RuntimeError) as e:
            last_err = e
            # Exhaustion is persistent for this window — don't burn more attempts (each
            # with a longer timeout) re-confirming it; fail over to the next brain now.
            if looks_exhausted(str(e)):
                logger.warning("Claude CLI exhaustion detected; skipping remaining retries",
                               extra={"web": web, "error": str(e)[:200]})
                break
            if attempt < retries:
                backoff = _BACKOFFS[min(attempt, len(_BACKOFFS) - 1)]
                logger.warning(
                    f"Claude CLI attempt {attempt + 1}/{retries + 1} failed; "
                    f"retrying in {backoff}s",
                    extra={"attempt": attempt + 1, "web": web, "error": str(e)[:200]})
                time.sleep(backoff)
    logger.error("Claude CLI failed after retries",
                 extra={"attempts": retries + 1, "web": web, "error": str(last_err)[:300]})
    if looks_exhausted(str(last_err)):
        raise ProviderExhaustedError(
            f"claude cli exhausted after {retries + 1} attempts: {last_err}",
            provider=f"claude_cli/{model or 'default'}")
    raise RuntimeError(f"claude cli failed after {retries + 1} attempts: {last_err}")


class ClaudeCliOperator(Operator):
    """Verification brain via the claude CLI. No web — rules from passages only."""
    def __init__(self, model: Optional[str] = None):
        self.model = model
        self.name = f"claude-cli/{model or 'default'}"

    @track_latency(name="claude_cli_raw")
    def _raw(self, system: str, user: str, temperature: float) -> str:
        return run_claude_cli(f"{system}\n\n{user}", web=False, model=self.model)


class ClaudeCliGroundingProvider(SearchProvider):
    """Live web-search grounding via the claude CLI. Returns resolvable URLs + passages."""
    def __init__(self, model: Optional[str] = None,
                 timeout: int = 180, timeout_max: Optional[int] = None,
                 escalation: float = 1.5, retries: int = 1,
                 queue_timeout: Optional[float] = None):
        self.model = model
        self.timeout = timeout
        self.timeout_max = timeout_max or timeout
        self.escalation = escalation
        self.retries = retries
        self.queue_timeout = queue_timeout

    @track_latency(name="claude_cli_search")
    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        prompt = (
            f"Use web search to find evidence about: {query}\n"
            f"Return ONLY a JSON array of up to {k} objects, each exactly "
            f'{{"url": "<real resolvable source url>", "text": "<relevant passage, '
            f'<= {max_chars} chars>", "published_at": "<date or null>"}}. '
            "Use only real source URLs you actually retrieved. No prose, no code fences."
        )
        logger.info(f"Claude CLI Search started: {query!r}")
        # Transport/exhaustion failure PROPAGATES so the fallback layer can fail over
        # (and, if all providers are out, run_check defers — never a false kill).
        resp = run_claude_cli(prompt, web=True, model=self.model,
                              timeout=self.timeout, timeout_max=self.timeout_max,
                              escalation=self.escalation, retries=self.retries,
                              queue_timeout=self.queue_timeout)
        try:
            data = _extract_json(resp)
        except Exception as e:
            logger.warning(f"Claude CLI Search: unparseable response, treating as empty: {e}",
                           extra={"error": str(e)})
            return []
        if isinstance(data, dict):
            data = data.get("results") or data.get("passages") or []
        # Resolve URLs in PARALLEL, dropping dead/fabricated ones (identical to serial).
        from .retrieval import resolve_sources
        out = resolve_sources(data, query, max_chars, k)
        logger.info(f"Claude CLI Search returned {len(out)} results", extra={"count": len(out)})
        return out
