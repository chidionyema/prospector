"""The pluggable 'brain' (Part 1). Same tooling, swappable operator.

Every model call goes through Operator.complete_json(), which enforces strict JSON
output with repair-retries (Part 9) — a bad parse never crashes a run. Adapters:
  - GeminiOperator: google-genai direct. Default for 'now' (key present).
  - MiniMaxOperator: MiniMax OpenAI-compatible API. Routed to NON-VERIFICATION
    tasks only (generation, marketing content, artifacts). The verification moat
    (kill-check verdicts, adversarial pass) MUST stay with Claude/Gemini per
    CLAUDE.md.  MiniMax is ~$0.001/M tokens input vs Claude Opus ~$0.015 —
    15× cheaper for creative/structuring tasks.
  - MockOperator: deterministic, for tests / fixtures (no network, no spend).
"""
from __future__ import annotations

import http.client
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


def _loads(candidate: str) -> Any:
    """`json.loads` with `strict=False` — the ONLY loader this module may use.

    `strict=True` (the default) rejects a literal newline or tab INSIDE a string with
    `Invalid control character`.  Models write multi-sentence rationales and put real line
    breaks in them; the JSON spec says escape them, and a model that doesn't is not
    thereby saying nothing.  `strict=False` accepts the control character and returns the
    string intact.

    MEASURED 2026-08-15, and it is the reason this exists.  A minimax verdict of the form

        {"verdict":"supported","confidence":0.8,"rationale":"…statutory.<LF>…28-day
        timetable.","citations":["a1b2c3d4e5f6a7b8"]}

    failed every strategy below on that one newline.  It did not fail loudly: Strategy 2
    scans for `[`…`]` BEFORE `{`…`}`, so it found the citations array, parsed it happily,
    and `_extract_json` returned `['a1b2c3d4e5f6a7b8']` — a list where the caller expects
    the verdict dict.  The check came out `unverifiable, conf 0.0, rationale ""`, and the
    golden gate then recorded that the BRAIN had answered without a reason.  It had not.
    It answered in full and we threw the answer away, then blamed it for the silence.
    """
    return json.loads(candidate, strict=False)


# A quoted key followed by a colon — the minimum signature of an object this engine asked for.
# BOTH quote styles: a single-quoted key is a Python-repr-shaped reply, one of the commonest
# malformations a model emits and one `json.loads` refuses outright, so demanding a double
# quote here would have gated out a whole class of genuinely repairable payloads.
# Bounded repetition, not `.*`: this runs on multi-KB model output, and an unbounded scan over
# a pathological reply is the CPU-bound hang `_tail_json_candidates`' cap already exists to stop.
_RE_JSON_KEY = re.compile(r"""("[^"\n]{1,120}"|'[^'\n]{1,120}')\s*:""")


