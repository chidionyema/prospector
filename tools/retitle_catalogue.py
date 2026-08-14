#!/usr/bin/env python3
"""Rewrite live pack titles into the declared format: `Name, what it does`, at most 60 chars.

Why
---
The title is the only string every surface shows at once — shelf card, pack page H1, the
`<title>` a search result prints, the OG image on a shared link. Until 2026-08-09 nothing
bounded it or shaped it, and it showed. Measured over the 48 live catalogue rows that day:

    title length      min 16   median 96.5   max 176
    clean under the new rule (pack_linter.check_title)   1 of 48
      too long        43        no descriptor   4
    separators in use: ", " x34, em-dash x7, none x4, en-dash x3

The same packs were meanwhile carrying a `card_line` of min 40 / median 52.5 / max 60 on all
36 rows that had one — which is the proof that the short form is writable. It simply was not
being asked for: `prompts/generate_system.md` said "a short name, then a dash, then what it
does" and named no length, so the model obliged on both counts and `nodash` rewrote the
mandated dash to ", " at publish. That prompt is fixed; this tool repairs the packs that
shipped under the old one.

How the format is guaranteed
----------------------------
The model is never asked for a formatted string. `prompts/retitle.md` returns `name` and
`does` as separate fields and THIS FILE joins them with ", ", so a malformed separator is
unrepresentable. Only the length can be got wrong, and every draft is put through the real
`pack_linter.check_title` before it is accepted — the same function the publish gate runs, so
a title that passes here cannot fail there. A breach is fed back verbatim and re-asked, up to
`--attempts` times; a pack that never converges is REPORTED AND SKIPPED, never truncated.

Why it writes in two places
---------------------------
`bridge._update_catalog` sources the catalogue row's title from `candidate.title` in the
dossier (bridge.py:1514). Patching only the live row would therefore be undone by the next
republish of that pack, silently and at an unpredictable time. So `--apply` writes both:

  1. the live row, through `PATCH /internal/catalog/{id}/copy` — the narrow door, which
     reaches copy and nothing else. `title` was added to that endpoint on 2026-08-09 for
     this job: before it, `pack.Title` was written only inside the upsert (Program.cs 466
     and 480), the endpoint whose own contract documents two silent ways it breaks a live
     pack's money rail. The PATCH response is asserted against `INVARIANTS` — reusing
     `backfill_listing_copy.patch_copy` rather than a second definition of "the money did
     not move", because two definitions is how they come to disagree.
  2. `candidate.title` in `store/dossiers/<id>.pass.json`, so a republish preserves it.

Both are recorded to `store/retitle_log.jsonl` BEFORE the write, one row per pack, carrying
the old and new title. That file is the rollback: nothing here is reversible from the
catalogue alone, because the old title is not projected by any GET once overwritten.

Usage
-----
    .venv/bin/python tools/retitle_catalogue.py --dry-run            # the 48-row diff
    .venv/bin/python tools/retitle_catalogue.py --dry-run --only <id>
    STORE_INTERNAL_API_KEY=... .venv/bin/python tools/retitle_catalogue.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests  # noqa: E402
from backfill_listing_copy import DEFAULT_API_URL, patch_copy  # noqa: E402  (same dir)

from prospector import prompts  # noqa: E402
from prospector.artifacts import CARD_LINE_MAX  # noqa: E402
from prospector.config import Config, load_config  # noqa: E402
from prospector.errors import ProviderExhaustedError  # noqa: E402
from prospector.pack_linter import (  # noqa: E402
    TITLE_MAX_CHARS,
    check_claims,
    check_title,
    check_title_claims,
)
from prospector.plain_text import nodash, to_plain_text  # noqa: E402
from prospector.run import _NONCRITICAL_ORDER  # noqa: E402

RETITLE_LOG = "retitle_log.jsonl"


def build_operator(cfg: Config):
    """The non-critical chain — copy generation, never a verdict.

    Same tiers (`run._NONCRITICAL_ORDER`) and the same health file as generation, prescreen
    and score, so a CLI hiccup here cannot blind the moat's verdict path. A title is
    marketing prose: it rules nothing, so it has no claim on the moat's brain. Chain
    construction is duplicated rather than imported because `run._build_operator_chain` is a
    closure over `cfg` inside `_run_generate`; the tier ORDER is imported, so the one thing
    that could drift silently cannot.
    """
    from prospector.health import get_noncritical_health
    from prospector.operator import FallbackOperator, _build_operator

    tiers = []
    for kind in _NONCRITICAL_ORDER:
        try:
            tiers.append((kind, _build_operator(kind, cfg, fast=True)))
        except (RuntimeError, ValueError):
            pass  # tier not configured / CLI not on PATH
    if not tiers:
        raise RuntimeError(
            f"no non-critical operator available from {'/'.join(_NONCRITICAL_ORDER)}")
    print(f"operator chain      : {' -> '.join(n for n, _ in tiers)}")
    if len(tiers) == 1:
        return tiers[0][1]
    r = cfg.retrieval
    return FallbackOperator(tiers, failure_threshold=r.breaker_failure_threshold,
                            cooldown_s=r.breaker_cooldown_s,
                            health=get_noncritical_health())


def _fetch_catalogue(api_url: str) -> List[Dict[str, Any]]:
    r = requests.get(f"{api_url}/catalog", timeout=30)
    r.raise_for_status()
    rows = r.json()
    if isinstance(rows, dict):
        rows = rows.get("items") or rows.get("listings") or []
    return rows


HEADLINE_MAX = 100

#: The pack's own description and structured facts. Deliberately EXCLUDES title, headline and
#: cardLine: those are the lines under repair, and copy under repair cannot be the evidence
#: that the repair is truthful. 13 of the 48 live headlines are verbatim copies of their
#: title, so a title checked against its own headline would be checked against itself.
_CLAIM_SOURCE_FIELDS = ("oneLine", "proofPoint", "whoPays", "payer", "audience", "mechanism",
                        "advantages", "commitment", "sector", "effortTag",
                        "timeToFirstRevenue")

#: Buyer-visible prose that is NOT being rewritten but may still carry a raw em/en dash.
#: Repaired deterministically by `nodash` — the same function the publish path runs — so no
#: model call is spent on punctuation and no wording changes.
_DASH_REPAIR_FIELDS = ("oneLine", "proofPoint", "subhead")

_DASH = re.compile(r"[—–]")


def _claim_sources(row: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for key in _CLAIM_SOURCE_FIELDS:
        v = row.get(key)
        if isinstance(v, str) and v.strip():
            out.append(v)
        elif isinstance(v, list):
            out.extend(str(x) for x in v if str(x).strip())
    return out


def _hard(problems: List[Dict[str, str]]) -> List[str]:
    """Only the tier a machine may rule on. `title_new_word` is reported, never enforced."""
    return [p["detail"] for p in problems if p["check"] == "title_claim"]


def _soft(problems: List[Dict[str, str]]) -> List[str]:
    return [p["detail"] for p in problems if p["check"] == "title_new_word"]


def _clean(value: Any) -> str:
    """Whitespace, plain text and `nodash` — exactly what the publish path applies."""
    return nodash(to_plain_text(" ".join(str(value or "").split()), collapse=True)).strip()


#: Why a row is rewritten under `--rewrite-all`. The register change is an AUDIENCE fix, and
#: no linter can see an audience: "HoursBack, finds the pay your NHS rota says you are owed"
#: is a well-formed sentence addressed to the wrong person. So the migration cannot be driven
#: by `assess`, which only reports what is mechanically wrong.
REGISTER_MIGRATION = ("register migration 2026-08-13: business-first, no product name, "
                      "addressed to the person deciding whether to start it")

#: The same migration, for the two lines that were NOT swept with the titles. `--from-plan`
#: patches the approved title and returns, so on 2026-08-13 fifty titles moved to the new
#: register while fifty headlines and card lines stayed in the old one. The result is a shelf
#: card whose heading talks to the reader and whose second line talks to the customer of the
#: service: `Injury claim service for delivery riders, fixed fee` above `A fixed £180 fee
#: covers the whole claim` (pack 224578cd860491c9, live). Like the title migration this is
#: invisible to `assess` — that card line is short, dash-free, sourced and does not repeat the
#: title, so every mechanical check passes it.
LINE_MIGRATION = ("line migration 2026-08-13: headline and card line still address the "
                  "customer of the service, not the reader deciding whether to run it")


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", str(value or "").lower()).strip()


def _is_title_echo(headline: str, title: str) -> bool:
    """Does the headline spend the page's most valuable line saying the title again?

    Prefix in EITHER direction, because the defect shows up both ways in the live data: 13
    rows repeat the title exactly and 2 hold a truncated copy of it. Deliberately not a
    fuzzy-similarity score — a headline that merely shares vocabulary with the title is a
    judgement call, and this function only claims to catch copies.
    """
    h, t = _norm(headline), _norm(title)
    if not h or not t:
        return False
    return h == t or t.startswith(h) or h.startswith(t)


def assess(row: Dict[str, Any], *, max_chars: int = TITLE_MAX_CHARS) -> Dict[str, List[str]]:
    """Which buyer-visible lines on this row are defective, and why. {} means leave it alone."""
    title = (row.get("title") or "").strip()
    headline = (row.get("headline") or "").strip()
    card = (row.get("cardLine") or "").strip()
    src = _claim_sources(row)
    market = row.get("market") or ""
    needs: Dict[str, List[str]] = {}

    why = [p["detail"] for p in check_title(title, max_chars=max_chars)]
    why += _hard(check_title_claims(title, src, market=market))
    if why:
        needs["title"] = why

    why = []
    if not headline:
        why.append("empty")
    elif _is_title_echo(headline, title):
        why.append("repeats the title instead of saying what changes for the buyer")
    else:
        if len(headline) > HEADLINE_MAX:
            why.append(f"{len(headline)} chars exceeds the {HEADLINE_MAX} limit")
        if _DASH.search(headline):
            why.append("carries a raw dash")
        why += _hard(check_claims(headline, src, market=market, where="headline"))
    if why:
        needs["headline"] = why

    why = []
    if not card:
        why.append("empty")
    else:
        if len(card) > CARD_LINE_MAX:
            why.append(f"{len(card)} chars exceeds the {CARD_LINE_MAX} limit")
        if _DASH.search(card):
            why.append("carries a raw dash")
        if _norm(card) == _norm(title):
            why.append("repeats the title")
        why += _hard(check_claims(card, src, market=market, where="card_line"))
    if why:
        needs["cardLine"] = why
    return needs


def dash_repairs(row: Dict[str, Any]) -> Dict[str, str]:
    """Fields fixable without a model: punctuation only, wording untouched."""
    out: Dict[str, str] = {}
    for key in _DASH_REPAIR_FIELDS:
        v = row.get(key)
        if isinstance(v, str) and _DASH.search(v):
            fixed = _clean(v)
            if fixed and fixed != v:
                out[key] = fixed
    return out


def _validate(kind: str, value: str, row: Dict[str, Any], *, max_chars: int
              ) -> Tuple[List[str], List[str]]:
    """(hard breaches, soft notes) for one proposed line, by the rules that line answers to."""
    src = _claim_sources(row)
    market = row.get("market") or ""
    if kind == "title":
        if not value:
            return ["`title` was empty"], []
        problems = check_title(value, max_chars=max_chars)
        claims = check_title_claims(value, src, market=market)
        return [p["detail"] for p in problems] + _hard(claims), _soft(claims)
    if not value:
        return [f"`{kind}` was empty"], []
    breaches: List[str] = []
    if kind == "headline":
        if len(value) > HEADLINE_MAX:
            breaches.append(f"{len(value)} chars exceeds the {HEADLINE_MAX} limit")
        if _is_title_echo(value, row.get("_new_title") or row.get("title") or ""):
            breaches.append("still repeats the title; say what CHANGES for the buyer instead")
    else:
        if len(value) > CARD_LINE_MAX:
            breaches.append(f"{len(value)} chars exceeds the {CARD_LINE_MAX} limit")
        if _norm(value) == _norm(row.get("_new_title") or row.get("title") or ""):
            breaches.append("repeats the title")
    claims = check_claims(value, src, market=market, where=kind)
    return breaches + _hard(claims), _soft(claims)


_FIELD_KEY = {"title": "title", "headline": "headline", "cardLine": "card_line"}


def propose(op, row: Dict[str, Any], *, max_chars: int, attempts: int,
            needs: Optional[Dict[str, List[str]]] = None
            ) -> Tuple[Optional[Dict[str, str]], List[str], List[str]]:
    """Return (fields, trail, soft notes). fields is None when it never converged.

    Only the defective lines are asked for and only they are returned, so a pack with a good
    headline keeps the headline it has: this tool repairs, it does not re-author a catalogue.
    """
    wanted = list((needs if needs is not None else assess(row, max_chars=max_chars)).keys())
    trail: List[str] = []
    feedback = ""
    for attempt in range(attempts):
        system, user = prompts.render(
            "retitle",
            current_title=row.get("title") or "",
            one_line=row.get("oneLine") or "",
            headline=row.get("headline") or "(none)",
            card_line=row.get("cardLine") or "(none)",
            who_pays=row.get("whoPays") or row.get("payer") or "",
            sector=row.get("sector") or "",
            market=row.get("market") or "",
            max_chars=max_chars,
            feedback=feedback,
        )
        data = op.complete_json(system, user, temperature=0.6 if attempt == 0 else 0.2)
        if not isinstance(data, dict):
            trail.append(f"attempt {attempt + 1}: operator returned {type(data).__name__}")
            feedback = "Your output was not a JSON object. Output ONLY the four named fields."
            continue

        # One field, not `name` + `does` joined here: since 2026-08-13 the title carries no
        # product name at all, so there is nothing to compose and no separator to get wrong.
        drafts = {"title": _clean(data.get("title", "")).rstrip(".").strip()}
        drafts["headline"] = _clean(data.get("headline", ""))
        drafts["cardLine"] = _clean(data.get("card_line", ""))
        # The headline and card line are graded against the title this same draft proposes,
        # not the broken one on the row: otherwise a good headline is rejected for echoing a
        # title that is about to be replaced.
        # ...but only when the title is actually being replaced. Under --rewrite-lines the
        # model still emits a title it was not asked for and that will not ship, and grading
        # the two lines against that phantom rejects a good headline for echoing a string
        # nobody will ever see.
        proposed = drafts["title"] if "title" in wanted else ""
        graded = dict(row, _new_title=proposed or row.get("title") or "")

        breaches: List[str] = []
        notes: List[str] = []
        fields: Dict[str, str] = {}
        for kind in wanted:
            hard_b, soft_n = _validate(kind, drafts[kind], graded, max_chars=max_chars)
            breaches += [f"{_FIELD_KEY[kind]}: {b}" for b in hard_b]
            notes += [f"{_FIELD_KEY[kind]}: {n}" for n in soft_n]
            fields[kind] = drafts[kind]

        if not breaches:
            sizes = ", ".join(f"{_FIELD_KEY[k]} {len(v)}" for k, v in fields.items())
            trail.append(f"attempt {attempt + 1}: accepted ({sizes})")
            return fields, trail, notes

        trail.append(f"attempt {attempt + 1}: rejected — " + "; ".join(breaches))
        # Verbatim, including every count: a vague "too long" gets a draft one character
        # shorter, and a vague "unsupported" gets the same claim in a synonym.
        feedback = ("Your previous answer was REJECTED for these reasons:\n"
                    + "\n".join(f"  - {b}" for b in breaches)
                    + "\nRewrite it. Do not truncate; say a shorter true thing. Where a claim "
                      "is not in the supplied description, remove it rather than rephrase it.")
    return None, trail, []


def _write_dossier_title(store_dir: Path, pack_id: str, title: str) -> str:
    """Set `candidate.title` in the dossier so a republish does not revert the rewrite.

    Edited in place, key by key, never round-tripped through `models.Dossier` — these files
    are the audit trail for verdicts ruled by earlier engine versions and a re-render would
    silently drop any key the current dataclasses do not model.
    """
    path = store_dir / "dossiers" / f"{pack_id}.pass.json"
    if not path.exists():
        return f"no dossier at {path.name} — live row patched, a republish WILL revert it"
    doc = json.loads(path.read_text(encoding="utf-8"))
    cand = doc.get("candidate")
    if not isinstance(cand, dict):
        return f"{path.name} has no `candidate` object — a republish WILL revert it"
    cand["title"] = title
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.rename(path)
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api-url", default=DEFAULT_API_URL)
    ap.add_argument("--store", default="store")
    ap.add_argument("--config", default="config.yaml")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True,
                      help="report the diff and write nothing (the default)")
    mode.add_argument("--apply", action="store_true",
                      help="PATCH the live rows and update the dossiers")
    ap.add_argument("--only", action="append", default=[], help="pack id (repeatable)")
    ap.add_argument("--limit", type=int, default=0, help="stop after N packs (0 = all)")
    ap.add_argument("--attempts", type=int, default=3,
                    help="drafts per pack before it is skipped (default: 3)")
    ap.add_argument("--max-chars", type=int, default=TITLE_MAX_CHARS)
    ap.add_argument("--from-file", default="",
                    help="read the catalogue from a JSON file instead of the API")
    ap.add_argument("--from-plan", default="",
                    help="TSV of ALREADY-APPROVED titles (id<TAB>before<TAB>after), one per "
                         "line. A row named here is patched with that exact string and the "
                         "model is never called for it. This exists because --apply otherwise "
                         "RE-GENERATES: without a plan the titles that ship are not the titles "
                         "that were reviewed, which makes the review meaningless.")
    ap.add_argument("--rewrite-all", action="store_true",
                    help="rewrite every title, not only the ones that fail the linter "
                         "(the 2026-08-13 register migration: a title can be well-formed "
                         "and still be addressed to the wrong reader)")
    ap.add_argument("--plan-out", default="",
                    help="write every proposed line to this TSV as id<TAB>field<TAB>value. "
                         "A dry run with --plan-out and an apply with --from-lines ship "
                         "EXACTLY what was reviewed, for one model run instead of two.")
    ap.add_argument("--from-lines", default="",
                    help="TSV of ALREADY-APPROVED lines (id<TAB>field<TAB>value). A field "
                         "named here is patched with that exact string and the model is "
                         "never called for it. The field-grain twin of --from-plan.")
    ap.add_argument("--rewrite-lines", action="store_true",
                    help="rewrite every headline and card line, leaving the title to the "
                         "linter. This is the other half of --rewrite-all: --from-plan "
                         "patches an approved title and returns, so a plan sweep moves the "
                         "titles and leaves the other two lines in the old register.")
    args = ap.parse_args()

    if args.apply and not os.environ.get("STORE_INTERNAL_API_KEY"):
        print("--apply needs STORE_INTERNAL_API_KEY; refusing.", file=sys.stderr)
        return 2
    internal_key = os.environ.get("STORE_INTERNAL_API_KEY", "")

    # Parsed BEFORE the catalogue is fetched: a malformed plan should cost nothing.
    approved: Dict[str, str] = {}
    if args.from_plan:
        for lineno, line in enumerate(
                Path(args.from_plan).read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 3 or not parts[0].strip() or not parts[-1].strip():
                print(f"--from-plan line {lineno}: expected id<TAB>before<TAB>after",
                      file=sys.stderr)
                return 2
            # The two plan formats are both id<TAB>_<TAB>_, so the WRONG flag parses cleanly
            # and writes silently. On 2026-08-14 a --plan-out file (id/field/value) was fed to
            # --from-plan, which keys by id alone and takes parts[-1]: ten of fourteen live rows
            # had a headline or a card line written into their TITLE, two of them over the
            # 60-char cap, and the run reported "patched: 14, failed: 0". A field name in
            # column 2 is what distinguishes the formats, and it is the only thing that can:
            # a genuine `before` title is prose, never one of these three tokens.
            if parts[1].strip() in _FIELD_KEY:
                print(f"--from-plan line {lineno}: column 2 is {parts[1].strip()!r}, a field "
                      f"name — this is a --plan-out file. Use --from-lines, which patches the "
                      f"named field; --from-plan would write column 3 into the title.",
                      file=sys.stderr)
                return 2
            approved[parts[0].strip()] = parts[-1].strip()
        print(f"approved plan       : {len(approved)} titles from {args.from_plan}")

    # The same idea at field grain. --from-plan carries one string per pack because a title is
    # one line; a headline-and-card-line sweep proposes two, so the plan has to name which.
    approved_lines: Dict[str, Dict[str, str]] = {}
    if args.from_lines:
        for lineno, line in enumerate(
                Path(args.from_lines).read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) != 3 or not all(p.strip() for p in parts[:2]):
                print(f"--from-lines line {lineno}: expected id<TAB>field<TAB>value",
                      file=sys.stderr)
                return 2
            pack_id, field, value = (p.strip() for p in parts)
            if field not in _FIELD_KEY:
                print(f"--from-lines line {lineno}: unknown field {field!r}", file=sys.stderr)
                return 2
            approved_lines.setdefault(pack_id, {})[field] = value
        print(f"approved lines      : "
              f"{sum(len(v) for v in approved_lines.values())} fields across "
              f"{len(approved_lines)} packs from {args.from_lines}")

    rows = (json.loads(Path(args.from_file).read_text()) if args.from_file
            else _fetch_catalogue(args.api_url))
    if args.only:
        rows = [r for r in rows if r.get("id") in set(args.only)]
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        print("no rows to process", file=sys.stderr)
        return 1

    plan = [(r, assess(r, max_chars=args.max_chars), dash_repairs(r)) for r in rows]
    if args.rewrite_all:
        for _row, needs, _fixes in plan:
            needs.setdefault("title", [REGISTER_MIGRATION])
    if args.rewrite_lines:
        # Deliberately NOT title: the fifty live titles were reviewed one by one and approved,
        # and re-rolling them here would quietly replace strings a human signed off. A title
        # that genuinely breaches still arrives through `assess` above.
        for _row, needs, _fixes in plan:
            needs.setdefault("headline", [LINE_MIGRATION])
            needs.setdefault("cardLine", [LINE_MIGRATION])
    todo = [(r, n, d) for r, n, d in plan if n]
    dash_only = [(r, d) for r, n, d in plan if not n and d]
    clean = len(plan) - len(todo) - len(dash_only)
    counts = {k: sum(1 for _, n, _ in plan if k in n) for k in ("title", "headline", "cardLine")}
    print(f"catalogue rows      : {len(rows)}")
    print(f"nothing to do       : {clean}")
    print(f"punctuation only    : {len(dash_only)}  (deterministic, no model call)")
    print(f"needs a rewrite     : {len(todo)}  "
          f"(title {counts['title']}, headline {counts['headline']}, "
          f"cardLine {counts['cardLine']})")
    if not todo and not dash_only:
        return 0

    patches: List[Tuple[Dict[str, Any], Dict[str, str]]] = []
    for row, fixes in dash_only:
        print(f"\n{row.get('id')}  punctuation only: {', '.join(fixes)}")
        patches.append((row, fixes))

    skipped: List[Tuple[Dict[str, Any], List[str]]] = []
    # Three failures in a row is a brain, not a row: no realistic per-row flake rate produces
    # three consecutive misses, and stopping there costs at most three wasted calls instead of
    # a shelf's worth of them.
    _OUTAGE_RUN = 3
    consecutive_failures = 0
    op = None
    # Only when at least one row still needs a model. A fully-approved plan must not depend on
    # a brain being reachable: the thinking already happened and was reviewed.
    def _covered(row: Dict[str, Any], needs: Dict[str, List[str]]) -> bool:
        """Is every line this row needs already an approved string?"""
        if row.get("id") in approved:
            return True
        have = approved_lines.get(row.get("id") or "", {})
        return bool(needs) and all(k in have for k in needs)

    if any(not _covered(r, n) for r, n, _f in todo):
        cfg = load_config(args.config)
        op = build_operator(cfg)
    store_dir = Path(args.store)

    for i, (row, needs, fixes) in enumerate(todo, 1):
        old = (row.get("title") or "").strip()
        print(f"\n[{i}/{len(todo)}] {row.get('id')}")
        why = "; ".join(f"{k}: {', '.join(v)}" for k, v in needs.items())
        print(f"  repairing    {why}")
        # The source every rewritten line must not out-claim, printed so the dry run can be
        # reviewed at all. The truth rule is enforced mechanically for figures, places,
        # institutions and guarantees; this line is what the residue is judged against.
        print(f"  source       {(row.get('oneLine') or '')[:160]}")
        print(f"  title  before ({len(old):3d}) {old}")
        if row.get("id") in approved:
            # No model call, no re-validation against a linter the approver has already
            # overruled: an approved string is a decision, not a draft.
            value = approved[row["id"]]
            print(f"  title        ({len(value):3d}) {value}   [from plan]")
            patches.append((row, dict({"title": value}, **fixes)))
            continue
        have = approved_lines.get(row.get("id") or "", {})
        if have and all(k in have for k in needs):
            # Same rule as --from-plan, one grain finer: an approved line is a decision.
            chosen = {k: have[k] for k in needs}
            for kind, value in chosen.items():
                print(f"  {kind:12s} ({len(value):3d}) {value}   [from plan]")
            patches.append((row, dict(chosen, **fixes)))
            continue
        try:
            fields, trail, notes = propose(op, row, max_chars=args.max_chars,
                                           attempts=args.attempts, needs=needs)
        except ProviderExhaustedError as e:
            # A dead brain ENDS the run. There is nothing to retry against and no verdict of
            # "no" to record — every remaining row would fail identically.
            print(f"  OPERATOR EXHAUSTED: {e}", file=sys.stderr)
            print(f"  stopping after {i - 1} of {len(todo)} — re-run to resume", file=sys.stderr)
            break
        except Exception as e:
            # One row's failure is NOT an outage. Measured 2026-08-14: MiniMax-M3 spends its
            # whole token budget thinking on a per-CALL coin flip (`finish_reason=length`; the
            # same 14 packs truncated at pack 2 on one run and pack 5 on the next), and the old
            # bare `break` here turned one such flip into 61 unattempted rows. The row is
            # recorded as skipped, exactly like an attempts-exhausted row, and a second pass
            # picks up the stragglers.
            #
            # The outage case still has to be caught, because an unreachable endpoint ALSO
            # arrives as a plain exception: a run of consecutive failures is what distinguishes
            # "the brain is down" from "this row was unlucky", so the counter — not the first
            # failure — is the stop condition.
            consecutive_failures += 1
            print(f"  FAILED: {type(e).__name__}: {e}", file=sys.stderr)
            skipped.append((row, [f"{type(e).__name__}: {e}"]))
            if consecutive_failures >= _OUTAGE_RUN:
                print(f"  {consecutive_failures} consecutive failures — treating as an outage; "
                      f"stopping after {i} of {len(todo)}, re-run to resume", file=sys.stderr)
                break
            continue
        consecutive_failures = 0
        if fields is None:
            print(f"  SKIPPED after {args.attempts} attempts:")
            for line in trail:
                print(f"    {line}")
            skipped.append((row, trail))
            continue
        for kind, value in fields.items():
            print(f"  {kind:12s} ({len(value):3d}) {value}")
        for note in notes:
            # Not a breach and not enforceable — a machine cannot rule on whether a word is
            # fair paraphrase. Named here so the reviewer reads three words, not two pages.
            print(f"  CHECK        {note}")
        if len(trail) > 1:
            print(f"    ({len(trail)} drafts)")
        patches.append((row, dict(fields, **fixes)))

    print(f"\n{'=' * 72}")
    print(f"rows to patch : {len(patches)}")
    print(f"skipped       : {len(skipped)}")

    if args.plan_out:
        # Written from `patches`, the same object the apply path patches from, so the plan
        # cannot describe something other than what would have shipped. Tabs and newlines are
        # stripped because the plan is TSV and a line that re-parses wrong is worse than one
        # that fails to parse: it would ship silently truncated.
        out = Path(args.plan_out)
        with out.open("w", encoding="utf-8") as fh:
            written_rows = 0
            for row, fields in patches:
                for kind, value in fields.items():
                    flat = " ".join(str(value).split())
                    fh.write(f"{row['id']}\t{kind}\t{flat}\n")
                    written_rows += 1
        print(f"plan written  : {written_rows} lines to {out}")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply "
              "(needs STORE_INTERNAL_API_KEY).")
        return 0

    log_path = store_dir / RETITLE_LOG
    written = failed = 0
    for row, fields in patches:
        pack_id = row["id"]
        # Logged BEFORE the write: once a column is overwritten the old value is not readable
        # from any GET projection, so a crash between write and log is unrecoverable.
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "at": datetime.now(timezone.utc).isoformat(),
                "id": pack_id,
                "before": {k: row.get(k) or "" for k in fields},
                "after": fields,
            }, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

        ok, problem = patch_copy(args.api_url, internal_key, pack_id, dict(fields), row)
        if not ok:
            print(f"  FAILED {pack_id}: {problem}", file=sys.stderr)
            failed += 1
            continue
        if "title" in fields:
            note = _write_dossier_title(store_dir, pack_id, fields["title"])
            if note:
                print(f"  WARNING {pack_id}: {note}", file=sys.stderr)
        written += 1

    print(f"\npatched  : {written}")
    print(f"failed   : {failed}")
    print(f"rollback : {log_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
