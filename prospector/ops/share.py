"""Share any file in this repo as a link that works without a console session.

The founder asked for this on 2026-08-19, in these words: "not deep linnk but every file
sheeable", "would nake eternal consulationo a breeze", "i can share with claude web nonre
easily", "needs to be seanles". So the deliverable is not a browser — the console already has
one at /docs. It is a URL you can paste to a consultant, or to Claude on the web, and have them
read the file with no account, no login and no checkout.

"Deep link" and "share link" are the same object here. One URL opens one file directly.

WHAT MAKES THIS SAFE IS THE DENY-LIST, NOT THE TOKEN. A token stops strangers guessing. It does
nothing about the operator accidentally sharing a credential file. So the fence is a list of
things that can never be served, and it is applied twice: when a link is minted, and again every
time one is read. The second check is not redundant — a file can stop being tracked, or a new
secret can land under a path that was safe last week, long after a link was handed out.

THE ALLOW-LIST IS `git ls-files` WHERE GIT CAN ANSWER, AND THE DENY-LIST EVERYWHERE.
`.dockerignore` keeps `.git/` out of the engine image (see its comment: the store is 691 MB of
live state and local-only config must never be baked in), so in production `git ls-files` cannot
run. That is survivable precisely because the same file already removed `store/`, `storage/`,
`.venv/` and `node_modules/` from the image, so a tree walk in the container sees roughly what
git would list on the laptop. Both paths then pass through the same deny-list, which is written
to stand on its own rather than to top up git's answer.

BINARY FILES ARE LISTED AND NOT RENDERED. A share view that dumps bytes into a browser is a
download surface. The size and the fact that it is binary are useful; the bytes are not.
"""
from __future__ import annotations

import fnmatch
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import time
from pathlib import Path

#: What a share can cover. `file` is one path. `tree` is a directory and everything under it,
#: which is what makes an external review seamless — one link, and the reader can navigate.
#: `repo` is everything shareable. Ordered widest-last so a UI can present the safe default first.
SCOPES = ("file", "tree", "repo")

#: How long a link lives if nobody says. Deliberately short. A link with no expiry is a
#: credential nobody remembers issuing.
DEFAULT_DAYS = 7
MAX_DAYS = 90

#: Never served, whatever git says and whatever the operator asks for. Matched against the
#: repo-relative POSIX path, case-insensitively, with fnmatch.
#:
#: This list is the fence, so it is written to be safe ALONE. Do not thin it on the grounds that
#: `.gitignore` or `.dockerignore` already covers an entry — that reasoning is what turns three
#: independent fences into one, and the day the other two change nobody re-reads this file.
DENY_GLOBS = (
    ".env", ".env.*", "*.env", ".envrc",
    "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", "*.pkcs12",
    "id_rsa*", "id_ed25519*", "*.ppk",
    "*.sqlite", "*.sqlite3", "*.db",
    "*.crt",  # a certificate is public, but a mis-named private key with this suffix is not
    ".git/*", ".git",
    ".venv/*", "venv/*", "node_modules/*", "**/node_modules/*",
    "store/*", "storage/*", "signals/pending/*", "graphify-out/*",
    ".lux/keys/*",
    "**/.next/*", "__pycache__/*", "**/__pycache__/*", "*.pyc",
    "*.p8", "*.mobileprovision",
    "*secrets.yaml", "*secrets.yml", "*secrets.json", "*.secrets",
)

#: Read as text and rendered above this and it is truncated with a flag, never silently.
_MAX_BYTES = 600_000

_STORE_FILENAME = "shares.json"
_READS_FILENAME = "share_reads.jsonl"


