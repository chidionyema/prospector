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

from .cli_auth import subscription_env
from .cli_governor import make_governor
from .errors import ProviderExhaustedError, looks_exhausted
from .models import Source
from .operator import Operator, _extract_json
from .retrieval import SearchProvider
from .telemetry import logger, record_usage, track_latency

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
    # `provider=` matters: without it record_usage defaults to "unknown" (telemetry.py:194), so
    # every call through the moat's PRIMARY brain was filed under a bucket named after nothing
    # and `get_usage_summary()["by_provider"]` could never name claude_cli. Same shape as the
    # web_calls counter that was structurally zero.
    #
    # This deliberately does NOT add claude_cli to telemetry.PRICING. That would make
    # record_usage emit an `event: "spend"` row (telemetry.py:227 gates on `cost > 0`), which is
    # what scheduler/guard.py counts as METERED, billed money against `daily_cap_usd`. CLI usage
    # is subscription-equivalent — guard.py:36-39 measured that folding it in "would halt the
    # daemon within about two hours of every day for spend that is never invoiced". The
    # subscription leg is already tracked separately, from the "Claude CLI usage" row below.
    record_usage(input_tokens=inp, output_tokens=out, total_tokens=total,
                 cached_tokens=cached, web=web, provider="claude_cli")
    # cost_usd here is the CLI's own billed figure (more accurate than an estimate);
    # costs_report sums it into spend.
    logger.info("Claude CLI usage", extra={"web": web, "input": inp, "output": out,
                                           "total": total, "cached": cached, "cost_usd": cost})


def _safe_record(data: dict, web: bool) -> None:
    """Bank usage without ever being able to break the call being measured.

    A meter that can raise replaces the caller's real exception with its own — and the real
    exception is precisely what `errors.looks_exhausted` reads to retire a spent brain
    (392ce4c: a live brain benched nine times because the reason never reached the
    classifier). Now that recording happens on the FAILURE paths too, an accounting bug would
    be able to swallow a dead-brain trace. It must not.
    """
    try:
        _record_claude_usage(data, web)
    except Exception:  # noqa: BLE001 - accounting must never mask the real failure
        logger.warning("failed to record claude cli usage", exc_info=True)


