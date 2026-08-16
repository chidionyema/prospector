"""The field: who is already there, in their own words.

WHY THIS FILE EXISTS
--------------------
The founder's reading of a shipped pack, 2026-08-15: "there is no background". That is not a
tone problem, it is a plumbing one. The engine runs an `incumbency` check — it writes queries,
fetches pages about who already serves this market, and reads them — and then throws almost
all of it away. What survives into the pack is the verdict brain's one-paragraph `rationale`.
The PASSAGES, which are the only place the pack ever holds a named competitor saying what it
charges and who it serves, reach the dossier on disk and are never rendered for the buyer.

So the most background-rich material this system retrieves has been sitting unread in
`store/dossiers/*.json` while the buyer opened a pack that explained nothing about the world it
was about. This module renders it.

WHAT IT DOES NOT DO
-------------------
It does not characterise the competition. Every sentence here is either a field already on the
dossier or a verbatim excerpt of a page we fetched, attributed to that page. There is no
summary of "the competitive landscape", because a summary is a claim and no retrieval backs
one. The buyer gets what we read and who said it; the reading is theirs.

Excerpts are filtered, not trimmed blind. A retrieved passage is frequently navigation
furniture, a cookie banner or a link list, and quoting that at a buyer is worse than quoting
nothing: it reads as padding AND makes the evidence look thin. `_readable_excerpt` requires
prose-shaped text and returns "" otherwise, so a page with nothing quotable contributes its
link and no quote.

Shape-agnostic by construction: every read is a `getattr`, because two objects reach here — a
live `Dossier` and the `SimpleNamespace` tree `pack_manifest.dossier_from_dict` builds for the
backfill, whose verdicts are plain strings.
"""
from __future__ import annotations

import re
from typing import Any, List, Optional

from . import admissibility, models
from .dossier import _host, link_inline_citations, source_index

FILENAME = "The_Field.md"
TITLE = "The field: who is already there"

# The buyer-visible name of the section that owns the incumbency rationale on a refuted or
# unverifiable verdict (see `render`). Spelled out rather than imported from `pack_bear_case`:
# these two modules are siblings that bridge loads independently, and a rendering module that
# imports another rendering module to read one string is a cycle waiting to be introduced by
# the next person who needs the same trick in the other direction. Same trade
# `pack_checklist.BUILD_SPEC_SECTION` and `pack_floors.QA_SECTION` already make.
BEAR_CASE_SECTION = "What would sink this"

# The checks whose retrieved pages are ABOUT the field rather than about the reader's plan.
# `incumbency` is the substance; `price_comparables` is evidence-only by design
# (`price_comparables.py` — it can never kill) and is exactly the "what do people already pay"
# material a buyer needs next to it.
_FIELD_CHECKS = ("incumbency", "price_comparables")

