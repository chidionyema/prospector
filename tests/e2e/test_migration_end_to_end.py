"""The whole migration chain, joined, against a substrate made of directories.

Every other test in this programme grades ONE link: the compiler refuses a bad plan, the runner
emits a heartbeat, the adapter names both ends, the folder counts the steps. All four passed
while the runner handed its adapters an empty environment and told them where a resource was
going but never where it was -- because no test ever ran a plan the compiler produced through an
adapter that read what the runner set.

THIS FILE RUNS THE WIRE. Probe report -> `kit/migrate/plan.py` -> `kit/migrate/run.py` -> the
real `kit/classes/*.sh` -> a `deploy/cutover.sh` that actually moves a file -> back through
`kit/migrate/progress.py` to the shape the console renders. Nothing is stubbed except the
substrate itself, which is two directories, so the test needs no cloud account and no
credentials -- a test that needs those is a test that gets skipped, and a skipped test proves
nothing at 3am.

The clauses of `docs/GOLD_STANDARD_SPEC.md` are graded here because here is the only place they
are true or false: A1 the wall clock, A2 nothing left behind unnamed, A4 nothing silent, and the
resource is checked to have ACTUALLY ARRIVED, which no unit test can see.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from kit.migrate import run as runner
from kit.migrate.plan import main as plan_main
from kit.migrate.progress import read as read_progress

REPO = Path(__file__).resolve().parents[2]
DECLARATION = "kit/projects/prospector.yaml"

#: A `deploy/cutover.sh` that moves a file between two directories and says what it did. It is a
#: stand-in for the real one ONLY in that its substrate is a directory: it takes the same
#: arguments, reads the same environment, and fails the same way, so the adapter above it is the
#: real adapter running its real code path.
FAKE_CUTOVER = """#!/usr/bin/env bash
set -euo pipefail
FROM_DIR=""; TO_DIR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --from) FROM_DIR="$2"; shift 2 ;;
    --to)   TO_DIR="$2"; shift 2 ;;
    --dry-run) shift ;;
    *) shift ;;
  esac
done
[ -n "${ESTATE:-}" ] || { echo "cutover: no ESTATE" >&2; exit 1; }
[ -n "${RESOURCE:-}" ] || { echo "cutover: no RESOURCE" >&2; exit 1; }
# The one rule the real script enforces: the source is stopped before the state moves, so the
# resource is never present on both substrates at once. Here that is just the mv being atomic.
mkdir -p "$ESTATE/$TO_DIR"
[ -e "$ESTATE/$FROM_DIR/$RESOURCE" ] || { echo "cutover: $RESOURCE is not on $FROM_DIR" >&2; exit 1; }
mv "$ESTATE/$FROM_DIR/$RESOURCE" "$ESTATE/$TO_DIR/$RESOURCE"
echo "moved $RESOURCE: $FROM_DIR -> $TO_DIR"
"""


def resource(name, cls, where, **kw):
    """The real shape of one row from `scripts/estate_inventory.py --json`."""
    row = {"name": name, "class": cls, "where": where, "described_by": None,
           "restore": None, "last_run": "-", "problem": None, "admitted": None}
    row.update(kw)
    return row


@pytest.fixture
def estate(tmp_path, monkeypatch):
    """A throwaway repo holding the REAL kit, and a substrate that is two directories."""
    repo = tmp_path / "repo"
    (repo / "kit" / "classes").mkdir(parents=True)
    (repo / "kit" / "migrate").mkdir(parents=True)
    (repo / "kit" / "projects").mkdir(parents=True)
    (repo / "deploy").mkdir()

    for src in (REPO / "kit").rglob("*"):
        if src.is_file() and "__pycache__" not in str(src):
            dst = repo / src.relative_to(REPO)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    cutover = repo / "deploy" / "cutover.sh"
    cutover.write_text(FAKE_CUTOVER)
    cutover.chmod(0o755)

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)

    substrate = tmp_path / "substrate"
    (substrate / "fly").mkdir(parents=True)
    (substrate / "fly" / "engine").write_text("the running service")

    monkeypatch.chdir(repo)
    monkeypatch.setenv("ESTATE", str(substrate))
    return {"repo": repo, "substrate": substrate, "tmp": tmp_path}


def compile_plan_file(estate, *resources, target="sshdocker"):
    """Through the compiler's own CLI, so its refusals and its output shape are both exercised."""
    report = estate["tmp"] / "probe.json"
    report.write_text(json.dumps({"resources": list(resources)}))
    out = estate["tmp"] / "plan.json"
    code = plan_main(["--report", str(report), "--project", DECLARATION,
                      "--to", target, "--out", str(out)])
    assert code == 0, "the compiler refused a plan this test needs"
    return out


