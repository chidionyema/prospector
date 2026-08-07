"""Market-Readiness Gate (Epic D).

A market is CLOSED until the engine demonstrates it can actually SEE it. "Seeing" is
measured, not asserted: a fixed calibration set of candidates with known outcomes runs
through the real pipeline in that market, and four numbers must clear their bars.

The bars are all about EVIDENCE, never about the verdict bar itself. That distinction is
the whole point: if a market yields nothing, the engine has failed to find evidence
there, and the answer is better queries, better authority domains, or not opening the
market. The answer is never a lower threshold — which is why `MARKET_FORBIDDEN_KEYS` in
config.py makes lowering it a load error rather than a temptation.

Artifact: `store/markets/<code>/READINESS.json`, holding the measurements, the verdict,
and a fingerprint of the config the probe ran under. `markets open` refuses to act on a
stale artifact, so a market cannot be opened on the strength of a probe that measured a
different configuration.
"""
from __future__ import annotations

import datetime
import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from .config import Config
from .models import Decision, Verdict

READINESS_FILENAME = "READINESS.json"

# The four bars a market must clear. Deliberately conservative — a market opened on thin
# evidence produces confident-looking dossiers grounded in nothing, which is worse than
# no market at all.
DEFAULT_BARS: dict[str, float] = {
    # Fraction of checks that reached a real verdict (supported/refuted) rather than
    # unverifiable. The core question: can the engine find evidence here at all?
    "min_grounding_rate": 0.55,
    # Fraction of retrieved sources on the market's own authority domains. Guards the
    # failure where a market "grounds" entirely on blogs and content farms.
    "min_authority_rate": 0.25,
    # Agreement with the calibration set's known outcomes. Guards the opposite failure:
    # plenty of evidence, but the engine reads it wrong in this jurisdiction.
    "min_discrimination": 0.70,
    # A market where nothing survives is not calibrated, it is blind.
    "min_pass_rate": 0.05,
}


@dataclass
class ProbeOutcome:
    """One calibration candidate's result."""
    title: str
    expected: str                  # "pass" | "kill"
    actual: str                    # "pass" | "kill" | "defer"
    gate_fired: str = ""
    grounded_checks: int = 0
    total_checks: int = 0
    authority_sources: int = 0
    total_sources: int = 0

    @property
    def correct(self) -> bool:
        return self.actual == self.expected

    @property
    def decided(self) -> bool:
        """DEFER is infrastructure failure, not a judgement — it must not count as a
        wrong answer, and it must not count as a right one either."""
        return self.actual in (Decision.PASS.value, Decision.KILL.value)


@dataclass
class Readiness:
    market: str
    verdict: str                   # "ready" | "not_ready"
    measured_at: str
    config_fingerprint: str
    n_candidates: int
    metrics: dict[str, float]
    bars: dict[str, float]
    failures: list[str] = field(default_factory=list)
    outcomes: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.verdict == "ready"


def config_fingerprint(cfg: Config, market: str) -> str:
    """Hash of everything that determines what a probe in this market measures.

    If any of it changes, the stored measurement no longer describes the running system
    and must not be used to justify opening the market.

    Operational `status` is excluded: `markets open` flips closed→open and must not
    make a just-used READY probe look STALE (same class of bug as lane-resolved
    fingerprints — see test_fingerprint_stable_across_status_flip).
    """
    block = dict(cfg.market_config(market) or {})
    block.pop("status", None)
    material = json.dumps({
        "market": block,
        "hard_gates": cfg.hard_gates,
        "thresholds": asdict(cfg.thresholds),
        "weights": cfg.weights,
    }, sort_keys=True, default=str)
    return hashlib.sha1(material.encode()).hexdigest()[:16]


