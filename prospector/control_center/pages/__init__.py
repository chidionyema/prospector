"""Control Center pages.

Each page module exposes a `render()` function.
Import pages via this package: `from prospector.control_center.pages import _overview`
"""
from . import (  # noqa: F401 - re-exported page modules for discovery
    _catalogue,
    _diagnostics,
    _engine,
    _launcher,
    _metrics,
    _overview,
    _parameters,
    _reports,
    _resume,
    _runs,
    _spend,
)
