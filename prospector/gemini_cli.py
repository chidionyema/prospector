"""Gemini CLI adapters — use the locally-installed `gemini` CLI on its free OAuth
quota (Code Assist), sidestepping the API key whose project has free-tier quota = 0.

Provides BOTH:
  - GeminiCliOperator: the verification brain (no web; rules from given passages only).
  - GeminiCliGroundingProvider: real web-search grounding -> resolvable URLs + passages.

The CLI is invoked headless: `gemini --skip-trust -o json [-y] -p <prompt>`. We strip
GEMINI_API_KEY / GOOGLE_API_KEY from the child env so the CLI uses the OAuth login path
rather than the quota-locked key.
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

GEMINI_BIN = os.environ.get("GEMINI_BIN", "gemini")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Layer 3 — resource governance. The `gemini` CLI is a heavy node process; firing many
# at once (5 vet workers × nested per-check search threads) overwhelms the free OAuth
# tier and the searches start failing. This semaphore caps how many CLI subprocesses
# run AT ONCE regardless of how many threads call us, so logical concurrency (candidates)
# is decoupled from physical load (processes). Tune via PROSPECTOR_GEMINI_CONCURRENCY.
_MAX_CLI = max(1, int(os.environ.get("PROSPECTOR_GEMINI_CONCURRENCY", "2") or "2"))
_CLI_SEM = threading.Semaphore(_MAX_CLI)
_SEM_LOCK = threading.Lock()

# Layer 2 — operational resilience. Backoff schedule (seconds) between transient retries.
_BACKOFFS = (2, 5, 10)


def configure_concurrency(n: int) -> None:
    """Resize the CLI subprocess governor from config (single source of truth).
    The PROSPECTOR_GEMINI_CONCURRENCY env var, if set, pins the value and wins.
    Call at startup (make_provider) before any calls are in flight."""
    global _CLI_SEM, _MAX_CLI
    if os.environ.get("PROSPECTOR_GEMINI_CONCURRENCY"):
        return
    n = max(1, int(n))
    with _SEM_LOCK:
        if n != _MAX_CLI:
            _MAX_CLI = n
            _CLI_SEM = threading.Semaphore(n)


def _sum_token_usage(stats: Optional[dict]) -> dict:
    """Sum token counts across every model the CLI used for one call.

    The CLI's `-o json` stats look like:
      stats.models.<model>.tokens.{input, candidates, total, cached, ...}
    and a single call may fan across >1 model (a utility router + the main
    model), so we aggregate them all.
    """
    models = ((stats or {}).get("models") or {})
    out = {"input": 0, "output": 0, "total": 0, "cached": 0}
    for m in models.values():
        tk = (m or {}).get("tokens") or {}
        out["input"] += int(tk.get("input", 0) or 0)
        out["output"] += int(tk.get("candidates", 0) or 0)
        out["total"] += int(tk.get("total", 0) or 0)
        out["cached"] += int(tk.get("cached", 0) or 0)
    return out


def _cli_env() -> dict:
    env = dict(os.environ)
    env.pop("GEMINI_API_KEY", None)        # force the free OAuth path, not the limit:0 key
    env.pop("GOOGLE_API_KEY", None)
    env["GEMINI_CLI_TRUST_WORKSPACE"] = "true"
    return env


def _attempt_gemini_cli(cmd: list[str], timeout: int, web: bool,
                        queue_timeout: Optional[float] = None) -> str:
    """One CLI invocation under the concurrency cap. Raises RuntimeError /
    TimeoutExpired on transient failure so the caller can retry.

    The slot wait is BOUNDED by queue_timeout (None => block, the verdict-brain
    default): a grounding call that can't get a slot within the budget fails fast to
    failover instead of blocking a vet indefinitely. This is the bug that made the
    timeout meaningless — the semaphore wait used to sit OUTSIDE the timeout clock."""
    if not _CLI_SEM.acquire(timeout=queue_timeout):   # bound concurrent heavy node processes
        raise RuntimeError(
            f"gemini cli slot acquire timed out after {queue_timeout}s (grounding queue saturated)")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, env=_cli_env(),
                              cwd=REPO_ROOT, timeout=timeout)
    finally:
        _CLI_SEM.release()
    if proc.returncode != 0:
        raise RuntimeError(f"gemini cli exit {proc.returncode}: {proc.stderr[-300:]}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"gemini cli non-JSON output: {proc.stdout[:200]!r}") from e
    usage = _sum_token_usage(data.get("stats"))
    record_usage(input_tokens=usage["input"], output_tokens=usage["output"],
                 total_tokens=usage["total"], cached_tokens=usage["cached"], web=web)
    logger.info("Gemini CLI usage", extra={"web": web, **usage})

    resp = data.get("response")
    if not resp:
        raise RuntimeError(f"gemini cli empty response: {str(data)[:200]}")
    return resp


@track_latency(name="run_gemini_cli")
def run_gemini_cli(prompt: str, *, web: bool = False, model: Optional[str] = None,
                   timeout: int = 240, timeout_max: Optional[int] = None,
                   escalation: float = 1.0, retries: int = 2,
                   queue_timeout: Optional[float] = None) -> str:
    """Run the CLI headless and return the model's response text.

    Resilient by design: transient failures (timeout, non-zero exit, garbled output —
    the symptoms of an overloaded free-tier CLI) are retried with backoff under a global
    concurrency cap. The per-attempt timeout is ADAPTIVE — it escalates by `escalation`
    each retry up to `timeout_max`, because a timeout often means slow-but-working, not
    dead; a flat short budget would just keep clipping a recovering provider. Only a
    PERSISTENT failure raises — and callers (the grounding provider) turn that into a
    deferral, never a kill.
    """
    cmd = [GEMINI_BIN, "--skip-trust", "-o", "json"]
    if web:
        cmd += ["-y"]                      # auto-approve the web_search tool
    if model:
        cmd += ["-m", model]
    cmd += ["-p", prompt]

    logger.info("Invoking Gemini CLI", extra={"model": model, "web": web})

    ceiling = timeout_max or timeout
    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        attempt_timeout = min(ceiling, int(round(timeout * (escalation ** attempt))))
        try:
            return _attempt_gemini_cli(cmd, attempt_timeout, web, queue_timeout)
        except (subprocess.TimeoutExpired, RuntimeError) as e:
            last_err = e
            # Quota/credit exhaustion is PERSISTENT for this window — retrying (with an
            # even longer timeout) just burns ~timeout seconds per attempt re-confirming a
            # dead brain. Fail over NOW so the breaker/failover layer can skip it.
            if looks_exhausted(str(e)):
                logger.warning("Gemini CLI exhaustion detected; skipping remaining retries",
                               extra={"web": web, "error": str(e)[:200]})
                break
            if attempt < retries:
                backoff = _BACKOFFS[min(attempt, len(_BACKOFFS) - 1)]
                logger.warning(
                    f"Gemini CLI attempt {attempt + 1}/{retries + 1} failed; "
                    f"retrying in {backoff}s",
                    extra={"attempt": attempt + 1, "web": web, "error": str(e)[:200]})
                time.sleep(backoff)
    logger.error("Gemini CLI failed after retries",
                 extra={"attempts": retries + 1, "web": web, "error": str(last_err)[:300]})
    # Quota/credit exhaustion is a FAILOVER signal (the fallback layer retires this
    # provider and tries the next), distinct from a generic transient failure.
    if looks_exhausted(str(last_err)):
        raise ProviderExhaustedError(
            f"gemini cli exhausted after {retries + 1} attempts: {last_err}",
            provider=f"gemini_cli/{model or 'default'}")
    raise RuntimeError(f"gemini cli failed after {retries + 1} attempts: {last_err}")


class GeminiCliOperator(Operator):
    """Verification brain via the CLI. No web — rules only from supplied passages."""
    def __init__(self, model: Optional[str] = None):
        self.model = model
        self.name = f"gemini-cli/{model or 'default'}"

    @track_latency(name="gemini_cli_raw")
    def _raw(self, system: str, user: str, temperature: float) -> str:
        return run_gemini_cli(f"{system}\n\n{user}", web=False, model=self.model)


class GeminiCliGroundingProvider(SearchProvider):
    """Live web-search grounding via the CLI. Returns resolvable URLs + passages."""
    def __init__(self, model: Optional[str] = None,
                 timeout: int = 75, timeout_max: Optional[int] = None,
                 escalation: float = 1.5, retries: int = 1,
                 queue_timeout: Optional[float] = None):
        self.model = model
        self.timeout = timeout      # fail-fast budget per web-search (free tier throttles)
        self.timeout_max = timeout_max or timeout
        self.escalation = escalation
        self.retries = retries
        self.queue_timeout = queue_timeout  # bounded slot wait before failover

    @track_latency(name="gemini_cli_search")
    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        prompt = (
            f"Use google web search to find evidence about: {query}\n"
            "Do NOT write, save, or create any file. Do NOT use any file-writing or "
            "shell tool. Use ONLY web search, then put the answer directly in your reply.\n"
            f"Your ENTIRE final reply must be ONLY a JSON array of up to {k} objects, each exactly "
            f'{{"url": "<real resolvable source url>", "text": "<relevant passage, '
            f'<= {max_chars} chars>", "published_at": "<date or null>"}}. '
            "Use only real source URLs you actually retrieved. No prose, no code fences, "
            "no file references — emit the raw JSON array as the message text itself."
        )
        logger.info(f"Gemini CLI Search started: {query!r}")
        # A TRANSPORT failure (timeout, quota, bad exit — run_gemini_cli already retried
        # and gave up) means we never got to look. It must PROPAGATE so run_check counts a
        # failed search and the candidate DEFERS — swallowing it as [] would make an outage
        # indistinguishable from "searched, found nothing" and wrongly KILL the idea.
        resp = run_gemini_cli(prompt, web=True, model=self.model,
                              timeout=self.timeout, timeout_max=self.timeout_max,
                              escalation=self.escalation, retries=self.retries,
                              queue_timeout=self.queue_timeout)  # raises -> retrieval_failed
        try:
            data = _extract_json(resp)
        except Exception as e:
            # The search RAN but returned no parseable JSON. That is a legitimate empty
            # result (the model found nothing usable), not an outage -> return [].
            logger.warning(f"Gemini CLI Search: unparseable response, treating as empty: {e}",
                           extra={"error": str(e)})
            return []
        if isinstance(data, dict):
            data = data.get("results") or data.get("passages") or []
        # Verify each URL actually resolves (HEAD), dropping fabricated/dead ones —
        # done in PARALLEL (independent checks; identical outcome to serial).
        from .retrieval import resolve_sources
        out = resolve_sources(data, query, max_chars, k)
        logger.info(f"Gemini CLI Search returned {len(out)} results", extra={"count": len(out)})
        return out