def execute_plan(estate, plan_path):
    """Through the runner's own CLI, writing events to a file, exactly as the console reads it."""
    events = estate["tmp"] / "events.jsonl"
    code = runner.main(["--plan", str(plan_path), "--events", str(events)])
    return code, events


# ── the wire, joined ─────────────────────────────────────────────────────────

def test_a_resource_actually_arrives_on_the_other_substrate(estate):
    """The claim no unit test can make: the thing moved.

    Every link runs its real code here. If the runner hands the adapter an empty environment the
    fake cutover cannot find $ESTATE; if it omits the `from` end the adapter refuses before it
    starts. Both of those were live defects that four green unit-test files did not see.
    """
    plan_path = compile_plan_file(
        estate,
        resource("engine", "compute", "fly/deployed"),
        resource("zone", "dns", "cloudflare/live", admitted="#99"),
    )
    code, events = execute_plan(estate, plan_path)

    assert code == 0, (estate["tmp"] / "events.jsonl").read_text()
    assert (estate["substrate"] / "sshdocker" / "engine").is_file(), "it never arrived"
    assert not (estate["substrate"] / "fly" / "engine").exists(), (
        "it is on BOTH substrates -- two engines keep two spend ledgers")

    view = read_progress(events)
    assert view["state"] == "finished"
    assert view["done"] == view["total"] == 1
    assert view["steps"][0]["state"] == "done"
    assert view["target"] == "sshdocker"


def test_what_the_probe_admitted_is_named_on_the_page_not_dropped(estate):
    """Clause A2 is 0 resources left behind. A gap that reaches neither the plan nor the page is
    a resource nobody will notice is still on the old substrate at 9am."""
    plan_path = compile_plan_file(
        estate,
        resource("engine", "compute", "fly/deployed"),
        resource("zone", "dns", "cloudflare/live", admitted="#99"),
        resource("bucket", "object_storage", "r2/live", admitted="#114"),
    )
    _, events = execute_plan(estate, plan_path)

    left = read_progress(events)["left_behind"]
    assert {row["resource"] for row in left} == {"zone", "bucket"}
    assert all(row["reason"] for row in left), "a gap with no reason is a gap nobody can close"


def test_the_run_stays_inside_the_wall_clock_and_never_goes_silent(estate):
    """Clauses A1 and A4, graded on a real run rather than on a hand-built stream."""
    plan_path = compile_plan_file(estate, resource("engine", "compute", "fly/deployed"))
    code, events = execute_plan(estate, plan_path)
    assert code == 0

    stream = [json.loads(line) for line in events.read_text().splitlines() if line.strip()]
    assert stream[0]["kind"] == "run_started"
    assert stream[-1]["kind"] == "run_done", "the stream must SAY it is over"
    assert stream[-1]["exit_code"] == 0
    assert stream[-1]["elapsed_s"] <= 1800.0, "clause A1"

    gaps = [round(b["at"] - a["at"], 2) for a, b in zip(stream, stream[1:])]
    assert max(gaps) < runner.HEARTBEAT_S + 1.0, f"clause A4: silent for {max(gaps)}s"


# ── the wire, honestly broken ────────────────────────────────────────────────

