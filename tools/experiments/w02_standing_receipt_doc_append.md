### W0.2 standing receipt — 2026-08-07 .. 2026-08-13

- vetted: **577**, decisions {'kill': 559, 'pass': 18}, provisional 9
- PASS rate: **18/577** (95% CI 2.0%–4.9%)
- unverifiable: **1742/2743** checks; retrieval_failed 0, degraded 0
- confidence gap (ruled − unverifiable): **-0.0405**
- composite: {'n': 142, 'mean': 2.0606, 'median': 2.1, 'p10': 1.55, 'p90': 2.6, 'min': 0.0, 'max': 3.0} against bar 2.5
- spend: {"ledger": "/Users/chidionyema/Documents/code/prospector/store/prospector.jsonl", "days_requested": 7, "days_covered": ["2026-08-07", "2026-08-08", "2026-08-09", "2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13"], "days_with_rows": ["2026-08-07", "2026-08-08", "2026-08-09", "2026-08-10", "2026-08-11", "2026-08-13"], "days_unknown_dropped_by_checkpoint": [], "scan_span_oldest_day": "2026-06-27", "metered_usd": 5.091444, "subscription_usd": 1643.551725, "complete": true, "note": "metered is billed money and is what daily_cap_usd enforces; subscription is Claude Code CLI burn (cost_usd, no event key), API-equivalent and not invoiced. They differ by orders of magnitude \u2014 report both or neither."}
- $/vetted: {"metered_usd_per_vetted": 0.008824, "subscription_usd_per_vetted": 2.848443}

Re-run: `.venv/bin/python tools/experiments/w02_standing_receipt.py --days 7`

**Follow-through:** SHIPPED prospector/verify.py — the confidence inversion this receipt has been reporting since it was written is guarded in PR #570: an unverifiable ruling scores 0.0 grounding confidence. Full-corpus measurement in `tools/experiments/e19_confidence_gap.py`. No line number on purpose; grep `Verdict.UNVERIFIABLE`.
