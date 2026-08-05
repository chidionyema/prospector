# Self-Improvement Infrastructure: Production-Grade Build-Out

## Context
Prospector's recursive self-improvement architecture has the right bones (separated demand/truth loops, kill-fast gates, golden-set regression) but is a hollow shell. Health score was 21.3%, now 46.2% after fixing the datetime comparison bug that silently dropped all injection log entries.

## Current State (after datetime fix)

| Component | Before | After | Target |
|-----------|--------|-------|--------|
| injection_relevance | 0% | 99.2% | ✅ Fixed |
| policy_firings | 0% | 0.5% | >20% |
| auto_fixes | 4.3% | 4.3% | >30% |
| learning | 100% (stub) | 100% | Genuine metric |
| estate_health | 50% | 50% | >70% |
| **TOTAL** | **21.3%** | **46.2%** | **>70%** |

## Remaining Work (6 priorities)

---

### Priority 2: Self-Modification Log + Rollback
**File:** `prospector/self_modify.py` (new)
**Tests:** `tests/test_self_modify.py` (new)

Every self-modification must be logged and reversible:

1. **SelfModificationLog** class:
   - SQLite table at `store/self_modifications.db` with: `change_id, timestamp, component, field, old_value, new_value, trigger_signal, expected_effect, status (pending|active|rolled_back), measured_effect (nullable)`
   - `record(component, field, old, new, trigger, expected)` → returns change_id
   - `rollback(change_id)` → restores old value, marks rolled_back
   - `list_recent(n=20)` → recent changes
   - `diff(change_id)` → pretty-print before/after

2. **ConfigSnapshot** class:
   - Stores full `config.yaml` before each modification to `store/config_snapshots/change_<id>_before.yaml`
   - `restore(change_id)` → copies snapshot back to config.yaml

3. **Auto-rollback trigger:**
   - After each modification, monitor yield for next 10 runs
   - If yield drops >50% vs pre-change baseline → auto-rollback + alert via hermes send

4. **CLI integration:**
   - `prospector rollback --list` — show recent changes
   - `prospector rollback --last` — undo most recent
   - `prospector rollback --change-id X` — undo specific change

**Acceptance test:**
```python
def test_rollback_restores_config():
    log = SelfModificationLog(store)
    cid = log.record("generation", "temperature", "0.7", "0.9", "test", "increase creativity")
    log.rollback(cid)
    assert log.get(cid).status == "rolled_back"
    # Verify config was restored
```

---

### Priority 3: Time-Series Metrics Store + Trend Dashboard
**File:** `prospector/metrics_store.py` (new)
**Tests:** `tests/test_metrics_store.py` (new)

1. **RunMetrics** class (SQLite at `store/run_metrics.db`):
   - Table: `run_id, timestamp, yield_rate, kill_rate_by_gate (JSON), diversity_score, health_score, health_sub_scores (JSON), candidates_generated, candidates_passed, lane`
   - `record_run(run_id, dossiers, health_score)` → writes metrics row
   - `trend(window=50)` → yield, kill rate, diversity trends
   - `alert_check()` → returns list of triggered alerts

2. **Trend alerts:**
   - Yield declining 3+ consecutive windows → `yield_decline` alert
   - Gate dominance >85% → `gate_dominance` alert  
   - Diversity dropping below floor → `diversity_collapse` alert
   - Health score declining 5+ points in a week → `health_decline` alert

3. **Dashboard command:**
   - `prospector dashboard` → prints text-based dashboard with:
     - Yield trend (last 50 runs, sparkline)
     - Kill-rate-by-gate distribution (bar chart)
     - Diversity trend
     - Health score trend with 14-day sparkline
   - `prospector dashboard --json` → machine-readable output
   - `prospector dashboard --html > dashboard.html` → static HTML report

4. **Integration:** Wire `record_run()` call into `prospector/run.py` after each `vet` or `run` completes.

