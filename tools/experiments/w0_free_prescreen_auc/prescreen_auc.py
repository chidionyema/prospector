"""Does prescreen's own score predict the paid outcome?

This is the question k=50 rests on. `schedule.batch_size` bounds how many candidates reach
the PAID moat, so raising `candidates_per_signal` only widens the pool that
`novelty.select_diverse_candidates` (`novelty.py:42`) picks from — and its criterion is
`prescreen_score(i) * exp(-lambda * max sim(i,j))` (`novelty.py:51`). If `prescreen_score`
carries no signal, k=50 buys generation cost and a more diverse, not better, 15.

The counterfactual arm is unobservable — nothing ever vets a prescreen-DROPPED candidate.
But the KEPT arm is fully observable and it is the weaker-to-refute half: if prescreen's
score cannot separate pass from kill among candidates it kept, it will not rank a wider pool.

Joins `store/prescreen_shadow/shadow-*.jsonl` (candidate_id, llm_score, llm_keep) to the
labelled dossier outcomes.
"""
import json, glob, os, math, collections

HERE = os.path.dirname(os.path.abspath(__file__))
labelled = json.load(open(os.path.join(HERE, 'labelled.json')))
outcome = {}
for r in labelled:
    if r['decision'] in ('pass', 'kill'):
        # Dossier files are `<candidate_id>.json` for passes and `<candidate_id>.kill.json`
        # for kills — the outcome is encoded in the NAME, so a naive splitext leaves `.kill`
        # attached and the join silently returns 0 rows.
        stem = os.path.basename(r['file'])
        for suf in ('.json', '.kill', '.pass', '.defer'):
            if stem.endswith(suf):
                stem = stem[: -len(suf)]
        outcome[stem] = 1 if r['decision'] == 'pass' else 0

shadow = []
for f in glob.glob('store/prescreen_shadow/shadow-*.jsonl'):
    for line in open(f):
        line = line.strip()
        if line:
            try:
                shadow.append(json.loads(line))
            except Exception:
                pass
print(f"shadow rows: {len(shadow)}   labelled outcomes: {len(outcome)}")
print(f"llm_keep=False in shadow: {sum(1 for s in shadow if s.get('llm_keep') is False)}")

joined = [(s, outcome[s['candidate_id']]) for s in shadow
          if s.get('candidate_id') in outcome]
print(f"JOINED (shadow row has a dossier outcome): {len(joined)}")
if not joined:
    ids_s = {s.get('candidate_id') for s in shadow}
    print("  no join. sample shadow ids:", list(ids_s)[:3])
    print("  sample outcome ids       :", list(outcome)[:3])
    raise SystemExit(0)

n_pass = sum(o for _, o in joined)
print(f"  of which pass={n_pass}  kill={len(joined)-n_pass}")


def auc(pairs):
    """Rank AUC of score vs binary outcome, average ranks on ties."""
    pairs = sorted(pairs, key=lambda t: t[0])
    n = len(pairs)
    ranks = [0.0] * n
    i = 0; r = 1
    while i < n:
        j = i
        while j + 1 < n and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        avg = (r + r + (j - i)) / 2.0
        for t in range(i, j + 1):
            ranks[t] = avg
        r += (j - i + 1); i = j + 1
    n1 = sum(o for _, o in pairs); n0 = n - n1
    if n1 == 0 or n0 == 0:
        return float('nan')
    s1 = sum(ranks[t] for t in range(n) if pairs[t][1] == 1)
    return (s1 - n1 * (n1 + 1) / 2.0) / (n1 * n0)


scored = [(float(s.get('llm_score') or 0.0), o) for s, o in joined
          if s.get('llm_score') is not None]
print(f"\nAUC of prescreen llm_score vs PASS: {auc(scored):.3f}   (n={len(scored)})")

print("\n--- pass rate by prescreen score bucket")
buckets = collections.defaultdict(lambda: [0, 0])
for sc, o in scored:
    b = round(sc, 1)
    buckets[b][0] += 1; buckets[b][1] += o
for b in sorted(buckets):
    n, p = buckets[b]
    print(f"    score {b:>4}  n={n:<5} pass={p:<4} {p/n:6.1%}")

vals = [sc for sc, _ in scored]
print(f"\nscore spread: min={min(vals)} max={max(vals)} distinct={len(set(vals))}")
print("A score with almost no spread cannot rank anything, whatever its AUC says.")
