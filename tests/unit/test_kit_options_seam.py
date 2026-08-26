"""The declaration's own knobs, from the YAML to the adapter's environment.

WHY THIS SEAM EXISTS. An adapter for `secret` has to know which keys travel; an adapter for
`datastore` has to know where the state lands. Both answers differ per business. Compiling
either into `kit/` puts one business's private facts in shared code, which clause A5 forbids,
and makes the second business need a code change, which clause A7 forbids. So the answers ride
in the declaration and the kit passes them through without reading them.

WHAT IS ACTUALLY GRADED HERE IS THE PASS-THROUGH. Every refusal below is knowable from the
declaration alone, and every one of them would otherwise surface as an adapter behaving oddly
at whatever minute the run first reached that class -- the most expensive place in a migration
to learn anything at all.
"""

from __future__ import annotations

import pytest

from kit.migrate.plan import _step
from kit.migrate.run import step_vars
from kit.projects.schema import CLASS_ADAPTERS, DeclarationError, validate


def declaration(**class_body):
    """The smallest declaration that validates, with one class body under test."""
    body = {"targets": ["fly"], **class_body}
    return {"project": "x", "names": ["x"], "resources_declaration": "r.yaml",
            "classes": {"secret": body}}


def test_a_key_beside_targets_becomes_an_option():
    project = validate(declaration(keep_pattern="^A=", env_file="/tmp/x"))
    assert project.classes["secret"].options == {"keep_pattern": "^A=", "env_file": "/tmp/x"}


def test_targets_is_not_an_option():
    """`targets` is the kit's own field. Leaking it into the options would hand every adapter an
    OPT_TARGETS it never asked for, and invite one to read it instead of FROM and TO."""
    assert validate(declaration()).classes["secret"].options == {}


def test_a_class_with_no_options_hands_the_adapter_none():
    """The ordinary case, and the one an adapter must survive: absent, not empty-string."""
    step = _step({"name": "r", "where": "fly"}, validate(declaration()).classes["secret"], "k8s")
    assert step["options"] == {}
    assert not [k for k in step_vars(step) if k.startswith("OPT_")]


def test_the_option_reaches_the_adapter_as_an_env_var():
    decl = validate(declaration(keep_pattern="^A=")).classes["secret"]
    env = step_vars(_step({"name": "r", "where": "fly"}, decl, "k8s"))
    assert env["OPT_KEEP_PATTERN"] == "^A="


def test_an_option_cannot_overwrite_a_variable_the_runner_owns():
    """The `OPT_` prefix is load-bearing. Without it a declaration could name an option `to` and
    silently redirect the move to a substrate the plan never mentioned -- a change of destination
    that no reader of the plan could see."""
    decl = validate(declaration(to="somewhere-else", verb="rollback")).classes["secret"]
    env = step_vars(_step({"name": "r", "where": "fly"}, decl, "k8s"))
    assert env["TO"] == "k8s" and env["VERB"] == "move"
    assert env["OPT_TO"] == "somewhere-else" and env["OPT_VERB"] == "rollback"


def test_a_number_survives_as_a_string():
    """YAML types an unquoted 30 as an int. An environment variable is text, and the conversion
    has to happen where it can be reported, not inside `subprocess` as a TypeError."""
    env = step_vars(_step({"name": "r", "where": "fly"},
                          validate(declaration(timeout_s=30)).classes["secret"], "k8s"))
    assert env["OPT_TIMEOUT_S"] == "30"


@pytest.mark.parametrize("body, because", [
    ({"keys": ["A", "B"]}, "a list cannot ride in an environment variable"),
    ({"nested": {"a": 1}}, "nor can a mapping"),
    ({"keep-pattern": "^A="}, "OPT_KEEP-PATTERN is not a name any shell can read back"),
    ({"enabled": True}, "a bool would reach the adapter as `True`, which no shell test matches"),
])
def test_an_option_the_runner_could_not_pass_is_refused_at_load(body, because):
    with pytest.raises(DeclarationError):
        validate(declaration(**body)), because


def test_two_options_that_collide_when_upper_cased_are_refused():
    """Both become OPT_KEEP_PATTERN. The survivor would be whichever the mapping yielded last,
    which is a coin toss decided by file order -- and the loser is silently ignored."""
    with pytest.raises(DeclarationError, match="OPT_KEEP_PATTERN"):
        validate(declaration(keep_pattern="^A=", KEEP_PATTERN="^B="))


def test_the_error_names_the_class_and_the_option():
    """A declaration is read by a person under time pressure. `class secret: option keys` is a
    line they can go and look at; "invalid declaration" is a file they have to search."""
    with pytest.raises(DeclarationError) as raised:
        validate(declaration(keys=["A"]))
    assert "secret" in str(raised.value) and "keys" in str(raised.value)


def test_the_shipped_declaration_gives_both_wired_classes_what_they_need():
    """The seam is only worth anything if the real declaration actually carries the real knobs.
    These two names are the contract between `kit/projects/prospector.yaml` and the adapters in
    `kit/classes/`, and nothing else checks that the two files agree."""
    from pathlib import Path

    from kit.projects.schema import load

    project = load(Path(__file__).resolve().parents[2] / "kit" / "projects" / "prospector.yaml")
    assert "keep_pattern" in project.classes["secret"].options
    assert {"remote_path", "verify_cmd"} <= set(project.classes["datastore"].options)
    for klass in ("secret", "datastore"):
        assert CLASS_ADAPTERS[klass] == f"kit/classes/{klass}.sh"
