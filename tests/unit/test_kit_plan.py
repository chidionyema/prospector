"""The plan compiler's one invariant, and the refusals that make it worth having.

The invariant is clause A2 of docs/GOLD_STANDARD_SPEC.md, enforced before anything moves:
every resource the probe found is either in a step or in `skipped` with a reason.

The fixture below is the real shape of `scripts/estate_inventory.py --json`, measured
2026-08-21 against the live estate. It is a fixture rather than a live call because CI has
no platform credentials, and a test that needs them is a test that gets skipped.
"""

from __future__ import annotations

import json

import pytest

from kit.migrate.plan import EX_CONFIG, PlanRefused, compile_plan, main, substrate_of
from kit.projects.schema import DeclarationError, load, validate

DECLARATION = "kit/projects/prospector.yaml"


def report(*resources):
    return {"resources": list(resources)}


def resource(name, cls, where, **kw):
    base = {"name": name, "class": cls, "where": where, "described_by": None,
            "restore": None, "last_run": "—", "problem": None, "admitted": None}
    base.update(kw)
    return base


@pytest.fixture
def project():
    return load(DECLARATION)


# ── the invariant ────────────────────────────────────────────────────────────

def test_every_resource_lands_in_a_step_or_a_reasoned_skip(project):
    probe = report(
        resource("engine", "compute", "fly/deployed"),
        resource("store", "datastore", "fly/deployed"),
        resource("zone", "dns", "cloudflare/live"),
        resource("cert", "tls_certificate", "fly/issued"),
        resource("key", "secret", "fly/set"),
        resource("bucket", "object_storage", "r2/live"),
        resource("nightly", "scheduled_job", "launchd/loaded"),
        resource("logs", "log_sink", "fly/live"),
        resource("stripe", "payment_integration", "stripe/live"),
        resource("runner", "ci_runner", "fly/deployed"),
    )
    plan = compile_plan(probe, project, "sshdocker")

    placed = {s["resource"] for s in plan["steps"]} | {s["resource"] for s in plan["skipped"]}
    assert placed == {r["name"] for r in probe["resources"]}
    assert plan["counts"]["resources"] == len(plan["steps"]) + len(plan["skipped"])
    assert all(s["reason"] for s in plan["skipped"])


def test_a_resource_already_on_the_target_is_skipped_with_that_reason(project):
    plan = compile_plan(report(resource("engine", "compute", "sshdocker/deployed")), project, "sshdocker")
    assert plan["steps"] == []
    assert plan["skipped"] == [{"resource": "engine", "class": "compute", "reason": "already on sshdocker"}]


def test_an_admitted_gap_is_skipped_and_carries_its_problem(project):
    probe = report(resource("orphan", "compute", "fly/deployed",
                            problem="admitted gap (issue #74)", admitted="nothing describes it"))
    plan = compile_plan(probe, project, "sshdocker")
    assert plan["steps"] == []
    assert "issue #74" in plan["skipped"][0]["reason"]


# ── the refusals: both are knowable at second 0 ──────────────────────────────

def test_an_undeclared_class_refuses_the_plan_and_names_it(project):
    with pytest.raises(PlanRefused) as exc:
        compile_plan(report(resource("queue", "message_queue", "fly/live")), project, "sshdocker")
    assert "message_queue" in str(exc.value)
    assert "queue" in str(exc.value)


def test_a_target_the_adapter_cannot_reach_refuses_the_plan(project):
    with pytest.raises(PlanRefused) as exc:
        compile_plan(report(resource("engine", "compute", "fly/deployed")), project, "heroku")
    assert "heroku" in str(exc.value)
    assert "compute" in str(exc.value)


def test_a_report_that_is_not_a_probe_report_refuses(project):
    with pytest.raises(PlanRefused):
        compile_plan({"machines": []}, project, "sshdocker")


# ── ordering, verbs and downtime ─────────────────────────────────────────────

def test_secrets_come_before_compute_and_dns_comes_last(project):
    probe = report(
        resource("zone", "dns", "cloudflare/live"),
        resource("engine", "compute", "fly/deployed"),
        resource("key", "secret", "fly/set"),
    )
    order = [s["class"] for s in compile_plan(probe, project, "sshdocker")["steps"]]
    assert order.index("secret") < order.index("compute") < order.index("dns")


def test_a_pointer_a_third_party_holds_is_a_repoint_not_a_move(project):
    probe = report(
        resource("stripe", "payment_integration", "stripe/live"),
        resource("zone", "dns", "cloudflare/live"),
        resource("engine", "compute", "fly/deployed"),
    )
    verbs = {s["class"]: s["verb"] for s in compile_plan(probe, project, "sshdocker")["steps"]}
    assert verbs["payment_integration"] == "repoint"
    assert verbs["dns"] == "repoint"
    assert verbs["compute"] == "move"


def test_only_dns_is_allowed_to_cost_customer_visible_downtime(project):
    probe = report(*[resource(f"r{i}", cls, "fly/live") for i, cls in enumerate(project.classes)])
    for step in compile_plan(probe, project, "sshdocker")["steps"]:
        if step["downtime"] == "customer":
            assert step["class"] == "dns", f"{step['class']} claims customer-visible downtime"


def test_every_step_names_an_adapter_under_kit(project):
    probe = report(*[resource(f"r{i}", cls, "fly/live") for i, cls in enumerate(project.classes)])
    for step in compile_plan(probe, project, "sshdocker")["steps"]:
        assert step["adapter"].startswith("kit/classes/")


