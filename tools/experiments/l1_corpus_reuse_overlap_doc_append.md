### L1 — L1 corpus-reuse sizing against §13's 20% bar (measurement only)

_Run 2026-08-07T20:23:54+00:00 · `l1_corpus_reuse_overlap.py` · registered docs/COMMERCIAL_READINESS_PROGRAM.md §13 (line ~452)_

- **checks measured**: 7,774
- **M1 url hit (decisive)**: 1698/7774 = 21.84%
- **M2 exact query hit**: 9/7774 = 0.12%
- **M3 topic hit, template stripped (upper bound)**: 194/7774 = 2.50%
- **M3 topic hit, RAW (confounded)**: 209/7774 = 2.69%
- **§13 bar**: 20%
- **margin against the bar**: +1.84pp
- **same rate under a 30-day freshness TTL**: 19.71%
- **decision**: BUILD (CONDITIONAL — a 30-day TTL puts it below the bar)
- **what to build**: url/passage-keyed store — reuse is document-level; the query-keyed and query-embedding forms both miss the bar

**Verdict:** BUILD — 1698/7774 = 21.84% of checks refetched a url an earlier candidate had already retrieved, clearing §13's 20% bar by +1.84pp. CONDITIONAL: the margin does not survive a freshness policy — with a 30-day TTL the rate is 19.71%, BELOW the bar. §13 specifies 'serve from corpus when fresh-enough', so the build decision is a decision about the TTL, not about the corpus.

Population / selection rule: every check in every parseable dossier json: 7774 checks across 1587 dossiers. No sampling. Replay is created_at-ascending with a path tiebreak; same-candidate reuse excluded by construction.

Limitations:
- M1 counts an OBSERVED refetch of the same url. It is a lower bound on corpus value: a corpus could also serve a DIFFERENT url that answers the same question, which M1 cannot see and M3 only proxies lexically.
- M3 is a lexical Jaccard over query tokens, not an embedding similarity. It is reported as the ceiling for the embedding-index version, not as its prediction.
- M3_topic_raw is confounded by verify.py's fixed query template tails, which are byte-identical across candidates. Only M3_topic_stripped answers the question; the raw figure is published so the size of the confound is visible.
- Replay order uses dossier `created_at`. Dossiers missing it sort first and can only under-count hits, never inflate them.
- Nothing was built. This module writes no passage store, no index and no cache.

Receipt: `tools/experiments/l1_corpus_reuse_overlap_receipts.json` — reproduce with `.venv/bin/python tools/experiments/runner.py run L1`

**Follow-through:** TICKET #566 — BUILD at 21.84% but only without a freshness policy; a 30-day TTL puts it at 19.71%, below the bar. The TTL is a decision about serving stale evidence to a buyer, which is a founder call, not an engineering one.