# --------------------------------------------------------------------------- #
# The allow-list
# --------------------------------------------------------------------------- #
def _compile_deny(globs: tuple[str, ...]):
    """Precompile every deny pattern into the three tests `is_denied` runs.

    THIS IS A SPEED FIX AND NOTHING ELSE. The answers are identical to the fnmatch loop it
    replaces -- `tests/unit/test_share_deny_globs.py` runs both implementations over every
    tracked file and a crafted adversarial set and asserts the same pattern comes back.

    The measurement that bought it: the shares view calls this once per repo file, and with
    2,169 files and 39 patterns that was 140,716 `fnmatch.fnmatch` calls per page load --
    0.60s on the laptop, and `fnmatch` re-runs `os.path.normcase` on every one. Compiling the
    patterns once at import moves that work out of the loop.
    """
    out = []
    for pat in globs:
        low_pat = pat.lower()
        path_re = re.compile(fnmatch.translate(low_pat))
        # Basename patterns only. A pattern carrying a `/` is a path pattern and must never be
        # matched against a bare basename -- see the comment in `is_denied`.
        base_re = path_re if "/" not in low_pat else None
        prefix = low_pat[:-1] if low_pat.endswith("/*") else None
        out.append((pat, path_re, base_re, prefix))
    return tuple(out)


_DENY_COMPILED = _compile_deny(DENY_GLOBS)

#: One alternation of every pattern, so the common case -- a file that matches nothing -- costs
#: two regex matches and one `str.startswith` instead of a walk over all 39 patterns.
_ANY_PATH_RE = re.compile("|".join(f"(?:{fnmatch.translate(p.lower())})" for p in DENY_GLOBS))
_ANY_BASE_RE = re.compile(
    "|".join(f"(?:{fnmatch.translate(p.lower())})" for p in DENY_GLOBS if "/" not in p.lower())
    or r"(?!)"  # matches nothing, for the day every pattern carries a slash
)
_ANY_PREFIX = tuple(p.lower()[:-1] for p in DENY_GLOBS if p.lower().endswith("/*"))


def is_denied(rel: str) -> str:
    """The reason `rel` may never be shared, or "" if it may.

    Returns the matching pattern rather than a bool so the console can tell an operator WHICH
    rule refused them. "not shareable" with no reason is the kind of message that gets a fence
    removed by the next person who hits it.
    """
    low = (rel or "").lower().lstrip("/")
    if not low or "\x00" in rel:
        return "not a path"
    base = low.rsplit("/", 1)[-1]
    # Fast reject. Nothing below can match if none of these do, and almost every file lands here.
    if not (_ANY_PATH_RE.match(low)
            or _ANY_BASE_RE.match(base)
            or low.startswith(_ANY_PREFIX)):
        return ""
    for pat, path_re, base_re, prefix in _DENY_COMPILED:
        if path_re.match(low):
            return pat
        # EVERY PATTERN IS ALSO MATCHED AGAINST THE BASENAME. Without this, `id_rsa*` refuses
        # `id_rsa` at the repo root and hands over `keys/id_rsa`, which is the same key one
        # directory down. Found by the parametrised test on 2026-08-19, before this shipped.
        # The directory patterns carry a `/`, so they never match a basename by accident.
        if base_re is not None and base_re.match(base):
            return pat
        # Belt and braces on the directory patterns, and it is REDUNDANT TODAY -- measured
        # 2026-08-21. The comment here used to claim `store/*` matches `store/a` but not
        # `store/a/b` under fnmatch. That is false: fnmatch's `*` crosses `/` (it translates to
        # `.*` with DOTALL, unlike glob), so `store/*` already refuses `store/a/b/c`. Proved by
        # deleting this branch from the fast-reject and finding no test could tell.
        # It stays because it is free -- it only runs on a path something already matched --
        # and because it is the one check that does not depend on fnmatch keeping that
        # behaviour. Do not add a pattern that RELIES on it; write the pattern to stand alone.
        if prefix is not None and low.startswith(prefix):
            return pat
    return ""


