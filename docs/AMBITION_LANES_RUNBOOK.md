# Ambition lanes — runbook

**Who this is for:** you, without an agent. How to change what *kind* of business ideas the
engine generates (solo side-hustle vs small-team vs venture-scale startup), and how to prove the
change actually reached the running daemon.

Written 2026-08-01, after the fix described in "The bug this replaced" at the bottom.

---

## 1. The one-paragraph model

A **lane** (a.k.a. ambition tier) is the *bar* an idea is judged against. An **archetype** is the
*founder capacity* an idea is generated for. They are different axes, wired together in
`config.yaml`:

| lane | archetype | means |
|---|---|---|
| `side_hustle` | `solo_agent` | one AI-leveraged person, no team, no capital, owned/free distribution |
| `smb` | `small_team` | 2–10 people, modest seed capital OK, paid acquisition allowed |
| `growth` | `startup` | venture-track founding team, must show a repeatable growth motion |
| `venture` | `startup` | unicorn-ambition, must clear the durable-moat bar |

A third axis, **market**, is the jurisdiction (uk/us) — orthogonal to both. See
`docs/` + `config.yaml` `markets:` block.

**The lane changes the bar and the generation framing. It never lowers the moat.** Grounding
(source-or-die) is identical in every lane.

---

## 2. Change the mix (the thing you'll actually do)

Everything lives in **`config.yaml`**, in the `active_lane` / `active_lanes` / `lane_quota`
block (search for `^lane_quota`). No code change, no restart of anything but
the daemon.

```yaml
active_lane: ""                              # "" = use active_lanes below. Set to ONE lane
                                             #   name to pin every run to that single tier.
active_lanes: [side_hustle, smb, growth, venture]   # the mixed-ambition fan-out
lane_quota:                                  # candidates generated per tier per run
  side_hustle: 3                             # solo_agent
  smb: 5                                     # small_team
  growth: 4                                  # startup
  venture: 3                                 # startup
```

### Recipes

**"I want more startup ideas, fewer solo ones."** Raise `growth` / `venture`, lower
`side_hustle`. Current shipped values give 12 of 15 non-solo (80%).

**"I want ONLY venture-scale ideas for a while."** Set `active_lane: "venture"`. This pins every
run to one tier and overrides `active_lanes` entirely. Set it back to `""` to return to the mix.

**"Drop a lane without editing YAML by hand."**
```bash
.venv/bin/python -m prospector.run lanes list          # show current config
.venv/bin/python -m prospector.run lanes nix side_hustle
.venv/bin/python -m prospector.run lanes natch side_hustle
```
These rewrite the `active_lanes` line in `config.yaml` in place.

### How the numbers turn into candidates

`lane_quota` values are **weights**, not absolute counts. The batch size comes from
`schedule.batch_size` in `config.yaml` (currently 15). `run.py::_lane_counts` distributes
the batch across lanes proportional to the weights, with a floor of 1 per lane.

The shipped weights sum to exactly 15 = `batch_size`, so they map 1:1 with no rounding. **If you
change `batch_size`, the quota re-proportions** — e.g. batch_size 20 with the same weights gives
roughly 4/7/5/4. Keeping the weights summing to `batch_size` is the easiest way to get exactly
what you typed.

---

## 3. Verify BEFORE you restart (10 seconds, no spend)

This is the check that would have caught the original bug. It resolves the config exactly the way
the daemon does, without generating anything:

```bash
cd /Users/chidionyema/Documents/code/prospector
.venv/bin/python - <<'EOF'
import argparse
from prospector.config import load_config
from prospector.run import _resolve_lanes, _lane_counts
cfg = load_config()
lanes = _resolve_lanes(cfg, argparse.Namespace(lane=None))
counts = _lane_counts(cfg, lanes, cfg.schedule.get("batch_size", 15))
solo = sum(v for t, v in counts.items()
           if cfg.for_lane(t).generation.get("operator_archetype") == "solo_agent")
total = sum(counts.values())
print("lanes :", lanes)
print("counts:", counts, "total", total)
print(f"solo_agent {solo}/{total} | non-solo {total-solo}/{total}")
EOF
```