**Acceptance test:**
```python
def test_metrics_trend_detection():
    store = MetricsStore(db_path)
    # Record 5 runs with declining yield
    for i in range(5):
        store.record_run(f"run_{i}", mock_dossiers(yield=0.5 - i*0.1), 0.5)
    alerts = store.alert_check()
    assert any(a["type"] == "yield_decline" for a in alerts)
```

---

### Priority 4: Causal Attribution
**File:** `prospector/attribution.py` (new)
**Tests:** `tests/test_attribution.py` (new)

1. **Tag runs with active changes:**
   - Each run records which `change_id`s were active (from SelfModificationLog)
   - `RunMetrics` table gets `active_changes` column (JSON array of change_ids)

2. **Paired comparison:**
   - `measure_effect(change_id, metrics_store)` → compares N runs before vs N runs after change
   - Returns: effect size on yield, diversity, gate distribution; confidence interval; p-value
   - Updates `measured_effect` on the change record

3. **Auto-flag bad changes:**
   - If effect is negative with confidence >90% → flag for rollback
   - Surface in dashboard: "Change #47 caused -12% yield (p < 0.05)"

4. **Dashboard integration:**
   - `prospector dashboard` shows top-5 most impactful recent changes
   - Each shows: what changed, direction, magnitude, confidence

**Acceptance test:**
```python
def test_attribution_detects_negative_change():
    store = MetricsStore(db_path)
    log = SelfModificationLog(store)
    cid = log.record("generation", "steer", "old", "bad_steer", "test", "test")
    # Record 10 runs before (good yield) and 10 after (bad yield)
    for i in range(10):
        store.record_run(f"before_{i}", mock_dossiers(yield=0.5), 0.5, active_changes=[])
    for i in range(10):
        store.record_run(f"after_{i}", mock_dossiers(yield=0.1), 0.1, active_changes=[cid])
    effect = measure_effect(cid, store)
    assert effect["direction"] == "negative"
    assert effect["significant"] == True
```

---

### Priority 5: Simulation Harness (Test the Improver)
**File:** `tests/test_self_improvement.py` (new)

Deterministic mock mode that tests the adaptation loop:

1. **Mock fixtures:**
   - Fixed retrieval passages (`tests/fixtures/mock_passages.json`)
   - Deterministic model responses (`tests/fixtures/mock_verdicts.json`)
   - These replace real web search and real model calls

2. **Simulation runs:**
   - `simulate_runs(n=50, adaptation=True)` → runs pipeline N times, records metrics
   - `simulate_runs(n=50, adaptation=False)` → baseline without adaptation
   - Assert: adaptation-enabled yield > adaptation-disabled yield

3. **Bad-steer injection test:**
   - Inject a known-bad steer midway through simulation
   - Assert system detects yield drop and either reverts or flags

