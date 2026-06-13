SYSTEM: Score a vetted opportunity on six axes, 0-5, grounded ONLY in the provided
claims. Same standard for any sector. Score `automatability` REALISTICALLY against what
current, real tooling can actually do today — not aspiration. Justify each in one line
citing source_ids where used.
USER: Candidate: {candidate_json}   Claims: {claims_json}
Axes: pain_acuity, money_provability, distribution, defensibility, build_feasibility, automatability.
Output ONLY: {"scores":{axis:int...}, "justification":{axis:"..."}}
