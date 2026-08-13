# W0.1 — can a FREE proxy rank candidates before the paid moat? — **CLOSED, negative**

**Verdict: no.** Nothing computable from the candidate's own text, at zero tokens, predicts the
paid PASS/KILL outcome out-of-time. Both arms the war plan named were run to completion and both
land at or below chance on the honest split. Admission *ordering* by a free text model loses its
funding. The one free lever that survived is **not** a text model — see "what did survive".

Re-run everything from the repo root (the scripts glob `store/dossiers/*.json` relative to cwd):

```bash
python3 tools/experiments/w0_free_prescreen_auc/extract.py     # -> labelled.json (derived)
python3 tools/experiments/w0_free_prescreen_auc/auc.py         # lexical arm  (auc.out)
python3 tools/experiments/w0_free_prescreen_auc/dense.py       # dense arm    (dense.out)
python3 tools/experiments/w0_free_prescreen_auc/lane_base.py   # is metadata just lane base rates?
python3 tools/experiments/w0_free_prescreen_auc/lever.py       # Wilson + time-confound challenge
python3 tools/experiments/w0_free_prescreen_auc/prescreen_auc.py  # does prescreen's own score predict?
```

`labelled.json` and `emb_cache.json` are **not committed**: the first is derived by `extract.py`
in seconds, the second is 61 MB of embeddings that `dense.py` rebuilds. `auc.out` and `dense.out`
are the run outputs quoted below and ARE committed, because a number nobody can point at is the
thing Wave 0 exists to stop.

## The measurements

n = 1904 labelled dossiers (pass 73, kill 1831). `defer` has no outcome and is excluded.
Pre-registered temporal split: fit on `created_at < 2026-08-05`, test on `>= 2026-08-05`
(train n=1095 / pass 40, test n=809 / pass 33).

| feature | plain temporal | **regime-restricted** (>= 2026-07-01) |
|---|---|---|
| tf-idf logreg (\|V\|=8000) | 0.613 | **0.502** |
| tf-idf kNN centroid (k=15) | 0.449 | 0.417 |
| nomic-embed-text one-liner, logreg | 0.653 | **0.411** |
| nomic-embed-text one-liner, PASS/KILL centroid | 0.655 | 0.409 |
| nomic-embed-text full text, logreg | 0.624 | 0.382 |
| metadata only (tier/market/len) | 0.556 | 0.610 |

The war plan's own decision rule: `AUC ≈ 0.5` → the proxy carries no signal; `AUC > 0.75` →
admission ordering becomes a headline item. Every text feature is in the first bucket.

### Why the regime-restricted column is the one that counts

The plain temporal column is **confounded and must not be quoted**. June 2026 contributed 724
candidates and **zero** passes, so any model fit across that boundary can reach AUC 0.6 by
learning "June-era phrasing ⇒ kill" — a fact about when the engine changed, not about the idea.
Restricting both fit and test to the post-2026-07-01 regime removes that free win, and when it
is removed the lexical arm drops 0.613 → 0.502 and the dense arm drops 0.653 → 0.411.

**Below 0.5 is not "a bit worse than chance" and it is not a bug to fix by flipping the sign.**
A cross-fitted score that inverts out-of-time is what an over-fitted direction looks like when
the regime moves under it; the honest reading is that there is no stable direction to find.

### The 5-fold number is the trap this file exists to record

Stratified 5-fold over all data, ignoring time, gives **0.770 ± 0.038** for tf-idf logreg —
i.e. it *clears* the war plan's 0.75 headline bar. It is worthless. Shuffling folds across the
June boundary puts June rows in both train and test, so the fold model gets to learn the regime
label it is then scored on. Anyone re-opening W0.1 will find this number first; it is quoted here
so that finding it again is not mistaken for a new result.

### The dense arm was the plan's own feature, so it had to be run

The war plan named "local `nomic-embed-text` embedding of the one-liner, k-NN distance to
historical PASS/KILL centroids". Ruling W0.1 on the lexical arm alone would have closed it on a
feature the plan did not ask for. It is installed locally (274 MB, 768-dim) and the repo already
speaks to it (`prospector/prescreen_prefilter.py:149`), so the arm cost zero tokens and zero web
calls — 3805 vectors cached over two passes. All six dense variants land 0.375–0.411.

## What DID survive

**Metadata is the only feature that holds up out-of-time (0.610), and `lane_base.py` shows why:
it is lane base rates, not a judgement about the idea.** Per-lane `min_composite` differs by
construction (3.8 / 3.4 / 2.9 / 2.6 in `config.yaml`), so a metadata model partly re-reads which
gate the candidate was routed to.

`lever.py` challenged the one gap large enough to act on, with Wilson intervals and a
time-confound check: within 2026-08, **US 15/106 = 14.2% [8.8, 22.0] vs UK 38/826 = 4.6%
[3.4, 6.2]** — non-overlapping, 3.1x. That is a steering fact about *where to generate*, and it
is free. It is not a pre-ranker, and it does not reopen W0.1.

## What this does NOT say

It does not say prescreen is useless — `prescreen_auc.py` asks the separate question of whether
prescreen's own LLM score predicts the paid outcome among candidates it *kept*, and the dropped
arm is unobservable by construction (nothing ever vets a prescreen-dropped candidate). It does
not say candidate text is uninformative to a *paid* model. It says a free, zero-token ranker over
that text does not transfer across a regime change, on this corpus, at this n.
