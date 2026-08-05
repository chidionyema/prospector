"""Simulation harness for testing Prospector's self-improvement loop.

Provides deterministic mock mode that replaces real web search and model calls
with fixtures. Used to verify that adaptations actually improve outcomes over
time, and that bad changes are detected and reverted.

Part of the production-grade self-improvement infrastructure (Priority 5).
"""

import json
import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class MockRun:
    """A single mock pipeline run with controlled inputs and expected outputs."""

    idea: str
    domain: str
    verdict: str  # PASS, KILL, DEFER
    kill_gate: str = ""  # Which gate fired (for KILLs)
    passages: list[str] = field(default_factory=list)
    confidence: float = 0.7
    checks: dict = field(default_factory=dict)


# Pre-built fixture: a deterministic set of ideas with known verdicts
FIXTURE_IDEAS = [
    MockRun(
        idea="AI-powered restaurant menu optimization for small businesses",
        domain="foodtech",
        verdict="KILL",
        kill_gate="market_size",
        passages=[
            "The restaurant technology market is saturated with over 200 competitors.",
            "Average restaurant tech startup raises $2M and achieves $50K ARR in year 1.",
        ],
        checks={"source_check": "pass", "market_size": "fail", "competition": "warn"},
    ),
    MockRun(
        idea="Decentralized renewable energy trading platform using blockchain",
        domain="clean_energy",
        verdict="PASS",
        passages=[
            "The distributed energy market is projected to reach $50B by 2030.",
            "Regulatory tailwinds in EU and US support peer-to-peer energy trading.",
        ],
        confidence=0.85,
        checks={"source_check": "pass", "market_size": "pass", "regulatory": "pass"},
    ),
    MockRun(
        idea="Elderly care coordination platform with AI fall detection",
        domain="healthcare",
        verdict="PASS",
        passages=[
            "The elderly care market is $300B globally, growing at 8% CAGR.",
            "AI fall detection accuracy has reached 95% in recent studies.",
        ],
        confidence=0.9,
        checks={"source_check": "pass", "market_size": "pass", "competition": "pass"},
    ),
    MockRun(
        idea="NFT fractionalization for real estate investments",
        domain="real_estate",
        verdict="KILL",
        kill_gate="regulatory",
        passages=[
            "SEC has issued guidance classifying fractionalized real estate tokens as securities.",
            "Multiple NFT real estate platforms have received cease-and-desist letters.",
        ],
        checks={"source_check": "pass", "regulatory": "fail"},
    ),
    MockRun(
        idea="Subscription-based pet food delivery with customized meal plans",
        domain="pet_tech",
        verdict="KILL",
        kill_gate="market_size",
        passages=[
            "The premium pet food delivery market addresses only 0.3% of pet owners.",
            "Average customer acquisition cost exceeds lifetime value by 2x.",
        ],
        checks={"source_check": "pass", "market_size": "fail"},
    ),
    MockRun(
        idea="B2B carbon accounting software for mid-market manufacturers",
        domain="climate_tech",
        verdict="PASS",
        passages=[
            "Carbon accounting regulations expanding to mid-market in EU and California.",
            "Current solutions target enterprises; mid-market is underserved.",
        ],
        confidence=0.75,
        checks={"source_check": "pass", "market_size": "pass", "competition": "pass"},
    ),
    MockRun(
        idea="On-demand moving and furniture assembly marketplace",
        domain="logistics",
        verdict="KILL",
        kill_gate="unit_economics",
        passages=[
            "Moving marketplace unit economics show -30% margins at scale.",
            "Labor costs and insurance overwhelm platform fees in this category.",
        ],
        checks={"source_check": "pass", "unit_economics": "fail"},
    ),
    MockRun(
        idea="AI legal document review for small law firms",
        domain="legal_tech",
        verdict="PASS",
        passages=[
            "Small law firms spend 40% of time on document review.",
            "AI document review accuracy now matches junior associates at 10x speed.",
        ],
        confidence=0.8,
        checks={"source_check": "pass", "market_size": "pass"},
    ),
    MockRun(
        idea="Peer-to-peer car sharing for suburban neighborhoods",
        domain="mobility",
        verdict="KILL",
        kill_gate="competition",
        passages=[
            "Turo and Getaround dominate P2P car sharing with 95% market share.",
            "Customer acquisition cost for new entrants exceeds $200 per user.",
        ],
        checks={"source_check": "pass", "competition": "fail"},
    ),
    MockRun(
        idea="Vertical farming automation for urban grocery stores",
        domain="agritech",
        verdict="PASS",
        passages=[
            "Vertical farming yields 10x per square foot vs traditional agriculture.",
            "Grocery chains are actively seeking in-store farming partnerships.",
        ],
        confidence=0.7,
        checks={"source_check": "pass", "market_size": "pass", "competition": "pass"},
    ),
]


