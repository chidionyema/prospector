"""DPP-based novelty selection (Stage 1).
Greedily selects a diverse subset of candidates using embeddings and prescreen scores.
"""
from __future__ import annotations

import math
from typing import List, Tuple
from .models import Candidate
from .operator import Operator
from .telemetry import logger, track_latency

def cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b: return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0: return 0.0
    return dot / (mag_a * mag_b)

@track_latency(name="select_diverse_candidates")
def select_diverse_candidates(
    op: Operator,
    candidates_with_scores: List[Tuple[Candidate, float, str]],
    k: int,
    lambda_param: float = 0.5
) -> List[Candidate]:
    """Greedily selects k diverse candidates using a DPP-like approach.
    
    Score for candidate i given already selected set S:
      total_score(i) = prescreen_score(i) * exp(-lambda * max_{j in S} sim(i, j))
    """
    if not candidates_with_scores:
        return []
    
    if len(candidates_with_scores) <= k:
        return [c for c, s, f in candidates_with_scores]

    # Generate embeddings for all candidates using the provided features
    embeddings = []
    for cand, score, features in candidates_with_scores:
        # Fallback to title + one_liner if features are empty
        text = features or f"{cand.title} {cand.one_liner}"
        emb = op.embed(text)
        embeddings.append(emb)

    selected_indices: List[int] = []
    
    # 1. Pick the best one first
    best_idx = 0
    max_score = -1.0
    for i, (_, score, _) in enumerate(candidates_with_scores):
        if score > max_score:
            max_score = score
            best_idx = i
    selected_indices.append(best_idx)

    # 2. Greedily pick the rest
    while len(selected_indices) < k:
        best_next_idx = -1
        max_marginal_score = -1.0
        
        for i in range(len(candidates_with_scores)):
            if i in selected_indices:
                continue
            
            cand, score, _ = candidates_with_scores[i]
            emb = embeddings[i]
            
            # Find max similarity to any already selected candidate
            max_sim = 0.0
            for s_idx in selected_indices:
                sim = cosine_similarity(emb, embeddings[s_idx])
                max_sim = max(max_sim, sim)
            
            # Penalty term: exp(-lambda * max_sim)
            # lambda_param controls the trade-off between quality and diversity.
            diversity_penalty = math.exp(-lambda_param * max_sim)
            marginal_score = score * diversity_penalty
            
            if marginal_score > max_marginal_score:
                max_marginal_score = marginal_score
                best_next_idx = i
        
        if best_next_idx == -1:
            break
        selected_indices.append(best_next_idx)

    result = [candidates_with_scores[i][0] for i in selected_indices]
    logger.info(f"DPP Selection: selected {len(result)} diverse candidates from {len(candidates_with_scores)}")
    return result
