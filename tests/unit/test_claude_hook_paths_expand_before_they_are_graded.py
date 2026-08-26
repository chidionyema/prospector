"""The `claude hooks` check must not report a file that is present on disk.

Measured 2026-08-21: it reported four missing hook scripts. Three of them existed -- the regex
was anchored at "/", so it matched "/.claude/scripts/x.py" out of "~/.claude/scripts/x.py" and
the leading ~ fell outside the match, which made the expansion a no-op. The fourth,
"/checkout_currency.py", was never a path at all: it was bitten out of the git revision spec
`git show origin/main:scripts/checkout_currency.py`.

The cost of the false version is not the wrong count. It is that every session that read the
audit went hunting for a file that had been there the whole time, and that a check nobody
believes stops being read at all -- so the day a hook script really does get renamed, the red
line looks like the same old noise.
"""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "process_audit_hookpaths", ROOT / "scripts" / "process_audit.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _hooks(*commands):
    return {"PreToolUse": [{"hooks": [{"command": c} for c in commands]}]}


def test_a_tilde_path_that_exists_is_not_reported_missing(tmp_path, monkeypatch):
    script = tmp_path / "guard.py"
    script.write_text("print(1)\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    mod = _load()

    events, missing = mod.scan_hook_scripts(_hooks("python3 ~/guard.py"))

    assert events == 1
    assert missing == [], f"a ~ path that exists was reported missing: {missing}"


def test_a_dollar_var_path_is_expanded_before_the_existence_test(tmp_path, monkeypatch):
    script = tmp_path / "fence.sh"
    script.write_text("true\n", encoding="utf-8")
    monkeypatch.setenv("GUARDS", str(tmp_path))
    mod = _load()

    _events, missing = mod.scan_hook_scripts(_hooks("bash $GUARDS/fence.sh"))

    assert missing == [], f"a $VAR path that exists was reported missing: {missing}"


def test_a_git_revision_spec_yields_no_path_at_all():
    """The colon in `origin/main:scripts/x.py` is not part of any filesystem path."""
    mod = _load()

    _events, missing = mod.scan_hook_scripts(
        _hooks("git show origin/main:scripts/checkout_currency.py")
    )

    assert missing == [], f"a git revision spec was read as a path: {missing}"


def test_a_hook_script_that_is_genuinely_gone_is_still_reported(tmp_path, monkeypatch):
    """The check must keep its teeth. This is the failure it exists to catch."""
    monkeypatch.setenv("HOME", str(tmp_path))
    mod = _load()

    _events, missing = mod.scan_hook_scripts(_hooks("python3 ~/renamed-away.py"))

    assert missing == ["~/renamed-away.py"], missing


def test_every_hook_command_is_counted_even_when_it_names_no_script():
    mod = _load()

    events, missing = mod.scan_hook_scripts(_hooks("echo hello", "true"))

    assert (events, missing) == (2, [])
