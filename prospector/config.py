"""Typed config loader. The gates/weights/thresholds are DATA (Part 4/13A) so the
golden set can tune them without code changes."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Retrieval:
    provider: str = "fixture"
    queries_per_check: int = 2
    results_per_query: int = 4
    max_passage_chars: int = 1500
    cache: bool = True
    # Checks that skip the LLM query-gen call and use deterministic disconfirming
    # templates instead (cheap decisive gates that kill most candidates).
    template_checks: list[str] = field(default_factory=list)
    fast_queries: int = 1  # query count used for template_checks
    # Web-grounding fail-fast budget. The free gemini web-search tool throttles after a
    # burst and then internally backs off for ~hours, which presents as a 240s hang. A
    # short timeout + few retries makes a throttled search GIVE UP quickly so the candidate
    # DEFERS (re-vet later) instead of blocking the whole run. Verdict calls (no web) are
    # unaffected — they use run_gemini_cli's normal timeout.
    search_timeout: int = 75      # seconds per grounding web-search call
    search_retries: int = 1       # retries for a grounding web-search call (fail fast)


@dataclass
class Thresholds:
    confidence_floor: float = 0.6
    min_composite_to_pass: float = 3.2


@dataclass
class Spend:
    daily_cap_usd: float = 20.0
    warn_at_usd: float = 15.0


@dataclass
class Config:
    operator: str = "mock"
    model: str = ""
    # Optional lighter model for mechanical calls (query-gen, prescreen). Empty
    # => reuse `model` (the CLI already auto-routes utility calls to flash).
    model_fast: str = ""
    model_version_tag: str = ""
    retrieval: Retrieval = field(default_factory=Retrieval)
    thresholds: Thresholds = field(default_factory=Thresholds)
    # hard_gates: list of single-key dicts, preserves kill-fast order
    hard_gates: list[dict[str, Any]] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)
    generation: dict[str, Any] = field(default_factory=dict)
    listing: dict[str, Any] = field(default_factory=dict)
    schedule: dict[str, Any] = field(default_factory=dict)
    spend: Spend = field(default_factory=Spend)
    store: dict[str, Any] = field(default_factory=lambda: {"dir": "store"})

    @property
    def store_dir(self) -> Path:
        d = Path(self.store.get("dir", "store"))
        return d if d.is_absolute() else REPO_ROOT / d

    def gate_map(self) -> dict[str, list[str]]:
        """Flatten hard_gates to {gate_name: [killing_verdicts]} (excludes adversarial flag)."""
        out: dict[str, list[str]] = {}
        for g in self.hard_gates:
            for k, v in g.items():
                if k != "adversarial_decisive":
                    out[k] = list(v)
        return out

    @property
    def adversarial_decisive_kills(self) -> bool:
        for g in self.hard_gates:
            if "adversarial_decisive" in g:
                return bool(g["adversarial_decisive"])
        return True


def load_config(path: str | Path | None = None) -> Config:
    p = Path(path) if path else REPO_ROOT / "config.yaml"
    raw = yaml.safe_load(p.read_text()) if p.exists() else {}
    return Config(
        operator=raw.get("operator", "mock"),
        model=raw.get("model", ""),
        model_fast=raw.get("model_fast", ""),
        model_version_tag=raw.get("model_version_tag", ""),
        retrieval=Retrieval(**(raw.get("retrieval") or {})),
        thresholds=Thresholds(**(raw.get("thresholds") or {})),
        hard_gates=raw.get("hard_gates") or [],
        weights=raw.get("weights") or {},
        generation=raw.get("generation") or {},
        listing=raw.get("listing") or {},
        schedule=raw.get("schedule") or {},
        spend=Spend(**(raw.get("spend") or {})),
        store=raw.get("store") or {"dir": "store"},
    )
