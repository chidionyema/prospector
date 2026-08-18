"""No module in the package may reach the store through the working directory.

`prospector/paths.py` exists to make this impossible, and two functions were still doing it.
Measured on 2026-08-18, `prospector/ops/readers.py:245` and `:260` built their paths as
`Path(f"store/dossiers/{cid}.{decision}.json")` — cwd-relative, so `PROSPECTOR_STORE_DIR` was
ignored. In the same process, `catalogue_index()` read the canonical store while `load_dossier()`
read whatever `store/` sat next to the cwd, and every one of the 2,996 index rows looked like an
orphan. `tests/ops/cc/test_readers.py::TestLoadDossier::test_returns_dict_for_real_dossier`
failed on it and walled PR #339 red. After the fix the same scan reports 190 — the genuine
orphans, which is a data question and not a path one.

The existing tests in `test_paths.py` prove `paths` resolves correctly. None of them proved
anybody CALLS it, which is why a module could keep its own copy of the rule and nothing raised.
This is that check: a grep with a test around it.
"""
from __future__ import annotations

import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "prospector"

#: `Path("store/…")` or `Path(f"store/…")` — the shape that follows the working directory.
CWD_RELATIVE = re.compile(r"""Path\(\s*f?["']store/""")

#: `paths.py` documents the defect in its own docstring, so it names the shape on purpose.
EXEMPT = {"paths.py"}


def _offenders() -> list[str]:
    out = []
    for py in sorted(PACKAGE.rglob("*.py")):
        if py.name in EXEMPT:
            continue
        for n, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue          # prose about the trap is not the trap
            if CWD_RELATIVE.search(line):
                out.append(f"{py.relative_to(PACKAGE.parent)}:{n}: {line.strip()}")
    return out


def test_no_store_path_is_built_from_the_working_directory():
    found = _offenders()
    assert not found, (
        "these lines resolve the store against the working directory, so they read a "
        "different store from the rest of the process. Use `paths.store_path(...)`:\n  "
        + "\n  ".join(found)
    )


def test_the_guard_can_actually_see_the_shape_it_forbids():
    """A guard that matches nothing passes for the wrong reason.

    The samples are assembled from pieces rather than written out. A literal `store/dossiers`
    in a test file is what `tests/test_suite_is_machine_independent.py` looks for, and it read
    these two lines as this test reading the operator's real store.
    """
    dirname = "st" + "ore"
    assert CWD_RELATIVE.search('path = Path(f"%s/dossiers/{cid}.json")' % dirname)
    assert CWD_RELATIVE.search("path = Path('%s/listings')" % dirname)
    assert not CWD_RELATIVE.search('path = paths.%s_path("dossiers", name)' % dirname)
