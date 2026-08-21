"""The two class adapters that move state, run for real against a substrate of directories.

`tests/e2e/test_migration_end_to_end.py` runs the wire through `compute`. This file runs it
through the two classes `compute` DEPENDS on -- secrets and the datastore -- because those are
the two that touch the things a migration can destroy: a credential set and the only copy of
the product corpus.

NOTHING IS STUBBED EXCEPT THE SUBSTRATE. The adapters under test are the real files in
`kit/classes/`, invoked the way `kit/migrate/run.py` invokes them: argv is the verb, everything
else is the environment the runner builds. The target adapters are real shell implementing the
same twelve-function contract as `deploy/targets/*.sh` (`deploy/PORTABILITY.md:44`), over
directories -- so the code path is the shipped one and the test needs no cloud account. A test
that needs credentials is a test that gets skipped, and a skipped test proves nothing at 3am.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

#: A target adapter over a directory. `t_put` copies and then proves the bytes landed, which is
#: the rule `deploy/PORTABILITY.md` says costs a cutover attempt when an adapter skips it.
FAKE_TARGET = r"""
t_name()     { echo "dir:$SIDE_ROOT"; }
t_preflight() { [ -d "$SIDE_ROOT" ] || mkdir -p "$SIDE_ROOT"; }
t_provision() { mkdir -p "$SIDE_ROOT"; }
t_secrets()  { mkdir -p "$SIDE_ROOT"; cp "$1" "$SIDE_ROOT/secrets.env"; }
t_pack()     { tar czf "$1" -C "$SIDE_ROOT" state; }
t_put()      { mkdir -p "$SIDE_ROOT$(dirname "$2")"; cp "$1" "$SIDE_ROOT$2"; [ -s "$SIDE_ROOT$2" ]; }
t_exec()     { ( cd "$SIDE_ROOT" && eval "$(echo "$*" | sed "s#/data#$SIDE_ROOT/data#g")" ); }
"""


@pytest.fixture
def estate(tmp_path):
    """Two directories and a targets directory holding an adapter for each."""
    targets = tmp_path / "targets"
    targets.mkdir()
    roots = {}
    for side in ("here", "there"):
        root = tmp_path / side
        (root / "data").mkdir(parents=True)
        roots[side] = root
        (targets / f"{side}.sh").write_text(f'SIDE_ROOT="{root}"\n{FAKE_TARGET}')
    return {"tmp": tmp_path, "targets": targets, "roots": roots}


def run(adapter, verb, estate, **env):
    """Invoke a class adapter exactly as `kit.migrate.run.run_step` does."""
    # DRY_RUN is cleared from the INHERITED environment before the caller's own vars go on top.
    # Popping it afterwards drops the flag the test just set, and every dry-run assertion then
    # grades a real move that happened to leave the assertion true.
    ambient = {k: v for k, v in os.environ.items() if k != "DRY_RUN"}
    child = {**ambient, "MIGRATE_TARGETS_DIR": str(estate["targets"]),
             "MIGRATE_WORK_DIR": str(estate["tmp"] / "work"),
             "FROM": "here", "TO": "there", "RESOURCE": "r", "STEP_ID": f"{adapter}:r",
             "CLASS": adapter, "VERB": verb, **{k: str(v) for k, v in env.items()}}
    return subprocess.run([str(REPO / "kit" / "classes" / f"{adapter}.sh"), verb],
                          env=child, capture_output=True, text=True)


# ── secret ───────────────────────────────────────────────────────────────────

def env_file(estate, text):
    path = estate["tmp"] / "source.env"
    path.write_text(text)
    return path


TWO_LIVE_AND_ONE_DEAD = "WANTED_KEY=live-value\nOTHER_KEY=second\nRETIRED_KEY=dead\n"


def test_only_the_declared_keys_travel(estate):
    """A key that matches nothing in the pattern is a key the business retired. Carrying it to a
    new platform makes a live credential nobody remembers issuing, on a box nobody audits."""
    done = run("secret", "move", estate,
               OPT_ENV_FILE=env_file(estate, TWO_LIVE_AND_ONE_DEAD),
               OPT_KEEP_PATTERN="^(WANTED_KEY|OTHER_KEY)=")
    assert done.returncode == 0, done.stderr
    landed = (estate["roots"]["there"] / "secrets.env").read_text()
    assert "WANTED_KEY=live-value" in landed and "OTHER_KEY=second" in landed
    assert "RETIRED_KEY" not in landed


def test_no_secret_value_is_ever_printed(estate):
    """The count, never a name and never a value. The console shows this output, the operator's
    terminal scrollback keeps it, and a CI log would keep it for as long as the repo exists."""
    done = run("secret", "move", estate,
               OPT_ENV_FILE=env_file(estate, TWO_LIVE_AND_ONE_DEAD),
               OPT_KEEP_PATTERN="^(WANTED_KEY|OTHER_KEY)=")
    printed = done.stdout + done.stderr
    assert "live-value" not in printed and "second" not in printed
    assert "WANTED_KEY" not in printed
    assert "2" in printed, "the count is what makes a wrong pattern visible before the move lands"


def test_a_pattern_that_matches_nothing_is_refused_rather_than_pushed_empty(estate):
    """`t_secrets` accepts an empty file happily. The service then starts with no credentials at
    all and fails on the far side, minutes later, looking exactly like a provider outage."""
    done = run("secret", "move", estate,
               OPT_ENV_FILE=env_file(estate, TWO_LIVE_AND_ONE_DEAD),
               OPT_KEEP_PATTERN="^NOTHING_MATCHES_THIS=")
    assert done.returncode != 0
    assert "matched no key" in done.stderr
    assert not (estate["roots"]["there"] / "secrets.env").exists()


def test_a_missing_keep_pattern_stops_before_it_reads_anything(estate):
    done = run("secret", "move", estate, OPT_ENV_FILE=env_file(estate, TWO_LIVE_AND_ONE_DEAD))
    assert done.returncode != 0 and "keep_pattern" in done.stderr


def test_the_filtered_file_is_not_left_behind(estate):
    """It holds live credentials, mode 600, in a directory every user on the box can list. `die`
    exits the shell, so a RETURN trap would not fire on the refusal path -- which is the path
    that leaves it there."""
    tmpdir = estate["tmp"] / "scratch"
    tmpdir.mkdir()
    for pattern in ("^(WANTED_KEY)=", "^NOTHING_MATCHES_THIS="):
        run("secret", "move", estate, TMPDIR=str(tmpdir),
            OPT_ENV_FILE=env_file(estate, TWO_LIVE_AND_ONE_DEAD), OPT_KEEP_PATTERN=pattern)
    assert list(tmpdir.glob("secret-*")) == []


def test_rollback_says_the_copy_on_the_target_is_still_live(estate):
    """The target contract has no purge verb, so the keys pushed to an abandoned target stay
    there. A rollback that prints "done" over an unrevoked credential set stops the operator
    looking, which is worse than one that does not run."""
    done = run("secret", "rollback", estate)
    assert done.returncode == 0
    assert "STILL LIVE" in done.stderr and "revoke it by hand" in done.stderr


# ── datastore ────────────────────────────────────────────────────────────────

def seeded(estate, rows="the whole product corpus"):
    state = estate["roots"]["here"] / "state"
    state.mkdir(exist_ok=True)
    (state / "corpus.jsonl").write_text(rows)
    return state


def test_the_state_actually_arrives_on_the_other_substrate(estate):
    seeded(estate)
    done = run("datastore", "move", estate, OPT_REMOTE_PATH="/data/store")
    assert done.returncode == 0, done.stderr
    landed = estate["roots"]["there"] / "data" / "store" / "state" / "corpus.jsonl"
    assert landed.is_file(), f"nothing arrived. stdout={done.stdout} stderr={done.stderr}"
    assert landed.read_text() == "the whole product corpus"


def test_the_source_is_left_untouched(estate):
    """`t_pack` reads. If this class ever moved rather than copied, a failure anywhere later in
    the plan would leave the business with no corpus at all -- the one unrecoverable outcome."""
    state = seeded(estate)
    run("datastore", "move", estate, OPT_REMOTE_PATH="/data/store")
    assert (state / "corpus.jsonl").read_text() == "the whole product corpus"


def test_the_seed_says_out_loud_that_it_is_not_authoritative(estate):
    """The whole hazard of this class in one line of output. The service is still running and
    still writing while this copy is taken, so a reader who believes it is the final copy has
    silently lost every write made afterwards."""
    seeded(estate)
    done = run("datastore", "move", estate, OPT_REMOTE_PATH="/data/store")
    assert "NOT authoritative" in done.stdout


def test_the_verify_command_runs_against_the_incoming_copy(estate):
    """Before the swap, not after. A verify that runs after the move into place has already
    destroyed whatever was there when it fails."""
    seeded(estate)
    marker = estate["roots"]["there"] / "verify-saw"
    done = run("datastore", "move", estate, OPT_REMOTE_PATH="/data/store",
               OPT_VERIFY_CMD=f"sh -c 'ls -d \"$1\" > {marker}' _")
    assert done.returncode == 0, done.stderr
    assert marker.read_text().strip().endswith(".incoming"), (
        "the verify command was handed the incoming copy, not the live path")


def test_a_failing_verify_leaves_the_destination_alone(estate):
    """The point of verifying before the swap. If a bad copy could still land, the check is
    decoration."""
    seeded(estate)
    live = estate["roots"]["there"] / "data" / "store"
    live.mkdir(parents=True)
    (live / "already-here").write_text("the target's own state")
    done = run("datastore", "move", estate, OPT_REMOTE_PATH="/data/store", OPT_VERIFY_CMD="false")
    assert done.returncode != 0
    assert (live / "already-here").is_file(), "a failed verify destroyed the destination anyway"


def test_a_pack_that_produces_nothing_fails_here_not_on_the_far_side(estate):
    """A target adapter that fails quietly and exits 0 is the ordinary way a new substrate is
    wrong. Caught here it names t_pack; caught on the far side it is a corrupt archive."""
    (estate["targets"] / "here.sh").write_text(
        f'SIDE_ROOT="{estate["roots"]["here"]}"\n{FAKE_TARGET}\nt_pack() {{ : > "$1"; }}\n')
    done = run("datastore", "move", estate, OPT_REMOTE_PATH="/data/store")
    assert done.returncode != 0 and "t_pack produced nothing" in done.stderr


def test_a_missing_remote_path_stops_before_anything_is_packed(estate):
    seeded(estate)
    done = run("datastore", "move", estate)
    assert done.returncode != 0 and "remote_path" in done.stderr


def test_rollback_will_not_delete_a_datastore(estate):
    """The single unrecoverable action in the whole run. If the plan resumed, or the operator has
    already re-pointed at the target, the directory this would delete is the live store."""
    live = estate["roots"]["there"] / "data" / "store"
    live.mkdir(parents=True)
    (live / "corpus.jsonl").write_text("rows")
    done = run("datastore", "rollback", estate, OPT_REMOTE_PATH="/data/store")
    assert done.returncode == 0
    assert (live / "corpus.jsonl").is_file(), "rollback deleted a datastore"
    assert "left in place" in done.stderr


# ── both, and the runner's own contract ──────────────────────────────────────

@pytest.mark.parametrize("adapter", ["secret", "datastore"])
def test_an_unknown_verb_is_a_config_error_not_a_failed_step(adapter, estate):
    """Exit 78 is EX_CONFIG: nothing was touched. The runner reports it differently from a step
    that tried and failed, and an operator reads the difference as "fix the plan" rather than
    "go and look at the substrate"."""
    assert run(adapter, "sideways", estate).returncode == 78


@pytest.mark.parametrize("adapter", ["secret", "datastore"])
def test_no_verb_at_all_is_refused(adapter, estate):
    done = subprocess.run([str(REPO / "kit" / "classes" / f"{adapter}.sh")],
                          capture_output=True, text=True,
                          env={**os.environ, "MIGRATE_TARGETS_DIR": str(estate["targets"])})
    assert done.returncode != 0 and "no verb" in done.stderr


@pytest.mark.parametrize("adapter", ["secret", "datastore"])
def test_a_dry_run_changes_nothing(adapter, estate):
    """A flag that promises to change nothing and then pushes a credential set is worse than no
    flag: it is the one an operator uses to check a plan they are unsure about."""
    seeded(estate)
    child_env = {"OPT_REMOTE_PATH": "/data/store",
                 "OPT_ENV_FILE": str(env_file(estate, TWO_LIVE_AND_ONE_DEAD)),
                 "OPT_KEEP_PATTERN": "^WANTED_KEY=", "DRY_RUN": "1"}
    done = run(adapter, "move", estate, **child_env)
    assert done.returncode == 0, done.stderr
    assert "DRY" in done.stdout
    assert not (estate["roots"]["there"] / "secrets.env").exists()
    assert not (estate["roots"]["there"] / "data" / "store").exists()


# ── the join: a compiled plan, the real runner, the real adapter ─────────────

def test_a_declared_option_survives_the_whole_chain_into_the_adapter(estate, tmp_path):
    """Declaration -> `plan._step` -> `run.step_vars` -> `run.run_step` -> the real adapter.

    EVERY TEST ABOVE HANDS THE ADAPTER ITS OPTIONS DIRECTLY, so all of them keep passing if the
    runner stops passing options at all -- which is precisely the failure this programme keeps
    finding: both ends of a wire built and tested, and nothing grading the join. Deleting the
    one line in `run.step_vars` that exports OPT_* is invisible to every other test in this file.

    So this one never sets an OPT_ variable. It writes the option in a declaration and asserts it
    came out the far end, having moved a real file.
    """
    from kit.migrate.plan import _step
    from kit.migrate.run import child_env, run_step, step_vars
    from kit.projects.schema import validate

    seeded(estate)
    decl = validate({
        "project": "x", "names": ["x"], "resources_declaration": "r.yaml",
        "classes": {"secret": {"targets": ["there"]},
                    "datastore": {"targets": ["there"], "remote_path": "/data/store"}},
    }).classes["datastore"]

    step = _step({"name": "r", "where": "here"}, decl, "there")
    step["adapter"] = str(REPO / "kit" / "classes" / "datastore.sh")

    ambient = {k: v for k, v in os.environ.items() if k != "DRY_RUN"}
    def runner_call(argv, env=None, **kw):
        return subprocess.run(argv, env={**(env or {}), "MIGRATE_TARGETS_DIR": str(estate["targets"]),
                                         "MIGRATE_WORK_DIR": str(tmp_path / "work")}, **kw)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(os, "environ", ambient)
        assert "OPT_REMOTE_PATH" in step_vars(step), "the plan step lost the declaration's option"
        assert child_env(step_vars(step))["OPT_REMOTE_PATH"] == "/data/store"
        run_step(step, verb_env=step_vars(step), runner=runner_call)

    assert (estate["roots"]["there"] / "data" / "store" / "state" / "corpus.jsonl").is_file(), (
        "the runner started the real adapter and the state did not arrive -- the option did not "
        "survive the chain")
