"""Claude CLI adapters — use the locally-installed `claude` CLI (Claude Code) on
its subscription, no API key. The failover twin of gemini_cli: when Gemini's
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
import subprocess
import threading
import time
from typing import Optional

from .errors import ProviderExhaustedError, looks_exhausted
from .models import Source
from .operator import Operator, _extract_json
from .retrieval import SearchProvider
from .telemetry import logger, record_usage, track_latency

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Cap concurrent heavy CLI subprocesses (mirrors gemini_cli's governor).
_MAX_CLI = max(1, int(os.environ.get("PROSPECTOR_CLAUDE_CONCURRENCY", "2") or "2"))
_CLI_SEM = threading.Semaphore(_MAX_CLI)
_BACKOFFS = (2, 5, 10)


def _record_claude_usage(data: dict, web: bool) -> None:
    """Log token usage + the CLI's real total_cost_usd against the current phase,
    mirroring gemini_cli so `report --costs` accounts for Claude calls too."""
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


def _attempt_claude_cli(cmd: list[str], timeout: int, web: bool) -> str:
    """One CLI invocation under the concurrency cap. Raises on transient failure."""
    with _CLI_SEM:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              cwd=REPO_ROOT, timeout=timeout, stdin=subprocess.DEVNULL)
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
                   timeout: int = 180, retries: int = 1) -> str:
    """Run the claude CLI headless and return the response text.

    Transient failures are retried with backoff; a persistent failure raises —
    ProviderExhaustedError if it looks like quota/credit exhaustion (so the
    fallback layer retires this provider), else a plain RuntimeError.
    """
    cmd = [CLAUDE_BIN, "-p", prompt, "--output-format", "json"]
    if web:
        cmd += ["--allowedTools", "WebSearch"]
    if model:
        cmd += ["--model", model]

    logger.info("Invoking Claude CLI", extra={"model": model, "web": web})

    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            return _attempt_claude_cli(cmd, timeout, web)
        except (subprocess.TimeoutExpired, RuntimeError) as e:
            last_err = e
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
                 timeout: int = 180, retries: int = 1):
        self.model = model
        self.timeout = timeout
        self.retries = retries

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
                              timeout=self.timeout, retries=self.retries)
        try:
            data = _extract_json(resp)
        except Exception as e:
            logger.warning(f"Claude CLI Search: unparseable response, treating as empty: {e}",
                           extra={"error": str(e)})
            return []
        if isinstance(data, dict):
            data = data.get("results") or data.get("passages") or []
        out: list[Source] = []
        from .retrieval import _resolve
        for item in (data or [])[:k]:
            url = str(item.get("url", ""))
            if not url:
                continue
            resolved = _resolve(url)
            if not resolved:
                logger.warning("Dropping fabricated/dead URL", extra={"url": url})
                continue
            out.append(Source.make(url=resolved,
                                   text=str(item.get("text", ""))[:max_chars],
                                   published_at=item.get("published_at"), query=query))
        logger.info(f"Claude CLI Search returned {len(out)} results", extra={"count": len(out)})
        return out
