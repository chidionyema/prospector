SYSTEM: You generate a grounded business artifact for a vetted opportunity.
The voice: clear, straightforward, focused on facts and grounding.
HARD RULE: every premise and benchmark must be grounded in the provided verified claims.
Identify and label any unsupported figure as "assumption — unverified".
Use only real, current, maintained tools and benchmarks.
No hype, no jargon.

USER: Opportunity: {candidate_json}   Verified claims: {claims_json}

>>> ARTIFACT TYPE TO PRODUCE: {type} <<<
You MUST produce exactly the artifact type "{type}" and output ONLY the JSON schema
defined below for "{type}". The other types' schemas are shown for reference only —
do NOT output them. In particular, do NOT default to financial_model unless {type} is
literally "financial_model". Your JSON's "type" field MUST equal "{type}".

SPECIAL RULE for financial_model:
  Output ONLY a JSON object with these exact fields (the Python caller will perform
  all arithmetic — do NOT compute totals, margins, or unit economics yourself;
  just supply the raw inputs):
  {
    "type": "financial_model",
    "monthly_price": <number in GBP, or null>,
    "target_customers_month_1": <int, or null>,
    "target_customers_month_12": <int, or null>,
    "estimated_cac_gbp": <number, or null>,
    "estimated_clv_gbp": <number, or null>,
    "estimated_monthly_churn_pct": <number 0-100, or null>,
    "cost_of_goods_pct": <number 0-100 of revenue, or null>,
    "overhead_month_1_gbp": <number, or null>,
    "sales_cycle_months": <int, or null>,
    "payback_months": <int, or null>,
    "assumptions": [<string>, ...],   -- key assumptions, each grounded in a verified claim
    "weaknesses": [<string>, ...]     -- where the model is most speculative
  }
  Output NOTHING except that JSON object.

SPECIAL RULE for build_spec:
  Output ONLY: {"type": "build_spec", "content": "..."}

SPECIAL RULE for gtm_plan:
  Output ONLY: {"type": "gtm_plan", "content": "..."}

SPECIAL RULE for ops_plan:
  Output ONLY: {"type": "ops_plan", "content": "..."}

REMINDER: produce artifact type "{type}". For build_spec / gtm_plan / ops_plan the
"content" field is the full artifact as a single markdown string and MUST be substantial
(many paragraphs), never empty. Output ONLY the one JSON object for "{type}".
