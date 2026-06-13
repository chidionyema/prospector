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

# Layer 2 — operational resilience. Backoff schedule (seconds) between transient retries.
_BACKOFFS = (2, 5, 10)


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


def _attempt_gemini_cli(cmd: list[str], timeout: int, web: bool) -> str:
    """One CLI invocation under the concurrency cap. Raises RuntimeError /
    TimeoutExpired on transient failure so the caller can retry."""
    with _CLI_SEM:                         # bound concurrent heavy node processes
        proc = subprocess.run(cmd, capture_output=True, text=True, env=_cli_env(),
                              cwd=REPO_ROOT, timeout=timeout)
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
                   timeout: int = 240, retries: int = 2) -> str:
    """Run the CLI headless and return the model's response text.

    Resilient by design: transient failures (timeout, non-zero exit, garbled output —
    the symptoms of an overloaded free-tier CLI) are retried with backoff under a global
    concurrency cap. Only a PERSISTENT failure raises — and callers (the grounding
    provider) turn that into a deferral, never a kill.
    """
    cmd = [GEMINI_BIN, "--skip-trust", "-o", "json"]
    if web:
        cmd += ["-y"]                      # auto-approve the web_search tool
    if model:
        cmd += ["-m", model]
    cmd += ["-p", prompt]

    logger.info("Invoking Gemini CLI", extra={"model": model, "web": web})

    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            return _attempt_gemini_cli(cmd, timeout, web)
        except (subprocess.TimeoutExpired, RuntimeError) as e:
            last_err = e
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
                 timeout: int = 75, retries: int = 1):
        self.model = model
        self.timeout = timeout      # fail-fast budget per web-search (free tier throttles)
        self.retries = retries

    @track_latency(name="gemini_cli_search")
    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        prompt = (
            f"Use google web search to find evidence about: {query}\n"
            f"Return ONLY a JSON array of up to {k} objects, each exactly "
            f'{{"url": "<real resolvable source url>", "text": "<relevant passage, '
            f'<= {max_chars} chars>", "published_at": "<date or null>"}}. '
            "Use only real source URLs you actually retrieved. No prose, no code fences."
        )
        logger.info(f"Gemini CLI Search started: {query!r}")
        # A TRANSPORT failure (timeout, quota, bad exit — run_gemini_cli already retried
        # and gave up) means we never got to look. It must PROPAGATE so run_check counts a
        # failed search and the candidate DEFERS — swallowing it as [] would make an outage
        # indistinguishable from "searched, found nothing" and wrongly KILL the idea.
        resp = run_gemini_cli(prompt, web=True, model=self.model,
                              timeout=self.timeout, retries=self.retries)  # raises -> retrieval_failed
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
        out: list[Source] = []
        from .retrieval import _resolve
        for item in (data or [])[:k]:
            url = str(item.get("url", ""))
            if not url:
                continue
            
            # Tier 2 Bug 4: Verify the URL actually exists (HEAD request)
            resolved = _resolve(url)
            if not resolved:
                logger.warning("Dropping fabricated/dead URL", extra={"url": url})
                continue

            out.append(Source.make(url=resolved,
                                   text=str(item.get("text", ""))[:max_chars],
                                   published_at=item.get("published_at"), query=query))
        
        logger.info(f"Gemini CLI Search returned {len(out)} results", extra={"count": len(out)})
        return out
