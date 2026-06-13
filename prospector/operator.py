"""The pluggable 'brain' (Part 1). Same tooling, swappable operator.

Every model call goes through Operator.complete_json(), which enforces strict JSON
output with repair-retries (Part 9) — a bad parse never crashes a run. Adapters:
  - GeminiOperator: google-genai direct. Default for 'now' (key present).
  - ClaudeOperator: Anthropic API (select once ANTHROPIC_API_KEY is set).
  - MockOperator: deterministic, for tests / fixtures (no network, no spend).

DeepSeek/Minimax etc. are deliberately NOT runtime adapters — they are reserved for
feature build-out via aider, never the verification brain (the moat stays Claude/Gemini).
"""
from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from .telemetry import track_latency


class ParseError(Exception):
    pass


def _extract_json(text: str) -> Any:
    """Best-effort: strip code fences, find the first balanced JSON value."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.MULTILINE).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    # find first { or [ and match to its close
    start = min([i for i in (t.find("{"), t.find("[")) if i != -1], default=-1)
    if start == -1:
        raise ParseError(f"no JSON found in: {text[:200]!r}")
    depth, instr, esc = 0, False, False
    for i in range(start, len(t)):
        c = t[i]
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
                    return json.loads(t[start:i + 1])
    raise ParseError(f"unbalanced JSON in: {text[:200]!r}")


class Operator(ABC):
    """Backend that turns (system, user) -> raw text. complete_json adds the
    structured-output discipline on top, identical across adapters."""

    name = "operator"

    @abstractmethod
    def _raw(self, system: str, user: str, temperature: float) -> str:
        ...

    @property
    def model_version(self) -> str:
        return self.name

    @track_latency(name="operator_complete_json")
    def complete_json(self, system: str, user: str, *,
                      temperature: float = 0.7, retries: int = 2,
                      validate: Optional[Callable[[Any], Any]] = None) -> Any:
        """Strict-JSON call with repair-retries. Raises ParseError only if all
        attempts fail (callers decide fail-safe behaviour, e.g. -> unverifiable)."""
        from .telemetry import logger
        logger.info(f"LLM completion started: {self.name}", extra={"retries_allowed": retries})
        
        last_err: Optional[Exception] = None
        sys = system + "\n\nReturn ONLY valid JSON. No prose, no code fences."
        for attempt in range(retries + 1):
            try:
                text = self._raw(sys, user, temperature)
                data = _extract_json(text)
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
        self.name = f"claude/{model}"

    @track_latency(name="claude_raw_call")
    def _raw(self, system: str, user: str, temperature: float) -> str:
        resp = self._client.messages.create(
            model=self.model, max_tokens=4096, temperature=temperature,
            system=system, messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


class GeminiOperator(Operator):
    def __init__(self, model: str = "gemini-2.0-flash", api_key: Optional[str] = None):
        from google import genai
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY not set")
        self._client = genai.Client(api_key=key)
        self.model = model
        self.name = f"gemini/{model}"

    @track_latency(name="gemini_raw_call")
    def _raw(self, system: str, user: str, temperature: float) -> str:
        from google.genai import types
        resp = self._client.models.generate_content(
            model=self.model, contents=f"{system}\n\n{user}",
            config=types.GenerateContentConfig(temperature=temperature),
        )
        return resp.text or ""


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
        if self.router:
            out = self.router(system, user)
            if out is not None:
                return json.dumps(out)
        for key, val in self.responses.items():
            if key in system or key in user:
                return json.dumps(val)
        return "{}"


def make_operator(cfg, fast: bool = False) -> Operator:
    kind = cfg.operator
    # fast=True selects the lighter model for mechanical calls (query-gen,
    # prescreen); falls back to the main model when model_fast is unset.
    model = (getattr(cfg, "model_fast", "") or cfg.model) if fast else cfg.model
    if kind == "gemini_cli":
        from .gemini_cli import GeminiCliOperator
        return GeminiCliOperator(model=(model or None))
    if kind == "gemini":
        return GeminiOperator(model=model)
    if kind == "claude":
        return ClaudeOperator(model=model)
    if kind == "mock":
        return MockOperator()
    raise ValueError(f"unknown operator: {kind!r} (expected gemini|claude|mock)")
