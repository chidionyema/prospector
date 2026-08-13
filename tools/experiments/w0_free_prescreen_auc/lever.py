"""Is the lane/market pass-rate gap a real free lever, or a time effect in disguise?

The only out-of-time signal W0.1 found was metadata (AUC 0.610), and lane_base.py showed it
is lane base rates. Before that funds a steering change it has to survive two challenges:
  1. Wilson intervals — is the gap bigger than the noise on 106 US rows?
  2. Time confound — if US / side_hustle generation only STARTED recently, and the engine
     also got better recently, the "lane effect" is just recency wearing a lane's name.
"""
import json, os, math, collections
HERE = os.path.dirname(os.path.abspath(__file__))
rows = json.load(open(os.path.join(HERE, 'labelled.json')))
d = [r for r in rows if r['decision'] in ('pass', 'kill') and r['created'][:10] >= '2026-07-01']


def wilson(p_count, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = p_count / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, c - h), min(1.0, c + h))


for key in ('tier', 'market'):
    print(f"\n--- {key}: pass rate with 95% Wilson CI (>=2026-07-01, n={len(d)})")
    agg = collections.defaultdict(lambda: [0, 0])
    for r in d:
        a = agg[r.get(key) or '(none)']
        a[0] += 1; a[1] += (r['decision'] == 'pass')
    for k, (n, p) in sorted(agg.items(), key=lambda kv: -kv[1][1] / max(kv[1][0], 1)):
        lo, hi = wilson(p, n)
        print(f"    {k:<14} n={n:<5} pass={p:<4} {p/n:6.1%}   95% CI [{lo:.1%}, {hi:.1%}]")

# --- time confound: is the mix itself moving?
print("\n--- MIX BY MONTH (share of candidates generated in each lane/market)")
by_month = collections.defaultdict(lambda: collections.Counter())
pass_by_month = collections.defaultdict(lambda: [0, 0])
for r in d:
    m = r['created'][:7]
    by_month[m]['n'] += 1
    by_month[m][f"tier:{r.get('tier') or '(none)'}"] += 1
    by_month[m][f"mkt:{r.get('market') or '(none)'}"] += 1
    pass_by_month[m][0] += 1
    pass_by_month[m][1] += (r['decision'] == 'pass')
for m in sorted(by_month):
    c = by_month[m]; n = c['n']
    tot, ps = pass_by_month[m]
    print(f"  {m}  n={n:<5} pass={ps} ({ps/tot:.1%})   "
          f"us={c['mkt:us']/n:.0%} uk={c['mkt:uk']/n:.0%}  "
          f"side_hustle={c['tier:side_hustle']/n:.0%} smb={c['tier:smb']/n:.0%}")

# --- the decisive control: hold the month fixed, compare markets WITHIN it
print("\n--- WITHIN-MONTH market comparison (kills the recency explanation)")
for m in sorted({r['created'][:7] for r in d}):
    sub = [r for r in d if r['created'][:7] == m]
    line = [f"  {m}"]
    for mkt in ('us', 'uk'):
        s = [r for r in sub if (r.get('market') or '') == mkt]
        if not s:
            line.append(f"{mkt}: n=0"); continue
        p = sum(1 for r in s if r['decision'] == 'pass')
        lo, hi = wilson(p, len(s))
        line.append(f"{mkt}: {p}/{len(s)}={p/len(s):.1%} [{lo:.0%},{hi:.0%}]")
    print("   ".join(line))
