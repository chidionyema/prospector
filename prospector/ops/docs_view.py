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

#: Directories under `docs/` that are a category by virtue of being a directory, in the order an
#: operator would want them. Anything not listed is still readable by name if it is under the docs
#: root — this only shapes the index.
#:
#: `archive/` is deliberately absent. `design/` is too: it is mostly `.png`, which `_SUFFIXES`
#: drops anyway.
_DIR_SECTIONS = (
    ("decisions", "Decisions — what we chose and why"),
    ("incidents", "Incidents — what broke, and what stops it repeating"),
    ("personas", "Personas — how each role actually works"),
)

#: How the ~78 documents at the TOP LEVEL of `docs/` are split up.
#:
#: WHY THIS TABLE EXISTS. Until 2026-08-20 the index had three sections and the third was the
#: empty string, which meant "everything else at the top level". Measured that day: 104 documents,
#: three sections, **78 of them in that one bucket**. The founder's words were "no way to search
#: and filter etc or categorise", and an unsorted list of 78 is what he was looking at. A bucket
#: holding three quarters of the estate's writing is not a category.
#:
#: FIRST MATCH WINS, so the order is the meaning. `PLATFORM_PORTABILITY_AUDIT.md` is an audit
#: before it is a platform document, and `ENGINE_MIGRATION_PROGRAM.md` is a programme before it is
#: anything else — programmes are the things with a ledger, so they lead.
#:
#: A rule is `(kind, needle)` where kind is `suffix`, `prefix` or `has`, matched against the
#: filename in upper case. `_categorise` is the only reader.
_CATEGORIES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    ("Programmes — tracked work with a ledger", (
        ("suffix", "_PROGRAM.MD"),
        ("suffix", "_WAR_PLAN.MD"),
    )),
    ("Audits and reviews — what was measured", (
        ("has", "AUDIT"), ("has", "REVIEW"), ("has", "CRITIQUE"), ("has", "BASELINE"),
        ("has", "FLAKINESS"),
    )),
    ("Specs and contracts — what the thing must do", (
        ("suffix", "_SPEC.MD"), ("suffix", "_SPECIFICATION.MD"),
        ("has", "CONTRACT"), ("has", "_TICKET"),
    )),
    ("Runbooks and process — how to do it", (
        ("has", "RUNBOOK"), ("has", "_PROCESS"), ("has", "WAYS_OF_WORKING"),
        ("has", "AGENT_SETUP"), ("has", "DEPLOY_PIPELINE"), ("has", "GATES"),
        ("has", "PRINCIPLES"), ("has", "DIRECTIVES"), ("has", "MANIFESTO"),
    )),
    ("Platform and estate — what is running, and where", (
        ("prefix", "PLATFORM_"), ("prefix", "ESTATE_"), ("prefix", "RELIABILITY_"),
        ("prefix", "ARCHITECTURE_"), ("prefix", "LOGGING_"), ("prefix", "CI_"),
        ("has", "PROCESS_INVENTORY"), ("has", "AUTONOMY"),
    )),
    ("Briefs — work handed to someone else", (
        ("has", "BRIEF"),
    )),
    ("Registers and status — where things stand", (
        ("has", "BACKLOG"), ("has", "WORK_REGISTER"), ("prefix", "NEXT_MOVE"),
        ("has", "PROGRESS"), ("has", "LEDGER"), ("prefix", "BRANCH_CLEANUP"),
        ("has", "LINKS"), ("has", "FOUNDER_NOTES"), ("has", "REMAINING_WORK"),
    )),
)

#: Where a top-level document goes when no rule above claims it. Kept as a real label rather than
#: a silent bucket, so it is obvious on the page when it starts growing again.
_UNCATEGORISED = "Everything else"


def _categorise(filename: str) -> str:
    """The section label for one top-level document. First matching rule wins."""
    upper = filename.upper()
    for label, rules in _CATEGORIES:
        for kind, needle in rules:
            if kind == "suffix" and upper.endswith(needle):
                return label
            if kind == "prefix" and upper.startswith(needle):
                return label
            if kind == "has" and needle in upper:
                return label
    return _UNCATEGORISED


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


def _entry(root: Path, path: Path, category: str = "") -> dict:
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
    return {"name": rel, "title": title, "bytes": stat.st_size, "modified": stat.st_mtime,
            "category": category or _categorise(path.name)}


def docs_index(repo_root: Path) -> dict:
    """Every readable doc, grouped into the sections above. No file contents."""
    root = _docs_root(repo_root)
    if not root.is_dir():
        return {"root": str(root), "sections": [], "count": 0,
                "note": "there is no docs/ directory in this checkout"}

    sections: list[dict] = []
    seen: set[str] = set()

    def _collect(base: Path, label: str) -> list[dict]:
        """The readable files directly in `base`, as index entries. Never recurses.

        Nested trees stay out of the index so it does not become a wall; they are still readable
        by name through `doc_view`.
        """
        out = []
        for p in sorted(base.iterdir()):
            if not p.is_file() or p.suffix.lower() not in _SUFFIXES:
                continue
            resolved = p.resolve()
            rel = resolved.relative_to(root).as_posix()
            if rel in seen:
                continue
            seen.add(rel)
            out.append(_entry(root, resolved, label))
        return out

    for sub, label in _DIR_SECTIONS:
        base = (root / sub).resolve()
        if not base.is_dir():
            continue
        found = _collect(base, label)
        if found:
            sections.append({"label": label, "docs": found})

    # The top level, split by `_CATEGORIES` rather than dumped into one bucket. Collected first,
    # then grouped, so the category order below is the declared one and not the filesystem's.
    top = _collect(root, "")
    by_label: dict[str, list[dict]] = {}
    for entry in top:
        by_label.setdefault(entry["category"], []).append(entry)
    for label, _rules in _CATEGORIES:
        if by_label.get(label):
            sections.append({"label": label, "docs": by_label[label]})
    if by_label.get(_UNCATEGORISED):
        sections.append({"label": _UNCATEGORISED, "docs": by_label[_UNCATEGORISED]})

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