_MIN_EXCERPT_WORDS = 14
_MIN_SEGMENT_WORDS = 8
_MAX_EXCERPT_CHARS = 420
# A trailing ellipsis in any of the shapes that reach here, including one wearing a closing
# quote. Same expression as `pack_floors._ELLIPSIS_TAIL`, and deliberately a copy: these are
# sibling renderers that bridge loads independently, and neither owns the other's constants
# (see `BEAR_CASE_SECTION` above for the same trade).
_ELLIPSIS_TAIL = re.compile(r"(?:…|\.\.\.)[\s.…]*[\"'’)\]]?\s*$")
# AN ELLIPSIS AT THE END OF A LINE DELETES THE LINE (2026-08-15).
#
# `plain_text._repair_truncation` (plain_text.py:396) treats a trailing ellipsis as evidence
# of truncation, cuts back to the last sentence terminator inside the line, and returns "" when
# there is none — and `bridge._create_bundle` now runs this section, like the other four late
# renderers, through `plain_text.publish_pass_document`. A retrieved passage is frequently ONE
# long sentence, so the clip below produced exactly that shape and the whole `> quote` line was
# removed after this module returned it. Measured before the fix on the 449-character passage
# in `tests/unit/test_pack_render_defects.py`: `len(_readable_excerpt(...)) == 420`, tail
# `'etitor in this space quietly makes most…'`, and `publish_pass_document('> ' + quote) == ''`
# — the citation and its link still published, with no passage under them, on a source-or-die
# storefront.
#
# `pack_floors._whole_sentences` fixed its own instance of this by DROPPING the fragment, and
# that is the right answer there because a rationale that will not fit is content we hold in
# full elsewhere. It is the wrong answer here: this module's entire reason to exist is that the
# passages were being thrown away, and `test_a_quote_that_really_was_cut_still_says_so` pins
# that a genuinely cut passage must still carry its marker — dropping it would trade a false
# "truncated" for a false "complete", which is the worse lie in a document made of receipts.
#
# So the marker stays and stops being the last thing on the line. The ellipsis marks the cut
# where the cut happened, and an editorial note in square brackets closes the line on a full
# stop, which `_TRAILING_ELLIPSIS` (plain_text.py:273) does not match. The buyer keeps the
# quote, keeps the truthful "this was cut", and is told where the rest is; the publish pass
# sees a line that ends in a sentence and leaves it alone. Bracketed because it is OUR sentence
# inside a block quote of somebody else's words.
_CUT_NOTE = "[passage cut here; the rest is on the page linked above.]"
# Retrieved passage text arrives with the page's furniture glued to its prose and no blank
# lines: a title, a breadcrumb and a heading run into the first real sentence with nothing but
# a dash or a markdown marker between them. Splitting on sentence ends alone leaves the whole
# lot in one "sentence", so these are boundaries too. Measured on `e698149e137fc164`, adding
# them is what separates "National Data Privacy Agreement – Student Data Privacy Consortium
# (SDPC) Close Student Data Privacy Consortium (SDPC) ..." from the paragraph after it.
#
# The last alternative is a ZERO-WIDTH break on a full stop with no space after it. That is a
# scrape artifact, not punctuation: it is where a page's title element ended and its body began
# with nothing between them. It matters because the sentence-end rule above requires whitespace,
# so without this the title and the prose stay ONE segment -- and the prose then carries the
# title past the lower-case ratio test that exists to reject titles. Shipped on `/sample`,
# attributed to capterra.com, as the fourth quote in the section that proves we quote:
#
#     "Payapps Logo Payapps Software Review 2026: Features, Integrations, Pros & Cons.Payapps
#      includes invoice management, purchase order management, and accounting integration ..."
#
# Split rather than rejected, so the real sentence after the glue survives and only the title is
# dropped. Two lower-case letters on the left and a capital plus two lower-case on the right
# keeps initials and abbreviations ("U.S. Bank", "e.g.Foo" is not a shape prose produces) and
# every decimal, since digits are excluded on both sides.
_SEGMENT_BREAK = re.compile(
    r"(?<=[.!?])\s+|\s+[—–]\s*|\s*\|\s*|\s*#{1,6}\s+|\s*»\s*|\s*-{3,}\s*|\s*\n+"
    r"|(?<=[a-z]{2}\.)(?=[A-Z][a-z]{2})")
_LOWER_WORD = re.compile(r"\b[a-z][a-z'\-]{1,}\b")
_ANY_WORD = re.compile(r"\b[A-Za-z][A-Za-z'\-]*\b")
# `workflowResourceReport` — a nav list concatenated without spaces. Two lower-case letters,
# an upper-case, then more lower-case is the signature. `iKeepSafe` and `eBay` do not match
# (one leading lower-case letter), which is deliberate: real brands must survive.
_RUN_TOGETHER = re.compile(r"[a-z]{3}[A-Z][a-z]{3}")
# The OTHER concatenation signature: a table or a card list flattened into one line, where the
# cells keep their own capitals and their own currency figures. Observed verbatim on
# `ltcillinois.org` in `e698149e137fc164`:
#
#     "View all Resources Events Illinois Education and Technology Conference 2026 (IETC)Nov
#      11, 2026$250Learn"
#
# That passed every earlier filter — it is long, lower-case-heavy, and starts with a word.
# Three glue points give it away and none of them occurs in written prose: a bracket closed
# straight into a capitalised word, a digit closed straight into a currency symbol, and a
# currency figure closed straight into a capitalised word.
#
# The last clause requires a CAPITAL after the figure on purpose: `$250m`, `£20k` and `$3bn`
# are ordinary prose and must survive. "$250Learn" is a price cell touching a button label.
_GLUED_CELLS = re.compile(r"[)\]][A-Z][a-z]{2}|\d\s?[$£€]|[$£€]\d[\d,.]*[A-Z]")
# Furniture, not prose. A segment starting with one of these is page chrome; quoting it tells
# the buyer nothing and costs the pack credibility.
_FURNITURE = re.compile(
    r"^(cookie|we use cookies|accept all|skip to|sign in|log in|subscribe|menu|home\b|"
    r"privacy|terms|javascript|enable javascript|404|page not found)", re.IGNORECASE)
