"""One YAML parser for the whole estate, backed by libyaml where libyaml exists.

WHY THIS FILE EXISTS, with the measurement that bought it.

`config.yaml` is 2,778 lines and 194 KB. PyYAML's default `safe_load` is a pure-Python
scanner, and on that file it costs **0.79s on the laptop and 2.49s in the engine container**.
Nothing in the estate reads config.yaml once: `config.load_config` is uncached, and a single
ops-console page load calls it twice, on top of ~1.9s of imports. Measured in production on
2026-08-21, one console read of the shares view took **13.76s**, and 5.0s of it was this parse.

PyYAML ships a libyaml-backed loader that parses the same document to the same object. Measured
on the same two machines the same day:

    laptop     safe_load 0.788s  ->  CSafeLoader 0.039s   (20x)
    container  safe_load 2.490s  ->  CSafeLoader 0.233s   (11x)

and `yaml.safe_load(src) == yaml.load(src, Loader=CSafeLoader)` on our actual config.yaml.

IT FALLS BACK, AND THAT IS THE POINT. `CSafeLoader` only exists when PyYAML was built against
libyaml. It is present in the manylinux wheels we deploy and in this laptop's venv, but a fresh
environment somewhere else may not have it, and a config parser that raises ImportError at
startup would take the engine down to save a second. `LIBYAML` says which one is live, so a test
can assert the fast path is actually being taken where we expect it rather than trusting that it
is.

SAFE means the same thing in both. `CSafeLoader` uses `SafeConstructor`, so it constructs only
plain Python scalars, lists and dicts -- no arbitrary object instantiation, the property that
makes `safe_load` safe to point at a file an operator can edit from the portal.
"""

from __future__ import annotations

from typing import Any

import yaml

try:  # pragma: no cover - the branch taken depends on how PyYAML was built, not on our code
    from yaml import CSafeLoader as _Loader

    LIBYAML = True
except ImportError:  # pragma: no cover - see above
    from yaml import SafeLoader as _Loader  # type: ignore[assignment]

    LIBYAML = False

#: The loader in use. Exported so a caller that must parse with extra options still gets the
#: fast one, instead of quietly reaching for `yaml.SafeLoader` and losing the win.
Loader = _Loader

__all__ = ["LIBYAML", "Loader", "safe_load"]


def safe_load(stream: Any) -> Any:
    """`yaml.safe_load`, on libyaml when it is available.

    Identical contract to `yaml.safe_load`: same accepted inputs (str, bytes or a file object),
    same returned objects, same `yaml.YAMLError` on a malformed document.
    """
    return yaml.load(stream, Loader=_Loader)
