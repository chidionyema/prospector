"""Control Center pages.

Each page module exposes a `render()` function.
Import pages via this package: `from prospector.control_center.pages import _overview`
"""
from . import _overview
from . import _catalogue
from . import _launcher
from . import _diagnostics
from . import _parameters
from . import _reports
from . import _resume