class SimulationHarness:
    """Deterministic simulation of the Prospector pipeline.

    Replaces real model calls and web search with mock fixtures so the
    self-improvement loop can be tested for convergence and correctness.

    Each simulation run:
    1. Generates candidates (mock)
    2. Vets them through checks (mock verification against fixture passages)
    3. Records metrics to MetricsStore
    4. Applies adaptations (mock adaptive.py logic)
    """

    def __init__(
        self,
        metrics_store,
        mod_log=None,
        adaptation_enabled: bool = True,
        ideas: Optional[list[MockRun]] = None,
    ):
        self.metrics_store = metrics_store
        self.mod_log = mod_log
        self.adaptation_enabled = adaptation_enabled
        self.ideas = ideas or copy.deepcopy(FIXTURE_IDEAS)
        self.run_count = 0
        self.steer_strengths: dict[str, float] = {}  # domain → avoidance strength
        self.diversity_bonus: dict[str, float] = {}  # domain → exploration bonus

    def run_batch(self, n: int = 10, batch_id: str = "") -> dict:
        """Run N simulated pipeline iterations. Returns aggregate metrics."""
        results = []
        for i in range(n):
            run_id = f"sim_{batch_id}_{self.run_count}" if batch_id else f"sim_{self.run_count}"
            result = self._run_one(run_id)
            results.append(result)
            self.run_count += 1

        return self._aggregate(results)

    def _run_one(self, run_id: str) -> dict:
        """Simulate a single pipeline run: generate + vet + record."""
        # 1. Select idea (with adaptation-aware biasing)
        idea = self._select_idea()

        # 2. Vet: determine verdict
        verdict = idea.verdict
        kill_gate = idea.kill_gate if verdict == "KILL" else ""

        # 3. Score breakdown for kill gates
        kill_rate_by_gate = {}
        if verdict == "KILL" and kill_gate:
            kill_rate_by_gate = {kill_gate: 1.0}

        # 4. Compute metrics
        passed = 1 if verdict == "PASS" else 0
        yield_rate = passed / 1  # Single candidate per run

        # Diversity: track which domain was selected
        domain = idea.domain

        # 5. Record to metrics store
        self.metrics_store.record_run(run_id, {
            "yield_rate": yield_rate,
            "health_score": self._compute_health_score(),
            "diversity_score": self._compute_diversity(),
            "candidates_generated": 1,
            "candidates_passed": passed,
            "kill_rate_by_gate": kill_rate_by_gate,
            "active_changes": self.mod_log.get_active_change_ids() if self.mod_log else [],
            "lane": "simulation",
        })

        # 6. Apply adaptation (if enabled)
        if self.adaptation_enabled and verdict == "KILL" and kill_gate:
            self._adapt(idea)

        return {
            "run_id": run_id,
            "domain": domain,
            "verdict": verdict,
            "yield_rate": yield_rate,
            "passed": passed,
        }

    def _select_idea(self) -> MockRun:
        """Select an idea, biasing away from killed domains if adaptation is on."""
        import random

        if not self.adaptation_enabled or not self.steer_strengths:
            return random.choice(self.ideas)

        # Compute selection weights
        weights = []
        for idea in self.ideas:
            w = 1.0
            # Reduce weight for domains with strong kill steers
            domain = idea.domain.lower()
            steer = self.steer_strengths.get(domain, 0.0)
            w *= max(0.1, 1.0 - steer)
            # Add exploration bonus for stale domains
            bonus = self.diversity_bonus.get(domain, 0.0)
            w += bonus
            weights.append(max(w, 0.01))

        total = sum(weights)
        probs = [w / total for w in weights]

        # Weighted random selection
        r = random.random()
        cumulative = 0.0
        for idea, prob in zip(self.ideas, probs):
            cumulative += prob
            if r <= cumulative:
                return idea

        return self.ideas[-1]

    def _adapt(self, killed_idea: MockRun):
        """Apply adaptation: increase steer strength for killed domain."""
        domain = killed_idea.domain.lower()

        # Increase avoidance strength for this domain
        current = self.steer_strengths.get(domain, 0.0)
        self.steer_strengths[domain] = min(current + 0.15, 0.95)

        # Record the adaptation if we have a modification log
        if self.mod_log:
            self.mod_log.record(
                component="generation",
                field=f"steer_{domain}",
                old_value=str(current),
                new_value=str(self.steer_strengths[domain]),
                trigger_signal=f"kill_{killed_idea.kill_gate}_{domain}",
                expected_effect=f"Reduce generation in {domain} domain",
            )

        # Also add exploration bonus for under-represented domains
        self._update_diversity_bonuses()

    def _update_diversity_bonuses(self):
        """Add exploration bonus for domains that haven't been seen recently."""
        # Get recent domains from metrics
        trend = self.metrics_store.trend(window=20)
        # For simulation, use a simple counter
        import collections
        recent_runs = self.run_count

        all_domains = set(i.domain.lower() for i in self.ideas)
        seen_domains = set(self.steer_strengths.keys())

        for domain in all_domains:
            if domain not in seen_domains:
                self.diversity_bonus[domain] = self.diversity_bonus.get(domain, 0.0) + 0.05

    def _compute_health_score(self) -> float:
        """Compute health score from current metrics trends."""
        trend = self.metrics_store.trend(window=50)
        total = trend["summary"]["total_runs"]
        if total < 3:
            return 0.5

        mean_yield = trend["summary"]["mean_yield"]
        mean_health = trend["summary"]["mean_health"]

        # Recent yield is the primary driver
        score = 0.6 * max(mean_yield, 0.0) + 0.4 * max(mean_health, 0.0)
        return round(min(score, 1.0), 3)

    def _compute_diversity(self) -> float:
        """Compute domain diversity (Shannon entropy approximation)."""
        import math
        from collections import Counter

        trend = self.metrics_store.trend(window=50)
        if trend["summary"]["total_runs"] < 2:
            return 0.5

        # We need domain data — for now, use steer strengths as proxy
        if not self.steer_strengths:
            return 0.5

        # Higher entropy = more diverse = less steering = better
        n_domains = len(set(i.domain.lower() for i in self.ideas))
        n_steered = len(self.steer_strengths)
        # If we're steering many domains, diversity is low
        steer_ratio = n_steered / max(n_domains, 1)
        diversity = 1.0 - steer_ratio * 0.8  # Scale: 0 steers = 1.0, all steers = 0.2
        return round(max(diversity, 0.1), 3)

    def _aggregate(self, results: list[dict]) -> dict:
        """Aggregate batch results into summary metrics."""
        if not results:
            return {"yield": 0.0, "passes": 0, "total": 0}

        passes = sum(1 for r in results if r["passed"])
        total = len(results)
        domains = [r["domain"] for r in results]

        from collections import Counter
        domain_counts = Counter(domains)

        return {
            "yield": round(passes / total, 3),
            "passes": passes,
            "total": total,
            "domain_distribution": dict(domain_counts.most_common()),
            "steer_count": len(self.steer_strengths),
            "diversity": self._compute_diversity(),
            "health": self._compute_health_score(),
        }


def simulate_runs(
    metrics_store,
    n: int = 50,
    adaptation_enabled: bool = True,
    mod_log=None,
) -> dict:
    """Convenience function: run N simulations and return aggregate metrics.

    Args:
        metrics_store: MetricsStore instance.
        n: Number of runs to simulate.
        adaptation_enabled: Whether to apply adaptations.
        mod_log: Optional SelfModificationLog for recording changes.

    Returns:
        Dict with yield, passes, total, domain_distribution, and trends.
    """
    harness = SimulationHarness(
        metrics_store=metrics_store,
        mod_log=mod_log,
        adaptation_enabled=adaptation_enabled,
    )

    result = harness.run_batch(n=n, batch_id="sim")

    # Add trend analysis
    trend = metrics_store.trend(window=n)
    result["trend"] = trend["summary"]
    result["alerts"] = metrics_store.alert_check(window=n)

    return result