Expected today:

```
lanes : ['side_hustle', 'smb', 'growth', 'venture']
counts: {'side_hustle': 3, 'smb': 5, 'growth': 4, 'venture': 3} total 15
solo_agent 3/15 | non-solo 12/15
```

If `lanes` prints `None`, the daemon will run the single implicit default (solo_agent only) —
that is the bug state. Check `active_lanes` is non-empty and `active_lane` is `""`.

Then run the guard tests:
```bash
.venv/bin/python -m pytest tests/scheduler/test_daemon_lane_fanout.py -q
```

> Always invoke pytest as `.venv/bin/python -m pytest`. System `python3` lacks `ddgs` and
> manufactures phantom failures.

---

## 4. Restart the daemon (config AND code changes both need this)

The daemon is a long-running process. It reads `config.yaml` **once at startup**, so *any* edit
above requires a restart to take effect. Same for any Python change.

It is supervised by launchd with `KeepAlive=true` and `ThrottleInterval=30`, so **killing it is
the restart** — launchd relaunches it within ~30s with the new code and config.

```bash
# 1. Who is running, and since when?
ps -eo pid,lstart,command | grep "prospector.scheduler.run_scheduled --daemon" | grep -v grep

# 2. Restart (graceful; the daemon traps SIGTERM and stops at the next safe point)
kill <pid>

# 3. Wait ~30s, then confirm a NEW pid with a start time AFTER your edit
sleep 35
ps -eo pid,lstart,command | grep "prospector.scheduler.run_scheduled --daemon" | grep -v grep
```

**The restart test is `lstart` vs file mtime, never the tick log.** Compare the process start
time against `stat -f "%Sm %N" config.yaml`. If the process started *before* the file changed, it
is running stale config no matter what the logs say.

Prefer `launchctl kickstart -k gui/$(id -u)/com.prospector.scheduler` if you want launchd to do
it explicitly rather than relying on KeepAlive.

**Do not** use the `store/scheduler/PAUSE` file to force a reload. Deleting `PAUSE` does not
resume the daemon — it sleeps out the whole 7200s interval first, so a PAUSE/unPAUSE cycle costs
you two hours.

---

## 5. Prove it landed (the only proof that counts)

`pytest` green is necessary, not sufficient. The change is real when a live tick shows it.

A tick takes ~120–150 min and ~$1.20. After the next one completes:

```bash
# Every dossier from a multi-lane run carries ambition_tier. Absent = single-default = the bug.
.venv/bin/python - <<'EOF'
import json, glob, collections
rows = []
for f in glob.glob('store/dossiers/*.json'):
    try: d = json.load(open(f))
    except Exception: continue
    rows.append((d.get('created_at') or '', d.get('ambition_tier') or '<none>'))
rows.sort()
print("last 20 by created_at:", collections.Counter(t for _, t in rows[-20:]).most_common())
EOF
```

You want a spread across `smb` / `growth` / `venture` — **not** `<none>`.

> **Order dossiers by the `created_at` field inside the JSON, never by file mtime.**
> `tools/backfill_market.py --apply` rewrote 861 dossier files inside a 4-second window and
> permanently destroyed mtime ordering. Sorting by mtime gives a confidently wrong answer.

Also peek, every run, per the standing habit:
- `store/scheduler/DIAGNOSTICS_LATEST.txt` — funnel, kill gates, grounding, closest-to-pass
- `store/scheduler/ticks.jsonl` (last row) — dossiers/passes/defers/provisional
- `store/scheduler/heartbeat.json` — live phase and pid