def _extract_json(text: str) -> Any:
    """Multi-strategy JSON extraction from verbose model output."""
    from .telemetry import logger

    # Strategy 1: Strip <think> blocks and try direct load
    t = _RE_THINK.sub("", text).strip()
    # Strip markdown code fences
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.MULTILINE).strip()
    try:
        return _loads(t)
    except json.JSONDecodeError:
        pass

    # Strategy 2: Find the largest possible range between braces/brackets
    # This works if the model outputs one main JSON block with noise around it.
    #
    # ORDER IS OUTERMOST-FIRST, not `[` before `{`. The fixed order was a silent
    # mis-extraction whenever an object failed to parse but contained an array: the
    # citations list of a verdict, the `queries` list of a query-gen reply. It returned a
    # LIST where every caller expects a dict, so the failure surfaced far away as a
    # missing field rather than here as a parse error. Whichever delimiter opens first in
    # the text is the outer structure, and that is the one the model meant to return.
    _pairs = [("[", "]"), ("{", "}")]
    _pairs.sort(key=lambda p: (text.find(p[0]) if text.find(p[0]) != -1 else len(text) + 1))
    for start_char, end_char in _pairs:
        start = text.find(start_char)
        end = text.rfind(end_char)
        if start != -1 and end != -1 and end > start:
            candidate = text[start:end+1]
            try:
                data = _loads(candidate)
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
                            data = _loads(candidate)
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
                data = _loads(candidate)
                logger.info(
                    f"JSON Strategy 4 success: {len(candidate)} chars taken from the tail of "
                    f"{len(source)}")
                return data
            except json.JSONDecodeError:
                continue

    # Strategy 5: hand it to a real repairing parser before giving up.
    #
    # Strategies 1-4 are hand-rolled DELIMITER heuristics: they answer "which span of this text
    # is the JSON?" and none of them repairs the span once found. So the whole family fails on
    # malformed-but-obvious payloads a repairer fixes trivially — an unescaped newline inside a
    # string (the defect measured 2026-08-15), a trailing comma, a single-quoted key, a value
    # truncated mid-object because the model ran out of budget.
    #
    # It runs LAST and only after every existing strategy has failed, so it cannot change any
    # response that parses today; the sole reachable effect is turning a ParseError into a
    # parse. The falsy guard is not defensive padding — `repair_json` answers `""` (and can
    # answer `{}` / `[]`) for input it cannot make sense of, and returning that would be
    # strictly worse than raising: an empty dict flows downstream as a REPLY with every field
    # missing, which reads as a brain that answered nothing rather than as a parse failure.
    # This repo has paid for that shape twice ("a swallowed outage returns empty, it does not
    # raise"; "an empty default erased clean from unchecked"), so an empty repair is treated as
    # no repair at all.
    # IT IS RUN ON A DELIMITED SPAN, NEVER ON THE WHOLE RESPONSE, and that is the load-bearing
    # detail. `repair_json` does not answer "is this JSON?" — it answers "what is the nearest
    # JSON to this?", and on prose it INVENTS. Measured 2026-08-15 on the live library:
    #     "Here is my analysis: the answer is unclear [see above] and I cannot say."
    #         -> ['see above']
    # A non-empty list of a fabricated string, from a reply whose actual content was a refusal.
    # That is worse than the empty case a falsy check catches, because it is indistinguishable
    # downstream from a real answer — the fabrication wears the costume of a parse. The first
    # cut of this strategy did exactly that and was caught by
    # `test_prose_with_no_json_at_all_still_raises_rather_than_scanning_forever`, a regression
    # test that predates it (committed 40212a3, 2026-08-14).
    #
    # So two gates, both required: the span must be delimiter-BOUNDED (an opener AND a closer,
    # which prose full of stray `{`/`[` does not have), and it must contain a QUOTED KEY. Every
    # payload this engine asks any brain for is an object or an array of objects, so "no
    # `"key":` anywhere in the span" means whatever this is, it is not our reply — and a
    # bracketed fragment of English is precisely what that rejects.
    try:
        from json_repair import repair_json
        for source in (t, text):
            # OUTERMOST-FIRST, for the identical reason Strategy 2 sorts its pairs: whichever
            # delimiter opens first is the outer structure, and a fixed order can select the
            # INNER one — returning a dict where the caller expects a list, the citations-array
            # mis-extraction mirrored.
            #
            # Correctness-by-construction, NOT a fix for an observed failure here — stated
            # plainly because the first version of this comment claimed otherwise. On the
            # motivating input `[{"url": "a", "text": "x"}, {"url": "b"` this ordering is never
            # exercised: STRATEGY 2 already returns, because `s.rfind("}")` finds the inner
            # object's closer and `s[1:33]` parses cleanly as a single dict. That is a
            # pre-existing truncated-array limitation of Strategy 2, older than this strategy
            # and deliberately not touched in the same change as a moat promotion. Its live
            # blast radius is small: the grounding path that would suffer it now runs under
            # `--json-schema`, where the CLI validates before we ever parse.
            pairs = sorted((("{", "}"), ("[", "]")),
                           key=lambda p: (source.find(p[0]) if source.find(p[0]) != -1
                                          else len(source) + 1))
            for open_c, close_c in pairs:
                start = source.find(open_c)
                if start == -1:
                    continue
                end = source.rfind(close_c)
                # An opener with NO closer is the TRUNCATION case, and it is the single most
                # valuable thing this strategy recovers: a model that exhausts its output
                # budget mid-object emits a perfectly good prefix and no closing brace, which
                # every strategy above rejects and a repairer closes trivially. It is admitted
                # only because the quoted-key gate below is what actually holds the line —
                # prose with a stray `{` and no `}` still carries no `"key":` and is still
                # refused (`test_prose_with_no_json_at_all_still_raises...`).
                span = source[start:end + 1] if end > start else source[start:]
                if not _RE_JSON_KEY.search(span):
                    continue
                repaired = repair_json(span, return_objects=True)
                # `or repaired == 0 or repaired is False` — a legitimately falsy payload is
                # still a payload; only the repairer's own "I could not" sentinels ('', {}, [])
                # are rejected. Returning one of those would flow downstream as a REPLY with
                # every field missing, reading as a brain that answered nothing rather than as
                # a parse failure ("a swallowed outage returns empty, it does not raise").
                if repaired or repaired == 0 or repaired is False:
                    logger.info(
                        f"JSON Strategy 5 (repair) success: {len(span)} chars of "
                        f"{len(source)} repaired",
                        extra={"repaired_type": type(repaired).__name__})
                    return repaired
                logger.warning(
                    "JSON Strategy 5 (repair) returned an EMPTY object; treating as a parse "
                    "failure rather than as an empty answer", extra={"span": len(span)})
    except ImportError:
        # Declared in requirements.txt; absent only in a partially-provisioned checkout. Never
        # fatal — the four strategies above are exactly the behaviour that shipped before this.
        logger.warning("json_repair not installed; Strategy 5 skipped")
    except Exception as e:  # a repairer that itself throws must not mask the real ParseError
        logger.warning(f"JSON Strategy 5 (repair) raised: {e}")

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


# ClaudeOperator (the PAID Anthropic API brain, ANTHROPIC_API_KEY) was DELETED on 2026-08-15
# by founder directive, alongside StandardComputeOperator below. It was one of the two names in
# MOAT_PRIMARY, so this is a trust-boundary change and not a cleanup: MOAT_PRIMARY is now
# `{"claude_cli"}` alone (see below). The engine runs on the Claude Code SUBSCRIPTION via
# `claude_cli`, which is unaffected — do not confuse the two, most lines in this file that say
# "claude" mean the subscription CLI.
#
# It was dead in practice anyway: `python -m prospector.golden --operator claude` on 2026-08-15
# failed to construct with "ANTHROPIC_API_KEY not set or anthropic not installed", i.e. the tier
# singled out as trusted could not serve a single call on this machine. Per the standing rule
# that a dead brain must leave a trace rather than sit in a chain as invisible failure, it is
# deleted rather than demoted, and `_build_operator` raises an explicit ValueError on the name.


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
            # PROPAGATE. `[]` is what line 336 returns on the success path when the response
            # carries no values, so a failed embedding call and an empty one were the same
            # bytes — and an empty embedding is not a vector, it is the absence of one.
            # Downstream (dedup, prescreen_prefilter) a zero-length vector silently scores
            # every comparison the same way, which reads as "nothing is a duplicate".
            from .telemetry import logger
            logger.error(f"Gemini embedding failed: {e}")
            raise


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


#: How much of an HTTP error body to keep. The MiniMax refusal that matters is ~180 bytes; 800
#: is room for a longer one without turning a health file into a log.
_ERROR_BODY_CHARS = 800


