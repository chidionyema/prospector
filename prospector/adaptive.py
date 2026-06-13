"""Adaptive-creativity controller (Part 3).
Adjusts exploration_level based on the rolling kill-rate to find fresh niches.
"""
from __future__ import annotations

from .models import Decision
from .store import Store


def calculate_exploration_level(store: Store, window: int = 50) -> float:
    """Determine the creativity level (0.0 to 1.0) based on recent kill-rate.
    
    If the moat is killing almost everything (>90%), we raise exploration
    to vary the lens and find fresh patterns.
    """
    rows = store.all()
    if not rows:
        return 0.5
    
    # Sort by creation date descending to get most recent
    rows.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    recent = rows[:window]
    
    kills = sum(1 for r in recent if r.get("decision") == Decision.KILL.value)
    kill_rate = kills / len(recent)
    
    # High kill-rate (>90%) -> Maximum exploration
    if kill_rate >= 0.9:
        return 1.0
    # Healthy kill-rate (70-90%) -> High exploration
    if kill_rate >= 0.7:
        return 0.8
    # Low kill-rate (<30%) -> Low exploration (exploit current patterns)
    if kill_rate <= 0.3:
        return 0.2
    
    # Default/Medium
    return 0.5


def get_recent_failure_modes(store: Store, window: int = 20) -> str:
    """Summarise recent hard-fail gates to avoid repeating dead-ends."""
    rows = store.all(decision=Decision.KILL.value)
    rows.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    recent = rows[:window]
    
    gates = [r.get("gate_fired") for r in recent if r.get("gate_fired")]
    if not gates:
        return ""
        
    counts = {}
    for g in gates:
        counts[g] = counts.get(g, 0) + 1
        
    sorted_gates = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    summary = ", ".join(f"{g} ({c})" for g, c in sorted_gates[:3])
    return f"Recent kill-gates: {summary}"