def _git_tracked(repo_root: Path) -> list[str] | None:
    """Every file git tracks, or None when git cannot answer here.

    None is not an error and is not empty. Empty would mean "nothing is shareable"; None means
    "use the walk", and the caller must not confuse the two. In the engine image `.git/` is
    absent by design, so None is the NORMAL production answer.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-z"],
            capture_output=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return [p for p in out.stdout.decode("utf-8", "replace").split("\0") if p]


def _walked(repo_root: Path) -> list[str]:
    """Every file in the tree, minus the denied ones. The container path.

    Prunes denied directories as it descends rather than filtering at the end, because walking
    `node_modules/` only to throw it away is how a listing takes minutes.
    """
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        rel_dir = Path(dirpath).relative_to(repo_root).as_posix()
        prefix = "" if rel_dir == "." else rel_dir + "/"
        dirnames[:] = [d for d in dirnames if not is_denied(f"{prefix}{d}/x")]
        for name in filenames:
            rel = f"{prefix}{name}"
            if not is_denied(rel):
                found.append(rel)
    return found


def shareable_files(repo_root: Path) -> list[str]:
    """Every path this repo will serve, sorted. Both sources pass through `is_denied`."""
    tracked = _git_tracked(repo_root)
    raw = tracked if tracked is not None else _walked(repo_root)
    return sorted({p for p in raw if not is_denied(p)})


def revision(repo_root: Path) -> str:
    """The commit this tree is at, short, or "" when git cannot answer.

    Shown on the repo index so a reader can tell one version of the tree from another. Empty in
    the engine image, where `.dockerignore` removes `.git/` — and empty is honest there. A stamp
    invented when git is absent would be a version number that means nothing.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            capture_output=True, timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.decode("utf-8", "replace").strip() if out.returncode == 0 else ""


def folder_view(repo_root: Path, files: list[str]) -> dict:
    """The same file list, grouped by the folder that holds it, with sizes.

    Why this exists. The founder asked for "a final doc with a view of all files in repo", and a
    flat list of ~2,000 paths is not a view of anything — it is a wall. Grouped by folder, with a
    count and a size per folder, it is something a person can actually read and an external
    reviewer can navigate.

    IT IS COMPUTED ON EVERY READ, which is the whole answer to "auto updating". Nothing is cached
    and nothing is written to disk, so a file committed a minute ago is in the next page load and
    a file deleted is gone from it. A generated document would need a job to keep it true, and a
    job that stops leaves a document that lies.

    A file that vanished between the listing and the stat is skipped rather than fatal: this runs
    against a live working tree, and a build or a checkout can move a file mid-read.
    """
    folders: dict[str, dict] = {}
    total = 0
    for rel in files:
        parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
        try:
            size = (repo_root / rel).stat().st_size
        except OSError:
            continue
        total += size
        slot = folders.setdefault(parent, {"path": parent, "count": 0, "bytes": 0, "files": []})
        slot["count"] += 1
        slot["bytes"] += size
        slot["files"].append({
            "name": rel,
            "label": rel.rsplit("/", 1)[-1],
            "bytes": size,
        })
    return {
        "folders": [folders[k] for k in sorted(folders)],
        "total_bytes": total,
        "revision": revision(repo_root),
        "source": allow_list_source(repo_root),
        "generated_at": _now(),
    }


def allow_list_source(repo_root: Path) -> str:
    """Which of the two answers is live here. Shown in the console, because an operator looking
    at a file list needs to know whether git filtered it or a tree walk did."""
    return "git ls-files" if _git_tracked(repo_root) is not None else "tree walk + deny-list"


# --------------------------------------------------------------------------- #
# The share records
# --------------------------------------------------------------------------- #
def _store_path(store_ops_dir: Path) -> Path:
    return store_ops_dir / _STORE_FILENAME


def _load(store_ops_dir: Path) -> list[dict]:
    try:
        data = json.loads(_store_path(store_ops_dir).read_text())
    except (OSError, ValueError):
        return []
    rows = data.get("shares") if isinstance(data, dict) else data
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _save(store_ops_dir: Path, rows: list[dict]) -> None:
    """tmp + os.replace, the same way `undo.py:232` writes, so a reader never sees half a file."""
    store_ops_dir.mkdir(parents=True, exist_ok=True)
    path = _store_path(store_ops_dir)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"shares": rows}, indent=2, sort_keys=True))
    os.replace(tmp, path)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _public(row: dict) -> dict:
    """A share as the console may see it. NEVER carries the token.

    The token is shown exactly once, in the response to the mint that created it. After that only
    its hash is on disk, so the shares file is a record of what was shared and not a ring of live
    keys — which matters because that file sits on the same volume as everything else.
    """
    return {k: v for k, v in row.items() if k != "token_sha256"}