def _http_error_with_body(e: "urllib.error.HTTPError") -> RuntimeError:
    """Turn an HTTPError into one whose message carries the provider's own explanation.

    `str(HTTPError)` is the status line and nothing else — `HTTP Error 429: Too Many Requests`.
    The reason is in the BODY, and urllib discards it unless someone reads the exception as a
    file. Measured 2026-08-18 against the live endpoint while the engine was moat-blind:

        $ curl -s -X POST https://api.minimax.io/v1/chat/completions ...
        {"type":"error","error":{"type":"rate_limit_error","message":"Token Plan usage limit
         reached: Upgrade your Token Plan or purchase Credits for more usage. (2056)",
         "http_code":"429"},"request_id":"06d39d81b21ad83755fc36146cd0e843"}

    Everything an operator needs is in that body, and none of it reached us. `provider_health.json`
    recorded `MiniMax quota exhausted: HTTP Error 429: Too Many Requests` — a sentence whose first
    half is our guess and whose second half is a generic status line. So the engine could not tell
    a plan window from a busy endpoint, `errors.classify_exhaustion` graded it TRANSIENT on the
    bare `\b429\b` and benched MiniMax for 60s at a time, and the founder had to be the one who
    knew the plan resets on a clock.

    With the body attached, the same failure classifies through `_PERMANENT_MARKERS` ("usage
    limit") and earns the hour-long mark that an allowance limit deserves, and the alert quotes
    the provider instead of paraphrasing it. Nothing here decides anything; it stops throwing
    away the evidence the decision needs.

    Returned rather than raised so the caller keeps its own `raise ... from` chain.
    """
    body = ""
    try:
        raw = e.read()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        body = " ".join(str(raw).split())[:_ERROR_BODY_CHARS]
    except (OSError, ValueError, http.client.HTTPException) as read_err:
        # Narrow on purpose, and NOT the empty string. A body that is empty and a body we
        # could not read are different facts, and this message is the only place either one is
        # ever seen. `tools/audit_swallow_sites.py` grades a broad, silent except that returns
        # the success path's own value as tier 1 — "the caller cannot tell" — and it is right.
        body = f"<error body unreadable: {type(read_err).__name__}>"
    # The status line stays FIRST and verbatim: `\b429\b` word-boundary matching in the retry
    # loop and in `errors` keys off it, and a body that happened to contain another number must
    # not be able to move it.
    return RuntimeError(f"HTTP Error {e.code}: {e.reason}" + (f" — {body}" if body else ""))


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
    try:
        resp = urllib.request.urlopen(req, timeout=stall_timeout)
    except urllib.error.HTTPError as e:
        # The provider said why. Keep it — see `_http_error_with_body`.
        raise _http_error_with_body(e) from e
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
        raise _MiniMaxDeadline(
            f"streamed response exceeded {total_deadline:.0f}s hard deadline")
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


class _MiniMaxDeadline(TimeoutError):
    """The hard ceiling in `_read_sse_bounded` — a body that trickled for the whole deadline.

    A TimeoutError subclass so every existing caller and message match is unchanged, but a
    DISTINCT type from the per-recv stall because the two earn opposite treatment. A stall is
    90s of silence: cheap to detect and worth one re-ask. This is 600s of a live stream that
    never stopped, so a re-ask most likely buys a second 600s of the same — and would put a
    single call's worst case at 1205s inside a tick budget. 345 stalls against 13 of these
    (`store/scheduler/launchd.err.log`, 2026-08-06 → 08-15): retrying the wrong one of the two
    is nearly all of the cost and almost none of the recovery.
    """