def test_a_class_with_no_adapter_fails_loudly_and_puts_the_resource_back(estate):
    """A plan naming a class that has no adapter must fail at the step, name it, roll back, and
    print what to type after the adapter is written -- not report a move that did not happen.

    THE CLASS COMES FROM `MISSING.md`, NOT FROM THIS FILE. It used to name `datastore`, which
    stopped being unwired the day `kit/classes/datastore.sh` landed -- so writing an adapter
    broke a test about adapters being absent, and the fix looked like deleting coverage. Reading
    the ledger makes this a test of the FAILURE PATH, which is permanent, rather than a test of
    which classes happen to be unwired today, which is not.
    """
    unwired = sorted(line.split("`")[1]
                     for line in (REPO / "kit" / "classes" / "MISSING.md").read_text().splitlines()
                     if line.startswith("- `"))
    if not unwired:
        pytest.skip("every declared class is wired -- there is no missing adapter left to grade")
    klass = unwired[0]

    (estate["substrate"] / "fly" / "ledger").write_text("rows")
    plan_path = compile_plan_file(
        estate,
        resource("ledger", klass, "fly/deployed"),
    )
    code, events = execute_plan(estate, plan_path)

    assert code == runner.EX_FAILED
    assert (estate["substrate"] / "fly" / "ledger").is_file(), "it was reported moved and was not"

    view = read_progress(events)
    assert view["state"] == "stopped"
    stopped = [row for row in view["steps"] if row["state"] != "done"]
    assert stopped and stopped[0]["class"] == klass
    assert stopped[0]["state"] == "not_started", (
        "an adapter that could not be STARTED touched nothing; reporting a failed rollback "
        "sends an operator hunting for a resource that is exactly where they left it")
    assert f"kit/classes/{klass}.sh" in stopped[0]["detail"], (
        "the failure must name the adapter that is missing, so the fix is obvious")
    assert view["needs_a_person"] is False, "nothing is stranded -- there is nothing to go and do"


def test_the_resume_line_the_page_prints_actually_resumes(estate):
    """The console's single most important string. A resume line that does not work is worse
    than none: it costs the operator a try at the exact minute they have none to spare."""
    (estate["substrate"] / "fly" / "ledger").write_text("rows")
    plan_path = compile_plan_file(
        estate,
        resource("engine", "compute", "fly/deployed"),
        resource("ledger", "datastore", "fly/deployed"),
    )
    code, events = execute_plan(estate, plan_path)
    assert code == runner.EX_FAILED

    view = read_progress(events)
    # `datastore` runs BEFORE `compute` -- secrets and state land before the service that reads
    # them (kit/projects/schema.py CLASS_NEEDS). So the run stops at the first step and the
    # engine is still on the old substrate, which is the whole point of stopping there.
    assert (estate["substrate"] / "fly" / "engine").is_file()
    resume = view["resume_with"]
    assert resume and resume.startswith("--from-step "), f"no usable resume line: {resume!r}"

    # Write the missing adapter, then take the page at its word.
    adapter = estate["repo"] / "kit" / "classes" / "datastore.sh"
    adapter.write_text((estate["repo"] / "kit" / "classes" / "compute.sh").read_text())
    adapter.chmod(0o755)

    again = estate["tmp"] / "events2.jsonl"
    code = runner.main(["--plan", str(plan_path), "--events", str(again)] + resume.split())
    assert code == 0, again.read_text()
    assert (estate["substrate"] / "sshdocker" / "ledger").is_file()

    resumed = read_progress(again)
    assert resumed["state"] == "finished"
    by_class = {row["class"]: row["state"] for row in resumed["steps"]}
    assert by_class == {"datastore": "done", "compute": "done"}, (
        "a resume must carry the run to the END, not just past the step that failed")
    assert (estate["substrate"] / "sshdocker" / "engine").is_file(), (
        "the steps BEHIND the failed one never ran, so the resume owes them too")


# ── the ledger that stops a class being claimed before it is wired ───────────