def readiness_path(cfg: Config, market: str) -> Path:
    """Where the readiness artifact lives for `market`.

    `readiness_ref` in config is store-relative (e.g. `store/markets/us/READINESS.json`).
    Resolve it under `cfg.store_dir` so `PROSPECTOR_STORE_DIR` isolation cannot be
    bypassed by a repo-relative string (CLI tests previously raced the live artifact).
    """
    ref = (cfg.market_config(market) or {}).get("readiness_ref")
    if not ref:
        return cfg.store_dir / "markets" / market / READINESS_FILENAME
    path = Path(ref)
    if path.is_absolute():
        return path
    parts = path.parts
    # Strip a leading `store/` so the path joins onto whatever store_dir resolves to.
    if parts and parts[0] == "store":
        parts = parts[1:]
    return cfg.store_dir.joinpath(*parts) if parts else cfg.store_dir / READINESS_FILENAME


def load_readiness(cfg: Config, market: str) -> Optional[Readiness]:
    path = readiness_path(cfg, market)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return Readiness(**data)


def bars_for(cfg: Config, market: str) -> dict[str, float]:
    """Bars for this market: the defaults, overridable per market ONLY upward.

    A market may demand MORE of itself, never less. Anything else would reintroduce the
    bar-lowering shortcut through the back door of the gate that exists to prevent it.
    """
    bars = dict(DEFAULT_BARS)
    for key, value in ((cfg.market_config(market) or {}).get("readiness_bars") or {}).items():
        if key in bars and float(value) > bars[key]:
            bars[key] = float(value)
    return bars


def _rate(numerator: float, denominator: float) -> float:
    return (numerator / denominator) if denominator else 0.0


def evaluate(cfg: Config, market: str, outcomes: list[ProbeOutcome]) -> Readiness:
    """Turn probe outcomes into a readiness verdict."""
    bars = bars_for(cfg, market)
    decided = [o for o in outcomes if o.decided]

    metrics = {
        "grounding_rate": _rate(sum(o.grounded_checks for o in outcomes),
                                sum(o.total_checks for o in outcomes)),
        "authority_rate": _rate(sum(o.authority_sources for o in outcomes),
                                sum(o.total_sources for o in outcomes)),
        "discrimination": _rate(sum(1 for o in decided if o.correct), len(decided)),
        "pass_rate": _rate(sum(1 for o in decided if o.actual == Decision.PASS.value),
                           len(decided)),
        "defer_rate": _rate(len(outcomes) - len(decided), len(outcomes)),
    }

    failures: list[str] = []
    for bar_key, metric_key in (("min_grounding_rate", "grounding_rate"),
                                ("min_authority_rate", "authority_rate"),
                                ("min_discrimination", "discrimination"),
                                ("min_pass_rate", "pass_rate")):
        if metrics[metric_key] < bars[bar_key]:
            failures.append(
                f"{metric_key} {metrics[metric_key]:.2f} < {bars[bar_key]:.2f}")

    # An all-DEFER probe measured the outage, not the market. Refuse to rule either way.
    if not decided:
        failures.append("every calibration candidate DEFERRED — the probe measured an "
                        "infrastructure outage, not the market; re-run when it recovers")

    return Readiness(
        market=market,
        verdict="ready" if not failures else "not_ready",
        measured_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        config_fingerprint=config_fingerprint(cfg, market),
        n_candidates=len(outcomes),
        metrics={k: round(v, 4) for k, v in metrics.items()},
        bars=bars,
        failures=failures,
        outcomes=[asdict(o) for o in outcomes],
    )


def save_readiness(cfg: Config, readiness: Readiness) -> Path:
    path = readiness_path(cfg, readiness.market)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(readiness), indent=2), encoding="utf-8")
    return path


