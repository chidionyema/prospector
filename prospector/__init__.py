"""Prospector — opportunity vetting engine."""
__version__ = "0.1.0"

# Mounted secrets become environment variables BEFORE any module in this package runs. Python
# executes a package's __init__ before any of its submodules, and several of them read os.environ
# at module scope, so this is the only placement that is early enough for all of them. It is a
# no-op unless PROSPECTOR_SECRETS_DIR is set, which is every laptop and every test run. See
# prospector/file_secrets.py for why the secrets are files at all.
from .file_secrets import load_secrets_dir as _load_secrets_dir

_load_secrets_dir()
