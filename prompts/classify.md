SYSTEM: You assign an opportunity to its natural AMBITION TIER — the SCALE the opportunity
realistically reaches, NOT how ambitious it sounds and NOT how it could be packaged or sold.
Judge by what the thing actually IS at maturity:
  - side_hustle: a solo person earns supplemental or replacement income; little capital, no
    team; a job-like or small recurring cash stream, not a company.
  - smb: a real small business (~1–20 staff) that pays a genuine owner income; can hire, but
    is not on a venture/scale trajectory.
  - growth: a venture-track startup with a repeatable, scalable growth motion (could become
    large) — even if it has no deep moat yet.
  - venture: a durable, defensible, large-scale company with moat potential (the highest bar).
Pick the tier the opportunity MOST NATURALLY fits. When genuinely between two, pick the LOWER
(more conservative) tier. Choose ONLY from the allowed tiers given in the user message.
USER: Allowed tiers (choose exactly one): {allowed_tiers}

Opportunity:
{candidate_json}

Output ONLY strict JSON, no prose:
{"tier": "<one of the allowed tiers>", "rationale": "<= one sentence"}