# Prose carries function words, and function words are lower case. A title, a breadcrumb or a
# heading is Title Case or CAPS almost throughout. 0.55 was chosen against the observed
# passages of `e698149e137fc164`: it rejects "ED-TECH COMPANIES: 3 Benefits To Data Privacy
# Certification US Federal and state laws require..." at 0.53 and keeps "The Student Data
# Privacy Consortium, a special interest group of the non-profit..." at 0.63.
#
# It is set for PRECISION, and the asymmetry is the argument. A rejected segment costs the
# buyer one quote under a link they can still click. An accepted one puts a cookie banner in a
# £30 product as evidence. Sources with nothing quotable are listed with their link alone.
_MIN_LOWER_RATIO = 0.55
# A QUOTE HAS TO START WHERE A SENTENCE STARTS (2026-08-15, founder on the live sample page).
#
# The segment splitter cuts on sentence ends AND on page furniture, so a passage whose first
# real prose is preceded by a heading can leave a run beginning in the middle of somebody's
# clause. Shipped on `/sample` under "Quoted rather than summarised", attributed to
# researchgate.net:
#
#     "retention and their effects on construction subcontractors in the UK. chasing the final
#      retention on its due date."
#
# Every other filter here passes it: it is long enough, it is lower-case-heavy, it is prose. It
# is also two halves of two different sentences, and it is the third thing a buyer reads in the
# section that exists to prove we quote rather than paraphrase.
#
# A leading digit is a sentence start (`3.9% of...`), and so is a lower-case-then-capital brand
# (`eBay`, `iKeepSafe`) -- the same shapes `_RUN_TOGETHER` was written to protect.
_SENTENCE_START = re.compile(r"^[\"'“‘(\[]?(?:[A-Z0-9£$€]|[a-z][A-Z])")


def _verdict(chk: Any) -> str:
    return str(getattr(getattr(chk, "verdict", None), "value", getattr(chk, "verdict", "")) or
               "").strip().lower()


def _check_named(checks: List[Any], name: str) -> Optional[Any]:
    for chk in checks:
        if str(getattr(chk, "check_name", "") or "").strip().lower() == name:
            return chk
    return None


def _readable_excerpt(text: str) -> str:
    """The first prose-shaped run of a retrieved passage, or "" if there isn't one.

    Deliberately strict. The cost of a false negative is one missing quote under a link the
    buyer can still click; the cost of a false positive is a £30 pack quoting a cookie banner
    at its reader as evidence. Those are not symmetric.
    """
    raw = " ".join(str(text or "").split())
    if not raw:
        return ""
    kept: List[str] = []
    for seg in (s.strip(" -–—*#|") for s in _SEGMENT_BREAK.split(raw) if s and s.strip()):
        words = _ANY_WORD.findall(seg)
        if len(words) < _MIN_SEGMENT_WORDS:
            continue
        if _FURNITURE.match(seg):
            continue
        if _RUN_TOGETHER.search(seg) or _GLUED_CELLS.search(seg):
            continue
        if len(_LOWER_WORD.findall(seg)) / len(words) < _MIN_LOWER_RATIO:
            continue
        # Only for the FIRST segment kept. A later one may legitimately continue the quote
        # across a break the splitter made, and rejecting those would shorten every excerpt
        # that runs past one sentence. What must not happen is the quote OPENING mid-clause.
        if not kept and not _SENTENCE_START.match(seg):
            continue
        kept.append(seg if seg[-1] in ".!?" else seg + ".")
        if len(" ".join(kept)) >= 200:
            break
    out = " ".join(kept).strip()
    if len(out.split()) < _MIN_EXCERPT_WORDS:
        return ""
    if len(out) > _MAX_EXCERPT_CHARS:
        cut = out[:_MAX_EXCERPT_CHARS].rsplit(" ", 1)[0]
        out = cut.rstrip(",;:") + "…"
    # The line must not END on the marker, or the publish pass deletes it — see `_CUT_NOTE`.
    # The substitution normalises whatever shape the ellipsis arrived in to one character:
    # a passage that reached us already truncated ("...", "....", "…'") is the same defect
    # arriving from upstream, and it is repaired here rather than left to be deleted there.
    if _ELLIPSIS_TAIL.search(out):
        out = _ELLIPSIS_TAIL.sub("…", out) + " " + _CUT_NOTE
    return out


