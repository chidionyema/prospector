"""Read the repo's own documentation from the ops console.

The founder asked twice on 2026-08-19 whether docs were reachable from ops. They were not: no
console page rendered markdown, no API route read `docs/`, and the console had no markdown
dependency at all. So a decision record, a runbook or a programme spec could only be read by
someone with a checkout and a terminal — which is the same "built and unreachable" failure the
cockpit work has hit before.

This module is the READ half. It lists the docs and returns one of them as text.

WHY THE INDEX COVERS THE WHOLE REPO, NOT `docs/` (changed 2026-08-21). The founder's words were
"no docs are nissed out". Measured that morning against `origin/main`: **298 tracked document
files, 113 of them visible on the page and 185 invisible.** Three mechanical causes, none of
them a decision anyone made:

  146  the index root was `docs/`, so nothing outside it existed
   21  `_collect` never recursed, so `docs/design/…` and `docs/storefront/…` were dropped
   18  the suffix allow-list was `(.md, .json)`, so every `.html` and `.txt` was dropped

The page therefore listed a third of the estate's writing while looking complete, which is worse
than listing none of it: an index that confidently omits things is one nobody re-checks.

ONE POPULATION, ONE FENCE. The index now enumerates `share.shareable_files()` — the exact list
the share tokens are minted from — filtered to document formats. That is deliberate and it is the
load-bearing part of this change: if the index and the share fence kept separate ideas of what
exists, a file could be listed and unshareable, or shareable and unlisted, and the two would drift
apart silently. `share.is_denied` is applied AGAIN in `_safe`, at read time, so widening the root
past `docs/` cannot widen what is readable. `.env`, `*.pem`, `store/*` and the other 36 globs are
refused here by the same rule that refuses them a share link.

PATH SAFETY IS THE WHOLE JOB HERE. The document name arrives from an HTTP query string, and this
is the first read view in the console that turns operator input into a filesystem path. A name
like `../../.env` must not resolve, and neither must a symlink pointing out of the tree. Both are
refused by resolving the candidate and requiring it to sit under the repo root, which is checked
AFTER resolution so a link cannot smuggle a path past a string comparison — and then the deny-list
runs on the resolved repo-relative path.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import share

#: Document formats served as text, anywhere in the repo.
#:
#: `.json` is NOT here and is handled separately below, because repo-wide it is a data format
#: rather than a document: 123 of them are `package.json`, `tsconfig.json` and test fixtures, and
#: listing those would bury the writing this page exists to surface. Under `docs/` it IS a
#: document — the incident records are JSON — so the rule is scoped rather than dropped.
_TEXT_SUFFIXES = (".md", ".html", ".txt")

#: Formats that are LISTED but not rendered as text. One file today
#: (`prospector-master-spec.pdf`, 219,811 bytes). It is listed rather than filtered out because a
#: silent exception is exactly the defect this rewrite closes; `doc_view` returns an honest
#: explanation for it instead of an error, so clicking it does something sensible.
_BINARY_SUFFIXES = (".pdf",)

#: How much of a file is read to find its title. The whole file used to be read and then split,
#: which on a 400 KB programme doc is 400 KB of I/O to look at 40 lines. With the index now
#: covering ~3x as many files, and the founder's complaint about this page being slow, the bound
#: matters: this is the only read the index does.
_TITLE_BYTES = 4096

#: Directories under `docs/` that are a category by virtue of being a directory, in the order an
#: operator would want them.
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

#: Where a top-level `docs/` document goes when no rule above claims it. Kept as a real label
#: rather than a silent bucket, so it is obvious on the page when it starts growing again.
_UNCATEGORISED = "Everything else"

#: Section label for documents that sit at the repo root (`README.md`, `CLAUDE.md`, `RUN.md`…).
_ROOT_SECTION = "Repo root"


def _categorise(filename: str) -> str:
    """The section label for one top-level `docs/` document. First matching rule wins."""
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


def _suffix(rel: str) -> str:
    """The lower-cased extension of a repo-relative POSIX path, or "".

    A plain string split rather than `PurePosixPath(rel).suffix`. Measured 2026-08-21: building a
    path object per file cost 261 ms across the repo walk, for an answer two `rsplit`s give.
    """
    name = rel.rsplit("/", 1)[-1]
    dot = name.rfind(".")
    return name[dot:].lower() if dot > 0 else ""


def _is_readable(rel: str) -> bool:
    """Whether `rel` may be returned as text. The suffix half of the read fence."""
    suffix = _suffix(rel)
    if suffix in _TEXT_SUFFIXES:
        return True
    # A data format everywhere except under docs/, where the incident records live.
    return suffix == ".json" and rel.startswith("docs/")


def _is_listed(rel: str) -> bool:
    """Whether `rel` belongs in the index. A superset of `_is_readable` by the binary formats."""
    return _is_readable(rel) or _suffix(rel) in _BINARY_SUFFIXES


def _section_for(rel: str) -> str:
    """The section label for one repo-relative document path.

    Three rules, in order. Top-level `docs/` files keep the `_CATEGORIES` split they already had.
    The three named `docs/` subdirectories keep their friendly labels. Everything else is grouped
    by DIRECTORY, at one level of depth outside `docs/` and two inside it — so `docs/design/…`
    and `docs/storefront/…` are their own sections rather than being folded into one `docs`
    heading, while `tools/experiments/…` and `tools/…` share one. The console renders one filter
    chip per section, so depth here is a choice about how many chips an operator has to read.
    """
    parts = rel.split("/")
    if len(parts) == 1:
        return _ROOT_SECTION
    if parts[0] == "docs":
        if len(parts) == 2:
            return _categorise(parts[1])
        for sub, label in _DIR_SECTIONS:
            if parts[1] == sub:
                return label
        return "docs/" + parts[1]
    return parts[0]


def _safe(root: Path, name: str) -> Path:
    """Resolve `name` under `root`, or raise. The only door onto the filesystem in this module.

    Resolution happens FIRST and the containment check second, so `..` segments and symlinks are
    both caught by the same test — a check on the raw string would pass a link that resolves out
    of the tree. The deny-list then runs on the resolved repo-relative path, which is what makes
    a repo-wide root safe: containment alone would now admit `.env`.

    `name` is repo-relative (`docs/LINKS.md`). A bare `LINKS.md` is also accepted and tried under
    `docs/`, because every `?open=` link minted before 2026-08-21 — and every link the Incidents
    page builds — is in the old docs-relative form, and a bookmark that silently 404s is the same
    "built and unreachable" failure this module exists to fix.
    """
    name = (name or "").strip().lstrip("/")
    if not name:
        raise ValueError("read docs needs --arg name=<path in the repo>")
    if "\x00" in name:
        raise ValueError("that is not a document name")

    # Both candidate forms are tried in full, and the FIRST ONE THAT PASSES EVERY CHECK wins.
    # Failing fast on the first candidate was a real bug for one turn on 2026-08-21: the Incidents
    # page links `incidents/INC-….json`, whose repo-root form is a `.json` outside `docs/` and so
    # is not a document — the suffix check refused it before the `docs/` form was ever tried, and
    # every incident link on the page went dead. Each candidate is fenced independently, so a
    # failure on one says nothing about the other.
    #
    # The rank picks WHICH failure to report when both fail: a file that exists and is refused is
    # a better explanation than one that was never there.
    failures: list[tuple[int, str]] = []
    for candidate_name in (name, f"docs/{name}"):
        candidate = (root / candidate_name).resolve()
        if not candidate.is_relative_to(root):
            failures.append((0, f"{name!r} is outside the repository, so it is not readable here"))
            continue
        rel = candidate.relative_to(root).as_posix()
        exists = candidate.is_file()
        denied = share.is_denied(rel)
        if denied:
            failures.append(
                (3 if exists else 1, f"{rel!r} is refused by the share deny-list ({denied})")
            )
            continue
        if not _is_readable(rel):
            failures.append((3 if exists else 1, (
                f"only {', '.join(_TEXT_SUFFIXES)} files, and .json under docs/, are readable here"
            )))
            continue
        if not exists:
            failures.append((2, f"{name!r} does not exist"))
            continue
        return candidate

    raise ValueError(max(failures, key=lambda item: item[0])[1])


def _title_of(path: Path, rel: str) -> str:
    """The document's own name for itself, or the path when it has none.

    Reads at most `_TITLE_BYTES`. A doc without a heading is listed under its path rather than
    dropped — an index that hides what it cannot label is the defect, not the fix.
    """
    suffix = path.suffix.lower()
    if suffix not in (".md", ".html"):
        return rel
    try:
        with path.open("rb") as fh:
            head = fh.read(_TITLE_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return rel
    if suffix == ".md":
        for line in head.splitlines():
            if line.startswith("# "):
                return line[2:].strip() or rel
        return rel
    # HTML: `<title>` first, then the first `<h1>`. Both are plain enough to find without a
    # parser, and a dependency for a page title is not worth the build.
    low = head.lower()
    for opener, closer in (("<title>", "</title>"), ("<h1>", "</h1>")):
        start = low.find(opener)
        if start == -1:
            continue
        end = low.find(closer, start)
        if end == -1:
            continue
        text = " ".join(head[start + len(opener):end].split())
        if text and "<" not in text:
            return text
    return rel


def _entry(root: Path, rel: str) -> dict | None:
    path = root / rel
    try:
        stat = path.stat()
    except OSError:
        # Listed by git but not on disk in this checkout. Skipped rather than crashing the whole
        # index: one missing file must not blank the page.
        return None
    return {
        "name": rel,
        "title": _title_of(path, rel),
        "bytes": stat.st_size,
        "modified": stat.st_mtime,
        "category": _section_for(rel),
        "readable": _is_readable(rel),
    }


def _section_order(label: str) -> tuple[int, str]:
    """Sections in the order an operator wants them, not the filesystem's.

    `docs/` first and in its declared category order, then the named `docs/` subdirectories, then
    the repo root, then every other tree alphabetically.
    """
    for i, (_sub, name) in enumerate(_DIR_SECTIONS):
        if label == name:
            return (1, f"{i:02d}")
    for i, (name, _rules) in enumerate(_CATEGORIES):
        if label == name:
            return (0, f"{i:02d}")
    if label == _UNCATEGORISED:
        return (0, "99")
    if label == _ROOT_SECTION:
        return (2, "")
    return (3, label)


def docs_index(repo_root: Path) -> dict:
    """Every document in the repo, grouped and labelled. No file contents.

    The population is `share.shareable_files()` — see the module docstring. Anything the share
    fence refuses is absent here too, by construction rather than by a second list that could
    drift.
    """
    root = Path(repo_root).resolve()
    # `keep=` narrows to documents BEFORE the deny-list runs, which is a cost change and not a
    # fence change — see `share.shareable_files`. The fence still runs on every path that
    # survives, and again in `_safe` at read time.
    rels = share.shareable_files(root, keep=_is_listed)

    # One stat and one 4 KB read per document, ~320 of them. Threaded because it is pure file
    # I/O with the GIL released: measured 745 ms serial, and the page this feeds is the one the
    # founder described as loading slow. Order is preserved by `map`, so the listing is stable.
    with ThreadPoolExecutor(max_workers=8) as pool:
        entries = list(pool.map(lambda rel: _entry(root, rel), rels))

    by_label: dict[str, list[dict]] = {}
    count = 0
    for entry in entries:
        if entry is None:
            continue
        count += 1
        by_label.setdefault(entry["category"], []).append(entry)

    sections = [
        {"label": label, "docs": by_label[label]}
        for label in sorted(by_label, key=_section_order)
    ]

    out = {"root": str(root), "sections": sections, "count": count}
    if not count:
        out["note"] = "this checkout carries no readable documents"
    return out


def _binary_view(root: Path, name: str) -> dict | None:
    """The payload for a listed-but-not-rendered document, or None if `name` is not one.

    A listed entry that raises when an operator clicks it is worse than an absent one, so this
    answers with an explanation and a size instead of an error. It runs the SAME containment and
    deny-list checks as `_safe` before admitting the file exists — a binary format is not a way
    round the fence.
    """
    for candidate_name in (name or "", f"docs/{name or ''}"):
        cleaned = candidate_name.strip().lstrip("/")
        if not cleaned or "\x00" in cleaned:
            return None
        candidate = (root / cleaned).resolve()
        if not candidate.is_relative_to(root):
            continue
        rel = candidate.relative_to(root).as_posix()
        if share.is_denied(rel) or _suffix(rel) not in _BINARY_SUFFIXES:
            return None
        if not candidate.is_file():
            continue
        size = candidate.stat().st_size
        return {
            "name": rel,
            "title": rel,
            "text": (
                f"{rel} is a {size:,}-byte {_suffix(rel).lstrip('.').upper()} document.\n\n"
                "It is listed here so that nothing in the repo is invisible, but the console does "
                "not render it: dumping bytes into a browser is a download surface rather than a "
                "page. Mint a share link for it, or open it from a checkout."
            ),
            "bytes": size,
            "truncated": False,
            "readable": False,
            "modified": candidate.stat().st_mtime,
        }
    return None


def doc_view(repo_root: Path, name: str, *, max_bytes: int = 400_000) -> dict:
    """One document as text.

    Truncates rather than refusing on a large file: the console must not be the reason an operator
    cannot see the top of a long programme doc. `truncated` says so plainly, because a silently
    shortened document is a document that lies.
    """
    root = Path(repo_root).resolve()
    binary = _binary_view(root, name)
    if binary is not None:
        return binary
    path = _safe(root, name)
    rel = path.relative_to(root).as_posix()
    raw = path.read_bytes()
    truncated = len(raw) > max_bytes
    text = raw[:max_bytes].decode("utf-8", errors="replace")
    return {
        "name": rel,
        "title": _title_of(path, rel),
        "text": text,
        "bytes": len(raw),
        "truncated": truncated,
        "readable": True,
        "modified": path.stat().st_mtime,
    }