def test_substrate_of_reads_the_platform_half(project):
    assert substrate_of("fly/deployed") == "fly"
    assert substrate_of("fly") == "fly"
    assert substrate_of(None) == "unknown"


# ── the declaration itself ───────────────────────────────────────────────────

def test_the_shipped_declaration_validates(project):
    assert project.project == "prospector"
    assert project.resources_declaration == "ops/config/estate_resources.yaml"
    assert set(project.classes) == {
        "secret", "datastore", "object_storage", "compute", "scheduled_job",
        "log_sink", "payment_integration", "tls_certificate", "dns", "ci_runner",
    }
    assert project.classes["dns"].downtime == "customer"
    assert project.classes["compute"].needs == ("secret", "datastore")


def test_the_declaration_points_at_a_resource_file_that_is_there(project, tmp_path):
    from pathlib import Path
    repo = Path(__file__).resolve().parents[2]
    assert (repo / project.resources_declaration).is_file()


@pytest.mark.parametrize("missing", ["project", "names", "resources_declaration", "classes"])
def test_a_missing_block_fails_and_names_itself(missing):
    raw = {"project": "x", "names": ["x"], "resources_declaration": "d.yaml",
           "classes": {"secret": {"targets": ["fly"]}}}
    raw.pop(missing)
    with pytest.raises(DeclarationError) as exc:
        validate(raw)
    assert missing in str(exc.value)


def test_an_unknown_class_is_named_along_with_the_known_ones():
    with pytest.raises(DeclarationError) as exc:
        validate({"project": "x", "names": ["x"], "resources_declaration": "d.yaml",
                  "classes": {"kafka": {"targets": ["fly"]}}})
    assert "kafka" in str(exc.value) and "compute" in str(exc.value)


def test_a_class_whose_prerequisite_is_undeclared_cannot_be_ordered():
    with pytest.raises(DeclarationError) as exc:
        validate({"project": "x", "names": ["x"], "resources_declaration": "d.yaml",
                  "classes": {"compute": {"targets": ["fly"]}}})
    assert "compute" in str(exc.value) and "secret" in str(exc.value)


def test_a_class_with_no_targets_is_refused():
    with pytest.raises(DeclarationError) as exc:
        validate({"project": "x", "names": ["x"], "resources_declaration": "d.yaml",
                  "classes": {"secret": {"targets": []}}})
    assert "secret" in str(exc.value)


# ── the CLI exits 78 on a configuration problem, not 1 ───────────────────────

def test_the_cli_writes_a_plan_and_exits_zero(tmp_path, capsys):
    r = tmp_path / "r.json"
    r.write_text(json.dumps(report(resource("engine", "compute", "fly/deployed"),
                                   resource("key", "secret", "fly/set"))))
    out = tmp_path / "plan.json"
    assert main(["--report", str(r), "--project", DECLARATION, "--to", "sshdocker", "--out", str(out)]) == 0
    written = json.loads(out.read_text())
    assert [s["class"] for s in written["steps"]] == ["secret", "compute"]


def test_the_cli_exits_78_on_a_missing_report(tmp_path):
    assert main(["--report", str(tmp_path / "nope.json"), "--project", DECLARATION, "--to", "sshdocker"]) == EX_CONFIG


def test_the_cli_exits_78_on_a_target_no_adapter_reaches(tmp_path):
    r = tmp_path / "r.json"
    r.write_text(json.dumps(report(resource("engine", "compute", "fly/deployed"))))
    assert main(["--report", str(r), "--project", DECLARATION, "--to", "heroku"]) == EX_CONFIG


def test_a_gap_whose_issue_is_only_in_restore_still_names_it(project):
    """The defect the fixtures missed and the live estate found.

    `mumchimp.com` carries `problem: null` and the owning issue in `restore`. Reading only
    `problem` reported "see the resource declaration" for 30 of the 66 real gaps.
    """
    probe = report(resource("mumchimp.com", "dns", where="godaddy", problem=None,
                              restore="admitted gap (issue #99)", admitted="applying the zone is a person"))
    plan = compile_plan(probe, project, "sshdocker")
    assert plan["skipped"][0]["reason"] == "admitted gap, owned by issue #99"


def test_a_gap_with_no_owning_issue_says_so_loudly(project):
    """A gap nobody owns must be louder than a gap somebody owns, not quieter."""
    probe = report(resource("orphan", "dns", where="godaddy", problem=None,
                               restore=None, admitted="nothing describes it"))
    plan = compile_plan(probe, project, "sshdocker")
    assert "NO owning issue" in plan["skipped"][0]["reason"]


def test_a_skip_carries_the_admitted_prose_for_the_console_to_show(project):
    probe = report(resource("orphan", "dns", where="godaddy", problem=None,
                               restore=None, admitted="applying the zone is a person in the panel"))
    plan = compile_plan(probe, project, "sshdocker")
    assert plan["skipped"][0]["admitted"] == "applying the zone is a person in the panel"


def test_no_skip_reason_is_a_bare_placeholder(project):
    """Clause A2, stated as a property: every left-behind resource names an owner or says
    outright that it has none. A reason pointing the reader at another file is neither."""
    probe = report(
        resource("a", "dns", where="godaddy", problem="admitted gap (issue #74)", admitted="x"),
        resource("b", "dns", where="godaddy", problem=None, restore="admitted gap (issue #99)", admitted="x"),
        resource("c", "dns", where="godaddy", problem=None, restore=None, admitted="x"),
    )
    plan = compile_plan(probe, project, "sshdocker")
    assert len(plan["skipped"]) == 3
    for skip in plan["skipped"]:
        assert "owned by issue #" in skip["reason"] or "NO owning issue" in skip["reason"]