def _bear_case_will_ship(dossier: Any) -> bool:
    """Will the section this module points at actually be in the buyer's download?

    THE POINTER MAY NOT OUTLIVE ITS TARGET (2026-08-15)
    ---------------------------------------------------
    `render` hands the incumbency rationale to **What would sink this** on a refuted or
    unverifiable verdict and prints a pointer instead. `bridge._create_bundle` guards each of
    the five late renderers INDIVIDUALLY and on purpose (bridge.py:1789) — "one that fails
    costs the pack that section and nothing else" — so `pack_bear_case.render` raising costs
    the pack the bear case while this section has already shipped a pointer to it. Measured
    before the fix, with `pack_bear_case.render` patched to raise: the pointer to 'What would
    sink this' is still emitted, and the rationale is then published in NO section of the pack.
    The buyer is sent to a file that is not in their zip, to read a paragraph nobody printed.
    That is a worse failure than the duplication the split exists to prevent, because the
    duplication was visible and this is silent.

    So the pointer is conditioned on the target's OWN answer rather than on a condition kept
    in step with it by hand. The call is cheap and safe to repeat: `pack_bear_case.render` is
    pure Python over the same dossier, makes no model call, and is the deterministic renderer
    the backfill already runs twice on packs it re-renders.

    Conservative in the only direction that matters. Bridge calls the bear case with
    `financial_md` as well, so it can produce a section on input this call does not have —
    never fewer. A `True` here therefore guarantees a section there; a `False` at worst prints
    the rationale in this section when the bear case would also have carried it, and `render`
    prints the pointer and the rationale on mutually exclusive branches, so even that cannot
    put the same paragraph in both places.

    Imported inside the function, not at module scope: these two are siblings that bridge
    loads independently, and a module-level edge between them is the cycle the note on
    `BEAR_CASE_SECTION` above declines to introduce.
    """
    try:
        from . import pack_bear_case
        return bool(pack_bear_case.render(dossier))
    except Exception:  # noqa: BLE001 — an unrenderable bear case is an absent target
        return False


def _dateline(src: Any) -> str:
    """`published_at` as a bare year, when the source carries one.

    A newspaper datelines its background for a reason: a fact about a market is a fact about a
    market ON A DATE, and a buyer deciding whether to act needs to know they are reading
    something from 2019. Rendered only when it is on disk; never inferred from the fetch time,
    which is when WE looked, not when the page was written.
    """
    raw = str(getattr(src, "published_at", "") or "").strip()
    m = re.search(r"(19|20)\d{2}", raw)
    return m.group(0) if m else ""


def _passage_block(src: Any, seen: set) -> List[str]:
    """One source: attribution line, link, and its excerpt if it has one we have not used.

    `seen` carries the excerpts already printed in this section. Two URLs on the same site
    routinely return byte-identical body text — `ikeepsafe.org` did it twice in
    `e698149e137fc164` — and printing the same paragraph twice under two links makes the
    evidence look padded rather than corroborated. The second source keeps its link, because
    it IS a second source; it just does not get to say the same thing again.
    """
    url = str(getattr(src, "url", "") or "").strip()
    if not url:
        return []
    host = _host(url) or url
    year = _dateline(src)
    label = admissibility.provenance_label(url)
    head = f"**{host}**" + (f", {year}" if year else "")
    if label:
        head += f" — {label}"
    out = [f"{head}  ", f"[{url}]({url})", ""]
    quote = _readable_excerpt(getattr(src, "text", ""))
    key = " ".join(quote.lower().split())
    if quote and key not in seen:
        seen.add(key)
        out.append(f"> {quote}")
        out.append("")
    return out


