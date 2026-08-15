"""Claim-safe pack floors (Epic C lite) — fill empty stubs without inventing facts.

When content_gen returns empty marketing / thin prose, published zips used to ship
23-byte Marketing_Assets stubs. These helpers synthesise buyer-facing text ONLY from
fields already on the dossier/candidate (title, one-liner, supported rationales).
No numbers, no unsourced claims — silence stays silence.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence

from .plain_text import publish_pass, to_plain_text
from .trimming import as_phrase

# The two places the executive summary sends a buyer NEXT.
#
# These were the literal filenames `QA_Report.md` and `05_First_Week_Checklist.md` until
# 2026-08-15, printed in bold inside the first block a buyer reads. On that date the `.md`
# stopped being archive entries (bridge.py split `PACK_DOCUMENTS`, the render input, from
# `BUNDLE_FILES`, the archive contract), which turned the pack's own opening instruction into
# a direction to open a file that is not in the download. A buyer following step 1 would have
# gone looking for `QA_Report.md`, failed to find it, and reasonably concluded the pack was
# short -- in the first five minutes, which is when the refund gets decided.
#
# So the copy names SECTIONS now. These strings must match the headings the reader actually
# prints, which are `bridge._SECTION_TITLES`; `tests/unit/test_pack_floors.py` pins them to it.
# They are duplicated here rather than imported because `bridge` imports this module, and a
# cosmetic import cycle on the money rail is not worth the DRY.
# Retitled 2026-08-15 away from the engine's own vocabulary. "The QA Report" is what WE call
# the artefact; a buyer has no QA department and did not buy a report about our process. The
# founder's reading of the shipped pack named this directly: "things our engine does that does
# not concern us". The document is unchanged; what it is CALLED now describes what the reader
# gets out of it.
QA_SECTION = "Every check, in full"
CHECKLIST_SECTION = "Your first fortnight"


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
# A trailing ellipsis in either spelling. Kept in step with `plain_text._TRAILING_ELLIPSIS`,
# which is the rule that actually deletes the line; this one only has to RECOGNISE the shape.
_ELLIPSIS_TAIL = re.compile(r"(?:…|\.\.\.)[\s.…]*[\"'’)\]]?\s*$")


def _whole_sentences(text: str, budget: int = 280) -> str:
    """As many WHOLE sentences as fit, and never a fragment. At least one, whatever its length.

    THE BUG THIS FIXES, WITH ITS RECEIPT
    ------------------------------------
    This used to be `clip_to_sentence(rationale, 280)`. That helper marks a mid-sentence cut
    with a trailing "…" so a truncation announces itself — correct, and the whole point of
    `trimming.py`. But `plain_text.publish_pass_document`, which every document is passed
    through in `bridge._create_bundle`, DELETES any line ending in "…"::

        >>> publish_pass_document("- **value durability:** ... vendors, the…")
        ''

    So a bullet whose rationale had no sentence boundary inside 280 characters was silently
    removed AFTER this function returned it, and the executive summary shipped a "## Grounded
    signals" heading with nothing under it. That empty heading was measured on 36 of 140 live
    bundles and had been read as "the dossier carried no supported rationales". It was not:
    the rationales were there, they were long-winded, and two correct components disagreed
    about who owns a truncation.

    Neither component is wrong, so neither is changed. The producer stops emitting fragments
    instead: whole sentences only, so there is no ellipsis for the publish pass to act on.
    """
    body = " ".join(str(text or "").split())
    if not body:
        return ""
    sentences = [s for s in _SENTENCE_SPLIT.split(body) if s]
    out = sentences[0]
    for nxt in sentences[1:]:
        if len(out) + 1 + len(nxt) > budget:
            break
        out = f"{out} {nxt}"
    # A single sentence longer than the hard stop is DROPPED, not marked. Fixed 2026-08-15.
    #
    # It used to be handed to `clip_to_sentence(out, 600)`, which marks a mid-word cut with a
    # trailing "…". That is correct behaviour for `trimming.py` and fatal here, because the
    # marked line does not survive to be read: `plain_text.publish_pass_document` runs every
    # pack line through `publish_pass`, and `_repair_truncation` (plain_text.py:396) treats a
    # trailing ellipsis as truncation, looks for an earlier sentence terminator inside the
    # line, finds none in a single sentence, and returns "" — so the whole bullet is deleted
    # after this function returned it. The deletion happened AFTER `exec_summary_md` had
    # already counted the bullet for its heading, so a 681-character single-sentence rationale
    # beside one short supported check shipped as "2 things that hold up" above one bullet.
    # The buyer counts them.
    #
    # Dropping it here loses no content that used to reach a reader — the publish pass was
    # deleting exactly these lines already — and it makes the count truthful, which is the
    # part that was broken. The same guard catches a rationale that arrived carrying an
    # upstream ellipsis of its own, which reaches the publish pass identically.
    if len(out) > 600 or _ELLIPSIS_TAIL.search(out):
        return ""
    return out


# The verdict brain writes its rationales as a report to US -- "The passages show that...",
# "The passages describe...", "One passage discusses...". That is the right voice for a verdict
# and the wrong voice for the first thing a buyer reads: it makes the finding a fact about our
# retrieval rather than a fact about their market. Measured on this dossier, 2026-08-15: 7 of
# the 9 rationales open on one of these.
#
# Only the OPENER goes. The sentence's claim, its hedges and its citations are untouched, so
# this cannot turn "the passages do not say X" into "X" -- the negation lives after the verb,
# and `tests/unit/test_pack_floors.py` pins that case specifically.
_REPORTING_OPENER = re.compile(
    r"^(?:the\s+)?(?:passages?|sources?|retrieved\s+\w+)\s+"
    r"(?:show|describe|discuss|indicate|say|state|suggest|confirm|establish)"
    r"(?:\s+that)?\s+", re.I)


def _finding(rationale: str) -> str:
    """A check rationale as a FINDING about the buyer's market, not a note about our search.

    "" when nothing publishable survives — see `_whole_sentences`. The caller must treat that
    as "no bullet", never as an empty bullet: an empty finding that is still counted is the
    defect the heading arithmetic in `exec_summary_md` was shipping.
    """
    body = _whole_sentences(rationale)
    stripped = _REPORTING_OPENER.sub("", body, count=1)
    if stripped == body or not stripped:
        return body
    # The opener carried the sentence's capital letter with it.
    return stripped[0].upper() + stripped[1:]


def _supported_bullets(checks: Sequence[Any], *, limit: int = 5) -> List[str]:
    """The supported findings, labelled with the QUESTION each answers.

    The label used to be the gate's own name with its underscores swapped for spaces --
    `- **value durability:** ...`, `- **pain reality:** ...`. That is a key from our schema,
    printed in bold as the first body text of the pack, and it was three of the four things
    the founder named on 2026-08-15 at once: engine vocabulary, jargon with no background, and
    a label that tells the buyer what our pipeline calls this rather than what it means for
    them. `dossier.check_label` already holds the buyer-facing question and is already used by
    the QA report and by `pack_reference`; using it here is what stops the pack's opening from
    being the one surface that still speaks schema.
    """
    from .dossier import check_label  # deferred: same trade `pack_checklist._labels` makes
    out: List[str] = []
    for c in checks or []:
        verdict = getattr(getattr(c, "verdict", None), "value", None) or getattr(c, "verdict", "")
        if str(verdict).lower() != "supported":
            continue
        finding = _finding((getattr(c, "rationale", None) or "").strip())
        if not finding:
            continue
        line = f"- **{check_label(getattr(c, 'check_name', '') or '')}** {finding}"
        # THE LIST THIS RETURNS IS ALSO THE COUNT THE HEADING PRINTS (2026-08-15).
        #
        # `exec_summary_md` interpolates the length of this list into "## What we found — {n}
        # things that hold up", and `bridge._create_bundle` then runs the document through
        # `publish_pass_document`, which DELETES any line the publish pass empties out. Every
        # line deleted after the count was taken is a bullet the buyer is told to expect and
        # cannot find, three lines further down the first page they read.
        #
        # `_whole_sentences` already stops the one shape that caused it in the field (a
        # rationale clipped to an ellipsis). This asks the publish pass itself rather than
        # modelling it, so a rationale emptied by some OTHER rule — a line that was nothing
        # but a passage id, say — cannot reopen the same defect through a door we did not
        # think of. Five bullets at most, so the cost is five regex passes.
        if not publish_pass(line):
            continue
        out.append(line)
        if len(out) >= limit:
            break
    return out


def claim_safe_marketing(
    candidate: Any,
    checks: Sequence[Any] = (),
) -> List[Dict[str, str]]:
    """Deterministic listing_page (+ light ancillary) from grounded fields only."""
    title = (getattr(candidate, "title", None) or "Opportunity pack").strip()
    one = (getattr(candidate, "one_liner", None) or "").strip()
    why = (getattr(candidate, "why_now", None) or "").strip()
    who = (getattr(candidate, "who_pays", None) or "").strip()
    bullets = _supported_bullets(checks)

    # This section is FIELDS TO LIFT, not prose to read, and it is now written as such.
    #
    # It used to be a second copy of the opening: title, one-liner, who pays, why now, then
    # `## What the evidence supports` followed by the same `_supported_bullets` the executive
    # summary prints. Measured on pack e698149e137fc164 on 2026-08-15 that made it the single
    # largest source of cross-section duplicate sentences in the document — the buyer persona,
    # the one-liner and two check rationales, each read twice.
    #
    # The section still has to restate the facts: that is what makes it pasteable, and a buyer
    # writing their own landing page should not have to go and re-extract them. So the fix is
    # not to strip the facts out, it is to stop presenting them as a second essay. Labelled
    # fields read as a form to copy from; they do not read as the pack repeating itself. The
    # bullet dump goes entirely — five rationales are a section of the pack, not ad copy — and
    # ONE proof line survives, which is what a landing page can actually carry.
    body_parts = [
        f"# {title}",
        "",
        "Lift these straight into a landing page, a cold email or a deck. Every line is "
        "already cited elsewhere in this pack, so nothing here needs its own claim check.",
        "",
        "**Headline**",
        "",
        title,
        "",
    ]
    if one:
        body_parts += ["**One line**", "", one, ""]
    if who:
        body_parts += ["**Who it is for**", "", who, ""]
    if why:
        body_parts += ["**Why now**", "", why, ""]
    if bullets:
        # `- **Is the problem real?** ...` -> the finding alone. The question label is the
        # pack's own furniture and means nothing on somebody else's landing page.
        lead = re.sub(r"^-\s*\*\*.*?\*\*\s*", "", bullets[0]).strip()
        body_parts += ["**The proof point to lead with**", "", lead, ""]
    body_parts += [
        "**What not to say**",
        "",
        "Nothing above adds a market size, a revenue figure or a promise about results. "
        "Neither should the version you ship: every number in this pack is either cited or "
        "marked as an assumption, and a claim you cannot point at a source for is the one "
        "that will be challenged first.",
        "",
    ]
    copy = "\n".join(body_parts).strip()
    return [
        {
            "type": "listing_page",
            "headline": title[:140],
            "subhead": (one or title)[:280],
            "copy": copy,
            "what_you_get": [
                "Blueprint / build spec",
                "Go-to-market plan",
                "Operations plan",
                # Not "from verified inputs": `_render_financial_model` (artifacts.py:152) takes
                # the `claims` list and never reads it, so the inputs are assumptions, printed as
                # assumptions. The arithmetic IS Python and IS exact; that is the whole claim.
                "Financial model (arithmetic computed in Python, assumptions listed)",
            ],
            # `bullets` are markdown list items (`- **buyer intent:** ...`). proof_point is
            # rendered by the storefront as literal text, so the markup has to come off here
            # or the buyer reads the asterisks. Words are preserved verbatim.
            "proof_point": to_plain_text(
                bullets[0] if bullets else one, collapse=True
            )[:240],
            "who_pays": who,
            "effort_tag": "solo_operator",
            "time_to_first_revenue": "",
        }
    ]


def exec_summary_md(candidate: Any, checks: Sequence[Any] = ()) -> str:
    """The opening: the situation, then why it is a business. Rewritten 2026-08-15.

    WHAT THIS USED TO BE, AND WHY IT CHANGED
    ----------------------------------------
    It opened with "Start here — the next ten minutes": a three-step instruction to open the
    check report, pick a supported claim, click its source, and claim a refund if the source
    did not say what we said. The reasoning was sound and is preserved below — the first five
    minutes are when a refund gets decided, and the honest micro-win for THIS product is
    verifying that we are not lying. It survives as "Before you go further" further down.

    What was wrong was its POSITION. The founder's reading of the shipped packs, 2026-08-15:
    "there is no background... our tone and language is hurried and cryptic... we don't
    motivate or inspire". A document that opens by instructing the reader to audit it has told
    them nothing about the world they just paid to understand. It also frames the product as a
    compliance artefact in the first thing they read.

    So the order is the newspaper order now. A situation the reader can picture, then the
    paragraph that says why this is a business — what Winburn calls the promise of the piece,
    not a summary of it — and only then the housekeeping.

    THE LEDE IS SITUATIONAL, NOT ANECDOTAL, AND THAT IS A LIMIT NOT A CHOICE
    ------------------------------------------------------------------------
    The WSJ formula wants a person: one named case, then the widening. This renderer cannot
    write one. It makes no model call — which is what lets it be backfilled onto packs already
    sold and re-rendered offline — and every sentence it emits must come from a dossier field.
    An invented protagonist would be the single worst thing this pack could contain.

    What it can do is name the real payer, the real trigger and the strongest thing actually
    found, in that order, which is the situation lede a wire service uses when it has no
    person. Where the specifics are absent from the dossier, the line is absent too rather
    than padded with a generic one.

    Everything here is derived from fields already on the verified dossier, so it stays
    claim-safe by construction.
    """
    title = (getattr(candidate, "title", None) or "Opportunity").strip()
    one = (getattr(candidate, "one_liner", None) or "").strip()
    who = (getattr(candidate, "who_pays", None) or "").strip()
    why_now = (getattr(candidate, "why_now", None) or "").strip()
    bullets = _supported_bullets(checks, limit=4)

    settled = [c for c in (checks or [])
               if str(getattr(getattr(c, "verdict", None), "value", None)
                      or getattr(c, "verdict", "")).lower() == "supported"]
    open_checks = [c for c in (checks or [])
                   if str(getattr(getattr(c, "verdict", None), "value", None)
                          or getattr(c, "verdict", "")).lower() in ("unverifiable", "refuted")]

    from .dossier import check_label  # deferred: same trade `pack_checklist._labels` makes

    lines: List[str] = [f"# {title}", ""]

    # --- The standfirst: what this IS, before anything else. ---
    #
    # `one_liner` used to sit four blocks down, under a "## Why this is a business" heading,
    # after a persona paragraph and a "What changed:" paragraph. So the first 150 words a buyer
    # read named a job title and three school districts without ever saying what the business
    # was. A newspaper puts that sentence directly under the headline and so does this now.
    if one:
        lines += [f"**{one}**", ""]

    # --- The lede: who is living with this today. ---
    #
    # It opened "Somebody is already dealing with this:" — a demonstrative with no antecedent,
    # as the pack's first sentence. `this` referred to the title, three lines up, which the
    # reader had no reason to parse as a problem statement. With the standfirst above, the
    # sentence now has something to point at, and it names the person rather than announcing
    # that a person exists.
    #
    # `who_pays` is set on its own line rather than inlined. It is written by the generator as
    # a full descriptive sentence — measured on the live catalogue it runs to forty words and
    # names three districts — so a lede that embeds it mid-clause buries its own verb.
    if who:
        lines += ["The person already paying for this problem, in time if not in money:", "",
                  f"**{as_phrase(who)}**", "",
                  "They are not waiting for a product. They are working around it today, with "
                  "whatever is to hand.", ""]
    if why_now:
        lines += ["What changed:", "", why_now, ""]
    elif who:
        lines += ["Nothing we found says this is a new problem, which is worth knowing: an old "
                  "problem with no product around it has usually resisted one before. That is a "
                  "question this pack puts to you rather than answers.", ""]

    # --- The findings. ---
    #
    # This block used to open "That is not a hunch. 3 of the checks behind this pack came back
    # supported by sources we retrieved and have linked, and every one of them is printed in
    # full later with the page it came from." Every clause of that is about US — our checks,
    # our retrieval, our layout. The founder's reading, 2026-08-15: "we ramble about composite
    # scores, things our engine does that does not concern us". The count is kept because a
    # reader deciding how much weight to put on the next three bullets needs it; the process
    # around it is not.
    if len(lines) > 2:
        lines += ["---", ""]
    # THE NUMBER IN THE HEADING IS THE NUMBER OF BULLETS UNDER IT (2026-08-15).
    #
    # It was `len(settled)` — every supported check — above a list capped at four. Six
    # supported checks printed "6 things that hold up" over four bullets, and a buyer whose
    # first act is to count four things under a promise of six has caught the pack
    # miscounting itself on its own first page. The count is not decoration: it is there so a
    # reader knows how much weight to put on what follows, which is exactly the job it cannot
    # do if it disagrees with the list.
    #
    # `bullets` is now the single source of both, so the two cannot drift again, whatever
    # thins the list — the cap, an empty rationale, or a line the publish pass would delete.
    if bullets:
        noun = "thing that holds" if len(bullets) == 1 else "things that hold"
        lines += [f"## What we found — {len(bullets)} {noun} up", ""]
        lines += bullets + [""]
    elif settled:
        # Supported checks exist but none of them is quotable here. Saying "nothing came back
        # confirmed" would be false, and this repo's first rule is source-or-die, so the
        # branch states what is actually true and sends the reader to where the checks are
        # printed whole.
        lines += ["## What we found", "",
                  f"{len(settled)} of the checks behind this pack came back supported. None of "
                  "them is quoted here: the rationale we hold for each is either absent or a "
                  "single sentence too long to excerpt without cutting it mid-thought, and half "
                  "a finding is not a finding. Each is printed whole, with the pages it came "
                  f"from, in **{QA_SECTION}**.", ""]
    else:
        lines += ["## What we found", "",
                  "Nothing here came back confirmed. That is unusual, and it is stated at the "
                  "top rather than buried: what follows is a plan built on evidence we could "
                  "not confirm, and the open questions are the part to read first.", ""]
    if open_checks:
        # Buyer-facing questions, not gate keys. `What it does not settle: incumbency, legality,
        # payer solvency.` was the engine's own schema, printed in the opening paragraph of the
        # document, with the underscores swapped for spaces and nothing else changed.
        #
        # They are set as a list rather than a comma run because `check_label` returns
        # QUESTIONS: "Is it legal?, Can the customer afford it?" is not a sentence, and reading
        # them as a list is also how a buyer would use them.
        questions = sorted({check_label(getattr(c, "check_name", "") or "")
                            for c in open_checks if getattr(c, "check_name", "")})
        if questions:
            lines += ["## What we could not settle", ""]
            lines += [f"- {q}" for q in questions]
            lines += ["", "These are not omissions. Each one is argued at full strength further "
                          "down, because the case against is the half that decides whether you "
                          "spend a year on this.", ""]

    # --- One line of guarantee, and where to go next. ---
    #
    # This replaces a block headed "Before you go further" that told the buyer to spend ten
    # minutes opening our sources and checking that the claims matched, and to claim a refund
    # if they did not. The founder's reading of it, 2026-08-15: "we are asking the user to do
    # our own work after purchasing". That is exactly what it was. Verification is what the
    # pack IS; a buyer who has paid for a verified pack should not be handed the verification
    # as their first task, and a document that opens by asking to be audited has told them
    # nothing about the world they just paid to understand.
    #
    # The guarantee survives, stated as our commitment rather than their homework, and the
    # sources it refers to are cited inline throughout and listed in full at the end for
    # anyone who wants them. Nobody is asked to go and look.
    lines += ["---", "",
              "Every claim in this pack names the page it came from. If one of them does not "
              f"say what we say it says, that is a refund, not an argument — **{QA_SECTION}** "
              "at the end has each check with its sources, for anyone who wants to look.", "",
              f"**{CHECKLIST_SECTION}** is where to start.", ""]
    return "\n".join(lines)


def first_week_checklist_md(candidate: Any) -> str:
    title = (getattr(candidate, "title", None) or "this opportunity").strip()
    who = (getattr(candidate, "who_pays", None) or "the stated buyer").strip()
    return "\n".join([
        f"# First-week checklist — {title}",
        "",
        "Claim-safe starter steps. Adapt only where your own evidence supports it.",
        "",
        "1. Re-read the QA report kill/pass gates and list every SUPPORTED citation URL.",
        "2. Confirm the buyer (`who_pays`) matches reality for your market — dossier says: "
        f"{who}.",
        "3. Sketch the smallest paid offer described in the build spec (no scope creep).",
        "4. Pick one distribution channel from the GTM plan; ignore the rest for week one.",
        "5. Write the first outreach / listing using only claims that survived claim-check.",
        "6. Log what you could not verify; do not invent substitutes.",
        "",
    ])


def ensure_marketing_floor(
    marketing: List[Dict[str, Any]] | None,
    candidate: Any,
    checks: Sequence[Any] = (),
) -> List[Dict[str, Any]]:
    """Return marketing list with at least a claim-safe listing_page."""
    pieces = list(marketing or [])
    has_listing = any(
        (m.get("type") == "listing_page" and (m.get("copy") or "").strip())
        for m in pieces
    )
    if not has_listing:
        pieces = claim_safe_marketing(candidate, checks) + [
            m for m in pieces if m.get("type") != "listing_page"
        ]
    return pieces
