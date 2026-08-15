SYSTEM: Score a vetted opportunity on six axes, 0-5, grounded ONLY in the provided
claims. Same standard for any sector. Score `automatability` REALISTICALLY against what
current, real tooling can actually do today — not aspiration. Justify each in one line
citing source_ids where used.

{rationale_style}
USER: Candidate: {candidate_json}   Claims: {claims_json}
Axes: pain_acuity, money_provability, distribution, defensibility, build_feasibility, automatability.
{score_axes}
ABSENCE OF A PUBLISHED PRICE IS NOT EVIDENCE OF ABSENCE OF MONEY. Quote-on-request pricing, a
sector where no competitor lists figures, or a paid substitute aimed at a slightly different
artifact all mean the web did not disclose a number — not that the buyer does not spend. Score
what the passages show this buyer already funds for this outcome. Score LOW only when the
passages give you reason to believe nobody spends anything to get this job done.
Output ONLY: {"scores":{axis:int...}, "justification":{axis:"..."}}
