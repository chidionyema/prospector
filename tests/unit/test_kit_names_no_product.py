"""Clause A5: no product name appears in the kit's code.

The kit moves any business. The moment one business's name is compiled into it, adding
the second product costs a code change instead of a declaration, which is clause A7 gone
as well. This test is what makes A5 mechanical rather than a promise.

WHAT IS EXEMPT, AND WHY. `kit/projects/*.yaml` — a project declaration is the seam where
names are SUPPOSED to live, and a declaration that could not name its own project would
be useless. Everything else under kit/ is graded, including the shell adapters.

The names are read from the declarations themselves, so adding a second product
automatically extends what this test forbids.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
KIT = REPO / "kit"
DECLARATIONS = KIT / "projects"


def product_names() -> set[str]:
    names: set[str] = set()
    for decl in sorted(DECLARATIONS.glob("*.yaml")):
        raw = yaml.safe_load(decl.read_text()) or {}
        names.update(n.lower() for n in raw.get("names", []))
        if isinstance(raw.get("project"), str):
            names.add(raw["project"].lower())
    return names


def graded_files() -> list[Path]:
    return [
        p for p in sorted(KIT.rglob("*"))
        if p.is_file()
        and p.suffix in {".py", ".sh", ".md"}
        and DECLARATIONS not in p.parents
    ]


def test_there_is_at_least_one_declaration_to_read_names_from():
    assert product_names(), "no project declaration under kit/projects/ — this test would grade nothing"


def test_there_is_something_to_grade():
    assert graded_files(), "no kit source files — this test would pass by finding nothing"


@pytest.mark.parametrize("path", graded_files(), ids=lambda p: str(p.relative_to(REPO)))
def test_no_product_name_appears_in_kit_source(path: Path):
    names = product_names()
    text = path.read_text(errors="replace")
    offences = []
    for lineno, line in enumerate(text.splitlines(), 1):
        low = line.lower()
        for name in names:
            if re.search(rf"\b{re.escape(name)}\b", low):
                offences.append(f"{path.relative_to(REPO)}:{lineno} names `{name}`")
    assert not offences, (
        "a product name is compiled into the kit — move it into a project declaration:\n  "
        + "\n  ".join(offences)
    )
