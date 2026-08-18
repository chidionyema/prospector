#!/usr/bin/env python3
"""Build ONE self-contained HTML file containing every document in docs/.

WHY THIS EXISTS. Founder, 2026-08-18: "no easy way to share these docs".

The docs were published as claude.ai artifacts. Those links live behind a session, so anyone
outside it sees six labels and nothing else. A consultant cannot read them, and neither can the
founder from another machine.

This produces docs/dist/prospector-docs.html: one file, no login, no session, no internet, no
external fonts or scripts. Open it in any browser. Email it. Put it in a folder. It also gets
committed, so GitHub serves it too.

Cross-document links are rewritten to in-page anchors, and every heading gets a stable id, so a
link to a SECTION of another document still lands on that section inside the bundle.

USAGE
    .venv/bin/python scripts/build_docs_bundle.py
    .venv/bin/python scripts/build_docs_bundle.py --out /tmp/somewhere.html
"""
from __future__ import annotations

import argparse
import html
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import mistune

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

# The reading order a newcomer needs. Everything not named here follows, alphabetically, under
# "Everything else". Names that do not exist are skipped without complaint, because this list is
# a preference and not a manifest.
LEAD = [
    "README.md",
    "docs/ESTATE_MAP.md",
    "docs/FOUNDER_NOTES.md",
    "docs/CONSULTANT_BRIEF_PRICING_AND_CONTENT.md",
    "docs/ENGINE_AUDIT_2026-08-10.md",
    "docs/ENGINE_AUDIT_AND_STORIES_2026-08-13.md",
    "docs/BACKLOG.md",
    "docs/ESTATE_CONTINUITY_PLAN.md",
    "docs/ENGINE_MIGRATION_PROGRAM.md",
    "docs/PLATFORM_MANIFESTO.md",
    "docs/WAYS_OF_WORKING.md",
    "docs/personas/README.md",
]


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "x"


def collect() -> list[tuple[str, Path]]:
    """Return [(repo-relative path, absolute path)] in reading order, no duplicates."""
    found: dict[str, Path] = {}
    readme = ROOT / "README.md"
    if readme.is_file():
        found["README.md"] = readme
    for p in sorted(DOCS.rglob("*.md")):
        # archive/ is superseded history. It bloats the bundle and misleads a reader who does not
        # know it is dead. Skipped deliberately, and said so in the output.
        rel = p.relative_to(ROOT).as_posix()
        if "/archive/" in rel:
            continue
        found[rel] = p
    ordered: list[tuple[str, Path]] = []
    for name in LEAD:
        if name in found:
            ordered.append((name, found.pop(name)))
    ordered.extend(sorted(found.items()))
    return ordered


def make_renderer():
    try:
        return mistune.create_markdown(
            escape=False, plugins=["table", "strikethrough", "url", "task_lists"]
        )
    except Exception:
        return mistune.create_markdown(escape=False)


HEADING = re.compile(r"<h([1-6])>(.*?)</h\1>", re.S)
HREF = re.compile(r'href="([^"]+)"')


def strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(DOCS / "dist" / "prospector-docs.html"))
    args = ap.parse_args()

    md = make_renderer()
    docs = collect()
    if not docs:
        print("no documents found", file=sys.stderr)
        return 1

    # Every path a link might use, mapped to the document's anchor. A markdown link can be
    # written docs/X.md, ./X.md, ../docs/X.md or X.md depending on where it sits, and all four
    # must resolve to the same place in one flat page.
    doc_id: dict[str, str] = {}
    for rel, _ in docs:
        did = "doc-" + slugify(rel.removesuffix(".md"))
        doc_id[rel] = did
        doc_id[rel.split("/")[-1]] = did
        doc_id["./" + rel] = did
        doc_id["/" + rel] = did

    bodies: list[str] = []
    nav: list[str] = []

    for rel, path in docs:
        did = doc_id[rel]
        raw = path.read_text(encoding="utf-8", errors="replace")
        body = md(raw)

        headings: list[tuple[int, str, str]] = []

        def add_id(m: re.Match) -> str:
            level, inner = int(m.group(1)), m.group(2)
            text = strip_tags(inner)
            hid = f"{did}--{slugify(text)}"
            n = 1
            while any(h[2] == hid for h in headings):
                n += 1
                hid = f"{did}--{slugify(text)}-{n}"
            headings.append((level, text, hid))
            return f'<h{level} id="{hid}">{inner}<a class="anchor" href="#{hid}">#</a></h{level}>'

        body = HEADING.sub(add_id, body)

        def fix_link(m: re.Match) -> str:
            target = m.group(1)
            if target.startswith(("http://", "https://", "mailto:", "#")):
                return m.group(0)
            base, _, frag = target.partition("#")
            base = base.split("?")[0].lstrip("./").removeprefix("../")
            key = base if base in doc_id else base.split("/")[-1]
            if key in doc_id:
                dest = doc_id[key]
                if frag:
                    dest = f"{dest}--{slugify(frag)}"
                return f'href="#{dest}"'
            # A link to a source file, not a document. Point it at GitHub so it still works.
            return f'href="https://github.com/chidionyema/prospector/blob/main/{base}"'

        body = HREF.sub(fix_link, body)

        title = next((t for lvl, t, _ in headings if lvl == 1), rel.split("/")[-1][:-3])
        bodies.append(
            f'<article class="doc" id="{did}">'
            f'<p class="crumb">{html.escape(rel)}</p>{body}'
            f'<p class="backtop"><a href="#top">back to contents</a></p></article>'
        )

        subs = "".join(
            f'<a class="sub lvl{lvl}" href="#{hid}">{html.escape(t)}</a>'
            for lvl, t, hid in headings
            if 2 <= lvl <= 3
        )
        nav.append(
            f'<details class="navdoc"><summary><a href="#{did}">{html.escape(title)}</a>'
            f'<span class="path">{html.escape(rel)}</span></summary>{subs}</details>'
        )

    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip() or "unknown"
    built = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    css = """
:root{--bg:#fbfaf8;--ink:#1a1a19;--soft:#6b6b66;--line:#e2e0da;--card:#fff;--accent:#7a4a2b;
--code:#f3f1ec;--nav:#f5f3ef}
@media (prefers-color-scheme:dark){:root{--bg:#16171a;--ink:#e8e6e1;--soft:#9a978f;--line:#2c2e33;
--card:#1c1e22;--accent:#d79b6e;--code:#212429;--nav:#191b1f}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{display:grid;grid-template-columns:320px minmax(0,1fr);gap:0;max-width:1400px;margin:0 auto}
nav{position:sticky;top:0;align-self:start;max-height:100vh;overflow-y:auto;padding:24px 18px;
background:var(--nav);border-right:1px solid var(--line)}
nav h2{font-size:13px;letter-spacing:.10em;text-transform:uppercase;color:var(--soft);margin:0 0 4px}
nav .meta{font-size:12px;color:var(--soft);margin:0 0 18px;line-height:1.5}
.navdoc{border-bottom:1px solid var(--line)}
.navdoc summary{cursor:pointer;padding:7px 0;font-size:14px;font-weight:600;list-style:none}
.navdoc summary::-webkit-details-marker{display:none}
.navdoc summary a{color:var(--ink);text-decoration:none}
.navdoc summary a:hover{color:var(--accent)}
.navdoc .path{display:block;font:11px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;
color:var(--soft);font-weight:400;word-break:break-all}
.sub{display:block;font-size:13px;color:var(--soft);text-decoration:none;padding:3px 0 3px 10px;
border-left:2px solid var(--line)}
.sub.lvl3{padding-left:22px}
.sub:hover{color:var(--accent);border-left-color:var(--accent)}
main{padding:36px 44px 120px;min-width:0}
header.top{border-bottom:2px solid var(--ink);padding-bottom:20px;margin-bottom:36px}
header.top h1{font-size:30px;margin:0 0 6px;letter-spacing:-.02em}
header.top p{margin:0;color:var(--soft);font-size:14px}
.doc{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:28px 32px;
margin-bottom:28px;overflow-wrap:anywhere}
.crumb{font:11px/1 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--soft);
letter-spacing:.05em;margin:0 0 14px;text-transform:uppercase}
.doc h1{font-size:26px;margin:.2em 0 .5em;letter-spacing:-.015em}
.doc h2{font-size:20px;margin:1.6em 0 .5em;padding-top:.4em;border-top:1px solid var(--line)}
.doc h3{font-size:16px;margin:1.3em 0 .4em}
.doc h4,.doc h5,.doc h6{font-size:14px;margin:1.2em 0 .3em}
.anchor{color:var(--line);text-decoration:none;margin-left:8px;font-weight:400;font-size:.8em}
.anchor:hover{color:var(--accent)}
a{color:var(--accent)}
code{background:var(--code);padding:1px 5px;border-radius:3px;
font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}
pre{background:var(--code);padding:14px 16px;border-radius:5px;overflow-x:auto;
border:1px solid var(--line)}
pre code{background:none;padding:0;font-size:12.5px;line-height:1.55}
blockquote{border-left:3px solid var(--accent);margin:1em 0;padding:.2em 0 .2em 16px;
color:var(--soft)}
table{border-collapse:collapse;width:100%;font-size:14px;display:block;overflow-x:auto}
th,td{border:1px solid var(--line);padding:7px 10px;text-align:left;vertical-align:top}
th{background:var(--code);font-weight:600}
td{font-variant-numeric:tabular-nums}
hr{border:0;border-top:1px solid var(--line);margin:2em 0}
img{max-width:100%}
.backtop{margin:28px 0 0;font-size:13px}
@media(max-width:900px){.wrap{grid-template-columns:1fr}
nav{position:static;max-height:none;border-right:0;border-bottom:1px solid var(--line)}
main{padding:24px 18px 80px}.doc{padding:20px 18px}}
"""

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Prospector — the estate documentation</title>
<style>{css}</style></head>
<body><div class="wrap">
<nav><h2>Contents</h2>
<p class="meta">{len(docs)} documents<br>commit {html.escape(sha)}<br>built {built}</p>
{''.join(nav)}</nav>
<main><header class="top" id="top">
<h1>Prospector — the estate documentation</h1>
<p>Every document in one file. No login, no network, no session. Cross-references between
documents are live links inside this page. Superseded material under docs/archive/ is excluded.</p>
</header>
{''.join(bodies)}
</main></div></body></html>
"""

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    kb = out.stat().st_size / 1024
    print(f"{out}  —  {len(docs)} documents, {kb:.0f} KB, commit {sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
