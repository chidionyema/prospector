"""Is the metadata-only AUC (0.610 out-of-time) just lane base rates?

If tier/market alone separates pass from kill, that is not a prediction about the IDEA.
It is the model re-reading which lane the candidate was routed into, whose pass rate
differs by construction (per-lane min_composite: 3.8/3.4/2.9/2.6, config.yaml).
"""
import json, os, collections
HERE = os.path.dirname(os.path.abspath(__file__))
rows = json.load(open(os.path.join(HERE, 'labelled.json')))
d = [r for r in rows if r['decision'] in ('pass', 'kill') and r['created'][:10] >= '2026-07-01']
print(f"post-regime n={len(d)} pass={sum(1 for r in d if r['decision']=='pass')}")

for key in ('tier', 'market'):
    print(f"\n--- pass rate by {key} (>=2026-07-01)")
    agg = collections.defaultdict(lambda: [0, 0])
    for r in d:
        a = agg[r.get(key) or '(none)']
        a[0] += 1
        a[1] += (r['decision'] == 'pass')
    for k, (n, p) in sorted(agg.items(), key=lambda kv: -kv[1][1] / max(kv[1][0], 1)):
        print(f"    {k:<22} n={n:<5} pass={p:<4} rate={p/n:.1%}")
