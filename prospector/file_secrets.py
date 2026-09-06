"""Read secrets from a mounted directory, one file per name, before anything reads os.environ.

WHY THIS EXISTS. `deploy/k8s/base/engine.yaml` mounts the `prospector-engine-env` Secret as a
directory of files rather than injecting it into the container's environment. That is not a
preference: `secrets-not-from-env-vars`, one of the 26 admission policies in `deploy/k8s/policies`,
refuses `envFrom.secretRef` and `env[].valueFrom.secretKeyRef` outright, so a pod spec that puts a
secret in the environment is refused at admission. Measured 2026-08-24 against the adapter's inline
Deployment: `pass: 19, fail: 10`, and this was one of the ten.

The rest of the engine reads `os.environ`. Measured 2026-08-24, 30 files call `os.environ.get` for
a credential directly — `prospector/retrieval.py`, `prospector/operator.py`, `prospector/bridge.py`,
`prospector/api.py`, `prospector/scheduler/telegram_sender.py` and 25 more. A resolver that only
`prospector/config.py` calls would fix none of them, so this module does the one thing that fixes
all of them at once: it copies the mounted files into `os.environ` before any of that code runs.

WHERE IT RUNS. `prospector/__init__.py`, at import. Python executes a package's `__init__` before
any module inside it, so this is the only place that is guaranteed to be first for every entry
point — `run.py`, the API, the scheduler, the consumer, a test, a one-off script. Several of the
call sites above read the environment at module scope, which is why "call it from main()" is not
good enough.

THE WRITER SIDE ALREADY EXISTED. `deploy/targets/k8s.sh:115` builds the Secret with
`kubectl create secret generic prospector-engine-env --from-env-file`, which produces exactly one
key per variable, which mounts as exactly one file per variable. Nothing new was needed there, and
the two sides agree on the name because they were checked against each other rather than assumed.

THE FILE WINS OVER THE ENVIRONMENT. Both can be set on a laptop that has a `.env` and a mount. The
mounted file is what the cluster deployed and what a rotation updates; a leftover environment
variable is the stale copy. Preferring the environment would mean a rotated secret silently does
not take effect, which is the failure that is hardest to see.

NO VALUE IS EVER LOGGED, RETURNED OR RAISED. LAW 21: naming a secret is fine, printing it is not.
Every function here returns or reports NAMES. The one exception would be an exception message, so
the two `RuntimeError`s below are built from paths and names only.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# The environment-variable grammar, applied to the filename. A Secret key cannot contain a `/` or a
# NUL, but it can contain a `.` or a `-`, and `os.environ["A.B"]` is settable in Python while being
# unreachable from a shell — a variable nothing can read is worse than one that is absent, because
# it looks present. Anything that is not a legal name is refused loudly below, never skipped.
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Kubernetes builds a projected secret volume as a symlink farm: the real bytes are in a timestamped
# directory, `..data` is a symlink to the current one, and each key is a symlink to `..data/<key>`.
# The key symlinks resolve to regular files and are read normally. The `..`-prefixed entries are the
# machinery and are not keys, so they are skipped rather than refused — the same is true of the
# `..2026_08_24_09_11_02.123456789` directory an atomic update leaves behind mid-rotation.
_K8S_INTERNAL_PREFIX = ".."

ENV_VAR = "PROSPECTOR_SECRETS_DIR"


def load_secrets_dir(directory: str | os.PathLike[str] | None = None) -> tuple[str, ...]:
    """Copy every file in the secrets directory into `os.environ`. Return the names, sorted.

    Returns an empty tuple when `PROSPECTOR_SECRETS_DIR` is unset, which is every laptop, every
    test run and every CI job. Setting it is what opts a process in.

    Raises `RuntimeError` when it is set and the directory is missing, empty, holds an unreadable
    file, or holds a name no shell could read. A half-loaded credential set is the failure this
    module exists to prevent: on 2026-08-24 a box came up carrying none of its 24 settings while
    the deploy script reported success, and the symptom surfaced hours later and somewhere else,
    as "All operators unavailable - check API keys". Failing at import turns that into a container
    that will not start, which is the same information delivered where it is cheap to read.
    """
    raw = os.environ.get(ENV_VAR, "").strip() if directory is None else str(directory)
    if not raw:
        return ()

    root = Path(raw)
    if not root.is_dir():
        raise RuntimeError(
            f"{ENV_VAR}={raw} but that is not a directory. Nothing was loaded, so every "
            "credential this process needs is missing. Either the Secret is not mounted or the "
            "mountPath and the variable disagree — deploy/k8s/base/engine.yaml sets both."
        )

    loaded: dict[str, str] = {}
    for entry in sorted(root.iterdir()):
        if entry.name.startswith(_K8S_INTERNAL_PREFIX):
            continue
        if not entry.is_file():
            continue
        if not _ENV_NAME.match(entry.name):
            raise RuntimeError(
                f"{root}/{entry.name} is not a legal environment variable name. Python would "
                "accept it and no shell could ever read it back, so it is refused here instead "
                "of becoming a variable that looks set and is unreachable."
            )
        try:
            value = entry.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            # The name and the class of failure, never the bytes.
            raise RuntimeError(
                f"{root}/{entry.name} could not be read as UTF-8 text: {type(exc).__name__}. "
                "Refusing to start on a partial credential set."
            ) from None
        # One trailing newline only, and never a full strip. `printf '%s' > file` and kubectl's
        # --from-env-file both write the exact bytes, while `echo > file` appends a newline that is
        # not part of the secret. Stripping whitespace generally would silently corrupt any
        # credential whose real value has a leading or trailing space.
        loaded[entry.name] = value[:-1] if value.endswith("\n") else value

    if not loaded:
        raise RuntimeError(
            f"{ENV_VAR}={root} is an empty directory. A mount that exists and holds nothing is "
            "the shape a misnamed Secret takes, and it is indistinguishable from success to "
            "everything downstream."
        )

    os.environ.update(loaded)
    return tuple(sorted(loaded))