def render(dossier: Any) -> str:
    """The field section as markdown, or "" when no field check retrieved anything.

    "" is the correct output for a dossier whose incumbency check fetched nothing. A section
    headed "who is already there" followed by nothing states, to a buyer, that nobody is —
    which is a claim, and one we would be making out of an empty list rather than out of
    evidence. The caller treats "" as "do not add this section".
    """
    checks = list(getattr(dossier, "checks", None) or [])
    if not checks:
        return ""

    field = [c for c in checks
             if str(getattr(c, "check_name", "") or "").strip().lower() in _FIELD_CHECKS]
    if not field:
        return ""

    index = source_index(dossier)
    seen: set = set()
    incumbency = _check_named(checks, "incumbency")
    price = _check_named(checks, "price_comparables")

    out: List[str] = [f"# {TITLE}", ""]

    # The lede of this section: what the reading of the field concluded, in one line, before
    # any of the evidence. Which line depends on the verdict, because the verdicts mean
    # genuinely different things to someone deciding whether to start.
    verdict = _verdict(incumbency) if incumbency is not None else ""
    if verdict == "supported":
        out += ["Somebody is already doing a version of this, and that is the useful finding. "
                "It means the problem is real enough that a business formed around it. It does "
                "not mean the field is closed, and it does not mean your version wins. Read who "
                "they are and decide which part of the job they are not doing.", ""]
    elif verdict == "refuted":
        out += ["We looked for people already doing this and the evidence went the other way. "
                "An empty field is the ambiguous case, not the good one: it is either an opening "
                "or a market that has already been tried and abandoned somewhere we could not "
                "see. Treat the absence as a question to answer in your first month, not as a "
                "clear run.", ""]
    else:
        out += ["We searched for who is already serving this market and could not settle it. "
                "What follows is what we actually read, so you can pick up where the search "
                "stopped rather than start it again.", ""]

    # THE INCUMBENCY RATIONALE HAS ONE OWNER, AND THE SPLIT IS ON THE VERDICT (2026-08-15).
    #
    # This block and `pack_bear_case._refuted_block` / `._unproven_block` both printed the same
    # paragraph verbatim, so "the field" and "what would sink this" shipped identical text —
    # two of the six findings `pack_linter.check_repetition` still blocked on after every other
    # fix. Splitting on the verdict makes an overlap impossible rather than merely unlikely:
    # the bear case only ever walks rows whose verdict is `refuted` or `unverifiable`, so a
    # rationale printed here on `supported` alone can never be the same row as one printed
    # there. No conditional in either module has to stay in step with the other.
    #
    # This section loses nothing on the other two verdicts. It still opens with a lede written
    # for that verdict, and it still holds what nothing else in the pack has: the passages, in
    # the competitor's own words, with links. That was always the reason this file exists.
    #
    # THE POINTER IS CONDITIONED ON THE TARGET, NOT ON THE VERDICT ALONE (2026-08-15). The
    # split above decides who OWNS the rationale; `_bear_case_will_ship` decides whether that
    # owner is in the buyer's download. Exactly one of {rationale, pointer} is printed on every
    # path, so the rationale can never appear twice and can never disappear: it is printed here
    # precisely when the section that would otherwise carry it is not going to exist. See
    # `_bear_case_will_ship` for the before-state measurement and why the fallback is safe.
    verdict_owned_here = verdict == "supported"
    handed_over = (incumbency is not None
                   and verdict in ("refuted", "unverifiable")
                   and _bear_case_will_ship(dossier))
    if incumbency is not None and (verdict_owned_here or not handed_over):
        rationale = link_inline_citations(
            str(getattr(incumbency, "rationale", "") or "").strip(), index)
        if rationale:
            out += [rationale, ""]
    elif handed_over:
        out += [f"What the reading of the field concluded, and why, is set out in "
                f"**{BEAR_CASE_SECTION}** with everything else that argues against starting. "
                "What follows here is the evidence itself.", ""]

    # The passages. This is the part that was being discarded.
    sources = [s for s in models.distinct_sources(
        [c for c in field if str(getattr(c, "check_name", "") or "").strip().lower()
         == "incumbency"])
        if str(getattr(s, "url", "") or "").strip()]
    if sources:
        out += ["---", "", "## What we read, in their words", "",
                "Excerpts from the pages the search returned, each with its link and its date "
                "where the page carries one. Quoted rather than summarised: a summary of a "
                "competitor is a claim about a competitor, and nothing we retrieved supports "
                "one.", ""]
        for src in sources[:10]:
            out += _passage_block(src, seen)

    if price is not None:
        anchors = [s for s in models.distinct_sources([price])
                   if str(getattr(s, "url", "") or "").strip()]
        rationale = link_inline_citations(
            str(getattr(price, "rationale", "") or "").strip(), index)
        if rationale or anchors:
            out += ["---", "", "## What people already pay", "",
                    "Prices found on the open web for work of this kind. These are what the "
                    "market has shown it will pay somebody, which is a different and harder "
                    "fact than what you hope to charge.", ""]
            if rationale:
                out += [rationale, ""]
            for src in anchors[:6]:
                out += _passage_block(src, seen)

    return "\n".join(out).rstrip() + "\n"
