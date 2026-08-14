"""The pluggable 'brain' (Part 1). Same tooling, swappable operator.

Every model call goes through Operator.complete_json(), which enforces strict JSON
output with repair-retries (Part 9) — a bad parse never crashes a run. Adapters:
  - GeminiOperator: google-genai direct. Default for 'now' (key present).
  - ClaudeOperator: Anthropic API (select once ANTHROPIC_API_KEY is set).
  - MiniMaxOperator: MiniMax OpenAI-compatible API. Routed to NON-VERIFICATION
    tasks only (generation, marketing content, artifacts). The verification moat
    (kill-check verdicts, adversarial pass) MUST stay with Claude/Gemini per
    CLAUDE.md.  MiniMax is ~$0.001/M tokens input vs Claude Opus ~$0.015 —
    15× cheaper for creative/structuring tasks.
  - MockOperator: deterministic, for tests / fixtures (no network, no spend).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any, Callable, Iterator, Optional

from .breaker import CircuitBreaker
from .telemetry import track_latency


class ParseError(Exception):
    pass


#: A reasoning model's <think>…</think> preamble, which is NOT the answer. Defined once because
#: two call sites now depend on it agreeing: the parser strips it to find the JSON, and the
#: MiniMax adapter uses "nothing left after stripping it" as its truncation test. A second copy
#: could disagree with the first about what counts as an answer.
_RE_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _extract_json(text: str) -> Any:
    """Multi-strategy JSON extraction from verbose model output."""
    from .telemetry import logger

    # Strategy 1: Strip <think> blocks and try direct load
    t = _RE_THINK.sub("", text).strip()
    # Strip markdown code fences
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.MULTILINE).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass

    # Strategy 2: Find the largest possible range between braces/brackets
    # This works if the model outputs one main JSON block with noise around it.
    for start_char, end_char in [("[", "]"), ("{", "}")]:
        start = text.find(start_char)
        end = text.rfind(end_char)
        if start != -1 and end != -1 and end > start:
            candidate = text[start:end+1]
            try:
                data = json.loads(candidate)
                logger.info(f"JSON Strategy 2 success: found {len(candidate)} chars from {start} to {end}")
                return data
            except json.JSONDecodeError:
                pass

    # Strategy 3: Balanced-brace parser (fallback for multiple top-level blocks or complex noise)
    start = min([i for i in (text.find("{"), text.find("[")) if i != -1], default=-1)
    if start != -1:
        depth, instr, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if instr:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    instr = False
            else:
                if c == '"':
                    instr = True
                elif c in "{[":
                    depth += 1
                elif c in "}]":
                    depth -= 1
                    if depth == 0:
                        candidate = text[start:i + 1]
                        try:
                            data = json.loads(candidate)
                            logger.info(f"JSON Strategy 3 success: found {len(candidate)} balanced chars starting at {start}")
                            return data
                        except json.JSONDecodeError as e:
                            logger.warning(f"JSON Strategy 3 balanced match failed: {e}",
                                           extra={"candidate_start": candidate[:50], "candidate_end": candidate[-50:]})
                            continue

    # Strategy 4: the LAST balanced block wins, not the first.
    #
    # Strategies 1-3 all assume the answer is the first JSON-shaped thing in the response.
    # That is false for a reasoning model, which thinks in prose first and answers last — and
    # its prose is full of JSON-shaped noise: measured 2026-08-14 on a live retitle run,
    # MiniMax returned 55,639 chars whose reasoning contained the literal `[Customers] [have
    # problem]`, so Strategy 3 locked on to `[Customers]` and every later attempt inherited a
    # broken depth count. The answer — a complete `{... "card_line": "..."}` — was the last
    # 200 characters of the response and no strategy ever looked there. The whole run produced
    # nothing, twice, at $0.0067 and four minutes a call.
    #
    # Strategy 1 already handles the well-formed case (`<think>…</think>` then JSON), so this
    # runs ONLY after 1-3 have failed and cannot change any response that parses today. It is
    # tried on the think-stripped text first and the raw text second, because a `<think>` with
    # no closing tag — which is what a model that runs out of budget mid-answer emits — leaves
    # the stripper nothing to remove.
    for source in (t, text):
        for candidate in _tail_json_candidates(source):
            try:
                data = json.loads(candidate)
                logger.info(
                    f"JSON Strategy 4 success: {len(candidate)} chars taken from the tail of "
                    f"{len(source)}")
                return data
            except json.JSONDecodeError:
                continue

    raise ParseError(f"no valid JSON found in {len(text)} chars. Start={text[:100]!r}, End={text[-100:]!r}")


def _tail_json_candidates(text: str, *, max_closers: int = 6,
                          max_openers: int = 200) -> Iterator[str]:
    """Substrings that could be the answer, searched inward from the END of the response.

    Deliberately NOT a balanced-depth scan. A depth counter is only correct if every brace
    before the answer is matched, and in reasoning prose they are not: one stray `{` in a
    sentence about a data shape swallows the real object, which is precisely how Strategy 3
    locked on to `[Customers]` and never recovered. Anchoring on the LAST closing brace and
    walking the opening braces backwards makes the noise before the answer irrelevant, and it
    finds a well-formed trailing object on the FIRST attempt.

    Bounded on purpose (`max_closers` × `max_openers`): a pathological response must not turn
    a parse failure into a CPU-bound hang on the publish path. Failures are cheap — `json.loads`
    on a candidate that starts mid-prose rejects at the first character.
    """
    closers = [i for i, c in enumerate(text) if c in "}]"]
    openers = [i for i, c in enumerate(text) if c in "{["]
    for close in reversed(closers[-max_closers:]):
        tried = 0
        for open_at in reversed([i for i in openers if i < close]):
            if tried >= max_openers:
                break
            tried += 1
            if text[open_at] == "{" and text[close] != "}":
                continue
            if text[open_at] == "[" and text[close] != "]":
                continue
            yield text[open_at:close + 1]


class Operator(ABC):
    """Backend that turns (system, user) -> raw text. complete_json adds the
    structured-output discipline on top, identical across adapters."""

    name = "operator"

    # The CONFIG TIER name this operator was built for ("claude_cli", "claude", "minimax",
    # ...), stamped by `make_operator`. It is deliberately NOT `self.name`: instance names
    # carry the model ("claude/claude-opus-4-8"), while MOAT_PRIMARY is a set of tier names,
    # so keying trust off `name` would mark a trusted `operator: claude` config provisional.
    # Empty for operators constructed directly (tests, fixtures), which keeps those on their
    # existing non-provisional behaviour.
    tier_name: str = ""

    @abstractmethod
    def _raw(self, system: str, user: str, temperature: float) -> str:
        ...

    def served_is_provisional(self) -> bool:
        """True if a ruling served by THIS operator must be stamped provisional.

        A single-tier config returns a bare operator with no chain to fail over to, so
        before this existed only `FallbackOperator` could answer the question and
        `verify._served_is_provisional` fell back to `False` — meaning a config of
        `operator: minimax` (a form `cfg.operator` explicitly supports) ruled as though a
        trusted moat brain had, and could publish on PASS. Audit finding #14.
        """
        return bool(self.tier_name) and is_provisional_provider(self.tier_name)

    def embed(self, text: str) -> list[float]:
        """Generate an embedding for the given text. Default returns empty list."""
        return []

    @property
    def model_version(self) -> str:
        return self.name

    @track_latency(name="operator_complete_json")
    def complete_json(self, system: str, user: str, *,
                      temperature: float = 0.7, retries: int = 2,
                      validate: Optional[Callable[[Any], Any]] = None,
                      coerce: Optional[Callable[[str], Any]] = None) -> Any:
        """Strict-JSON call with repair-retries. Raises ParseError only if all
        attempts fail (callers decide fail-safe behaviour, e.g. -> unverifiable).

        ``coerce`` (optional) runs when ``_extract_json`` fails — e.g. wrap bare
        markdown into a known JSON envelope for prose artifacts. It must raise
        ParseError/ValueError if the text cannot be coerced.
        """
        from .telemetry import logger
        logger.info(f"LLM completion started: {self.name}", extra={"retries_allowed": retries})
        
        last_err: Optional[Exception] = None
        sys = system + "\n\nReturn ONLY valid JSON. No prose, no code fences."
        for attempt in range(retries + 1):
            try:
                text = self._raw(sys, user, temperature)
                try:
                    data = _extract_json(text)
                except ParseError:
                    if coerce is None:
                        raise
                    data = coerce(text)
                
                # If we succeeded after a repair turn, record it as a self-correction
                if attempt > 0:
                    from .telemetry import record_usage
                    record_usage(provider=self.name, self_correction=True,
                                 message=f"LLM self-corrected on attempt {attempt}")
                
                return validate(data) if validate else data
            except (ParseError, json.JSONDecodeError, ValueError) as e:
                last_err = e
                logger.warning(f"LLM parse failure on attempt {attempt}: {e}", 
                               extra={"attempt": attempt, "error": str(e)})
                # repair turn: show the model its bad output and ask for valid JSON only
                user = (f"{user}\n\nYour previous reply was not valid JSON "
                        f"({e}). Return ONLY the corrected JSON value.")
                temperature = 0.0
        
        logger.error(f"LLM completion failed after {retries + 1} attempts", 
                     extra={"error": str(last_err), "model": self.name})
        raise ParseError(f"{self.name}: failed after {retries + 1} attempts: {last_err}")


class ClaudeOperator(Operator):
    """Anthropic API brain. Selectable once ANTHROPIC_API_KEY is present."""
    def __init__(self, model: str = "claude-opus-4-8", api_key: Optional[str] = None):
        from anthropic import Anthropic
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        self._client = Anthropic(api_key=key)
        self.model = model
        self.name = f"claude/{self.model}"

    @track_latency(name="claude_raw_call")
    def _raw(self, system: str, user: str, temperature: float) -> str:
        try:
            resp = self._client.messages.create(
                model=self.model, max_tokens=4096, temperature=temperature,
                system=system, messages=[{"role": "user", "content": user}],
            )
        except Exception as e:
            # This had NO try/except at all until 2026-08-10, the one gap `classify_exhaustion`
            # was built to close. "claude" is one of the two MOAT_PRIMARY names, so a raw
            # Anthropic SDK error (a genuine 402, a spent monthly allowance) propagated past
            # FallbackOperator's `hard = isinstance(e, ProviderExhaustedError)` check as an
            # ordinary failure -- never classified, never reaching `_health.mark_exhausted` --
            # so the one operator singled out as trusted got NONE of the persisted-dead-mark
            # protection every other adapter (MiniMax, DeepSeek, StandardCompute) gets here.
            # Net effect: a dead claude_cli key was retried fresh every tick instead of benched
            # for the documented 1h/60s. Same tested classifier as every other adapter, not an
            # ad-hoc substring test — see the marker list in errors.py.
            from .errors import ProviderExhaustedError, looks_exhausted
            if looks_exhausted(str(e)):
                raise ProviderExhaustedError(f"Claude API exhausted: {e}",
                                              provider=self.name) from e
            raise RuntimeError(f"Claude API call failed: {e}") from e
        # Track usage
        usage = resp.usage
        from .telemetry import record_usage
        record_usage(input_tokens=usage.input_tokens,
                     output_tokens=usage.output_tokens,
                     total_tokens=usage.input_tokens + usage.output_tokens,
                     provider=self.name)
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


class GeminiOperator(Operator):
    """DEPRECATED — replaced by AgyCliOperator. Google API brain via google-genai SDK.
    Kept for reference; not wired in the operator factory."""
    def __init__(self, model: str = "gemini-2.0-flash", api_key: Optional[str] = None):
        import warnings
        warnings.warn("GeminiOperator is DEPRECATED — use AgyCliOperator instead", DeprecationWarning, stacklevel=2)
        from google import genai
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY not set")
        self._client = genai.Client(api_key=key)
        self.model = model
        self.name = f"gemini/{self.model}"
        # Default embedding model for Stage 1 novelty selection
        self.embedding_model = "text-embedding-004"

    @track_latency(name="gemini_raw_call")
    def _raw(self, system: str, user: str, temperature: float) -> str:
        from google.genai import types
        resp = self._client.models.generate_content(
            model=self.model, contents=f"{system}\n\n{user}",
            config=types.GenerateContentConfig(temperature=temperature),
        )
        # Track usage
        usage = resp.usage_metadata
        if usage:
            from .telemetry import record_usage
            record_usage(input_tokens=usage.prompt_token_count or 0,
                         output_tokens=usage.candidates_token_count or 0,
                         total_tokens=usage.total_token_count or 0,
                         cached_tokens=usage.cached_content_token_count or 0,
                         provider=self.name)
        return resp.text or ""

    @track_latency(name="gemini_embed")
    def embed(self, text: str) -> list[float]:
        """Generate an embedding using text-embedding-004."""
        try:
            resp = self._client.models.embed_content(
                model=self.embedding_model,
                contents=text,
            )
            # Handle both single and batch response shapes
            embeddings = resp.embeddings
            if embeddings and hasattr(embeddings[0], "values"):
                return list(embeddings[0].values)
            return []
        except Exception as e:
            from .telemetry import logger
            logger.warning(f"Gemini embedding failed: {e}")
            return []


def _urlopen_read_bounded(req, *, timeout: float, total_deadline: float) -> bytes:
    """urlopen + full-body read bounded by a HARD total deadline.

    urllib's `timeout` is a PER-RECV socket timeout only: a server that trickles the response body
    resets it on every chunk, so `resp.read()` can block forever — this hung the daemon 34+ min on
    2026-07-01 (MiniMax TLS read wedged; per-recv 240s never fired). The body is read in a helper
    thread; if `total_deadline` is exceeded the socket is closed to break the wedged read so no
    thread or fd leaks, and TimeoutError propagates so the fallback chain moves to the next tier.
    """
    resp = urllib.request.urlopen(req, timeout=timeout)
    box: dict = {}

    def _read():
        try:
            box["data"] = resp.read()
        except BaseException as e:  # noqa: BLE001 — surfaced to the caller below
            box["err"] = e

    t = threading.Thread(target=_read, daemon=True)
    t.start()
    t.join(total_deadline)
    if t.is_alive():
        try:
            resp.close()  # break the wedged socket so the reader thread unblocks (no fd leak)
        except Exception:
            pass
        raise TimeoutError(f"response body read exceeded {total_deadline:.0f}s hard deadline")
    if "err" in box:
        raise box["err"]
    return box["data"]


def _read_sse_bounded(req, *, stall_timeout: float,
                      total_deadline: float) -> tuple[str, dict, str]:
    """Read an OpenAI-compatible SSE stream, bounded by a per-chunk STALL timeout and a hard total.

    Returns `(content, usage, finish_reason)`.

    WHY STREAM AT ALL — a socket timeout can only measure what the socket does
    ---------------------------------------------------------------------------
    On a NON-streamed completion the first byte arrives only once the model has finished, so
    time-to-first-byte IS the entire generation time. A per-recv timeout therefore cannot tell
    "reasoning hard" from "dead", and any value picked for it is simultaneously too short for the
    slow tail and too long for a corpse. Measured 2026-08-14 over the 406 MiniMax calls since
    12 Aug (`store/prospector.jsonl`, `operation=minimax_raw_call`):

        failures 116/406 = 28.6%     of which  23% landed at 239-246s (the 240s per-recv cap)
                                                9% landed at 246-310s (the 300s hard deadline)
        successes 290/406            60% under 60s — the provider was alive throughout

    i.e. roughly a third of the failures were a live provider cut off mid-answer, and the whole
    generation batch behind them was lost (`Generation chain EXHAUSTED`, 6 times in one tick).

    Streamed, the socket timeout measures SILENCE, which is the only thing that actually
    distinguishes slow from dead: tokens start flowing at ~1.3s (probed 2026-08-14) and continue,
    so `stall_timeout` fires only on a genuinely wedged connection while `total_deadline` stays
    the hard ceiling a trickled body cannot defeat — the same thread-and-close construction as
    `_urlopen_read_bounded` above, and for the same 46-hour reason.
    """
    resp = urllib.request.urlopen(req, timeout=stall_timeout)
    box: dict = {"parts": [], "usage": {}, "finish": ""}

    def _read():
        try:
            for raw_line in resp:  # per-recv timeout applies to EACH read, i.e. to each gap
                line = raw_line.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue  # SSE comments / keep-alives / blank frame separators
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue  # a partial frame is not a failed call
                if event.get("usage"):
                    box["usage"] = event["usage"]
                for choice in event.get("choices") or []:
                    piece = (choice.get("delta") or {}).get("content") or ""
                    if piece:
                        box["parts"].append(piece)
                    if choice.get("finish_reason"):
                        box["finish"] = choice["finish_reason"]
        except BaseException as e:  # noqa: BLE001 — surfaced to the caller below
            box["err"] = e
        finally:
            try:
                resp.close()
            except Exception:
                pass

    t = threading.Thread(target=_read, daemon=True)
    t.start()
    t.join(total_deadline)
    if t.is_alive():
        try:
            resp.close()  # break the wedged socket so the reader thread unblocks (no fd leak)
        except Exception:
            pass
        raise TimeoutError(f"streamed response exceeded {total_deadline:.0f}s hard deadline")
    if "err" in box:
        raise box["err"]
    return "".join(box["parts"]), box["usage"], box["finish"]


class _MiniMaxTruncated(RuntimeError):
    """M3 spent its whole token budget inside <think> and never emitted the answer.

    A distinct type rather than a message match, because the two callers want opposite
    things: `_raw` re-asks (the reasoning length is non-deterministic on an identical
    prompt), while everything above it must see a plain RuntimeError so the chain fails over
    normally once the re-asks are spent. It is deliberately NOT a ProviderExhaustedError —
    nothing is exhausted, the model simply talked too long.
    """


class MiniMaxOperator(Operator):
    """MiniMax OpenAI-compatible API brain.

    MiniMax is ~50× cheaper than Claude for input tokens ($0.30 vs $15/M).
    Routed to: generation, marketing content, artifact prompts, scoring.

    DEFAULT BAN — MUST NOT run the moat (kill-check verdicts or adversarial analysis)
    unless cleared per specs/offline-moat-validation.md §5:
      1. discrimination == 1.0 on golden set (promotion gate, fixtures-pinned retrieval)
      2. K=3 consecutive clean runs
      3. Clearance record written to store/golden_runs/
    The clearance record is the documented exception to this default ban.
    See: store/golden_runs/ for any active clearance records.

    Uses urllib directly (no extra dependencies). OpenAI-compatible endpoint.
    Correct base URL: https://api.minimax.io/v1 (confirmed from MiniMax platform docs).
    """

    # ---- Rate rails (added 2026-08-09 after a measured 429 storm) -------------------------
    #
    # THE INCIDENT: the first run that routed pack PROSE to MiniMax (artifact_operator gained
    # a minimax tier that night) produced 281 `HTTP Error 429: Too Many Requests` and zero
    # sellable packs. MiniMax was not the weak link — the same run logged a 34,200-char
    # ops_plan and a 29,888-char gtm_plan, both coherent. It was pure request pressure:
    # generate_artifacts and generate_marketing_content each fan out 4 concurrent calls
    # (artifacts.py:438/634/815) at max_tokens 32768, and when the resulting empties failed
    # validate_pack the driver retried the WHOLE pack 3x — so the flakiness budget fed the
    # thing causing the flakiness. 29 packs of that is the 281.
    #
    # Two rails, because either alone leaves the hole open:
    #   * a process-wide SEMAPHORE, since the burst is CONCURRENT, not sequential — a
    #     per-call sleep cannot bound 8 simultaneous requests; and
    #   * bounded BACKOFF on 429 specifically, because `classify_exhaustion` already grades
    #     429 as TRANSIENT backpressure while `complete_json`'s retry loop (:145) catches only
    #     ParseError/JSONDecodeError/ValueError. A transient signal was reaching a caller that
    #     had no path to wait it out, so it read as a hard failure.
    # Only after the backoff is spent does it raise ProviderExhaustedError, which is the
    # honest verdict at that point: we asked, we waited, it is still saying no.
    _throttle = threading.Semaphore(int(os.environ.get("PROSPECTOR_MINIMAX_CONCURRENCY", "3")))
    _RETRY_429_MAX = int(os.environ.get("PROSPECTOR_MINIMAX_429_RETRIES", "4"))
    _RETRY_429_BASE_S = float(os.environ.get("PROSPECTOR_MINIMAX_429_BACKOFF_S", "5"))

    # The transport is STREAMED (see `_read_sse_bounded`), so these two measure different things
    # and neither is the old 240s compromise between them:
    #   _STALL_TIMEOUT_S  — silence on an open stream. Probed 2026-08-14: first token at 1.31s and
    #                       a steady flow after, so 90s of nothing is a wedged socket, not thinking.
    #   _TOTAL_DEADLINE_S — the hard ceiling. A call only reaches it while ACTIVELY emitting
    #                       tokens, which is a live call; the old 300s cut live calls off at their
    #                       longest (measured: 23% of failures sat exactly at the per-recv cap).
    _STALL_TIMEOUT_S = float(os.environ.get("PROSPECTOR_MINIMAX_STALL_S", "90"))
    _TOTAL_DEADLINE_S = float(os.environ.get("PROSPECTOR_MINIMAX_DEADLINE_S", "600"))
    _RETRY_TRUNCATED_MAX = int(os.environ.get("PROSPECTOR_MINIMAX_TRUNCATION_RETRIES", "2"))

    # MiniMax API endpoint (OpenAI-compatible /v1/chat/completions).
    # The flagship reasoning model and the stable non-reasoning option for
    # structured JSON tasks are configured in `config.yaml` under
    # `model_defaults.minimax` and `model_defaults.minimax_fast`. The
    # factory passes them as `default_model` / `fast_model` arguments. This
    # is the *only* way to override the model — no hardcoded strings remain.
    _BASE_URL = "https://api.minimax.io/v1"

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None,
                 cheap: bool = False,
                 default_model: Optional[str] = None,
                 fast_model: Optional[str] = None):
        key = api_key or os.environ.get("MINIMAX_API_KEY")
        if not key:
            raise RuntimeError("MINIMAX_API_KEY not set")
        self._key = key
        # cheap=True uses the cheap/structured model; otherwise the full
        # reasoning model. An explicit `model` argument (from cfg.model)
        # overrides the cheap/non-cheap split — caller is being explicit.
        # All three sources are config-driven (see model-config audit ticket):
        # no hardcoded identifiers remain in this class.
        full_default = default_model or "MiniMax-M3"
        cheap_default = fast_model or "MiniMax-M2.7"
        self.model = (model
                      or (cheap_default if cheap else None)
                      or full_default)
        self.name = f"minimax/{self.model}"

    @property
    def model_version(self) -> str:
        return self.name

    @track_latency(name="minimax_raw_call")
    def _raw(self, system: str, user: str, temperature: float) -> str:
        """Call the endpoint, re-asking when M3 spends the whole budget thinking.

        A truncation is not a verdict about the request — it is a coin landing badly. The
        model's reasoning length is non-deterministic on an identical prompt: measured
        2026-08-14 on the retitle of the live shelf, the SAME 14 packs truncated at pack 2 on
        one run and at pack 5 on the next, and the packs that failed the first time succeeded
        the second. So the honest response to `finish_reason=length` is to ask again.

        Two attempts, not more. The retry is expensive (a full 32k-token budget burned to
        produce nothing) and this rail exists to keep a non-deterministic hiccup from stopping
        the line, not to grind a genuinely over-long prompt: three failures in a row is a
        prompt problem, and the exception then reaches the chain so the next tier can answer.
        """
        last: Optional[Exception] = None
        for attempt in range(self._RETRY_TRUNCATED_MAX + 1):
            try:
                return self._raw_once(system, user, temperature)
            except _MiniMaxTruncated as e:
                last = e
                from .telemetry import logger as _log
                _log.warning(
                    f"MiniMax spent its whole budget reasoning and returned no answer; "
                    f"re-asking (attempt {attempt + 1}/{self._RETRY_TRUNCATED_MAX})",
                    extra={"provider": self.name})
        raise RuntimeError(str(last))

    def _raw_once(self, system: str, user: str, temperature: float) -> str:
        """Call MiniMax OpenAI-compatible /v1/chat/completions endpoint."""
        import urllib.request

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # This is REQUIRED headroom, not generosity: M3 emits its reasoning in <think>…</think>
            # BEFORE the JSON, and generation reasoning ran 16k–28k tokens (measured 2026-07-02). A
            # cap of 16000 truncated the response mid-<think> — 0 JSON, 0 candidates, and the
            # claude_cli backstop can't catch it (a truncated body is an HTTP success that fails
            # PARSING, which retries MiniMax rather than failing over).
            #
            # RAISED 32768 → 65536 on 2026-08-14. The 2026-07-02 measurement went stale: M3's think
            # length grew until the cap itself became the failure. Median MiniMax response measured
            # 4,181 chars on 08-13 (n=177) and 47,602 chars on 08-14 (n=360), and a truncated call
            # that day burned ~34k think-tokens against the 32768 ceiling — i.e. the ceiling WAS the
            # truncation. That mattered more than usual because commit d704595 had just taken
            # claude_cli off the non-critical chain (founder: "claude should never be used for
            # non-critical") and standardcompute's free trial expired the same day, leaving MiniMax
            # alone on generation with nothing to fail over to: 231 `Generation chain EXHAUSTED`
            # lines and 22 consecutive ticks recording dossiers=0.
            #
            # 40960 and 65536 were both probed live against api.minimax.io on 2026-08-14 and
            # returned finish_reason=stop, so the ceiling is ours to set, not the endpoint's. This
            # raises the cost of a RUNAWAY call, not of a normal one — max_tokens bills what is
            # emitted, and a truncated call today bills its full budget for an unusable body.
            # Env-overridable so it can be walked back without a deploy.
            "max_tokens": int(os.environ.get("PROSPECTOR_MINIMAX_MAX_TOKENS", "65536")),
            # STREAMED so the socket timeout measures silence rather than total generation time
            # (`_read_sse_bounded` carries the measurement). `include_usage` is not optional: an
            # OpenAI-compatible stream omits the usage block entirely without it, and every
            # MiniMax call would then record 0 tokens into the spend ledger.
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self._BASE_URL}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._key}",
            },
            method="POST",
        )
        from .errors import ProviderExhaustedError, looks_exhausted
        from .telemetry import logger as _log

        content, usage, finish = "", {}, ""
        for attempt in range(self._RETRY_429_MAX + 1):
            try:
                # MiniMax M3 completions routinely take 75-115s (measured 2026-07-01: 75.7s and
                # 113.4s succeeded; calls cut at the old 120s cap failed with "read operation
                # timed out", zeroing whole generation batches when it was the only live brain).
                # Raising that cap to 240s did not fix it — it only moved the cliff: 2026-08-14
                # measured 28.6% of calls failing, a third of them exactly AT the cap. A duration
                # bound cannot grade a non-streamed call, so the transport streams and the two
                # bounds now measure what they are named for (see `_read_sse_bounded`).
                #
                # The semaphore is held only around the REQUEST, never around the backoff sleep:
                # a waiter that keeps its slot while sleeping converts backpressure into a
                # deadlock of the whole pool, which is the failure this rail exists to prevent.
                with self._throttle:
                    content, usage, finish = _read_sse_bounded(
                        req, stall_timeout=self._STALL_TIMEOUT_S,
                        total_deadline=self._TOTAL_DEADLINE_S)
                break
            except Exception as e:
                msg = str(e)
                # 429 is TRANSIENT backpressure (errors.classify_exhaustion), so it earns a
                # wait, not a verdict. Matched on a word boundary, never as a bare substring —
                # a request id or a byte count containing "429" once benched a live brain
                # (memory: substring-http-codes-bench-a-live-brain).
                if re.search(r"\b429\b", msg) and attempt < self._RETRY_429_MAX:
                    delay = self._RETRY_429_BASE_S * (2 ** attempt)
                    _log.warning(
                        f"MiniMax 429 backpressure; retrying in {delay:.0f}s "
                        f"(attempt {attempt + 1}/{self._RETRY_429_MAX})",
                        extra={"provider": self.name, "delay_s": delay})
                    time.sleep(delay)
                    continue
                # Shared classifier — same reasoning as the DeepSeek adapter above.
                if looks_exhausted(msg):
                    raise ProviderExhaustedError(f"MiniMax quota exhausted: {e}",
                                                 provider=self.name)
                raise RuntimeError(f"MiniMax call failed: {e}") from e

        # Track token usage (OpenAI-compatible usage block, delivered as the stream's last event)
        usage = usage or {}
        inp = int(usage.get("prompt_tokens", 0) or 0)
        out = int(usage.get("completion_tokens", 0) or 0)
        total = int(usage.get("total_tokens", 0) or 0)
        from .telemetry import logger, record_usage
        record_usage(input_tokens=inp, output_tokens=out, total_tokens=total,
                     cached_tokens=0, web=False, provider=self.name)

        # A response cut off at max_tokens is an HTTP SUCCESS carrying an unusable body: M3 spends
        # its budget inside <think>…</think> and a `length` finish means the JSON never came.
        # Measured 2026-08-14, one generation call: 142,992 chars that ended `</think>\n\n`, and
        # all the caller could say was "no valid JSON found" — which retries MiniMax (the same
        # over-long prompt, the same outcome) instead of failing over to a brain that could
        # answer. Naming the truncation converts a silent 3-attempt burn into one clean failover.
        if finish == "length" and not _RE_THINK.sub("", content).strip():
            raise _MiniMaxTruncated(
                f"MiniMax call failed: response truncated at max_tokens — {len(content)} chars of "
                f"reasoning and no answer (finish_reason=length)")
        logger.info(f"MiniMax response: length={len(content)}, start={content[:200]!r}, end={content[-200:]!r}")
        return content


class DeepSeekOperator(Operator):
    """DeepSeek OpenAI-compatible API brain.

    DeepSeek-chat is $0.27/M input / $1.10/M output — cheapest in-class for
    structured JSON generation.  Ideal for prescreen, scoring, classification,
    and marketing content.

    CLEARED FOR MOAT (KILL-CHECK VERDICTS + ADVERSARIAL):
      - Promotion gate: 5/5 discrimination × 3 consecutive runs (2026-06-15)
      - Audit trail: store/golden_runs/deepseek_20260615T190218971918.json (and 2 more)
      - Golden set: 5 KILL cases (value_durability/distribution/payer_solvency gates)
      - Clearance scope: six-check kill-filter + adversarial pass

    NOTE: deepseek's scoring model is conservative on consumer/generalist SaaS.
    PASS cases may incorrectly receive KILL verdicts from scoring. Use with care
    for borderline ideas; the six-check gate is the authoritative filter.

    See: specs/offline-moat-validation.md §5 for the promotion protocol.

    Uses urllib directly (no extra dependencies). OpenAI-compatible endpoint.
    See: https://api-docs.deepseek.com/
    """

    _BASE_URL = "https://api.deepseek.com/v1"

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None,
                 default_model: Optional[str] = None):
        key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            raise RuntimeError("DEEPSEEK_API_KEY not set")
        self._key = key
        # `default_model` comes from cfg.model_defaults.deepseek. An explicit
        # `model` (from cfg.model) overrides it. No hardcoded identifiers in
        # this class — see model-config audit ticket.
        self.model = model or default_model or "deepseek-chat"
        self.name = f"deepseek/{self.model}"

    @property
    def model_version(self) -> str:
        return self.name

    @track_latency(name="deepseek_raw_call")
    def _raw(self, system: str, user: str, temperature: float) -> str:
        """Call DeepSeek OpenAI-compatible /v1/chat/completions endpoint."""
        import urllib.request

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": 8192,
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self._BASE_URL}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._key}",
            },
            method="POST",
        )
        try:
            # Bounded read, not a bare per-recv timeout — see the note at the StandardCompute
            # call site for the 46-hour daemon wedge this shape produced on 2026-08-11.
            raw = _urlopen_read_bounded(req, timeout=120, total_deadline=180)
            data = json.loads(raw.decode("utf-8"))
        except Exception as e:
            # looks_exhausted, not an ad-hoc substring test. The hand-rolled
            # `"quota" in e or "limit" in e` that stood here missed "HTTP Error 402: Payment
            # Required" — see the marker list in errors.py for what that cost — and matched a
            # bare "limit" (e.g. a context-length error), hard-tripping a healthy brain for a
            # per-call mistake. One tested classifier, used by every metered adapter.
            from .errors import ProviderExhaustedError, looks_exhausted
            if looks_exhausted(str(e)):
                raise ProviderExhaustedError(f"DeepSeek quota exhausted: {e}",
                                              provider=self.name)
            raise RuntimeError(f"DeepSeek call failed: {e}") from e

        # Track token usage
        usage = data.get("usage") or {}
        inp = int(usage.get("prompt_tokens", 0) or 0)
        out = int(usage.get("completion_tokens", 0) or 0)
        total = int(usage.get("total_tokens", 0) or 0)
        from .telemetry import logger, record_usage
        record_usage(input_tokens=inp, output_tokens=out, total_tokens=total,
                     cached_tokens=0, web=False, provider=self.name)

        content = (data.get("choices", [{}])[0].get("message", {})
                   .get("content", "") or "")
        logger.info(f"DeepSeek response: length={len(content)}")
        return content


class StandardComputeOperator(Operator):
    """StandardCompute OpenAI-compatible API brain.

    Wire format verified live 2026-08-08 against https://api.stdcmpt.com/v1:
      - POST /v1/chat/completions  -> 200, OpenAI `choices[0].message.content` shape
      - POST /v1/messages          -> 404 {"detail":"Not Found"}   (NOT Anthropic-shaped)
      - GET  /v1/models            -> 200, one model, id "StandardCompute"
      - Auth is `Authorization: Bearer <key>`; `x-api-key` is not accepted.
    So this is an OpenAI-compatible adapter, never an Anthropic one. Pointing the
    Anthropic SDK (or ANTHROPIC_BASE_URL) at this host posts to a path that 404s.

    NOT CLEARED FOR MOAT. `MOAT_PRIMARY` does not contain "standardcompute", so
    everything this brain rules is stamped `provisional` and blocked from publishing
    (run.py:528). Promotion requires the golden-set gate recorded in config.yaml:50-52.

    Uses urllib directly (no extra dependencies), matching DeepSeekOperator above.
    """

    _BASE_URL = "https://api.stdcmpt.com/v1"
    _USER_AGENT = "prospector/1.0"
    # Upper bound on a body that may be read as an out-of-allowance notice rather than a
    # completion (see the end of `_raw`). Measured notice: 197 chars.
    _OUT_OF_CREDIT_MAX_CHARS = 1000

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None,
                 default_model: Optional[str] = None, base_url: Optional[str] = None,
                 cfg=None):
        key = api_key or os.environ.get("STANDARDCOMPUTE_API_KEY")
        if not key:
            raise RuntimeError("STANDARDCOMPUTE_API_KEY not set")
        self._key = key
        # `default_model` comes from cfg.model_defaults.standardcompute. An explicit
        # `model` (from cfg.model) overrides it. No hardcoded identifier is the
        # source of truth here — see the model-config audit ticket.
        self.model = model or default_model or "standardcompute"
        self.base_url = (base_url or os.environ.get("STANDARDCOMPUTE_BASE_URL")
                         or self._BASE_URL).rstrip("/")
        self.name = f"standardcompute/{self.model}"
        # Threaded into every record_usage() call below (audit HIGH finding 4) so that
        # once a real rate is entered under config.yaml's pricing.standardcompute block,
        # get_price() can actually see it. `cfg.pricing.standardcompute` currently
        # defaults to None (config.py) because no rate is publicly known — see the class
        # docstring; that stays a loud $0 (record_usage's `priced` warning), not a
        # fabricated number.
        self._cfg = cfg

    @property
    def model_version(self) -> str:
        return self.name

    @track_latency(name="standardcompute_raw_call")
    def _raw(self, system: str, user: str, temperature: float) -> str:
        """Call the StandardCompute OpenAI-compatible /v1/chat/completions endpoint."""
        import urllib.error
        import urllib.request

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": 8192,
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._key}",
                # REQUIRED, and it does not look required. This host sits behind
                # Cloudflare, which bot-blocks urllib's default signature: measured
                # 2026-08-08, identical request, UA "Python-urllib/3.14" -> 403
                # "error code: 1010", UA "prospector/1.0" -> 200. A 403 reads as a bad
                # key, so without this line the next diagnosis goes hunting for a
                # credential problem that does not exist.
                "User-Agent": self._USER_AGENT,
            },
            method="POST",
        )
        try:
            # HARD total deadline, not a bare per-recv timeout. `urlopen(timeout=300)` bounds each
            # individual socket recv; a server that trickles the body resets it on every chunk and
            # `resp.read()` blocks forever. That is not theoretical here: this adapter sits in BOTH
            # the verdict chain and the non-critical chain (`config.yaml:53` and `:76`), and on
            # 2026-08-11 the daemon logged `LLM completion started: fallback(claude_cli+
            # standardcompute+minimax)` at 08:05:25 and then emitted NOTHING for 46 hours, until
            # `Failed minimax_raw_call` at 2026-08-13T06:12:02. Two days of a live storefront's
            # supply, spent inside one `read()` that no timeout could reach.
            #
            # `_urlopen_read_bounded` (operator.py:277) was written for precisely this in July and
            # applied to MiniMax alone; every other metered adapter kept the bare call. One helper,
            # every call site — a bound that protects one provider protects nothing, because the
            # chain hangs on whichever member was left bare.
            raw = _urlopen_read_bounded(req, timeout=300, total_deadline=360)
            data = json.loads(raw.decode("utf-8"))
        except Exception as e:
            # The classifier needs the RESPONSE BODY, not just str(e). urllib renders an
            # HTTPError as "HTTP Error 402: Payment Required" and drops the JSON body, which
            # is the only place a provider spells out *which* allowance ran out. This
            # provider's exhaustion wording is unknown to us, so `_ALLOWANCE_LIMIT_RE`
            # (errors.py:112) gets the body too — a failure the classifier misses is retried
            # forever and never leaves a dead mark.
            detail = ""
            if isinstance(e, urllib.error.HTTPError):
                try:
                    detail = (e.read() or b"").decode("utf-8", "replace")[:600]
                except Exception:
                    detail = ""
            probe = f"{e} {detail}".strip()
            from .errors import ProviderExhaustedError, looks_exhausted
            if looks_exhausted(probe):
                raise ProviderExhaustedError(
                    f"StandardCompute quota exhausted: {probe}", provider=self.name)
            raise RuntimeError(f"StandardCompute call failed: {probe}") from e

        # Track token usage. The live probe returned prompt/completion/total plus a
        # prompt_tokens_details.cached_tokens field; feed the cached count through so the
        # ledger does not read a cache hit as fresh input.
        usage = data.get("usage") or {}
        inp = int(usage.get("prompt_tokens", 0) or 0)
        out = int(usage.get("completion_tokens", 0) or 0)
        total = int(usage.get("total_tokens", 0) or 0)
        cached = int(((usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)) or 0)
        from .telemetry import logger, record_usage
        record_usage(input_tokens=inp, output_tokens=out, total_tokens=total,
                     cached_tokens=cached, web=False, provider=self.name, cfg=self._cfg)

        content = (data.get("choices", [{}])[0].get("message", {})
                   .get("content", "") or "")
        logger.info(f"StandardCompute response: length={len(content)}")

        # A spent allowance arrives here as HTTP 200 with the upsell AS the completion, so the
        # except-branch above never sees it. Measured 2026-08-09: every layer upstairs read that
        # as a SUCCESSFUL call — FallbackOperator ran `record_success()` and `_health.clear()`,
        # which is why store/provider_health_noncritical.json was `{}` and no dead mark could
        # ever exist; the chain therefore never advanced to claude_cli, and `complete_json`
        # simply re-asked the same dead brain three times and raised ParseError. Thirteen
        # consecutive generation ticks produced nothing while the moat's own claude_cli was
        # answering verdicts normally. Raising is the whole difference between an outage and a
        # failover.
        #
        # The length bound is the false-positive guard: this notice is a short canned body
        # (197 chars measured), whereas a real completion that merely discusses a spent
        # allowance is long and structured. Both conditions must hold.
        from .errors import ProviderExhaustedError, looks_exhausted
        if len(content) <= self._OUT_OF_CREDIT_MAX_CHARS and looks_exhausted(content):
            raise ProviderExhaustedError(
                f"StandardCompute returned an out-of-allowance notice instead of a "
                f"completion: {content[:200]}", provider=self.name)
        return content



class OpenRouterOperator(Operator):
    """Intelligent multi-model OpenRouter operator with self-healing rotation.

    Design principles:
    - WARMUP: probes all models on first call to establish baseline latency/quality.
      Models that fail the probe (timeout, 429, empty content) are marked dead and
      skipped for the cooldown period. The warmup uses a tiny request (max_tokens=10)
      so it completes in seconds even for slow models.
    - PRIORITY ROTATION: models are sorted by a health score each call:
        score = (successes / total) * 100  -  median_latency_s  -  failures * 5
      Higher score = higher priority. Fast, reliable models bubble up.
    - FAST ROTATION: per-model timeout of 20s — a slow/hanging model fails fast and
      the next model is tried. A full rotation across 6 models costs at most ~2 min
      vs 10+ minutes a single 120s timeout would block.
    - RATE-LIMIT RESPECT: 429 errors respect the Retry-After header; the model is
      marked exhausted for that duration in health.py (cross-run persistence).
    - EMPTY CONTENT TRACKING: models returning zero content (finish_reason=length with
      empty string) are soft failures — they don't hard-trip the breaker but reduce score.
    - HEALTH INTEGRATION: consistently failing models get persisted dead marks so
      subsequent runs skip them from call #1 without re-probing.

    MUST NOT be used for kill-gate verdicts or adversarial analysis (the moat).
    """

    # The priority-ordered model list comes from cfg.model_defaults.openrouter.
    # The factory passes it as `default_models`; an explicit `models` argument
    # (from cfg.model, joined as a list if needed) overrides it. No hardcoded
    # list of model strings remains in this class.
    _BASE_URL = "https://openrouter.ai/api/v1"
    _MODEL_TIMEOUT_S = 20.0   # fail fast, rotate fast

    def __init__(self, models: Optional[list[str]] = None,
                 api_key: Optional[str] = None,
                 failure_threshold: int = 3,
                 cooldown_s: float = 300.0,
                 default_models: Optional[list[str]] = None):
        key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY not set")
        self._key = key
        # Fallback to the historical default if neither explicit nor config
        # is provided (lets MockOperator-style tests construct without cfg).
        _FALLBACK = [
            "google/gemma-4-31b-it:free",
            "google/gemma-4-26b-a4b-it:free",
            "qwen/qwen3-coder:free",
            "qwen/qwen3-next-80b-a3b-instruct:free",
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            "openrouter/free",
        ]
        self._models = models or list(default_models) if default_models else (models or _FALLBACK)
        self._failure_threshold = failure_threshold
        self._cooldown_s = cooldown_s
        self._health = None   # lazily imported
        self._lock = threading.Lock()
        # Per-model circuit breakers.
        self._breakers: dict[str, CircuitBreaker] = {
            m: CircuitBreaker(f"openrouter/{m}", failure_threshold=failure_threshold,
                               cooldown_s=cooldown_s, clock=time.monotonic)
            for m in self._models
        }
        # Per-model health record: successes, failures, latencies, etc.
        self._h: dict[str, dict] = {
            m: dict(successes=0, failures=0, empties=0, r429s=0,
                     latencies=[], _sorted=False)
            for m in self._models
        }
        self._warmed_up = False
        self.name = "openrouter/smart"

    @property
    def available_models(self) -> list[str]:
        """Current models sorted by health score (best first). Thread-safe snapshot."""
        with self._lock:
            return self._sorted_models()

    # ── warmup ─────────────────────────────────────────────────────────────────

    def _ensure_warmed_up(self) -> None:
        """Lazily probe the first model. Thread-safe — only first caller does work.

        Sequential probe (not concurrent) to avoid exhausting rate limits across the
        whole pool before the real work even starts. Probes one model with a tiny
        request; if it succeeds, records it and skips warmup for the rest (they
        inherit from runtime). If it fails, tries the next. Skips all if the first
        succeeds — a single working model is enough to confirm the operator is alive.
        """
        if self._warmed_up:
            return
        with self._lock:
            if self._warmed_up:
                return
            self._warmed_up = True
        # Sequential probe: one model at a time, use immediately on success.
        from .telemetry import logger
        for model in self._models:
            if self._health and self._health.is_dead(f"openrouter/{model}"):
                continue
            t0 = time.monotonic()
            body = json.dumps({
                "model": model,
                "messages": [{"role": "user", "content": "Reply with one word: ok."}],
                "max_tokens": 5,
                "temperature": 0.1,
            }).encode("utf-8")
            req = urllib.request.Request(
                self._BASE_URL, data=body,
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {self._key}"},
                method="POST")
            try:
                # Bounded read. The warm-up probe exists to fail a slow model FAST (see the
                # class docstring's "FAST ROTATION"); a bare per-recv timeout cannot deliver
                # that against a trickled body, which is the one failure it most needs to catch.
                raw = _urlopen_read_bounded(
                    req, timeout=self._MODEL_TIMEOUT_S,
                    total_deadline=self._MODEL_TIMEOUT_S * 1.5).decode("utf-8")
                latency = time.monotonic() - t0
                if raw.strip():
                    self._h[model]["successes"] = 1
                    self._h[model]["latencies"] = [latency]
                    self._h[model]["_sorted"] = False
                    logger.info(f"OpenRouter warmup ok: {model} ({latency:.1f}s)")
                    # Brief pause to let any CF challenge clear before real work starts.
                    time.sleep(2.0)
                    return  # one working model is enough
                else:
                    self._h[model]["empties"] += 1
                    self._h[model]["failures"] += 1
            except Exception:
                self._h[model]["failures"] += 1
        logger.warning("OpenRouter warmup: all models failed probe, using defaults")

    # ── priority rotation ─────────────────────────────────────────────────────

    def _sorted_models(self) -> list[str]:
        """Return models sorted by health score (best first). Cached until state changes."""
        scored = []
        for model, h in self._h.items():
            total = h["successes"] + h["failures"] + h["empties"]
            if total == 0:
                score = 50.0   # untested — middle ground
            else:
                rate = h["successes"] / total
                lats = h["latencies"]
                median_lat = sorted(lats)[len(lats)//2] if lats else 5.0
                # Higher rate, lower latency, fewer failures = higher score
                score = rate * 100 - median_lat - h["failures"] * 5 - h["r429s"] * 3
            scored.append((score, model))
        scored.sort(key=lambda x: -x[0])
        result = [model for _, model in scored]
        for m in self._h:
            self._h[m]["_sorted"] = True
        return result

    def _model(self) -> str:
        """Return the best available model (highest health score, breaker allows it)."""
        sorted_models = self._sorted_models()
        if self._health is None:
            from .health import get_health
            self._health = get_health()
        for model in sorted_models:
            if self._breakers[model].allow():
                if self._health.is_dead(f"openrouter/{model}"):
                    continue
                return model
        return sorted_models[0]

    def _mark(self, model: str, *, ok: bool = False, empty: bool = False,
              hard: bool = False) -> None:
        """Record a call result; invalidate sort cache."""
        h = self._h[model]
        h["_sorted"] = False
        if ok and not empty:
            h["successes"] += 1
        elif empty:
            h["empties"] += 1
            h["failures"] += 1
        else:
            h["failures"] += 1
            if hard:
                h["r429s"] += 1
        if h["failures"] >= self._failure_threshold:
            if self._health is None:
                from .health import get_health
                self._health = get_health()
            self._health.mark_exhausted(f"openrouter/{model}", self._cooldown_s)

    # ── core _raw ─────────────────────────────────────────────────────────────

    @track_latency(name="openrouter_raw_call")
    def _raw(self, system: str, user: str, temperature: float) -> str:
        from .errors import ProviderExhaustedError
        from .telemetry import logger

        self._ensure_warmed_up()

        if self._health is None:
            from .health import get_health
            self._health = get_health()

        last_err: Optional[Exception] = None

        for _ in range(len(self._models)):
            model = self._model()

            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": temperature,
                "max_tokens": 8192,
            }
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self._BASE_URL, data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._key}",
                    "HTTP-Referer": "https://prospector.local",
                    "X-Title": "Prospector",
                },
                method="POST",
            )
            t0 = time.monotonic()
            try:
                # Bounded read — same reason as the warm-up probe above.
                raw = _urlopen_read_bounded(
                    req, timeout=self._MODEL_TIMEOUT_S,
                    total_deadline=self._MODEL_TIMEOUT_S * 1.5).decode("utf-8")
                latency = time.monotonic() - t0
                if not raw.strip():
                    self._breakers[model].record_failure()
                    self._mark(model, empty=True)
                    logger.warning(f"OpenRouter {model} empty ({latency:.1f}s), rotating")
                    last_err = RuntimeError("empty response")
                    continue
                # Guard against Cloudflare bot pages (200 but HTML body) before JSON parse.
                if raw.lstrip()[:1] not in ('{', '['):
                    self._breakers[model].record_failure()
                    self._mark(model)
                    logger.warning(f"OpenRouter {model} non-JSON response ({latency:.1f}s, starts={raw[:50]!r}), rotating")
                    last_err = RuntimeError(f"non-JSON response: {raw[:100]}")
                    continue
                data = json.loads(raw)
                content = (data.get("choices", [{}])[0].get("message", {})
                           .get("content") or "")
                
                # Track usage
                usage = data.get("usage") or {}
                inp = int(usage.get("prompt_tokens", 0) or 0)
                out = int(usage.get("completion_tokens", 0) or 0)
                total = int(usage.get("total_tokens", 0) or 0)
                from .telemetry import record_usage
                record_usage(input_tokens=inp, output_tokens=out, total_tokens=total,
                             provider=f"openrouter/{model}")
                
                self._breakers[model].record_success()
                self._mark(model, ok=True)
                logger.info(f"OpenRouter {model} ok ({latency:.1f}s): {len(content)} chars")
                return content
            except urllib.error.HTTPError as e:
                elapsed = time.monotonic() - t0
                if e.code == 429:
                    retry_after = 60.0
                    try:
                        retry_after = float(e.headers.get("Retry-After", 60.0))
                    except (ValueError, TypeError):
                        pass
                    self._breakers[model].record_failure(hard=True)
                    self._mark(model, hard=True)
                    self._health.mark_exhausted(f"openrouter/{model}", retry_after)
                    last_err = ProviderExhaustedError(
                        f"openrouter/{model} 429; retry in {retry_after:.0f}s",
                        provider=f"openrouter/{model}")
                    logger.warning(f"OpenRouter 429 on {model} ({elapsed:.1f}s), rotating")
                    continue
                else:
                    self._breakers[model].record_failure()
                    self._mark(model)
                    last_err = RuntimeError(f"HTTP {e.code}: {e.reason}")
                    logger.warning(f"OpenRouter {model} HTTP {e.code} ({elapsed:.1f}s), rotating")
                    continue
            except Exception as e:
                elapsed = time.monotonic() - t0
                self._breakers[model].record_failure()
                self._mark(model)
                last_err = e
                logger.warning(f"OpenRouter {model} {type(e).__name__} ({elapsed:.1f}s), rotating")
                continue

        raise ProviderExhaustedError(
            f"All OpenRouter models exhausted: {last_err}",
            provider="openrouter")



class OllamaOperator(Operator):
    """Ollama local-operator brain for non-verification tasks.

    Fully local, zero token cost. OpenAI-compatible /v1/chat/completions endpoint.
    Default base URL: http://localhost:11434/v1. Override via OLLAMA_BASE_URL env var.
    Routed to non-verification tasks only: generation, prescreen, scoring.
    MUST NOT be used for kill-check verdicts or adversarial analysis (the moat).
    """
    _BASE_URL = "http://localhost:11434/v1"

    def __init__(self, model: Optional[str] = None, base_url: Optional[str] = None,
                 default_model: Optional[str] = None):
        # `default_model` comes from cfg.model_defaults.ollama. An explicit
        # `model` (from cfg.model) overrides it.
        self.model = model or default_model or "qwen2.5-coder:7b"
        self.base_url = (base_url or os.environ.get("OLLAMA_BASE_URL")
                         or self._BASE_URL)
        self.name = f"ollama/{self.model}"

    @property
    def model_version(self) -> str:
        return self.name

    @track_latency(name="ollama_raw_call")
    def _raw(self, system: str, user: str, temperature: float) -> str:
        """Call Ollama OpenAI-compatible /v1/chat/completions endpoint."""
        import urllib.request

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": 8192,
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            # Bounded read — a local Ollama that stalls mid-stream wedges the caller exactly the
            # same way a remote one does; see the StandardCompute call site for the incident.
            raw = _urlopen_read_bounded(req, timeout=300, total_deadline=360)
            data = json.loads(raw.decode("utf-8"))
        except Exception as e:
            from .errors import ProviderExhaustedError
            if "connection refused" in str(e).lower() or "connection" in str(e).lower():
                raise ProviderExhaustedError(f"Ollama not running or unreachable: {e}",
                                              provider=self.name)
            raise RuntimeError(f"Ollama call failed: {e}") from e

        content = (data.get("choices", [{}])[0].get("message", {})
                   .get("content", "") or "")
        from .telemetry import logger, record_usage
        # Track usage
        usage = data.get("usage") or {}
        inp = int(usage.get("prompt_tokens", 0) or 0)
        out = int(usage.get("completion_tokens", 0) or 0)
        total = int(usage.get("total_tokens", 0) or 0)
        record_usage(input_tokens=inp, output_tokens=out, total_tokens=total,
                     provider=self.name)
        
        logger.info(f"Ollama response: length={len(content)}")
        return content


class MockOperator(Operator):
    """Deterministic stub. Routes by a marker in the system prompt to fixture
    responses, so the full pipeline is testable with zero network/spend."""
    def __init__(self, responses: Optional[dict[str, Any]] = None,
                 router: Optional[Callable[[str, str], Any]] = None):
        self.responses = responses or {}
        self.router = router
        self.name = "mock"
        self.calls: list[tuple[str, str]] = []

    def _raw(self, system: str, user: str, temperature: float) -> str:
        self.calls.append((system, user))
        # Record mock usage for diagnostic testing
        from .telemetry import record_usage
        record_usage(input_tokens=100, output_tokens=50, total_tokens=150, 
                     provider=self.name)
        
        if self.router:
            out = self.router(system, user)
            if out is not None:
                return json.dumps(out)
        for key, val in self.responses.items():
            if key in system or key in user:
                return json.dumps(val)
        return "{}"


# The TRUSTED moat brains. A verdict/adversarial ruling served by ANY brain outside
# this set (i.e. the cheap emergency tail — deepseek, minimax) is `provisional`: it
# keeps throughput up during a moat quota outage but does not publish on PASS
# and is auto re-vetted by the moat on the next `vet --resume`. Single source of truth
# for "is this ruling trustworthy as final" — used by verify.py.
# deepseek REMOVED 2026-07-02 (founder no-deepseek directive + operating rule: DeepSeek/
# MiniMax never touch verification verdicts as trusted-final — non-critical chains only).
# cursor_cli REMOVED 2026-08-06 (founder directive: "we need to get rid of cursor_cli"). It
# had been in the moat since 2026-07-30; measured DEAD on 2026-08-06 with
#   ProviderExhaustedError: cursor cli exit 1: ActionRequiredError: You've hit your usage limit
# so every call paid its failure before reaching a brain that answers. The adapter is deleted,
# not merely demoted, so it cannot be reintroduced by a config typo.
#
# NOTE for historical dossiers: 172 of them record `"provider": "cursor_cli"`. Their verdicts
# are NOT re-derived from this set — `is_provisional_provider` is only ever called on the name
# of the brain that just served a LIVE call (see `served_is_provisional` below), never on a
# stored dossier field. Removing cursor_cli therefore cannot retroactively flip a past PASS.
MOAT_PRIMARY: frozenset[str] = frozenset({"claude_cli", "claude"})


def is_provisional_provider(name: str) -> bool:
    """True if a ruling served by brain `name` must be treated as provisional (a cheap
    fallback brain, not a trusted moat primary). An empty/unknown name is conservatively
    treated as trusted=False -> provisional, so we never silently finalise an unknown."""
    return name not in MOAT_PRIMARY


class FallbackOperator(Operator):
    """Chain of brains with quota-aware failover (Part 9 resilience).

    Each raw call tries operators in order, GUARDED BY A PER-BRAIN CIRCUIT BREAKER.
    The breaker is the cross-call memory that a permanent `_dead` set lacked: once a
    brain trips (hard-trip on quota/credit exhaustion, threshold-trip on transient
    failures) every later call SKIPS it instantly instead of re-paying its full
    timeout to re-confirm it is dead — the bug that made every parallel call in a
    generation wave burn ~100s on a known-exhausted Gemini. After a cooldown the
    breaker half-opens and admits ONE probe, so a mid-run quota reset is picked back
    up automatically (a permanent retirement would have wasted the recovered brain).
    Parse repair (bad JSON) stays with the working brain: it returns text, so the
    breaker records success; complete_json's repair loop re-prompts it. Only when
    every brain's breaker is open does _raw raise (ProviderExhaustedError) -> defer.
    """
    def __init__(self, operators: list[tuple[str, Operator]], *,
                 failure_threshold: int = 3, cooldown_s: float = 60.0,
                 clock=time.monotonic, health=None):
        if not operators:
            raise ValueError("FallbackOperator needs at least one operator")
        from .health import get_health
        self.operators = operators
        self.name = "fallback(" + "+".join(n for n, _ in operators) + ")"
        self._breakers = {
            name: CircuitBreaker(name, failure_threshold=failure_threshold,
                                 cooldown_s=cooldown_s, clock=clock)
            for name, _ in operators}
        self._health = health if health is not None else get_health()
        # Per-thread record of which brain actually served the most recent call on THIS
        # thread.  Thread-local because vet_workers run candidates concurrently on one
        # shared FallbackOperator; a plain attribute would race. The verdict/adversarial
        # path reads this immediately after the call (same thread) to know whether a
        # trusted primary or the cheap emergency tail ruled -> provisional marking.
        self._served = threading.local()

    def last_served(self) -> str:
        """Tier-name of the brain that served this thread's most recent successful call
        (e.g. 'agy_cli', 'deepseek'), or '' if none has yet."""
        return getattr(self._served, "name", "")

    def served_is_provisional(self) -> bool:
        """True if this thread's most recent ruling was served by the cheap emergency
        tail (outside MOAT_PRIMARY) rather than a trusted moat brain."""
        s = self.last_served()
        return bool(s) and is_provisional_provider(s)

    def _raw(self, system: str, user: str, temperature: float) -> str:
        from .errors import (
            PERMANENT,
            ProviderExhaustedError,
            classify_exhaustion,
            limit_window_seconds,
        )
        from .health import DEFAULT_EXHAUSTION_S, TRANSIENT_EXHAUSTION_S
        from .telemetry import logger
        last_err: Optional[Exception] = None
        skipped = 0
        for name, op in self.operators:
            br = self._breakers[name]
            # Persisted health (cross-run quota window) OR in-run breaker can skip it —
            # skipping a known-dead brain for free is the whole point: no re-probe cost.
            if self._health.is_dead(name) or not br.allow():
                skipped += 1
                continue
            try:
                out = op._raw(system, user, temperature)
                br.record_success()
                self._health.clear(name)   # proven alive — drop any stale dead mark
                self._served.name = name   # record who served (for provisional marking)
                return out
            except Exception as e:
                last_err = e
                hard = isinstance(e, ProviderExhaustedError)
                br.record_failure(hard=hard)
                if hard:
                    # How long to stay away is decided by WHAT failed, not by the fact that
                    # something did. A parsed reset time from the provider always wins; failing
                    # that, backpressure gets the 60s floor and a spent allowance gets the hour.
                    # Before 2026-08-06 both got the hour, so an HTTP 429 under our own drain
                    # load benched a live brain for 3600s and the emergency tail ruled instead.
                    # `limit_window_seconds` supersedes the old `parse_reset_seconds` here: same
                    # stated-reset-time-always-wins precedence, but it also reads ABSOLUTE resets
                    # ("resets at 5pm") and falls back to a per-CLASS window when nothing is
                    # stated. Before 2026-08-06 an absolute reset parsed to nothing, so Claude
                    # Code's weekly limit took the 1h default and was re-probed hourly for a week.
                    kind = classify_exhaustion(str(e))
                    # A window the RAISER knows outranks anything read back out of its own
                    # message: `ProviderExhaustedError.retry_after_s` is set by the usage-wall
                    # preflight, which holds the exact reset epoch. Parsing it back from the
                    # rendered prose returned None and cost the moat 46 benched minutes on
                    # 2026-08-08. Text parsing stays as the fallback for adapters that only ever
                    # see a provider's words.
                    dead_for = (getattr(e, "retry_after_s", None)
                                or limit_window_seconds(str(e))
                                or (DEFAULT_EXHAUSTION_S if kind == PERMANENT
                                    else TRANSIENT_EXHAUSTION_S))
                    self._health.mark_exhausted(name, dead_for, error=str(e))
                logger.warning(
                    f"Brain {name!r} {'exhausted' if hard else 'failed'} "
                    f"(breaker={br.state}); failing over to next: {str(e)[:160]}",
                    extra={"provider": name, "error": str(e)[:200]})
        raise ProviderExhaustedError(
            f"all brains exhausted/failed ({skipped} skipped, known-dead): {last_err}",
            provider="+".join(n for n, _ in self.operators))


def _build_operator(kind: str, cfg, fast: bool) -> Operator:
    # fast=True selects the lighter model for mechanical calls (query-gen,
    # prescreen); falls back to the main model when model_fast is unset.
    #
    # CRITICAL: cfg.model / cfg.model_fast are provider-specific pins.
    # They must NOT leak to other providers. Only apply cfg.model/model_fast
    # when they match the provider being built — determined by the model
    # name prefix or the config's implicit primary operator.
    # An empty string is treated as "unset" — the operator's own config
    # default is then used (cfg.model_defaults.<provider>).
    cfg_model = getattr(cfg, "model_fast", "") if fast else getattr(cfg, "model", "")
    # Per-provider config defaults (from cfg.model_defaults).
    md = getattr(cfg, "model_defaults", None)

    # Determine if cfg.model/model_fast was set FOR this provider.
    # Heuristic: a model name starting with the provider name or its aliases
    # (e.g. "claude-*", "deepseek-*", "minimax-*") belongs to that provider.
    _PROVIDER_MODEL_PREFIX = {
        "claude": ("claude-",),
        "claude_cli": ("claude-",),
        "deepseek": ("deepseek-",),
        "minimax": ("minimax-", "MiniMax-"),
        "ollama": (),
        "standardcompute": ("standardcompute",),
    }
    prefixes = _PROVIDER_MODEL_PREFIX.get(kind, ())
    model_matches = bool(cfg_model) and any(cfg_model.lower().startswith(p.lower()) for p in prefixes)
    model = cfg_model if model_matches else None
    has_cfg_model = model_matches
    if kind == "claude_cli":
        # cfg.model is an API pin; don't leak it to the claude CLI.
        from .claude_cli import ClaudeCliOperator
        return ClaudeCliOperator(model=None)
    if kind == "claude":
        try:
            if has_cfg_model:
                return ClaudeOperator(model=model)
            return ClaudeOperator(
                model=md.claude if md else "claude-sonnet-4-5"
            )
        except ModuleNotFoundError as e:
            raise RuntimeError("ANTHROPIC_API_KEY not set or anthropic not installed") from e
    if kind == "mock":
        return MockOperator()
    if kind == "minimax":
        # MiniMax is routed to non-verification tasks only (generation, marketing,
        # artifacts).  fast=True uses the cheap/structured model; fast=False uses
        # the full reasoning model. Both defaults come from cfg.model_defaults.
        # NEVER use cfg.model/cfg.model_fast here — those are Gemini-specific pins.
        return MiniMaxOperator(
            cheap=fast,
            default_model=md.minimax if md else None,
            fast_model=md.minimax_fast if md else None,
        )
    if kind == "deepseek":
        # Routed to non-verification tasks only (prescreen, scoring, content).
        # MUST NOT be used for kill-check verdicts or adversarial analysis (the moat).
        # NEVER use cfg.model/cfg.model_fast here — those are Gemini-specific pins.
        return DeepSeekOperator(
            default_model=md.deepseek if md else None,
        )
    if kind == "ollama":
        # Ollama: fully local, zero token cost. OpenAI-compatible endpoint.
        # Routed to non-verification tasks only (generation, prescreen, scoring).
        # MUST NOT be used for kill-check verdicts or adversarial analysis (the moat).
        return OllamaOperator(
            model=model,
            default_model=md.ollama if md else None,
        )
    if kind == "standardcompute":
        # OpenAI-compatible third-party endpoint (api.stdcmpt.com). Added 2026-08-08 to
        # move load off the Claude Code subscription. It is NOT in MOAT_PRIMARY, so any
        # verdict it serves is stamped `provisional` and cannot publish — promotion needs
        # the golden-set gate in config.yaml:50-52.
        return StandardComputeOperator(
            model=model,
            default_model=md.standardcompute if md else None,
            cfg=cfg,
        )
    # cursor_cli was removed here on 2026-08-06 (founder directive). It stays an EXPLICIT
    # error rather than an unknown one, so a stale config or plist fails loudly at startup
    # instead of silently building a chain one brain shorter than it reads.
    if kind == "cursor_cli":
        raise ValueError(
            "operator 'cursor_cli' was removed on 2026-08-06 (founder directive; it was "
            "measured at its usage limit and every call paid a guaranteed failure first). "
            "Use claude_cli. Update config.yaml `operator:`/`artifact_operator:`.")
    raise ValueError(f"unknown operator: {kind!r} "
                     "(expected claude_cli|claude|minimax|deepseek|ollama|"
                     "standardcompute|mock)")


def make_operator(cfg, fast: bool = False) -> Operator:
    # operator may be a single name or an ordered fallback chain.
    # Sync CLI concurrency governors from config (env overrides still win).
    r0 = getattr(cfg, "retrieval", None)
    if r0 is not None:
        try:
            from .claude_cli import configure_concurrency as _claude_conc
            _claude_conc(int(getattr(r0, "claude_concurrency", 2) or 2))
        except Exception:
            pass
    from .telemetry import logger

    kinds = cfg.operator
    kinds = [kinds] if isinstance(kinds, str) else list(kinds)
    # A tier whose CREDENTIALS are absent is skipped; a tier that is UNKNOWN or REMOVED is
    # still fatal. Before 2026-08-08 this was a list comprehension, so the moment the verdict
    # chain grew a `minimax` tail (founder directive, same day) every machine without
    # MINIMAX_API_KEY lost the whole chain — claude_cli included — at construction time. CI
    # caught it as 6 red tests in tests/unit/test_e1_abort_on_outage.py; the real blast radius
    # was any deploy, including the daemon, that does not carry a key for the FALLBACK.
    # Catching only RuntimeError is what draws that line: `_build_operator` raises RuntimeError
    # for a missing key and ValueError for an unknown/removed name (e.g. the cursor_cli fence
    # above), and a stale config must keep failing loudly.
    # This mirrors the two chains that already got it right: `run._build_operator_chain`
    # (run.py:618) and `run._build_artifact_op` (run.py:328).
    built: list[tuple[str, Operator]] = []
    for k in kinds:
        try:
            built.append((k, _build_operator(k, cfg, fast)))
        except RuntimeError as e:
            # Loud, and it names the consequence: a silently-dropped tier is exactly how a
            # fallback ends up configured-but-inert, which is the defect this whole change set
            # exists to close.
            logger.warning(
                "Operator tier %r unavailable (%s) — dropping it from the verdict chain. "
                "The chain will run WITHOUT it; if it was the fallback, there is no fallback.",
                k, e)
    if not built:
        # Never return a chain that cannot rule. The caller's DEFER path is the correct
        # outcome here, and it is reached by raising, not by handing back an empty chain.
        raise RuntimeError(
            f"no operator in {kinds!r} could be constructed — check API keys and credentials.")
    if len(built) == 1:
        # A one-tier config gets the bare operator — there is no chain to fail over to, so
        # wrapping it in a FallbackOperator would buy nothing and would rename it. But it
        # must still be able to answer "did a TRUSTED brain rule this?", so stamp the tier
        # name it was built from; `Operator.served_is_provisional` reads it. Audit #14.
        kind, op = built[0]
        op.tier_name = kind
        return op
    r = cfg.retrieval
    return FallbackOperator(built, failure_threshold=r.breaker_failure_threshold,
                            cooldown_s=r.breaker_cooldown_s)
