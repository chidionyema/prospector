"""Read the repo's own documentation from the ops console.

The founder asked twice on 2026-08-19 whether docs were reachable from ops. They were not: no
console page rendered markdown, no API route read `docs/`, and the console had no markdown
dependency at all. So a decision record, a runbook or a programme spec could only be read by
someone with a checkout and a terminal — which is the same "built and unreachable" failure the
cockpit work has hit before.

This module is the READ half. It lists the docs and returns one of them as text.

WHAT THIS IS NOT: the share half. A public or private link that expires and can be revoked is a
different build — it needs a token store and a route that answers without a session — and it is
tracked as its own task. Nothing here is reachable without an authenticated console session.

PATH SAFETY IS THE WHOLE JOB HERE. The document name arrives from an HTTP query string, and this
is the first read view in the console that turns operator input into a filesystem path. A name
like `../../.env` must not resolve, and neither must a symlink pointing out of the tree. Both are
refused by resolving the candidate and requiring it to sit under the docs root, which is checked
AFTER resolution so a link cannot smuggle a path past a string comparison.
"""
from __future__ import annotations

from pathlib import Path

#: Only these extensions are ever served. The docs tree holds `.json` incident records too, and
#: they are useful to read, but every one of them is also rendered by `incident.py`; keeping the
#: set to text formats means this view can never be pointed at a credential file that happens to
#: have been dropped under docs/.
_SUFFIXES = (".md", ".json")

#: Directories under `docs/` worth offering, in the order an operator would want them. Anything
#: not listed is still readable by name if it is under the docs root — this only shapes the index.
_SECTIONS = (
    ("decisions", "Decisions — what we chose and why"),
    ("incidents", "Incidents — what broke, and what stops it repeating"),
    ("", "Programmes, specs and runbooks"),
)


def _docs_root(repo_root: Path) -> Path:
    return (repo_root / "docs").resolve()


def _safe(root: Path, name: str) -> Path:
    """Resolve `name` under `root`, or raise. The only door onto the filesystem in this module.

    Resolution happens FIRST and the containment check second, so `..` segments and symlinks are
    both caught by the same test — a check on the raw string would pass a link that resolves out
    of the tree.
    """
    name = (name or "").strip().lstrip("/")
    if not name:
        raise ValueError("read docs needs --arg name=<path under docs/>")
    if "\x00" in name:
        raise ValueError("that is not a document name")
    candidate = (root / name).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"{name!r} is outside docs/, so it is not readable here")
    if candidate.suffix.lower() not in _SUFFIXES:
        raise ValueError(f"only {', '.join(_SUFFIXES)} files are readable here")
    if not candidate.is_file():
        raise ValueError(f"{name!r} does not exist")
    return candidate


def _entry(root: Path, path: Path) -> dict:
    rel = path.relative_to(root).as_posix()
    stat = path.stat()
    title = rel
    if path.suffix.lower() == ".md":
        # The first `# heading`, which is the doc's own name for itself. Falls back to the path,
        # so a doc without a heading is listed rather than dropped.
        try:
            for line in path.read_text(errors="replace").splitlines()[:40]:
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
        except OSError:
            pass
    return {"name": rel, "title": title, "bytes": stat.st_size, "modified": stat.st_mtime}


def docs_index(repo_root: Path) -> dict:
    """Every readable doc, grouped into the sections above. No file contents."""
    root = _docs_root(repo_root)
    if not root.is_dir():
        return {"root": str(root), "sections": [], "count": 0,
                "note": "there is no docs/ directory in this checkout"}

    sections = []
    seen: set[str] = set()
    for sub, label in _SECTIONS:
        base = (root / sub).resolve() if sub else root
        if not base.is_dir():
            continue
        # Top level of the section only. `archive/` and other nested trees stay out of the index
        # so it does not become a 400-line wall; they are still readable by name.
        found = []
        for p in sorted(base.iterdir()):
            if not p.is_file() or p.suffix.lower() not in _SUFFIXES:
                continue
            rel = p.resolve().relative_to(root).as_posix()
            if rel in seen:
                continue
            seen.add(rel)
            found.append(_entry(root, p.resolve()))
        if found:
            sections.append({"label": label, "docs": found})
    return {"root": str(root), "sections": sections, "count": len(seen)}


def doc_view(repo_root: Path, name: str, *, max_bytes: int = 400_000) -> dict:
    """One document as text.

    Truncates rather than refusing on a large file: the console must not be the reason an operator
    cannot see the top of a long programme doc. `truncated` says so plainly, because a silently
    shortened document is a document that lies.
    """
    root = _docs_root(repo_root)
    path = _safe(root, name)
    raw = path.read_bytes()
    truncated = len(raw) > max_bytes
    text = raw[:max_bytes].decode("utf-8", errors="replace")
    return {
        "name": path.relative_to(root).as_posix(),
        "title": _entry(root, path)["title"],
        "text": text,
        "bytes": len(raw),
        "truncated": truncated,
        "modified": path.stat().st_mtime,
    }
