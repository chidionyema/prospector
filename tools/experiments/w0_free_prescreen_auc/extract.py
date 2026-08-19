"""Pull the features the free-prescreen AUC experiment scores, from stored dossiers into a flat
table. Read-only over `store/`; writes only into this experiment's own directory.
"""
import json, glob, os, collections, statistics

OUT = os.path.dirname(os.path.abspath(__file__))
rows = []; bad = 0; skipped = collections.Counter()

for f in glob.glob('store/dossiers/*.json'):
    try:
        d = json.load(open(f))
    except Exception:
        bad += 1; continue
    if not isinstance(d, dict) or 'decision' not in d or 'candidate' not in d:
        skipped['no_decision_or_candidate'] += 1; continue
    c = d.get('candidate') or {}
    if not isinstance(c, dict):
        skipped['candidate_not_dict'] += 1; continue
    rows.append(dict(
        file=os.path.basename(f),
        decision=str(d.get('decision', '')),
        gate=str(d.get('gate_fired') or ''),
        provisional=bool(d.get('provisional')),
        tier=str(d.get('ambition_tier') or ''),
        created=str(d.get('created_at') or ''),
        n_checks=len(d.get('checks') or []),
        one_liner=str(c.get('one_liner') or c.get('oneliner') or ''),
        title=str(c.get('title') or ''),
        market=str(c.get('market') or ''),
        archetype=str(c.get('archetype') or ''),
        lane=str(c.get('lane') or c.get('ambition_tier') or ''),
        cand_keys=sorted(c.keys()),
    ))

print("=== TOTALS ===")
print("dossiers with decision:", len(rows), "| unreadable:", bad,
      "| skipped:", sum(skipped.values()), dict(skipped))

print("\n=== DECISION DISTRIBUTION ===")
for k, v in collections.Counter(r['decision'] for r in rows).most_common():
    print(f"  {k!r:16s} {v:5d}")

print("\n=== GATE_FIRED DISTRIBUTION (all decisions) ===")
for k, v in collections.Counter(r['gate'] for r in rows).most_common(25):
    print(f"  {(k or '(none)'):30s} {v:5d}")

print("\n=== KILL-ONLY gate distribution + composite-only share ===")
kills = [r for r in rows if 'KILL' in r['decision'].upper()]
gc = collections.Counter(r['gate'] for r in kills)
COMPOSITE = {'min_composite', 'source_or_die'}
comp = sum(v for k, v in gc.items() if k in COMPOSITE)
print(f"  total kills: {len(kills)}")
for k, v in gc.most_common():
    tag = '  <-- COMPOSITE-ONLY (pays for every check)' if k in COMPOSITE else ''
    print(f"    {(k or '(none)'):30s} {v:5d}{tag}")
print(f"  COMPOSITE-ONLY SHARE: {comp}/{len(kills)} = {100.0*comp/max(1,len(kills)):.1f}%")

print("\n=== n_checks by kill gate (does a composite kill really run the full set?) ===")
by = collections.defaultdict(list)
for r in kills:
    by[r['gate']].append(r['n_checks'])
for k, v in sorted(by.items(), key=lambda x: -len(x[1])):
    v = sorted(v)
    print(f"    {(k or '(none)'):30s} n={len(v):5d}  median_checks={statistics.median(v):.1f}"
          f"  min={v[0]}  max={v[-1]}")

print("\n=== CANDIDATE KEYS (union, top 30) ===")
ck = collections.Counter()
for r in rows:
    ck.update(r['cand_keys'])
for k, v in ck.most_common(30):
    print(f"    {k:30s} {v}")

print("\n=== FEATURE COVERAGE ===")
for field in ('one_liner', 'title', 'market', 'archetype', 'tier'):
    print(f"  non-empty {field:12s}: {sum(1 for r in rows if r[field])} / {len(rows)}")

print("\n=== TEMPORAL ===")
ds = sorted(r['created'][:10] for r in rows if r['created'])
if ds:
    print("  earliest", ds[0], " latest", ds[-1], " dated:", len(ds), "/", len(rows))
    for cut in ('2026-07-22', '2026-08-05'):
        print(f"  pre-{cut}: {sum(1 for d in ds if d < cut):5d}   "
              f"post: {sum(1 for d in ds if d >= cut):5d}")

json.dump(rows, open(os.path.join(OUT, 'labelled.json'), 'w'))
print("\nwrote", os.path.join(OUT, 'labelled.json'))
