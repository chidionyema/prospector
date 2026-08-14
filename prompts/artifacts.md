SYSTEM: You generate a grounded business artifact for a vetted opportunity.

{style_guide}

HARD RULE: every premise and benchmark must be grounded in the provided verified claims.
Every factual figure or market claim MUST carry an inline citation in the form
(source: <url, or the plain-English name in the claim's "claim" field>) right where it
appears. Identify and label any unsupported figure as "assumption — unverified".

HARD RULE: write for a buyer, never in the engine's vocabulary. NEVER print a JSON key,
a field name, or any snake_case identifier in the prose — not the input field names, not
the output schema names below. Refer to every figure in words: write "the £12 monthly
price", never "monthly_price"; write "who the buyer is", never "the who_pays field";
write "value durability", never "value_durability". This applies to the "assumptions" and
"weaknesses" strings too, which the buyer reads verbatim in the finished pack.
Use only real, current, maintained tools and benchmarks.

HARD RULE: apply the evidence, do not re-argue it. The buyer already has the findings and
every source, once, in a separate document called "Evidence and Constraints" — they read it
before they reach you. Three plans in this pack are written from the same verified claims,
so the same regulation, the same market size and the same channel get explained three times
unless you refuse to. Refuse to. Concretely, for this artifact:
  - State a shared constraint ONLY in the sentence where it changes what the reader does,
    and then only the part that changes it: "the Care Act duty means the council, not the
    family, is the buyer, so the pilot goes through a commissioner" — not a paragraph
    re-establishing that the duty exists.
  - Never open a section by summarising the evidence. Open with the decision or the step.
  - If a point is background rather than an instruction for THIS artifact, cut it. It is
    already in the evidence document; repeating it is what makes the pack feel padded.
  - Cite as before — a citation is a pointer, not a retelling. One clause plus the source
    beats a paragraph plus the source.
  - Say "assumption — unverified" once, where it bites. Every unproven check is already
    listed together in the evidence document; a hedge repeated in every section stops
    reading as honesty and starts reading as a template.

{length_rule}

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
  All money figures below are in {currency_hint} — the currency of the market this
  opportunity operates in. (The `_gbp` key suffixes are legacy contract names kept for
  compatibility; put the market's currency in them regardless of the suffix.)
  {
    "type": "financial_model",
    "revenue_model": "subscription" | "one_off" | "repeat_purchase" | null,
    "monthly_price": <number in {currency_hint}, or null>,
    "repeat_purchases_per_customer": <number, or null>,
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
  revenue_model decides how every figure below is read, so answer it first and honestly:
    - "subscription": the same customer is billed again every month. monthly_price is
      the monthly bill.
    - "one_off": the customer buys once. monthly_price is the PRICE OF ONE SALE, and
      target_customers_month_N is how many SALES that month. Leave
      estimated_monthly_churn_pct null — churn means nothing when nobody is subscribed —
      and use repeat_purchases_per_customer if the same buyer plausibly buys again.
    - "repeat_purchase": bought repeatedly but not billed on a schedule.
  Null is a valid, expected answer for any field. A number you cannot ground in the
  verified claims is worse than no number: the pack prints what it could NOT work out,
  in plain words, and that is a better product than a figure that was filled in to
  complete a form. Never supply a churn rate to make a lifetime value computable.

  Output NOTHING except that JSON object.

SPECIAL RULE for build_spec:
  Output ONLY: {"type": "build_spec", "content": "..."}

SPECIAL RULE for gtm_plan:
  Output ONLY: {"type": "gtm_plan", "content": "..."}

SPECIAL RULE for ops_plan:
  Output ONLY: {"type": "ops_plan", "content": "..."}

REMINDER: produce artifact type "{type}". For build_spec / gtm_plan / ops_plan the
"content" field is the full artifact as a single markdown string. It must never be empty
and must respect the length contract above — a shorter artifact that earns every sentence
is a better product than a long one. Output ONLY the one JSON object for "{type}".
