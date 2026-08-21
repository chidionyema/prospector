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
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Optional

from . import usage_wall
from .audit import audit as _audit
from .cli_auth import subscription_env
from .cli_governor import make_governor
from .errors import ProviderExhaustedError, cause_context, looks_exhausted
from .models import Source
from .operator import Operator, ParseError, _extract_json
from .retrieval import SearchProvider
from .telemetry import logger, record_usage, track_latency

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")

# The cheapest Claude tier, and the DEFAULT for every claude_cli call this estate makes.
# Founder directive 2026-08-19: "i need to ensure they fall back to the cheapest possible
# version of claude ... enforced and documented".
#
# Why this needs a pin rather than a comment: `run_claude_cli` only passes `--model` when a
# model is given, so a bare ClaudeCliOperator() inherits whatever the machine's Claude Code
# settings default to. Measured 2026-08-19 on this laptop that default was `opus[1m]`
# (~/.claude/settings.json:81) — the most expensive model there is, silently ruling verdicts
# on the £49 deliverable. The cost is not only money: `claude -p` spends the SUBSCRIPTION
# allowance, and Opus burns it several times faster than Haiku, so an unpinned fallback also
# hits `usage_wall` sooner and takes the whole failover chain down with it.
CHEAPEST_CLAUDE_MODEL = "claude-haiku-4-5-20251001"
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

# THE CEILING IS ONE. It is a CLAMP, not a default: nothing below may raise it -- not
# config.yaml, not the dashboard overlay, not PROSPECTOR_CLAUDE_CONCURRENCY.
#
# WHY (founder directive 2026-08-20, verbatim): "for the last tine i donnt want 4 claude
# processes, its epensive. this should never have happencd", "1 cludclaude cli", "not 4",
# "this needs to be enforce ruthlessly", "i alredy wanred you about this".
#
# The measurement behind it, taken inside the prospector-engine container the same day. Four
# concurrent `claude` Node runtimes on a shared-cpu-2x slice, by pid:
#
#     pid 4072  claude -p You write web search queries to fairly assess a business idea...
#     pid 4056  claude -p You write web search queries that fairly assess a business idea...
#     pid 4064  claude -p You write web search queries that fairly assess a business idea...
#     pid 4058  claude -p You are a ruthless, evidence-bound analyst...
#
# Host accounting at that moment: steal 91.7%, user 6.8%, sys 1.4%. The ops console was being
# starved 50-150x by its own engine -- importing console_api took 6078ms under that load and
# 125ms on the same machine idle. Nothing in the console had got slower.
#
# Two costs, and the money one is the reason this is a clamp rather than a tuned number. Each
# `claude -p` is a full Node runtime and spends the SUBSCRIPTION allowance; four of them spend
# it four times as fast and reach `usage_wall` four times sooner, which takes the whole
# failover chain down. claude_cli is the FAILOVER brain now (config.yaml `operator:` heads
# minimax), so there is no throughput argument on the other side of the ledger.
#
# If you are here because a config knob "does not take effect": that is this clamp working as
# ordered. Do not raise it. tests/unit/test_one_claude_cli_process.py fails if you do.
MAX_CLAUDE_CLI = 1


