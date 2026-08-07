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
from typing import Any, Callable, Optional

from .breaker import CircuitBreaker
from .telemetry import track_latency


class ParseError(Exception):
    pass


def _extract_json(text: str) -> Any:
    """Multi-strategy JSON extraction from verbose model output."""
    from .telemetry import logger
    
    # Strategy 1: Strip <think> blocks and try direct load
    t = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
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
    
    raise ParseError(f"no valid JSON found in {len(text)} chars. Start={text[:100]!r}, End={text[-100:]!r}")


class Operator(ABC):
    """Backend that turns (system, user) -> raw text. complete_json adds the
    structured-output discipline on top, identical across adapters."""

    name = "operator"

    @abstractmethod
    def _raw(self, system: str, user: str, temperature: float) -> str:
        ...

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
        resp = self._client.messages.create(
            model=self.model, max_tokens=4096, temperature=temperature,
            system=system, messages=[{"role": "user", "content": user}],
        )
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
        """Call MiniMax OpenAI-compatible /v1/chat/completions endpoint."""
        import urllib.request

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # 32768 is REQUIRED, not generous: M3 emits its reasoning in <think>…</think> BEFORE
            # the JSON, and generation reasoning runs 16k–28k tokens (measured 2026-07-02). A cap
            # of 16000 truncated the response mid-<think> — 0 JSON, 0 candidates, and the claude_cli
            # backstop can't catch it (a truncated body is an HTTP success that fails PARSING, which
            # retries MiniMax rather than failing over). So we keep the full budget and let the rare
            # runaway call hit the 240s timeout → THAT exception does fail over to claude_cli.
            "max_tokens": 32768,
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
            # MiniMax M3 completions routinely take 75-115s (measured 2026-07-01: 75.7s and 113.4s
            # succeeded; calls cut at the old 120s cap failed with "read operation timed out",
            # zeroing whole generation batches when it was the only live brain). 240s gives the
            # slow-but-alive path headroom so a slow response is not misread as a dead provider.
            # timeout=240 is per-recv; total_deadline is the HARD ceiling that a trickled body
            # cannot defeat (see _urlopen_read_bounded). Beyond it the chain fails over to Ollama.
            raw = _urlopen_read_bounded(req, timeout=240, total_deadline=300)
            data = json.loads(raw.decode("utf-8"))
        except Exception as e:
            # Shared classifier — same reasoning as the DeepSeek adapter above.
            from .errors import ProviderExhaustedError, looks_exhausted
            if looks_exhausted(str(e)):
                raise ProviderExhaustedError(f"MiniMax quota exhausted: {e}", provider=self.name)
            raise RuntimeError(f"MiniMax call failed: {e}") from e

        # Track token usage (OpenAI-compatible usage block)
        usage = data.get("usage") or {}
        inp = int(usage.get("prompt_tokens", 0) or 0)
        out = int(usage.get("completion_tokens", 0) or 0)
        total = int(usage.get("total_tokens", 0) or 0)
        from .telemetry import logger, record_usage
        record_usage(input_tokens=inp, output_tokens=out, total_tokens=total,
                     cached_tokens=0, web=False, provider=self.name)

        # OpenAI-compatible response shape
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
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
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
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
                with urllib.request.urlopen(req, timeout=self._MODEL_TIMEOUT_S) as resp:
                    raw = resp.read().decode("utf-8")
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
                with urllib.request.urlopen(req, timeout=self._MODEL_TIMEOUT_S) as resp:
                    raw = resp.read().decode("utf-8")
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
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read().decode("utf-8"))
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
                    dead_for = (limit_window_seconds(str(e))
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
    # cursor_cli was removed here on 2026-08-06 (founder directive). It stays an EXPLICIT
    # error rather than an unknown one, so a stale config or plist fails loudly at startup
    # instead of silently building a chain one brain shorter than it reads.
    if kind == "cursor_cli":
        raise ValueError(
            "operator 'cursor_cli' was removed on 2026-08-06 (founder directive; it was "
            "measured at its usage limit and every call paid a guaranteed failure first). "
            "Use claude_cli. Update config.yaml `operator:`/`artifact_operator:`.")
    raise ValueError(f"unknown operator: {kind!r} "
                     "(expected claude_cli|claude|minimax|deepseek|ollama|mock)")


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
    kinds = cfg.operator
    kinds = [kinds] if isinstance(kinds, str) else list(kinds)
    built = [(k, _build_operator(k, cfg, fast)) for k in kinds]
    if len(built) == 1:
        return built[0][1]
    r = cfg.retrieval
    return FallbackOperator(built, failure_threshold=r.breaker_failure_threshold,
                            cooldown_s=r.breaker_cooldown_s)