def test_every_class_the_declaration_offers_has_an_adapter_or_is_listed_as_missing():
    """A declaration that offers `sshdocker` for ten classes reads as ten classes that can move.
    One can. This test does not fail on that -- it fails when the two lists drift apart, so the
    number in the spec can never quietly disagree with the number on disk.
    """
    from kit.projects.schema import load

    declared = set(load(DECLARATION).classes)
    wired = {path.stem for path in (REPO / "kit" / "classes").glob("*.sh")}
    missing = sorted(declared - wired)

    ledger = REPO / "kit" / "classes" / "MISSING.md"
    assert ledger.is_file(), "the unwired classes must be written down where the adapters live"
    named = {line.split("`")[1] for line in ledger.read_text().splitlines()
             if line.startswith("- `")}
    assert named == set(missing), (
        f"the ledger says {sorted(named)}, the tree says {missing}. "
        "Write the adapter or update the ledger -- a class that is claimed and unwired fails "
        "at minute 12 of a move, not here.")


# ── one more link: the screen the operator actually watches ──────────────────

def test_the_console_page_shows_a_run_that_really_happened(estate, monkeypatch):
    """The last link of the wire, and the one with the most expensive way to be wrong.

    The console decides where a project's event stream lives; the runner writes it. Nothing made
    those two agree, and a disagreement is invisible in the worst way: the migration runs, the
    file fills up, and the page says "no run" for the whole thirty minutes. The operator watching
    it has no way to tell that from a run that never started.

    So this test never names a path. It asks the PAGE where the events go, runs a real migration
    into exactly that file, and asks the page again. If the two ends ever drift apart, the second
    read comes back empty and this fails.
    """
    from prospector.ops.migration_view import migration_view

    store = estate["tmp"] / "store"
    monkeypatch.setenv("PROSPECTOR_STORE_DIR", str(store))
    repo = estate["repo"]

    before = migration_view(repo)
    assert before["chosen"] == "prospector", before["projects"]
    assert before["run"]["state"] == "no run", "a store with no events is not a run in flight"

    events = Path(before["paths"]["events"])
    events.parent.mkdir(parents=True, exist_ok=True)

    plan_path = compile_plan_file(
        estate,
        resource("engine", "compute", "fly/deployed"),
    )
    code = runner.main(["--plan", str(plan_path), "--events", str(events)])
    assert code == 0, events.read_text()

    after = migration_view(repo)
    run = after["run"]
    # "finished" is the RUN; "done" is a STEP. The two vocabularies are deliberately
    # different, so a page cannot print one where it means the other.
    assert run["state"] == "finished", run
    assert run["done"] == run["total"] == 1, run
    assert run["exit_code"] == 0, run
    assert [s["class"] for s in run["steps"]] == ["compute"], run["steps"]
    # The page must be able to say what every state means without inventing a word of its own.
    assert set(run["steps"][0]["means"]) and run["steps"][0]["state"] in after["state_meaning"]
    # And the thing the run was for actually moved, on the same assertion as the wire test.
    assert (estate["substrate"] / "sshdocker" / "engine").is_file()


def test_the_page_admits_which_classes_have_no_adapter(estate, monkeypatch):
    """Clause A2 on the page: what cannot be moved is named, not quietly absent.

    A console that lists nine classes and moves one, without saying which is which, reads as a
    complete migration tool. The operator finds out at the point of use, which on this bar is
    thirty minutes into a cutover.
    """
    from prospector.ops.migration_view import migration_view

    monkeypatch.setenv("PROSPECTOR_STORE_DIR", str(estate["tmp"] / "store"))
    page = migration_view(estate["repo"])
    classes = page["projects"][0]["classes"]

    wired = {c["class"] for c in classes if c["adapter_exists"]}
    unwired = {c["class"] for c in classes if not c["adapter_exists"]}
    assert wired, "the page claims nothing can be moved at all"
    assert unwired, "if every class is wired, kit/classes/MISSING.md is stale and so is this test"

    ledger = (REPO / "kit" / "classes" / "MISSING.md").read_text()
    unlisted = sorted(name for name in unwired if name not in ledger)
    assert unlisted == [], (
        f"the page shows these classes as unwired and MISSING.md does not admit them: {unlisted}")

    # Every class carries the sentence that says what it costs a customer. Clause A3 is a
    # budget an operator has to spend, and they cannot spend it off a one-word enum.
    assert all(c["downtime_means"] for c in classes)