def _clamped(n: int) -> int:
    """Coerce any requested width down to MAX_CLAUDE_CLI, saying so when it bites."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = MAX_CLAUDE_CLI
    n = max(1, n)
    if n > MAX_CLAUDE_CLI:
        logging.getLogger(__name__).warning(
            "claude CLI concurrency %d requested; refusing and using %d. The ceiling is a "
            "founder directive (2026-08-20, \"1 claude cli, not 4\"), not a tuned default. "
            "See prospector/claude_cli.py MAX_CLAUDE_CLI.",
            n, MAX_CLAUDE_CLI,
        )
        n = MAX_CLAUDE_CLI
    return n


# Cap concurrent heavy CLI subprocesses.
_MAX_CLI = _clamped(os.environ.get("PROSPECTOR_CLAUDE_CONCURRENCY") or MAX_CLAUDE_CLI)
# Machine-wide, not per-process — see prospector/cli_governor.py. The 45s "grounding queue
# saturated" tail that killed job 20260730T212901866 was oversubscription across pipelines,
# not a too-small limit here.
_CLI_SEM = make_governor(_MAX_CLI, "claude")
_SEM_LOCK = threading.Lock()
_BACKOFFS = (2, 5, 10)


def configure_concurrency(n: int) -> None:
    """Resize the CLI subprocess governor from config, bounded by MAX_CLAUDE_CLI.

    PROSPECTOR_CLAUDE_CONCURRENCY still pins the value against config, but it is clamped
    too: the env var is an ops LOWER-ing hatch, never a way back up to four. Call at startup
    (make_provider) before any calls are in flight.
    """
    global _CLI_SEM, _MAX_CLI
    env = os.environ.get("PROSPECTOR_CLAUDE_CONCURRENCY")
    n = _clamped(env) if env else _clamped(n)
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
    # Named and banked, not folded away. This term used to exist only inside the `total`
    # expression below, so it had no column in telemetry._USAGE_KEYS and its 614,681 tokens
    # in the 2026-08-13T06:23:14 batch surfaced as an unexplained gap between
    # `input + output = 728,379` and `total = 1,990,168`, which read as a broken instrument.
    cache_write = int(u.get("cache_creation_input_tokens", 0) or 0)
    total = inp + out + cached + cache_write
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
                 cached_tokens=cached, cache_write_tokens=cache_write,
                 web=web, provider="claude_cli")
    # cost_usd here is the CLI's own billed figure (more accurate than an estimate);
    # costs_report sums it into spend.
    logger.info("Claude CLI usage", extra={"web": web, "input": inp, "output": out,
                                           "total": total, "cached": cached,
                                           "cache_write": cache_write, "cost_usd": cost})


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


_MIN_JSON_SCHEMA_CLI = (2, 1, 205)
_schema_support: Optional[bool] = None
_schema_lock = threading.Lock()


def _cli_version() -> tuple[int, ...]:
    """`claude --version` -> (2, 1, 232). () when it cannot be read."""
    try:
        out = subprocess.run([CLAUDE_BIN, "--version"], capture_output=True, text=True,
                             timeout=20, stdin=subprocess.DEVNULL,
                             env=subscription_env()).stdout
    except Exception:
        return ()
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", out or "")
    return tuple(int(g) for g in m.groups()) if m else ()


def supports_json_schema() -> bool:
    """Whether this machine's `claude` CLI can be trusted with `--json-schema`.

    VERSION-GATED, and the gate is the whole point. `--json-schema` is validate-and-re-prompt,
    not grammar-constrained, and before CLI **2.1.205** an invalid schema was *silently
    ignored* — the call succeeds, bills, and returns free-form prose while the caller believes
    it is holding validated JSON. That is the "swallowed outage returns data" shape: the worst
    possible failure mode, because nothing anywhere reports it. On an older or unreadable CLI
    we simply do not pass the flag and keep today's multi-strategy parsing, which is degraded
    but honest.

    Measured on this machine 2026-08-15: `claude --version` -> `2.1.232 (Claude Code)`, and
    `claude --help` advertises `--json-schema <schema>  JSON Schema for structured output`.
    """
    global _schema_support
    if _schema_support is None:
        with _schema_lock:
            if _schema_support is None:
                v = _cli_version()
                _schema_support = bool(v) and v >= _MIN_JSON_SCHEMA_CLI
                logger.info(
                    "claude CLI structured output: "
                    + ("enabled" if _schema_support else "DISABLED"),
                    extra={"cli_version": ".".join(map(str, v)) or "unreadable",
                           "min_required": ".".join(map(str, _MIN_JSON_SCHEMA_CLI))})
    return _schema_support


def _attempt_claude_cli(cmd: list[str], timeout: int, web: bool,
                        queue_timeout: Optional[float] = None,
                        expect_structured: bool = False) -> str:
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
    # an untrusted brain answering a call that MOAT_PRIMARY still counts as trusted).
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
        # The TAIL is the right slice for prose and the wrong one for `--output-format json`,
        # where trailing metadata pushes the cause out of the window. Measured 2026-08-07: the
        # payload that ended E3 run #6 reached the classifier as
        # `…"fast_mode_disabled_reason":"sdk_opt_in_required","subtype":"success","api_error_st`
        # and classified as NOT_EXHAUSTION, so the monthly-spend-limit outage left no dead mark
        # and nothing failed over — 50 further calls were spent into a provider already known
        # to be dead. `cause_context` scans the WHOLE payload for the marker vocabulary
        # `classify_exhaustion` already rules on, so the cause survives whatever the shape is;
        # the tail is kept alongside it because it is still the best summary when there is no
        # marker at all.
        cause = " | ".join(s for s in (cause_context(proc.stderr), cause_context(proc.stdout))
                           if s)
        detail = " | ".join(s for s in (cause,
                                        proc.stderr.strip()[-300:],
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
        # ANY `error*` subtype, not just `error_during_execution`. The CLI's convention is that
        # a failed run names itself in `subtype`, and structured output adds a new member to
        # that family — `error_max_structured_output_retries`, emitted when the model could not
        # produce a payload matching the schema within the CLI's own retry budget. Pinning the
        # single old literal would have let that one through to `data.get("result")`, which on
        # a failed structured run holds the last INVALID attempt: a partial answer returned as
        # if it were a whole one. `error_max_turns` is caught by the same widening, and for the
        # same reason — a run that stopped early has not answered, and this repo's expensive
        # lesson is that a truncated result flowing on as data is indistinguishable downstream
        # from a real one ("an exception is never evidence; a failed call DEFERS").
        subtype = str(data.get("subtype") or "")
        if data.get("is_error") or subtype.startswith("error"):
            raise RuntimeError(f"claude cli error result: {str(data)[:200]}")
        if expect_structured:
            # The docs are explicit that a `success` result can carry NO `structured_output`
            # field, and that this must be treated as a failure rather than as an empty answer.
            # Returning the free-form `result` here instead would silently reinstate exactly
            # the unvalidated path the schema was added to remove — and it would do it only on
            # the calls where validation failed, i.e. the ones that most need to fail loudly.
            structured = data.get("structured_output")
            if structured is None:
                raise RuntimeError(
                    "claude cli returned no structured_output for a --json-schema call "
                    f"(subtype={subtype!r}, stop_reason={data.get('stop_reason')!r}): "
                    f"{str(data.get('result'))[:200]}")
            # Re-serialised rather than handed back as an object: every caller of this function
            # is typed `-> str` and runs the result through `_extract_json`. Round-tripping a
            # dict json.dumps produced is the one input that parser is guaranteed to read, so
            # the strategies become dead code on this path without changing a single signature.
            return json.dumps(structured)
        resp = data.get("result")
        if resp:
            return str(resp)
    raise RuntimeError(f"claude cli empty/unexpected response: {str(data)[:200]}")


@track_latency(name="run_claude_cli")
def run_claude_cli(prompt: str, *, web: bool = False, model: Optional[str] = None,
                   timeout: int = 180, timeout_max: Optional[int] = None,
                   escalation: float = 1.0, retries: int = 1,
                   queue_timeout: Optional[float] = None,
                   json_schema: Optional[dict] = None) -> str:
    """Run the claude CLI headless and return the response text.

    Transient failures are retried with backoff; the per-attempt timeout is ADAPTIVE
    (escalates by `escalation` each retry up to `timeout_max` — slow≠dead). A persistent
    failure raises — ProviderExhaustedError if it looks like quota/credit exhaustion (so
    the fallback layer retires this provider), else a plain RuntimeError.
    """
    # USAGE-WALL PREFLIGHT. Otto and this daemon share ONE subscription, and whichever of them
    # hits the wall records when it lifts (`usage_wall`). Spawning `claude -p` into a wall we
    # can already see costs a process, a queue slot and a CLI-usage entry to be told something
    # the marker already says. Raising ProviderExhaustedError rather than inventing a new
    # signal is deliberate: the DEFER/dead-mark/`vet --resume` rails already handle an
    # exhausted brain correctly, and a wall IS exhaustion — it just happens to know its own
    # reset time. The message carries the literal "usage limit reached" so `looks_exhausted`
    # and `classify_exhaustion` classify it exactly as they would the CLI's own words.
    #
    # ...but the WINDOW must not travel as prose. `usage_wall.reason()` renders the reset for a
    # human ("capacity returns 2026-08-08 22:37:45 (14.0 min)"), and `limit_window_seconds`
    # returns None on that shape, so before 2026-08-08 a known 14-minute wall was benched as the
    # 1h default and the moat went provisional for 46 minutes it did not owe. We know the number
    # exactly — `blocked_for()` is the same value `reason()` is rendered from — so hand it over
    # structurally and let no regex stand between the two.
    walled = usage_wall.reason()
    if walled:
        logger.warning("Claude CLI skipped: usage wall is live", extra={"web": web})
        raise ProviderExhaustedError(
            f"claude cli not called: usage limit reached — {walled}",
            provider=f"claude_cli/{model or 'default'}",
            retry_after_s=usage_wall.blocked_for())

    cmd = [CLAUDE_BIN, "-p", prompt, "--output-format", "json"]
    # STRUCTURED OUTPUT. When the caller knows the shape it expects, ask the CLI to VALIDATE it
    # rather than parsing whatever prose comes back. This is the fix at source for the defect
    # class `_extract_json`'s four strategies exist to survive — measured 2026-08-15, one
    # literal newline inside a JSON string was enough to make it return the wrong array, and
    # that parser defect arrived downstream wearing the costume of a search that found nothing.
    #
    # Two constraints, both established live on 2026-08-15 rather than read off the docs:
    #  - the schema must be draft-07, and TOP-LEVEL ARRAYS ARE REJECTED. A bare
    #    `{"type": "array"}` schema returns `is_error: true, terminal_reason: "api_error"` with
    #    a zero-token, zero-cost result. Callers wanting a list must wrap it in an object.
    #  - success carries the payload in BOTH `structured_output` (parsed) and `result` (the
    #    same JSON as a clean string). We read the former; see `_attempt_claude_cli`.
    expect_structured = bool(json_schema) and supports_json_schema()
    if expect_structured:
        cmd += ["--json-schema", json.dumps(json_schema)]
    if web:
        cmd += ["--allowedTools", "WebSearch"]
    if model:
        cmd += ["--model", model]

    logger.info("Invoking Claude CLI",
                extra={"model": model, "web": web, "structured": expect_structured})

    ceiling = timeout_max or timeout
    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        attempt_timeout = min(ceiling, int(round(timeout * (escalation ** attempt))))
        try:
            return _attempt_claude_cli(cmd, attempt_timeout, web, queue_timeout,
                                       expect_structured=expect_structured)
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
        # RECIPROCITY. Reading the marker only fixes our half: if PROSPECTOR is the process
        # that meets the wall first, Otto keeps hammering until it meets it too. `observe`
        # gates on its own wall vocabulary, so a 402/credit-balance exhaustion — which is NOT
        # a subscription wall and has no reset time — writes nothing.
        usage_wall.observe(str(last_err), observed_by="prospector-cli")
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


# Draft-07, object-rooted, and deliberately NOT `additionalProperties: false` on the items:
# the CLI re-prompts the model until the payload validates, so a schema that forbids a harmless
# extra key spends real retries — and can end in `error_max_structured_output_retries` — over a
# field `resolve_sources` would simply have ignored. `published_at` is optional for the same
# reason: it is genuinely absent for plenty of real sources, and requiring it would turn "this
# page has no date" into a failed call.
_SEARCH_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "text": {"type": "string"},
                    "published_at": {"type": ["string", "null"]},
                },
                "required": ["url", "text"],
            },
        }
    },
    "required": ["results"],
}


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
        # The prompt asks for the OBJECT shape (`{"results": [...]}`) unconditionally, whether
        # or not the schema is passed, so that the two can never describe different payloads.
        # A top-level array is not an option: the CLI rejects an array-rooted schema outright
        # (proven 2026-08-15 — `is_error: true, terminal_reason: "api_error"`). Nothing
        # downstream changes, because the parse below already unwrapped `results`/`passages`
        # for dict replies long before this call had a schema.
        prompt = (
            f"Use web search to find evidence about: {query}\n"
            f'Return ONLY a JSON object {{"results": [...]}} whose array holds up to {k} '
            f'objects, each exactly {{"url": "<real resolvable source url>", '
            f'"text": "<relevant passage, <= {max_chars} chars>", '
            f'"published_at": "<date or null>"}}. '
            "Use only real source URLs you actually retrieved. No prose, no code fences."
        )
        logger.info(f"Claude CLI Search started: {query!r}")
        # AUDIT (added 2026-08-16). Every other grounding provider writes a `search` row;
        # this one never did, so its cost was invisible: on 2026-08-16 the whole search step
        # measured 21,338s while the ddg+exa rows summed to 2,036s, and the missing 90% was
        # this provider. Stage timers then measured it at 2,744s of 3,622s across 20 searches
        # (~196s per call) — it is the single most expensive thing in grounding, and until
        # this line existed no report could say so.
        _t0 = time.monotonic()
        # Transport/exhaustion failure PROPAGATES so the fallback layer can fail over
        # (and, if all providers are out, run_check defers — never a false kill).
        try:
            resp = run_claude_cli(prompt, web=True, model=self.model,
                                  timeout=self.timeout, timeout_max=self.timeout_max,
                                  escalation=self.escalation, retries=self.retries,
                                  queue_timeout=self.queue_timeout,
                                  json_schema=_SEARCH_SCHEMA)
        except Exception as e:
            _audit("search", provider="claude_cli", query=query[:200], k=k,
                   max_chars=max_chars, returned_n=0,
                   latency_ms=int((time.monotonic() - _t0) * 1000),
                   status="error", error=str(e)[:200])
            raise
        _call_ms = int((time.monotonic() - _t0) * 1000)
        try:
            data = _extract_json(resp)
        except Exception as e:
            # PROPAGATE. This used to `return []`, which is the same bytes as "I searched the
            # web and there is nothing there" — and the chain reads that as evidence: it
            # records a breaker SUCCESS, clears the provider's dead mark, and short-circuits
            # (`FallbackSearchProvider.search`, retrieval.py:1860-1895). A verdict then rules
            # `unverifiable` on no passages and that flows into the kill gates as a finding.
            # So an unreadable reply could kill an idea, and the dossier would look reasoned.
            #
            # We do not know what the model found. "Unparseable" is a statement about OUR
            # ability to read the answer, never about the web. Measured 2026-08-15, and this
            # is why the distinction is not academic: `_extract_json` was itself losing
            # perfectly good replies — one literal newline inside a JSON string made it
            # return the wrong array — so our own parser defect was arriving downstream
            # wearing the costume of a search that found nothing.
            #
            # Raising lands in `except Exception` at retrieval.py:1905: breaker failure,
            # fail over to the next provider. Only if EVERY provider is gone does the chain
            # raise `GroundingInfrastructureError`, which run_check turns into a DEFER.
            # "An exception is never evidence; a failed call DEFERS."
            logger.error(f"Claude CLI Search: unparseable response, failing over: {e}",
                         extra={"error": str(e), "chars": len(resp or "")})
            raise ParseError(
                f"Claude CLI Search returned {len(resp or '')} chars of unparseable "
                f"response for {query!r}: {e}") from e
        if isinstance(data, dict):
            data = data.get("results") or data.get("passages") or []
        # Resolve URLs in PARALLEL, dropping dead/fabricated ones (identical to serial).
        from .retrieval import resolve_sources
        out = resolve_sources(data, query, max_chars, k)
        logger.info(f"Claude CLI Search returned {len(out)} results", extra={"count": len(out)})
        # `call_ms` is the CLI itself (queue wait + attempts); `latency_ms` adds URL
        # resolution, so the gap between them says which half to attack.
        _audit("search", provider="claude_cli", query=query[:200], k=k,
               max_chars=max_chars, returned_n=len(out),
               latency_ms=int((time.monotonic() - _t0) * 1000), call_ms=_call_ms,
               status="ok" if out else "empty")
        return out