**The mode-collapse tell:** in `DIAGNOSTICS_LATEST.txt`, read the PASSES line and the
closest-to-pass kills together. If they are all the same *shape* (e.g. every one a "fixed-fee pack
for one individual"), generation has collapsed onto a single archetype regardless of what the
config says.

Do **not** try to attribute behaviour from `store/scheduler/audit/*.jsonl` — those rows carry no
pid or run_id, and daemon, backfill and manual runs interleave in the same file.

---

## 6. Tuning on evidence, not vibes

Before re-weighting, get the per-lane PASS rate. This is what justified the 2026-08-01 weights:

```bash
.venv/bin/python - <<'EOF'
import json, glob, collections
tot, pas = collections.Counter(), collections.Counter()
for f in glob.glob('store/dossiers/*.json'):
    try: d = json.load(open(f))
    except Exception: continue
    t = d.get('ambition_tier')
    if not t: continue
    tot[t] += 1
    if d.get('decision') == 'pass': pas[t] += 1
print(f"{'lane':14s}{'vetted':>8s}{'pass':>6s}{'rate':>8s}")
for t in ['side_hustle', 'smb', 'growth', 'venture']:
    r = pas[t] / tot[t] * 100 if tot[t] else 0
    print(f"{t:14s}{tot[t]:8d}{pas[t]:6d}{r:7.1f}%")
EOF
```

As of 2026-08-01 (221 tier-tagged dossiers, all generated via CLI runs — the daemon produced none):

| lane | vetted | pass | rate |
|---|---:|---:|---:|
| side_hustle | 94 | 4 | 4.3% |
| smb | 51 | 6 | **11.8%** |
| growth | 41 | 2 | 4.9% |
| venture | 35 | 0 | **0.0%** |

Two cautions on reading this table:

1. **`venture` at 0/35 is not proof the lane is broken.** It is the strictest bar (durable moat,
   `min_composite_to_pass` 2.5, incumbency + value_durability both hard gates). A 0% rate on 35
   samples is consistent with "working as designed and genuinely hard". It is a reason not to
   over-buy the lane, not a reason to delete it.
2. **The sample is CLI-only.** Because of the bug below, none of these came from the daemon.
   Re-measure once a few daemon batches have landed — the mix of signals differs.

**Never tune the mix by lowering a lane's bar.** `hard_gates` / `thresholds` inside a lane block
are the moat. Change `lane_quota` (how many you buy) — not what it takes to pass.

---

## 7. Adjacent knobs, for orientation

- **`generation.operator_archetype`** (top-level, under `generation:`) — the default when no lane is engaged. Lane
  blocks override it. Editing this alone does nothing while lanes are active.
- **`generation.archetypes`** — the actual prompt text (`binding` / `forbid`) injected
  per archetype. Edit here to change what "small team" or "startup" *means* to the generator.
- **`generation.structural_forms`** (8) × **`audience_forms`** (8) — the 64-cell diversity matrix
  that fights mode collapse on a different axis than lanes.
- **`profiles`** — reusable bundles of generation overrides, selectable with
  `--profile NAME`. Composes over a lane; never touches gates.

---

## The bug this replaced (so it isn't reintroduced)

Until 2026-08-01, `prospector/scheduler/run_scheduled.py::_default_generate` called:

```python
run_signal("", cfg=cfg, k=batch_size, publish=True)   # no lanes= !
```

With no `lanes=`, `run_signal` took its no-lane default branch (`run.py:604`) and generated under
the single implicit default archetype, `solo_agent`. `_resolve_lanes` was only ever called from
the four CLI paths (`run.py:1182/1224/1277/1837`).

**Net effect:** a CLI `generate` was mixed-ambition, but every *unattended* batch — i.e.
essentially the entire catalogue — was solo-operator-only. `active_lanes` looked correct in
config and did nothing.

It stayed invisible because the existing seam tests stub `run_signal` as
`lambda *a, **k: batch` and assert only on the returned summary — they never inspect the
arguments, so a collapsed single-lane batch looked identical to a four-lane fan-out.
`tests/scheduler/test_daemon_lane_fanout.py` now captures the kwargs instead.

**Generalise:** when a config block is meant to steer a background process, assert on what the
process *passes downstream*, not on what it *returns*.