def _now() -> float:
    return time.time()


def status_of(row: dict, now: float | None = None) -> str:
    now = _now() if now is None else now
    if row.get("revoked_at"):
        return "revoked"
    if float(row.get("expires_at") or 0) <= now:
        return "expired"
    return "live"


def mint(store_ops_dir: Path, repo_root: Path, *, scope: str, target: str,
         days: int = DEFAULT_DAYS, note: str = "", actor: str = "console") -> dict:
    """Create a share and return it WITH its token, once.

    Refuses at mint time as well as at read time. Both checks are load-bearing: this one gives
    the operator an error they can act on, and the read-time one covers everything that changes
    between now and whenever the link is opened.
    """
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {', '.join(SCOPES)}")
    try:
        days = int(days)
    except (TypeError, ValueError):
        raise ValueError("days must be a whole number of days") from None
    if not 1 <= days <= MAX_DAYS:
        raise ValueError(f"days must be between 1 and {MAX_DAYS}")

    target = (target or "").strip().strip("/")
    if scope == "repo":
        target = ""
    elif not target:
        raise ValueError(f"a {scope} share needs a path")
    else:
        reason = is_denied(target if scope == "file" else f"{target}/x")
        if reason:
            raise ValueError(f"{target!r} can never be shared: it matches {reason!r}")
        resolved = _resolve_under(repo_root, target)
        if scope == "file" and not resolved.is_file():
            raise ValueError(f"{target!r} is not a file in this repo")
        if scope == "tree" and not resolved.is_dir():
            raise ValueError(f"{target!r} is not a directory in this repo")

    token = secrets.token_urlsafe(32)
    now = _now()
    row = {
        "id": _digest(token)[:12],
        "token_sha256": _digest(token),
        "scope": scope,
        "target": target,
        "note": (note or "").strip()[:200],
        "actor": actor,
        "created_at": now,
        "expires_at": now + days * 86_400,
        "revoked_at": None,
        "reads": 0,
        "last_read_at": None,
    }
    rows = _load(store_ops_dir)
    rows.append(row)
    _save(store_ops_dir, rows)
    return {**_public(row), "token": token, "path": f"/s/{token}"}


def list_shares(store_ops_dir: Path) -> dict:
    rows = _load(store_ops_dir)
    now = _now()
    out = [{**_public(r), "status": status_of(r, now)} for r in rows]
    out.sort(key=lambda r: r["created_at"], reverse=True)
    return {
        "shares": out,
        "live": sum(1 for r in out if r["status"] == "live"),
        "note": "A link dies the moment it is revoked or expires. The token is shown once, when "
                "it is created, and only its hash is kept.",
    }


def revoke(store_ops_dir: Path, share_id: str, *, actor: str = "console") -> dict:
    rows = _load(store_ops_dir)
    for row in rows:
        if row.get("id") == share_id:
            if row.get("revoked_at"):
                return {**_public(row), "status": "revoked", "already": True}
            row["revoked_at"] = _now()
            row["revoked_by"] = actor
            _save(store_ops_dir, rows)
            return {**_public(row), "status": "revoked", "already": False}
    raise ValueError(f"no share {share_id!r}")


# --------------------------------------------------------------------------- #
# Serving, with no session
# --------------------------------------------------------------------------- #
def _resolve_under(root: Path, rel: str) -> Path:
    """Resolve `rel` under `root` or raise. The only door onto the filesystem in this module.

    Resolution happens FIRST and containment is checked second, so `..` segments and symlinks are
    caught by the same test. A check on the raw string passes a link that resolves out of the
    tree — the same shape as `docs_view._safe`, and it is written twice on purpose rather than
    shared, because the two have different roots and merging them would mean one bug becomes two.
    """
    rel = (rel or "").strip().lstrip("/")
    if "\x00" in rel:
        raise ValueError("that is not a path")
    root = root.resolve()
    candidate = (root / rel).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"{rel!r} is outside the repo")
    return candidate