class _MiniMaxStalled(RuntimeError):
    """The wire went silent — `_STALL_TIMEOUT_S` of nothing, or the hard deadline hit.

    Distinct from `_MiniMaxTruncated` because they have opposite causes and the same cure.
    M3 emits its reasoning as `<think>…</think>` INSIDE `delta.content` (see the truncation
    check in `_raw_once`, which strips it with `_RE_THINK`), so a reasoning call is streaming
    bytes the whole time it thinks. Silence on that stream is therefore NOT the model
    thinking: it is server-side queueing or a wedged socket, i.e. transient and worth
    re-asking, exactly like a truncation. Measured 2026-08-06→08-15 in
    `store/scheduler/launchd.err.log`: 345 `read operation timed out` against 23 truncations,
    and only the truncations were ever retried.
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
    # ONE stall retry, not two. A stall costs its full bound before it is even detected
    # (90s of silence, or 600s of trickle), so the budget here buys wall-clock at a much
    # worse rate than the truncation budget does — and if the cause is server-side queueing
    # under `minimax_concurrency`, a wide retry budget feeds the thing it is recovering from.
    _RETRY_STALL_MAX = int(os.environ.get("PROSPECTOR_MINIMAX_STALL_RETRIES", "1"))
    _RETRY_STALL_BACKOFF_S = float(os.environ.get("PROSPECTOR_MINIMAX_STALL_BACKOFF_S", "5"))

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
        from .telemetry import logger as _log
        last: Optional[Exception] = None
        truncations = stalls = 0
        while True:
            try:
                return self._raw_once(system, user, temperature)
            except _MiniMaxTruncated as e:
                last = e
                truncations += 1
                if truncations > self._RETRY_TRUNCATED_MAX:
                    break
                _log.warning(
                    f"MiniMax spent its whole budget reasoning and returned no answer; "
                    f"re-asking (attempt {truncations}/{self._RETRY_TRUNCATED_MAX})",
                    extra={"provider": self.name})
            except _MiniMaxStalled as e:
                last = e
                stalls += 1
                if stalls > self._RETRY_STALL_MAX:
                    break
                delay = self._RETRY_STALL_BACKOFF_S * stalls
                _log.warning(
                    f"MiniMax went silent on the wire; re-asking in {delay:.0f}s "
                    f"(attempt {stalls}/{self._RETRY_STALL_MAX})",
                    extra={"provider": self.name, "delay_s": delay})
                time.sleep(delay)
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
            #
            # PER STAGE since 2026-08-19. One number for every call meant a one-sentence shelf-copy
            # rewrite carried the same 65536 ceiling as a full dossier, and a runaway on that ask
            # bills the whole budget: `docs/CONTENT_CONTRACT_PROGRAM.md:489` records one that spent
            # 23 minutes and $0.059 and returned nothing. The ceiling could not simply be lowered,
            # because generation genuinely uses it (measured over 33,553 spend events in
            # `store/prospector.jsonl`: `generate` p50 32,094 / p95 65,536, against `verdict`
            # p50 390 / max 6,591). `minimax_max_tokens_for_stage` resolves it from the stage the
            # caller declared; an undeclared stage keeps the old ceiling, so this cannot narrow a
            # call by accident.
            "max_tokens": minimax_max_tokens_for_stage(),
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
                # SILENCE is retriable — see `_MiniMaxStalled`. Both bounds land here: the
                # per-recv stall arrives as `socket.timeout` ("The read operation timed out",
                # which IS `TimeoutError` on 3.10+) and the hard ceiling as the explicit
                # `TimeoutError` raised by `_read_sse_bounded`. Matched on the type AND the
                # message so a wrapped or renamed socket error cannot slip past the type check
                # and be re-classified as a permanent failure.
                if not isinstance(e, _MiniMaxDeadline) and (
                        isinstance(e, TimeoutError) or "timed out" in msg.lower()):
                    raise _MiniMaxStalled(f"MiniMax call failed: {e}") from e
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
            # Bounded read, not a bare per-recv timeout. `urlopen(timeout=...)` bounds each
            # individual socket recv, so a server that trickles the body resets it on every
            # chunk and `resp.read()` blocks forever: on 2026-08-11 the daemon logged one
            # `LLM completion started` line at 08:05:25 and emitted NOTHING for 46 hours.
            # (The adapter that wedged was standardcompute, removed 2026-08-15; the shape is
            # every metered adapter's, which is why the bound lives in one helper.)
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


# StandardComputeOperator (api.stdcmpt.com, STANDARDCOMPUTE_API_KEY) was DELETED on 2026-08-15 by
# founder directive, alongside ClaudeOperator above. STANDARDCOMPUTE_API_KEY is unset in this
# estate and the free trial is spent: the last live calls returned an out-of-allowance upsell body
# with HTTP 200 instead of a completion, and store/provider_health_noncritical.json carried
# strikes: 4 with that notice as `last_error`. A tier that cannot answer is not a failover — it is
# a guaranteed failure paid before every call, which is exactly the shape that got cursor_cli
# deleted on 2026-08-06.
#
# Per the standing rule that a dead brain must leave a trace, it is deleted rather than demoted,
# and `_build_operator` raises an explicit ValueError on the name so a stale config.yaml or
# launchd plist fails LOUDLY at startup instead of silently building a chain one brain shorter
# than it reads.
#
# What went with it: `Pricing.standardcompute` / `ModelDefaults.standardcompute`
# (prospector/config.py), the `standardcompute` tail of `_NONCRITICAL_ORDER` (prospector/run.py),
# and the `cfg=`-threading audit fix (ENGINE_AUDIT_2026-08-10 HIGH #4) whose only caller this
# adapter was. `record_usage(cfg=...)` still works and still warns on an unpriced provider; it
# simply has no caller passing `cfg` today.


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
            # same way a remote one does; see `_urlopen_read_bounded` for the 46-hour daemon
            # wedge on 2026-08-11 that made this a shared helper rather than one adapter's fix.
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


#: Sent by `OpenAICompatibleOperator` on every call. It exists because urllib's default
#: (`Python-urllib/3.x`) is refused with 403 by the bot filters in front of several providers —
#: measured against Groq on 2026-08-21. Keep it a plain, honest product identifier: this is not
#: an attempt to look like a browser, it is the engine saying which client it is.
_OPENAI_COMPAT_UA = "prospector/1.0 (+https://github.com/chidionyema/prospector)"


class OpenAICompatibleOperator(Operator):
    """One provider declared in `config.yaml providers:`, spoken to over OpenAI-compatible HTTP.

    This is `OllamaOperator` above with the two things a hosted provider needs that a local one
    does not: a bearer key read from a named env var, and its endpoint, model pair, token
    ceiling and timeout supplied by config rather than hardcoded. Every other adapter in this
    file is a variation on the same POST; declaring one is now a config block instead of a new
    class plus a new branch plus ~85 edits elsewhere.

    It is NEVER trusted by virtue of being declared. `operator.moat_primary()` is the only
    trust fence: a ruling served here is stamped `provisional` unless the name is also on
    `moat_primary:`, and `provisional` does not publish on PASS.

    ESTATE MODEL ROUTER OVERRIDE (crew#325). `LLM_BASE_URL` and `LLM_API_KEY`, when both set,
    outrank the `base_url`/`api_key_env` this operator was declared with — same idiom as
    `OllamaOperator.OLLAMA_BASE_URL` above. This is the seam that lets any declared,
    OpenAI-compatible tier be pointed at the estate's LiteLLM router (idp platform/llm,
    crew#284) with two env vars and zero config.yaml edits, so a laptop-only provider config
    still ships to a buyer's estate unmodified. Unset (either var, or both) is byte-for-byte
    today's behaviour: `base_url`/`api_key_env` from config, nothing else. `claude_cli` and
    `gemini_cli` never route here — they spend a subscription through a local CLI, not an API
    key over HTTP.
    """

    def __init__(self, name: str, base_url: str, api_key_env: str, model: str,
                 fast_model: str = "", max_tokens: int = 8192, timeout_s: int = 300,
                 cheap: bool = False):
        from .errors import ProviderExhaustedError

        self.provider_name = name
        router_base_url = os.environ.get("LLM_BASE_URL")
        router_api_key = os.environ.get("LLM_API_KEY")
        self.base_url = (router_base_url or base_url or "").rstrip("/")
        self.api_key_env = api_key_env
        # `cheap=True` is the mechanical-call path (query-gen, prescreen). A provider with no
        # second model uses its one model for both, same as a blank `model_fast` elsewhere.
        self.model = (fast_model or model) if cheap else model
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self.name = f"{name}/{self.model}"
        key = (router_api_key or os.environ.get(api_key_env) or "").strip()
        if not key:
            # ProviderExhaustedError, not RuntimeError, and AT CONSTRUCTION: a tier whose
            # credential is absent must be dropped from the chain by `make_operator` so the run
            # fails OVER to the next brain. Raising later — on the first real call, halfway
            # through a candidate — spends the run and then reports it as a provider outage.
            raise ProviderExhaustedError(
                f"neither LLM_API_KEY nor {api_key_env} is set, so provider {name!r} cannot "
                f"authenticate. Either export LLM_API_KEY (routes through the estate model "
                f"router) or {api_key_env}, or drop {name!r} from config.yaml `operator:`/"
                "`noncritical_operator:`/`moat_primary:`.",
                provider=self.name)
        self._key = key

    @property
    def model_version(self) -> str:
        return self.name

    @track_latency(name="openai_compatible_raw_call")
    def _raw(self, system: str, user: str, temperature: float) -> str:
        """POST to `<base_url>/chat/completions` with a bearer key."""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": self.max_tokens,
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self._key}",
                     # WHY THIS HEADER IS NOT OPTIONAL. Without it urllib sends
                     # `User-Agent: Python-urllib/3.x`, and the bot filters in front of several
                     # providers refuse that string outright. Measured against Groq on
                     # 2026-08-21, same key, same body, same endpoint, one header apart:
                     #     curl's own User-Agent  -> HTTP 200
                     #     Python-urllib/3.11     -> HTTP 403 Forbidden
                     # A 403 reads as a bad key, so the failure sends whoever meets it to
                     # re-issue a credential that was fine. It is also invisible until a
                     # DECLARED provider is actually used, which is why it survived: the
                     # built-in tiers do not come through this adapter.
                     "User-Agent": _OPENAI_COMPAT_UA},
            method="POST",
        )
        try:
            # Bounded read, for the same reason every adapter here uses it: urllib's timeout is
            # per-recv, so a trickled body resets it forever. See `_urlopen_read_bounded`.
            raw = _urlopen_read_bounded(req, timeout=self.timeout_s,
                                        total_deadline=self.timeout_s + 60)
            data = json.loads(raw.decode("utf-8"))
        except Exception as e:
            from .errors import ProviderExhaustedError, looks_exhausted
            if looks_exhausted(str(e)):
                # Quota, credit or backpressure: fail over, and let health.py bench it for the
                # right window. One shared classifier, so a new provider inherits every
                # exhaustion shape the estate has already paid to learn.
                raise ProviderExhaustedError(
                    f"{self.name} exhausted: {e}", provider=self.name) from e
            raise RuntimeError(f"{self.name} call failed: {e}") from e

        content = (data.get("choices", [{}])[0].get("message", {})
                   .get("content", "") or "")
        from .telemetry import logger, record_usage
        usage = data.get("usage") or {}
        record_usage(input_tokens=int(usage.get("prompt_tokens", 0) or 0),
                     output_tokens=int(usage.get("completion_tokens", 0) or 0),
                     total_tokens=int(usage.get("total_tokens", 0) or 0),
                     provider=self.name)
        logger.info(f"{self.name} response: length={len(content)}")
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
# NARROWED 2026-08-15 (founder directive): was `frozenset({"claude_cli", "claude"})`. The paid
# Anthropic API tier `claude` was deleted with its adapter, so the set is a single name. This is
# the line that decides what may PUBLISH — `is_provisional_provider` below is its only reader,
# and `health._brains_we_trust` is its only other consumer — so narrowing it means the engine
# now has exactly ONE trusted brain. That is a statement of fact, not a new risk: `claude` could
# not construct on this machine for want of ANTHROPIC_API_KEY, so it was never going to rule.
#
# The same historical-dossier note as cursor_cli applies: `is_provisional_provider` is only ever
# called on the name of the brain that just served a LIVE call, never on a stored dossier field,
# so removing `claude` cannot retroactively flip a past PASS.
# CONFIG-DECLARED 2026-08-15. This was a bare module constant with no config key, which made it
# the ONLY tier knob in the engine that needed a source edit and a daemon re-exec to move, while
# `operator:`, `noncritical_operator:`, `artifact_operator:` and `marketing_operator:` beside it
# were all config lines — a direct breach of this repo's own constraint ("Deterministic on config.
# Swapping operators requires no code change, only config.yaml"). It cost throughput, not just
# tidiness: with the trusted set welded to claude_cli, MiniMax's concurrency was unusable no
# matter how wide the chain ran, because everything it ruled was stamped `provisional` and could
# never publish. Promotion is now a config line + the golden gate, not a patch.
# The name is `MOAT_PRIMARY_DEFAULT`, not `MOAT_PRIMARY`: a stale `from ... import MOAT_PRIMARY`
# must fail at import rather than silently read a set the config has since overridden.
MOAT_PRIMARY_DEFAULT: frozenset[str] = frozenset({"claude_cli"})

# There is ONE list of buildable tier names in this module and it is `BUILDABLE_TIERS` below.
# This used to be a second, hand-maintained copy, and the copies drifted: `minimax_m27` was added
# to the public tuple and to `_build_operator` on 2026-08-15 and never to this one, so a config
# naming it in `moat_primary` was refused as unbuildable by the only surface that checks — while
# `noncritical_operator: [minimax, minimax_m27]` ran it in production. The console could not even
# save the roster already on disk.

MOAT_PRIMARY_ENV = "PROSPECTOR_MOAT_PRIMARY"

# Process override, installed by `config.load_config`. `is_provisional_provider(name)` is called
# with a bare brain name from ~10 sites that hold no Config, so the effective set has to be
# process state; `load_config` writes it on EVERY load (absent key => back to the default), so it
# is idempotent and one config can never poison the next.
_MOAT_PRIMARY: frozenset[str] | None = None
_MOAT_PRIMARY_LOCK = threading.Lock()


def _coerce_moat_primary(names, *, source: str) -> frozenset[str]:
    """Validate a declared trusted set. Raises ValueError on empty or unbuildable names."""
    if isinstance(names, str):
        names = [n for n in re.split(r"[,\s]+", names) if n]
    resolved = frozenset(str(n).strip() for n in (names or []) if str(n).strip())
    if not resolved:
        raise ValueError(
            f"{source} declares an EMPTY trusted verdict set. Every ruling would be stamped "
            "`provisional`, nothing would ever publish on PASS, and the engine would look "
            "unproductive rather than misconfigured. Name at least one tier.")
    # Read at CALL time, not import time: `BUILDABLE_TIERS` is defined further down the module.
    # A typo here fails SILENTLY in the worst direction — every ruling stamped provisional,
    # nothing published, the engine looking merely unproductive — so it is refused at declaration.
    # Declared providers count as buildable. `load_config` installs the parsed `providers:`
    # block process-wide BEFORE it gets here, which is the only way this check can see one:
    # `$PROSPECTOR_MOAT_PRIMARY` reaches this function with no Config anywhere in the call.
    # Without it a valid config is refused at startup and the message blames the config.
    from .providers import buildable_tiers, installed_declared
    buildable = frozenset(buildable_tiers(installed_declared()))
    unknown = sorted(resolved - buildable)
    if unknown:
        raise ValueError(
            f"{source} names unbuildable operator tier(s) {unknown}; expected a subset of "
            f"{sorted(buildable)}. A name that no tier ever serves would stamp every "
            "ruling `provisional` without ever saying why.")
    return resolved


def moat_primary() -> frozenset[str]:
    """The TRUSTED moat brains, as currently declared. THE reader of the trust fence.

    Precedence: `PROSPECTOR_MOAT_PRIMARY` (comma/space separated, ops override, matches
    `PROSPECTOR_VET_WORKERS`) > `config.yaml moat_primary:` > `MOAT_PRIMARY_DEFAULT`.
    """
    env = os.environ.get(MOAT_PRIMARY_ENV, "").strip()
    if env:
        return _coerce_moat_primary(env, source=f"${MOAT_PRIMARY_ENV}")
    with _MOAT_PRIMARY_LOCK:
        current = _MOAT_PRIMARY
    return current if current is not None else MOAT_PRIMARY_DEFAULT


MINIMAX_CONCURRENCY_ENV = "PROSPECTOR_MINIMAX_CONCURRENCY"
MINIMAX_CONCURRENCY_DEFAULT = 3


def set_minimax_concurrency(width) -> int:
    """Install the process-wide MiniMax request ceiling (called by `config.load_config`).

    `MiniMaxOperator._throttle` was built at IMPORT time from an env var alone, so the one knob
    that decides how fast the primary brain can work could not be moved from `config.yaml` — the
    same defect class as `MOAT_PRIMARY` before 7d4f17e, and it mattered for the same reason: the
    cheap brain leads the chain now, so this ceiling IS the engine's throughput.

    Measured 2026-08-15 against the live endpoint (probe: stepwise widths, counting 429s):
        width 2 → 0.07 calls/s · 4 → 0.60 · 6 → 0.89 · 8 → 1.36, with 16/16 clean and ZERO 429s
    at width 8. The old default of 3 was scar tissue from a 429 storm on an UNKNOWN tier
    (2026-08-09) and was never re-measured against MiniMax.

    Env still wins over config, for ops: a live 429 storm must be capped without an edit-and-deploy.
    Falsy/invalid `width` RESETS to the default rather than leaving the previous load's value, so a
    fixture config cannot poison the next load.
    """
    env = os.environ.get(MINIMAX_CONCURRENCY_ENV)
    resolved = None
    for candidate in (env, width):
        try:
            n = int(candidate)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if n >= 1:
            resolved = n
            break
    if resolved is None:
        resolved = MINIMAX_CONCURRENCY_DEFAULT
    MiniMaxOperator._throttle = threading.Semaphore(resolved)
    return resolved


MINIMAX_MAX_TOKENS_ENV = "PROSPECTOR_MINIMAX_MAX_TOKENS"
MINIMAX_MAX_TOKENS_DEFAULT = 65536
_MINIMAX_MAX_TOKENS_BY_STAGE: dict[str, int] = {}
_MINIMAX_MAX_TOKENS_LOCK = threading.Lock()


def set_minimax_max_tokens(table) -> dict[str, int]:
    """Install the process-wide per-stage MiniMax output ceiling (called by `config.load_config`).

    Same shape and same reason as `set_minimax_concurrency` above: the value is read inside
    `_raw_once`, which holds no Config, so this is the only place config CAN reach it. Written on
    every load, including when the key is absent (=> reset to empty), so a fixture config cannot
    poison the next load.

    A bad entry RAISES, unlike the concurrency knob, and the asymmetry is deliberate. A bad width
    falls back to a working default and the engine still runs. A misspelt stage name here would
    read as a configured ceiling while silently leaving that stage at 65536 — the config-that-
    cannot-mean-what-it-says failure `_validate_retrieval` and `_validate_admissibility` already
    stop at startup. Stage names are NOT validated against a list, because `telemetry.stage()`
    takes a free string and a new stage must not need an edit here to be declarable.
    """
    resolved: dict[str, int] = {}
    if table:
        if not isinstance(table, dict):
            raise ValueError(
                "config `retrieval.minimax_max_tokens` must be a mapping of stage name to a "
                f"positive integer, got {type(table).__name__}")
        for name, value in table.items():
            try:
                n = int(value)
            except (TypeError, ValueError):
                raise ValueError(
                    f"config `retrieval.minimax_max_tokens.{name}` must be a positive integer, "
                    f"got {value!r}") from None
            if n < 1:
                raise ValueError(
                    f"config `retrieval.minimax_max_tokens.{name}` must be >= 1, got {n}")
            resolved[str(name)] = n
    with _MINIMAX_MAX_TOKENS_LOCK:
        global _MINIMAX_MAX_TOKENS_BY_STAGE
        _MINIMAX_MAX_TOKENS_BY_STAGE = resolved
    return dict(resolved)


def minimax_max_tokens_for_stage(stage: str | None = None) -> int:
    """The output ceiling for one MiniMax call.

    Precedence: `$PROSPECTOR_MINIMAX_MAX_TOKENS` (ops override, no deploy) > the per-stage table
    from `config.yaml retrieval.minimax_max_tokens` > `MINIMAX_MAX_TOKENS_DEFAULT`. Env first
    matches `set_minimax_concurrency` and `moat_primary()`: an incident is capped from the plist.

    `stage` defaults to whatever `telemetry.stage()` context the caller is inside. A call made
    outside any stage — or inside a stage with no entry — gets the default. That is the safe
    direction: a stage nobody has measured keeps today's ceiling instead of being narrowed blind.
    """
    env = os.environ.get(MINIMAX_MAX_TOKENS_ENV)
    if env:
        try:
            n = int(env)
            if n >= 1:
                return n
        except (TypeError, ValueError):
            pass
    if stage is None:
        from .telemetry import STAGE
        stage = STAGE.get("") or ""
    with _MINIMAX_MAX_TOKENS_LOCK:
        table = _MINIMAX_MAX_TOKENS_BY_STAGE
    return table.get(stage, MINIMAX_MAX_TOKENS_DEFAULT)


def set_moat_primary(names) -> frozenset[str]:
    """Install the process-wide trusted set (called by `config.load_config`).

    Falsy `names` RESETS to `MOAT_PRIMARY_DEFAULT` rather than leaving the previous load's
    value in place: a config with no `moat_primary:` key must mean the default, in every
    process, whatever was loaded before it.
    """
    global _MOAT_PRIMARY
    resolved = (_coerce_moat_primary(names, source="config.yaml `moat_primary:`")
                if names else None)
    with _MOAT_PRIMARY_LOCK:
        _MOAT_PRIMARY = resolved
    return resolved if resolved is not None else MOAT_PRIMARY_DEFAULT


def is_provisional_provider(name: str) -> bool:
    """True if a ruling served by brain `name` must be treated as provisional (a cheap
    fallback brain, not a trusted moat primary). An empty/unknown name is conservatively
    treated as trusted=False -> provisional, so we never silently finalise an unknown."""
    return name not in moat_primary()


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


#: Both tables now live in `prospector.tiers`, a leaf module with no imports, and are
#: re-exported here so every existing `from prospector.operator import BUILDABLE_TIERS` keeps
#: working. See that file for why.
from .tiers import BUILDABLE_TIERS, COMPONENTS  # noqa: E402,F401


def component_pin(cfg, component: str | None, kind: str) -> str:
    """The model `component` pins for provider `kind`, or "" when it pins nothing.

    Reads `config.yaml component_models.<component>.<kind>`. Returns "" for every shape that is
    not an explicit non-blank string, including the MagicMock configs the unit suite builds —
    a Mock attribute is truthy, and treating one as a pin would hand every mocked test a model
    name that looks like `<MagicMock id=...>`.
    """
    if not component:
        return ""
    table = getattr(cfg, "component_models", None)
    if not isinstance(table, dict):
        return ""
    row = table.get(component)
    if not isinstance(row, dict):
        return ""
    val = row.get(kind)
    return val.strip() if isinstance(val, str) else ""


def resolve_model(cfg, kind: str, *, component: str | None = None,
                  fast: bool = False) -> str | None:
    """The single answer to "which model does <component> run on <provider>?".

    Three layers, most specific first:

      1. `component_models.<component>.<kind>` — this chain, this provider. Lets the moat run
         MiniMax-M3 while the non-critical tail runs something cheaper, without either config
         being able to move the other.
      2. `model_defaults.<kind>` (`<kind>_fast` when `fast` and that field is set) — the
         estate-wide default for that provider. Unchanged; this is where the models live today.
      3. `None` — the adapter's own default.

    Returns `None`, never "", for "nothing pinned": every adapter already reads `None` as
    "use your default", and an empty string would be passed through as a model name.
    """
    pin = component_pin(cfg, component, kind)
    if pin:
        return pin
    md = getattr(cfg, "model_defaults", None)
    if md is None:
        return None
    if fast:
        f = getattr(md, f"{kind}_fast", None)
        if isinstance(f, str) and f.strip():
            return f.strip()
    d = getattr(md, kind, None)
    return d.strip() if isinstance(d, str) and d.strip() else None


def _build_operator(kind: str, cfg, fast: bool, component: str | None = None) -> Operator:
    """Construct one provider tier, with the model `component` pins for it.

    `fast=True` selects the lighter model for mechanical calls (query-gen, prescreen).
    `component` is one of `COMPONENTS`, or `None` for a caller that is not a named chain —
    `None` simply skips layer 1 of `resolve_model` and behaves exactly as this function did
    before per-component pins existed.

    What was here until 2026-08-19: a `_PROVIDER_MODEL_PREFIX` table that guessed whether the
    estate-wide `cfg.model` "belonged to" the provider being built by matching a name prefix.
    Measured: the value it computed was used at exactly one construction site (`ollama`), whose
    prefix tuple was empty, so the match was always False and the model always `None`. The
    guess never selected a model for anything. `resolve_model` replaces it with an explicit
    per-component lookup, so which model a chain uses is a line in config.yaml, not an inference
    from a string.
    """
    md = getattr(cfg, "model_defaults", None)
    # There is deliberately no `model = resolve_model(...)` here. It was assigned on this line
    # and never read by any branch below -- ruff F841, pre-existing on main and invisible there
    # because the gate scopes ruff to the STAGED files and nobody had staged this one since.
    # Each `kind` resolves its own pin instead, and does it in a shape `resolve_model` cannot:
    # adapters like MiniMax take BOTH a full and a fast model and pick by `cheap=fast`, where
    # `resolve_model` collapses the pair to one string. So the inline layering is the richer
    # one, not a partial copy. `resolve_model` now has no call site anywhere in the repo.
    if kind == "claude_cli":
        # cfg.model is an API pin for a hosted tier; it must not leak to the claude CLI, whose
        # model names are different. But passing nothing is not free either: the CLI then uses
        # the machine's own default, which was measured as `opus[1m]` on 2026-08-19. So this
        # tier always carries an explicit pin, and it defaults to the cheapest Claude.
        from .claude_cli import CHEAPEST_CLAUDE_MODEL, ClaudeCliOperator
        return ClaudeCliOperator(
            model=(component_pin(cfg, component, "claude_cli")
                   or (getattr(cfg, "claude_cli_model", "") or "").strip()
                   or CHEAPEST_CLAUDE_MODEL))
    if kind == "claude":
        raise ValueError(
            "operator 'claude' (the PAID Anthropic API tier) was removed on 2026-08-15 "
            "(founder directive). It needed ANTHROPIC_API_KEY, which this estate does not "
            "set, so it could not construct at all. Use 'claude_cli' — the Claude Code "
            "SUBSCRIPTION CLI, which is unaffected. Update config.yaml "
            "`operator:`/`artifact_operator:`/`noncritical_operator:`.")
    if kind == "mock":
        return MockOperator()
    if kind == "minimax":
        # MiniMax is routed to non-verification tasks only (generation, marketing,
        # artifacts).  fast=True uses the cheap/structured model; fast=False uses
        # the full reasoning model. Both defaults come from cfg.model_defaults.
        # NEVER use cfg.model/cfg.model_fast here — those are Gemini-specific pins.
        # `model` is the component pin when there is one; without it this is exactly
        # `model_defaults.minimax` / `.minimax_fast`, which is what it was before.
        pin = component_pin(cfg, component, "minimax")
        return MiniMaxOperator(
            cheap=fast,
            default_model=pin or (md.minimax if md else None),
            fast_model=pin or (md.minimax_fast if md else None),
        )
    if kind == "minimax_m27":
        # The SECOND non-critical tier, added 2026-08-15. Same account, same adapter, a
        # DIFFERENT model — that is the entire point. `noncritical_operator: [minimax]` was one
        # tier deep and produced 231 terminal `Generation chain EXHAUSTED` against 67 for the
        # two-tier moat chain, so the gap was chain DEPTH, not model behaviour, and a second
        # tier pinned to the SAME model would have inherited every stall it was meant to survive.
        #
        # It is a separate `kind` string on purpose: FallbackOperator keys both its in-run
        # breaker and its persisted dead mark on the chain's tier NAME (`_raw`, above), so
        # reusing "minimax" would have benched this tier the moment M3 was benched — an inert
        # fallback that reads as depth. It must never LEAD: M2.7 measured 29.5s against M3's
        # 8.1s on a generation prompt (2026-08-15), so it buys survivability, never latency.
        m27 = (component_pin(cfg, component, "minimax_m27")
               or (md.minimax_m27 if md else None) or "MiniMax-M2.7")
        return MiniMaxOperator(cheap=fast, default_model=m27, fast_model=m27)
    if kind == "deepseek":
        # Routed to non-verification tasks only (prescreen, scoring, content).
        # MUST NOT be used for kill-check verdicts or adversarial analysis (the moat).
        # NEVER use cfg.model/cfg.model_fast here — those are Gemini-specific pins.
        return DeepSeekOperator(
            default_model=(component_pin(cfg, component, "deepseek")
                           or (md.deepseek if md else None)),
        )
    if kind == "ollama":
        # Ollama: fully local, zero token cost. OpenAI-compatible endpoint.
        # Routed to non-verification tasks only (generation, prescreen, scoring).
        # MUST NOT be used for kill-check verdicts or adversarial analysis (the moat).
        return OllamaOperator(
            model=component_pin(cfg, component, "ollama") or None,
            default_model=md.ollama if md else None,
        )
    if kind == "openrouter":
        # WHY THIS BRANCH IS NEW AND THE CLASS ABOVE IS NOT. `OpenRouterOperator` has been in
        # this file since before 2026-08-19 — ~300 lines with per-model circuit breakers, health
        # marking, Retry-After handling and a priority rotation — and NOTHING could construct it.
        # There was no branch here and no other call site in the repo, so `operator: [openrouter]`
        # raised `unknown operator`. Its own docstring described "the factory passes it as
        # `default_models`" and named `cfg.model_defaults.openrouter`, a field that did not exist.
        # Built and unreachable is its own defect class; this is the two lines that end it.
        #
        # It is the provider that makes "add a provider" cheap: OpenRouter fronts many vendors,
        # so a new model behind it is a config edit, not an adapter. It stays OUT of the moat by
        # policy — its own class docstring bars it from verdicts, and the free models it rotates
        # through are not what should rule a £49 deliverable.
        pin = component_pin(cfg, component, "openrouter")
        declared = getattr(md, "openrouter", None) if md else None
        return OpenRouterOperator(
            models=[pin] if pin else None,
            default_models=list(declared) if isinstance(declared, (list, tuple)) and declared else None,
        )
    # standardcompute was removed here on 2026-08-15 (founder directive), same treatment as
    # cursor_cli below: an EXPLICIT error, not an unknown-operator one, so a stale config or plist
    # fails loudly at startup instead of silently building a chain one brain shorter than it reads.
    if kind == "standardcompute":
        raise ValueError(
            "operator 'standardcompute' was removed on 2026-08-15 (founder directive): "
            "STANDARDCOMPUTE_API_KEY is unset in this estate and the free trial is spent, so the "
            "adapter returned an out-of-allowance upsell body instead of a completion and every "
            "call through it paid a guaranteed failure first. Use 'minimax' for non-critical work "
            "and 'claude_cli' for the moat. Update config.yaml "
            "`operator:`/`artifact_operator:`/`noncritical_operator:`.")
    # cursor_cli was removed here on 2026-08-06 (founder directive). It stays an EXPLICIT
    # error rather than an unknown one, so a stale config or plist fails loudly at startup
    # instead of silently building a chain one brain shorter than it reads.
    if kind == "cursor_cli":
        raise ValueError(
            "operator 'cursor_cli' was removed on 2026-08-06 (founder directive; it was "
            "measured at its usage limit and every call paid a guaranteed failure first). "
            "Use claude_cli. Update config.yaml `operator:`/`artifact_operator:`.")
    # CONFIG-DECLARED PROVIDERS, last. It runs after every built-in branch and after the two
    # removed-tier fences above, so a declaration can neither shadow a built-in nor bring back a
    # removed name. `providers.parse_declared` refuses both at load as well; this ordering is the
    # second lock, because a Config can also be built by hand in a test or a script.
    from .providers import buildable_tiers as _buildable_tiers
    declared = getattr(cfg, "providers", {}) or {}
    spec = declared.get(kind)
    if spec is not None:
        # Same model layering as the minimax branch: a component pin overrides BOTH models, so
        # `component_models.moat.<name>` moves the moat's model without moving the cheap tail's.
        pin = component_pin(cfg, component, kind)
        return OpenAICompatibleOperator(
            name=spec.name,
            base_url=spec.base_url,
            api_key_env=spec.api_key_env,
            model=pin or spec.model,
            fast_model=pin or spec.fast_model,
            max_tokens=spec.max_tokens,
            timeout_s=spec.timeout_s,
            cheap=fast,
        )
    raise ValueError(f"unknown operator: {kind!r} "
                     f"(expected {'|'.join(_buildable_tiers(declared))}). "
                     "Note `minimax_fast` is NOT an operator name — it is a `model_defaults` "
                     "field consumed by the `minimax` branch above. A name that is neither a "
                     "built-in tier nor a key under config.yaml `providers:` is a typo.")


def make_operator(cfg, fast: bool = False, component: str | None = "moat") -> Operator:
    # operator may be a single name or an ordered fallback chain.
    # Sync CLI concurrency governors from config (env overrides still win).
    r0 = getattr(cfg, "retrieval", None)
    if r0 is not None:
        try:
            from .claude_cli import configure_concurrency as _claude_conc
            _claude_conc(int(getattr(r0, "claude_concurrency", 1) or 1))
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
            built.append((k, _build_operator(k, cfg, fast, component=component)))
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