def _record_failed_call(stdout: str, web: bool) -> None:
    """Bank the usage of a call that BILLED and is about to raise.

    Silent no-op when stdout is not a JSON object carrying a usage block, which is the normal
    case for a process that exited non-zero.
    """
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, TypeError, ValueError):
        return
    if isinstance(data, dict) and (data.get("usage") or data.get("total_cost_usd")):
        _safe_record(data, web)


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
    # Strip the hijack vars so the CLI falls back to the subscription seat (matches CLAUDE.md:
    # "the entire engine runs within your Claude Code subscription").
    #
    # The definition lives in cli_auth, NOT inline here: it also strips ANTHROPIC_BASE_URL,
    # which is a moat-integrity control rather than a billing one (a repointed endpoint means
    # an untrusted brain answering a call that operator.py:889 still counts as MOAT_PRIMARY).
    child_env = subscription_env()
    # STABLE cwd per SLOT — not a fresh dir per call. Two constraints meet here, and the first
    # cut satisfied one by paying the other on every single call:
    #
    #  (a) COLLISION SAFETY. Claude Code derives its per-project session slug from the cwd PATH,
    #      so concurrent `claude -p` in a SHARED dir clobber each other's session state and
    #      degrade to non-JSON meta output. PROVEN 2026-07-02: parallel generation
    #      (concurrency=2) → 0/3 candidates, serialized (concurrency=1) → 2/3.
    #  (b) CACHE WARMTH. A cwd never used before is a COLD PROMPT CACHE. Measured 2026-08-06:
    #      mkdtemp-per-call re-wrote the ~10.4k-token prefix at the 1h-TTL 2.0x rate on every
    #      call and then deleted the directory — daemon $0.2650/req vs $0.0937 interactive,
    #      cache reuse ratio 0.72x vs 42.89x, $412.19 of pure cache_write in a single day.
    #      Controlled A/B (~/.claude/scripts/cli-cache-experiment.py), identical prompt: fresh
    #      cwd $0.1121/$0.1172/$0.1172/$0.1122 vs stable cwd $0.1121/$0.0899/$0.0134/$0.0132 —
    #      8.6x cheaper at steady state, identical output.
    #
    # mkdtemp buys (a) by making collision impossible; it forfeits (b) unconditionally. The
    # governor already enforces (a), and more cheaply: holding `slot_i.lock` is a machine-wide
    # LOCK_EX flock, so at most one process ANYWHERE holds slot i. Binding the cwd to the slot
    # index inherits that exclusivity proof verbatim — no second lock, no stale-slot reaper —
    # while the path stays constant across calls, which is all of (b). The directory is NOT
    # deleted afterwards: it is empty by design, and deleting it is precisely what threw the
    # cache away. Parent stays _NEUTRAL_CWD (outside the repo) so Claude Code's upward CLAUDE.md
    # walk still finds nothing project-specific — that property is deliberately unchanged.
    # getattr, not a direct call: cli_governor.py:58-59 promises the governor's public surface
    # stays drop-in for `threading.Semaphore` (acquire/release only), and callers rely on that —
    # tests/unit/test_claude_cli_failure_reason.py substitutes a bare acquire/release stub. A
    # governor that cannot name a slot is not an error, it just does not get the cache saving.
    slot = getattr(_CLI_SEM, "current_slot", lambda: None)()
    ephemeral = slot is None
    if ephemeral:
        # The governor could not name a slot (degraded in-process fallback). Reproduce the old
        # behaviour exactly rather than risk a shared cwd: correctness outranks the saving.
        call_cwd = tempfile.mkdtemp(prefix="c_", dir=_NEUTRAL_CWD)
    else:
        call_cwd = os.path.join(_NEUTRAL_CWD, f"slot_{slot}")
        os.makedirs(call_cwd, exist_ok=True)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              cwd=call_cwd, timeout=timeout, stdin=subprocess.DEVNULL,
                              env=child_env)
    finally:
        _CLI_SEM.release()
        if ephemeral:
            shutil.rmtree(call_cwd, ignore_errors=True)
    if proc.returncode != 0:
        # BOTH streams, because the CLI reports WHY on STDOUT, not stderr. Measured 2026-08-06:
        # `claude -p` with an unfunded key exits 1 printing "Credit balance is too low" on stdout
        # while stderr held only an unrelated connectors warning. A stderr-only message is
        # therefore EMPTY exactly when it matters — the daemon logged `claude cli exit 1: ` for
        # every failure at 04:37 — and `looks_exhausted("")` is False, so the head of the moat
        # was never marked exhausted and got re-probed on every call. "credit balance is too
        # low" and "usage limit" ARE in _EXHAUSTION_MARKERS (errors.py:66); they just never
        # reached the classifier. Same shape as the 402 miss (CLAUDE.md: a dead brain must
        # leave a trace).
        detail = " | ".join(s for s in (proc.stderr.strip()[-300:],
                                        proc.stdout.strip()[-300:]) if s)
        # Best-effort: a non-zero exit usually prints prose, not JSON, so there is normally
        # nothing to bank here. But an exit code is not a promise about the payload, and a
        # billed call that happens to still emit its usage block must not be dropped just
        # because the process died afterwards.
        _record_failed_call(proc.stdout, web)
        raise RuntimeError(f"claude cli exit {proc.returncode}: {detail}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"claude cli non-JSON output: {proc.stdout[:200]!r}") from e
    # RECORD BEFORE BRANCHING. The API request is already paid for by the time this payload
    # exists; whether we then like its CONTENTS is our problem, not the meter's. Recording only
    # on the success path (which is what this did until 2026-08-06) made every `is_error`,
    # every empty `result`, and every unexpected shape a free call in our own books. Measured
    # 2026-08-06: 1,926 daemon calls left a costed transcript, 1,568 reached
    # `store/prospector.jsonl` — 358 calls (18.6%) and $104.89 invisible in ONE day, at
    # $0.293/call, indistinguishable from the $0.265 measured mean of calls that DID record.
    # This is not a cost saving; it is the difference between a ledger and a guess, and
    # `spend.daily_subscription_cap_usd` (config.yaml:997) is now a real ceiling that reads
    # this leg — a ceiling fed by a meter that under-counts by 18.6% halts 18.6% too late.
    if isinstance(data, dict):
        _safe_record(data, web)
    # Headless JSON shape: {"type":"result","subtype":"success","result":"...","is_error":..}
    if isinstance(data, dict):
        if data.get("is_error") or data.get("subtype") == "error_during_execution":
            raise RuntimeError(f"claude cli error result: {str(data)[:200]}")
        resp = data.get("result")
        if resp:
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