def _in_scope(row: dict, rel: str) -> bool:
    scope, target = row.get("scope"), (row.get("target") or "").strip("/")
    if scope == "repo":
        return True
    if scope == "file":
        return rel == target
    if scope == "tree":
        return rel == target or rel.startswith(target + "/")
    return False


def _find(store_ops_dir: Path, token: str) -> dict | None:
    """The row for a token, by constant-time hash compare over every row.

    Scanning is fine: this list is a handful of entries, and looking a row up by an id derived
    from the token would leak which ids exist to anyone probing.
    """
    want = _digest(token or "")
    for row in _load(store_ops_dir):
        if hmac.compare_digest(str(row.get("token_sha256") or ""), want):
            return row
    return None


def _record_read(store_ops_dir: Path, row: dict, rel: str, viewer: str) -> None:
    """One line per anonymous read, plus a counter on the share.

    The founder must be able to see what an outside reader actually fetched, and when. A share
    feature with no read trail cannot answer "what did they see?" after the fact, which is the
    first question anyone asks.
    """
    try:
        store_ops_dir.mkdir(parents=True, exist_ok=True)
        with (store_ops_dir / _READS_FILENAME).open("a") as fh:
            fh.write(json.dumps({"at": _now(), "share_id": row.get("id"), "path": rel,
                                 "viewer": (viewer or "")[:120]}) + "\n")
        rows = _load(store_ops_dir)
        for r in rows:
            if r.get("id") == row.get("id"):
                r["reads"] = int(r.get("reads") or 0) + 1
                r["last_read_at"] = _now()
        _save(store_ops_dir, rows)
    except OSError:
        pass  # a read trail that cannot be written must not deny the read it was recording


def open_share(store_ops_dir: Path, repo_root: Path, token: str, name: str = "",
               *, viewer: str = "anonymous") -> dict:
    """What a link shows. The whole session-less surface is this one function.

    Every refusal returns the same message and says as little as possible about why: a revoked
    token and a token that never existed must look identical from outside, or the endpoint
    becomes a way to test guesses.
    """
    row = _find(store_ops_dir, token)
    if row is None or status_of(row) != "live":
        raise PermissionError("this link is not valid. It may have expired or been revoked.")

    scope, target = row["scope"], (row.get("target") or "").strip("/")
    rel = (name or "").strip().strip("/") or (target if scope == "file" else target)

    # A tree or repo share with no file named yet shows the index, so one link is enough to
    # navigate. This is the half that makes an external review seamless.
    if scope in ("tree", "repo") and not name:
        # Recomputed here, every single read. That is what makes a `repo` link a live view of the
        # tree rather than a snapshot of the day it was minted — see `folder_view`.
        files = [f for f in shareable_files(repo_root) if _in_scope(row, f)]
        _record_read(store_ops_dir, row, "(index)", viewer)
        return {"kind": "index", "scope": scope, "target": target,
                "files": files, "count": len(files),
                **folder_view(repo_root, files),
                "note": row.get("note", ""), "expires_at": row["expires_at"]}

    if not _in_scope(row, rel):
        raise PermissionError("this link does not cover that file.")
    if is_denied(rel):
        raise PermissionError("that file is never shareable.")

    path = _resolve_under(repo_root, rel)
    if not path.is_file():
        raise FileNotFoundError(f"{rel} is not in this repo")

    raw = path.read_bytes()
    _record_read(store_ops_dir, row, rel, viewer)
    if b"\x00" in raw[:8192]:
        return {"kind": "binary", "name": rel, "bytes": len(raw), "scope": scope,
                "target": target, "expires_at": row["expires_at"],
                "note": "binary, so it is listed and not rendered"}
    return {
        "kind": "file",
        "name": rel,
        "text": raw[:_MAX_BYTES].decode("utf-8", "replace"),
        "bytes": len(raw),
        "truncated": len(raw) > _MAX_BYTES,
        "scope": scope,
        "target": target,
        "expires_at": row["expires_at"],
        "note": row.get("note", ""),
    }