4. **Convergence test:**
   - Run 100 iterations → assert creativity dial stabilizes (doesn't oscillate)
   - Assert diversity doesn't collapse (entropy stays above floor)

5. **CI integration:**
   - Runs on every change to `adaptive.py`, auto_fixer, or policy engine
   - `pytest tests/test_self_improvement.py -v`

**Acceptance test:**
```python
def test_adaptation_improves_yield():
    adapted = simulate_runs(n=30, adaptation=True)
    baseline = simulate_runs(n=30, adaptation=False)
    assert adapted["mean_yield"] > baseline["mean_yield"]
    assert adapted["mean_yield"] > 0.1  # must actually work
```

---

### Priority 6: A/B Testing (Canary Mode)
**File:** `prospector/canary.py` (new)
**Tests:** `tests/test_canary.py` (new)

1. **Canary runner:**
   - `prospector run --canary` → uses proposed config, writes to separate dossiers dir
   - Canary runs tagged in metrics store with `canary=True`

2. **Automated comparison:**
   - After N canary runs (default 20), compare canary vs control metrics
   - `canary_verdict(control_metrics, canary_metrics)` → promote | revert | extend
   - Decision rule: promote if canary wins with p<0.1, revert if loses with p<0.1, extend if ambiguous

3. **Auto-promote/revert:**
   - `promote()` → copies proposed config to production
   - `revert()` → discards proposed config, logs reason
   - Both log to SelfModificationLog

4. **CLI:**
   - `prospector canary --status` → current canary status
   - `prospector canary --promote` → manual promotion
   - `prospector canary --revert` → manual revert

**Acceptance test:**
```python
def test_canary_promotes_better_config():
    # Run canary with better config
    canary_metrics = run_canary(Config(temperature=0.9), n=20)
    control_metrics = run_control(Config(temperature=0.5), n=20)
    verdict = canary_verdict(control_metrics, canary_metrics)
    assert verdict in ("promote", "extend")  # not revert
```

---

### Priority 7: Dead-Loop Prevention (Kill Decay + Re-Seeding)
**File:** `prospector/decay.py` (new)
**Tests:** `tests/test_decay.py` (new)

1. **Kill reason decay:**
   - Each kill reason's steer strength decays exponentially: `strength *= exp(-lambda * days_since_kill)`
   - Half-life configurable in config.yaml (default 30 days)
   - `get_active_steers()` → returns steers with decayed weights

2. **Periodic re-seeding:**
   - `re_seed_scheduler` in `store/scheduler/re_seed_state.json`
   - Every N days (default 14), select top-K most-stale domains and force-generate M candidates each
   - Log re-seed events in metrics store

3. **Diversity floor protection:**
   - Track Shannon entropy of generated domains over rolling window
   - If entropy drops below configurable floor → force re-seed immediately
   - Alert via hermes send

4. **Integration with adaptive.py:**
   - `adaptive.py` reads steers through `decay.get_active_steers()` instead of raw kill data
   - `select_lenses()` receives decayed domain weights

**Acceptance test:**
```python
def test_kill_reasons_decay_over_time():
    store = mock_store_with_kill("food_delivery", days_ago=45)
    steers = get_active_steers(store, half_life_days=30)
    food_strength = steers.get("food_delivery", 1.0)
    assert food_strength < 0.5  # should be significantly decayed

def test_diversity_floor_triggers_reseed():
    store = mock_store_with_collapsed_diversity()
    result = check_diversity_floor(store, floor=0.5)
    assert result["triggered"] == True
    assert result["action"] == "force_reseed"
```

---

## Verification

After each priority is implemented, run:
```bash
cd /Users/chidionyema/Documents/code/prospector
.venv/bin/python -m pytest tests/ -q -k "self_modify or metrics_store or attribution or self_improvement or canary or decay"
```

And verify the health score via:
```bash
cd /Users/chidionyema/.hermes && PYTHONPATH="$PWD/hermes-agent:$PYTHONPATH" python3 -c "
from gateway.operator_shell.otto_health import _compute_score
import json; print(json.dumps(_compute_score(), indent=2))
"
```

Target: score > 0.70 (from current 0.462).

## Implementation order
1. Metrics store (Priority 3) — needed by attribution and canary
2. Self-modification log + rollback (Priority 2) — needed by attribution and canary
3. Causal attribution (Priority 4) — depends on 2+3
4. Simulation harness (Priority 5) — independent, can run in parallel
5. Dead-loop prevention (Priority 7) — independent
6. A/B canary (Priority 6) — depends on 2+3+4

## Files to create:
- `prospector/metrics_store.py`
- `prospector/self_modify.py`
- `prospector/attribution.py`
- `prospector/canary.py`
- `prospector/decay.py`
- `tests/test_metrics_store.py`
- `tests/test_self_modify.py`
- `tests/test_attribution.py`
- `tests/test_canary.py`
- `tests/test_decay.py`
- `tests/test_self_improvement.py`
- `tests/fixtures/mock_passages.json`
- `tests/fixtures/mock_verdicts.json`

## Files to modify:
- `prospector/run.py` — wire metrics recording
- `prospector/adaptive.py` — wire decay-based steers
- `config.yaml` — add decay, canary, metrics config sections
