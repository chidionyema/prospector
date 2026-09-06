"""The operating-model gate here is a pointer, not a copy (crew#584 LAW 51). This test is the proof
for the ledger row `the-operating-model-gate-silently-stops-running`: the file must call the shared
idp gate at @main, on pull_request only, with pull-requests: write, or the law is prose again."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github" / "workflows" / "operating-model-gate.yml"


def test_the_gate_calls_the_shared_idp_gate_at_main():
    doc = yaml.safe_load(WF.read_text(encoding="utf-8"))
    job = doc["jobs"]["operating-model-gate"]
    assert job["uses"] == "chidionyema/idp/.github/workflows/operating-model-gate.yml@main", job
    assert job["permissions"]["pull-requests"] == "write", job


def test_the_gate_runs_on_pull_requests_only():
    doc = yaml.safe_load(WF.read_text(encoding="utf-8"))
    on = doc.get("on", doc.get(True))
    assert on == {"pull_request": None} or list(on) == ["pull_request"], on