def outcome_from_dossier(expected: str, dossier) -> ProbeOutcome:
    """Extract the probe measurements from a completed vet."""
    checks = list(getattr(dossier, "checks", []) or [])
    grounded = sum(1 for c in checks
                   if c.verdict in (Verdict.SUPPORTED, Verdict.REFUTED))
    sources = [s for c in checks for s in (getattr(c, "sources", []) or [])]
    return ProbeOutcome(
        title=dossier.candidate.title,
        expected=expected,
        actual=dossier.decision.value,
        gate_fired=getattr(dossier, "gate_fired", "") or "",
        grounded_checks=grounded,
        total_checks=len(checks),
        authority_sources=sum(1 for s in sources if _is_authority(s)),
        total_sources=len(sources),
    )


def _is_authority(source) -> bool:
    """True when the source sits on a domain the active market treats as authoritative.

    Reads the same ContextVar the fetch timeouts use, so "authority" means exactly one
    thing across the engine rather than two definitions that can drift apart.
    """
    import urllib.parse

    from .retrieval import _HIGH_AUTHORITY_DOMAINS, _market_authority_domains

    try:
        netloc = urllib.parse.urlparse(str(getattr(source, "url", "")).lower()).netloc
    except Exception:  # noqa: BLE001
        return False
    if netloc.startswith("www."):
        netloc = netloc[4:]
    if not netloc:
        return False
    if netloc.endswith(".gov") or netloc.endswith(".edu") or netloc.endswith(".int"):
        return True
    domains = _HIGH_AUTHORITY_DOMAINS | _market_authority_domains.get()
    return any(netloc == d or netloc.endswith("." + d) for d in domains)


def load_calibration_set(path: str | Path) -> list[dict[str, Any]]:
    """Read a JSONL calibration set: one {"title","one_liner","expected"} per line."""
    entries: list[dict[str, Any]] = []
    for i, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        entry = json.loads(line)
        expected = str(entry.get("expected", "")).lower()
        if expected not in (Decision.PASS.value, Decision.KILL.value):
            raise ValueError(
                f"{path}:{i}: 'expected' must be 'pass' or 'kill', got {expected!r}. "
                f"A calibration entry with no known outcome measures nothing.")
        if not str(entry.get("title", "")).strip():
            raise ValueError(f"{path}:{i}: entry needs a 'title'")
        entries.append(entry)
    if not entries:
        raise ValueError(f"{path}: calibration set is empty")
    if not any(e["expected"] == Decision.PASS.value for e in entries):
        raise ValueError(
            f"{path}: calibration set has no expected-PASS entries, so discrimination "
            f"would be satisfied by an engine that kills everything")
    if not any(e["expected"] == Decision.KILL.value for e in entries):
        raise ValueError(
            f"{path}: calibration set has no expected-KILL entries, so discrimination "
            f"would be satisfied by an engine that passes everything")
    return entries


def format_readiness(r: Readiness) -> str:
    """Human-readable probe report."""
    lines = [
        f"Market readiness — {r.market}",
        f"  verdict:     {'READY' if r.ready else 'NOT READY'}",
        f"  measured:    {r.measured_at}",
        f"  candidates:  {r.n_candidates}",
        f"  fingerprint: {r.config_fingerprint}",
        "",
        f"  {'metric':<18}{'measured':>10}{'bar':>10}",
    ]
    for bar_key, metric_key in (("min_grounding_rate", "grounding_rate"),
                                ("min_authority_rate", "authority_rate"),
                                ("min_discrimination", "discrimination"),
                                ("min_pass_rate", "pass_rate")):
        measured = r.metrics.get(metric_key, 0.0)
        bar = r.bars.get(bar_key, 0.0)
        mark = "ok " if measured >= bar else "FAIL"
        lines.append(f"  {metric_key:<18}{measured:>10.2f}{bar:>10.2f}  {mark}")
    lines.append(f"  {'defer_rate':<18}{r.metrics.get('defer_rate', 0.0):>10.2f}"
                 f"{'—':>10}")
    if r.failures:
        lines.append("")
        lines.append("  blocking:")
        lines.extend(f"    - {f}" for f in r.failures)
    return "\n".join(lines)
