# Prospector v2.0 — Durable Ledger
#
# Append-only log of mathematically proven kill-laws.
# The generator reads the last 15 entries before every batch.
# Format: one bullet per law, starting with "* LAW: ..."
#
# Created: 2026-06-23
#
# Purged 2026-08-01: the test suite wrote here on every run (paths bound at import, so
# isolation was a no-op — fixed in middleware.py / moat_prompts.py / tests/conftest.py, and
# guarded by tests/invariants/test_no_production_writes.py). 826 committed bullets held only
# 10 distinct laws; 821 were laws about test spec ids ("abc", "abc123", "test-2", "test-3"),
# which meant every one of the 15 bullets in the generator's window was test noise. The removed
# lines are recoverable from git history (`git show 103daf3:storage/durable_ledger.md`).
#
# The first bullet below is retained but UNATTRIBUTED: "transparent markets" is also the default
# law in the test_v2_rigorous fixture (tests/unit/test_v2_rigorous.py:32), so its 91 copies
# cannot be told apart from a real ruling. Kept once rather than dropped.

* LAW: Do not build wrappers on transparent markets.
* LAW: Do not generate concepts related to abb6f022f0bccd5b  failed moat schema validation 3 times.
* LAW: Do not generate concepts related to 45acf9336cafdc91  failed moat schema validation 3 times.
* LAW: Do not generate concepts related to 656ee509e6dd9c6d  failed moat schema validation 3 times.
* LAW: Do not generate concepts related to 376d6d047fa6c3ac  failed moat schema validation 3 times.
* LAW: Do not generate AI meeting assistants targeting SMBs without a strong regulatory or compliance pain point.