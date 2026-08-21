"""Claim-safe pack floors (Epic C lite) — fill empty stubs without inventing facts.

When content_gen returns empty marketing / thin prose, published zips used to ship
23-byte Marketing_Assets stubs. These helpers synthesise buyer-facing text ONLY from
fields already on the dossier/candidate (title, one-liner, supported rationales).
No numbers, no unsourced claims — silence stays silence.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence

from .pack_lede import select_lede
from .plain_text import publish_pass, to_plain_text
from .trimming import as_phrase, cap_words

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
    r"(?:\s+(?P<that>that))?\s+", re.I)
# THE OPENER GOVERNED MORE THAN ITS OWN CLAUSE (2026-08-15, founder on the live sample page).
#
# "The passages show THAT a, THAT b, and THAT c" is one verb with three complements. Deleting
# only the first four words leaves the other two `that`s reporting to a verb that is no longer
# there, and the first bullet of the first section of the free sample shipped as:
#
#     "Main contractors in the UK routinely withhold a percentage ... until milestones are met,
#      that unpaid subcontractors cause serious cash flow problems, and that Carillion's 2018
#      collapse left a trail ..."
#
# which is not a sentence. This removes the stranded conjunctions along with the verb that
# licensed them, and ONLY when the opener actually consumed a `that` -- "The passages show the
# Federation of Master Builders is ..." has no complementiser to strip and is left alone.
_ORPHAN_THAT = re.compile(r"([,;])(\s+)(and\s+|or\s+|but\s+)?that\s+", re.I)
# Some rationales are reporting voice in a shape the opener cannot take off cleanly ("The
# passages DO confirm the basic mechanics ... But they also contradict ..."): the verb carries
# an auxiliary, and stripping through it leaves a subject with no predicate. Detecting the
# residue is cheap and lets callers who can afford to say nothing say nothing, rather than
# print a sentence about our own retrieval to a reader who paid for a sentence about theirs.
_REPORTING_RESIDUE = re.compile(r"^(?:the\s+)?(?:passages?|sources?|retrieved)\b", re.I)


def _finding(rationale: str) -> str:
    """A check rationale as a FINDING about the buyer's market, not a note about our search.

    "" when nothing publishable survives — see `_whole_sentences`. The caller must treat that
    as "no bullet", never as an empty bullet: an empty finding that is still counted is the
    defect the heading arithmetic in `exec_summary_md` was shipping.
    """
    body = _whole_sentences(rationale)
    match = _REPORTING_OPENER.match(body)
    if not match:
        return body
    stripped = body[match.end():]
    if not stripped:
        return body
    if match.group("that"):
        stripped = _ORPHAN_THAT.sub(
            lambda m: f"{m.group(1)}{m.group(2)}{m.group(3) or ''}", stripped)
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
            # `cap_words`, never a bare slice. A hard cut here is worse than it looks: it
            # cuts mid-word, AND it destroys the untruncated source that `check_truncation`
            # needs to see the cut at all, so the linter cannot flag what this line did.
            "headline": cap_words(title, 140),
            "subhead": cap_words(one or title, 280),
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


def exec_summary_md(candidate: Any, checks: Sequence[Any] = (),
                    sources: Sequence[Any] = ()) -> str:
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

    # --- The named case, when the dossier actually holds one. ---
    #
    # The docstring above says this renderer cannot write a named case and that an invented
    # protagonist would be the worst thing the pack could contain. Both are still true. This
    # does not write one: `pack_lede.select_lede` QUOTES one, verbatim, out of a passage a
    # `supported` check already cited, and prints the URL under it.
    #
    # It sits directly under the standfirst because that is the position the 2026-08-15
    # rewrite established for the most concrete thing available, and a cited situation with a
    # named body and a number in it is more concrete than the payer description below.
    #
    # Measured 2026-08-21 over 108 pass dossiers: 19 of them (17.6%) hold a line that clears
    # every filter. The other 89 get nothing here, which is the same contract every floor in
    # this pack keeps -- an absent specific is an absent line, never a padded generic one.
    # The topic is the candidate's own words. Without it a supported check's off-subject
    # citation becomes the pack's opening sentence.
    lede = select_lede(sources, checks, " ".join(x for x in (title, one, who) if x))
    if lede:
        lines += [lede.as_markdown(), ""]

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
    #
    # AND IT SAYS SO WHEN IT IS A SUBSET (2026-08-15). The count above was made honest against
    # the list; it was still read against the STOREFRONT, which prints "6 checks cleared" over
    # the same pack. Four bullets under a heading that says four, beside a badge that says six,
    # is the same arithmetic failing one surface later. Naming the denominator costs three words
    # and turns a contradiction into a promise the rest of the pack keeps.
    if bullets:
        if len(settled) > len(bullets):
            head = f"## What we found — {len(bullets)} of the {len(settled)} things that hold up"
        else:
            noun = "thing that holds" if len(bullets) == 1 else "things that hold"
            head = f"## What we found — {len(bullets)} {noun} up"
        lines += [head, ""]
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
        #
        # A BARE QUESTION IS NOT INFORMATION (2026-08-15, founder on the live sample page).
        #
        # This shipped as three questions with nothing under them -- "Can the claims be
        # checked? / Is someone already doing this well? / Will this still be worth money
        # later?" -- which reads as three dead ends and tells the buyer only that we gave up.
        # It is also the founder's "we talk down the opportunity" in its purest form, because
        # what we actually HELD for two of those three was substantive: that retention is
        # still standard practice at the 3-5% level as of February 2025, and that the
        # incumbents we found handle applications for payment rather than retention release.
        # Both belong to the reader. "Could not settle" means the evidence did not CLOSE the
        # question, never that the search came back empty.
        #
        # The finding is printed only when `_finding` produced one in the buyer's voice.
        # A rationale that is still talking about our retrieval after that is dropped to the
        # bare question rather than published, because the alternative is a sentence about our
        # search where the reader is owed a sentence about their market.
        seen_labels: set = set()
        items: List[str] = []
        for chk in open_checks:
            label = check_label(getattr(chk, "check_name", "") or "")
            if not label or label in seen_labels:
                continue
            seen_labels.add(label)
            finding = _finding((getattr(chk, "rationale", None) or "").strip())
            if finding and not _REPORTING_RESIDUE.match(finding):
                line = f"- **{label}** {finding}"
            else:
                line = f"- **{label}**"
            if publish_pass(line):
                items.append(line)
        if items:
            lines += ["## What we could not settle", "",
                      "The evidence points, but it does not close these. What we did find is "
                      "under each one.", ""]
            lines += sorted(items)
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
    # The guarantee is ONE sentence, and the pointer is a second one. Written as a single
    # sentence it read "...that is a refund, not an argument — **Every check, in full** at the
    # end has each check with its sources", which stutters "each check" straight after a
    # section title that already contains the word: a section name is a noun phrase, and
    # splicing one mid-clause makes the sentence around it ungrammatical wherever the title
    # happens to end in a preposition or a comma.
    lines += ["---", "",
              "Every claim in this pack names the page it came from. If one of them does not "
              "say what we say it says, that is a refund, not an argument.", "",
              f"The page behind every claim is at the end, in **{QA_SECTION}**. "
              f"**{CHECKLIST_SECTION}** is where to start.", ""]
    return "\n".join(lines)


def first_week_checklist_md(candidate: Any) -> str:
    """The generic first week, for a pack `pack_checklist` could not write a specific one for.

    WHAT THIS USED TO BE, AND WHY IT CHANGED (2026-08-15)
    ----------------------------------------------------
    Six numbered lines addressed to somebody auditing the engine rather than to the person who
    paid: "Re-read the QA report kill/pass gates and list every SUPPORTED citation URL",
    "Confirm the buyer (`who_pays`) matches reality", "using only claims that survived
    claim-check", "Log what you could not verify". A snake_case schema key in a code span, our
    internal verdict words in capitals, and four of the six steps spent on our pipeline instead
    of the reader's market.

    `pack_checklist.render` was written to replace exactly this and does — for every pack it
    can describe specifically. This is what still prints when it cannot, and `exec_summary_md`
    now closes by naming this section as WHERE TO START. So the pack's opening promise pointed
    at the one surface still speaking schema.

    The ADVICE changed too, not only the vocabulary. `render` returns "" mainly when the
    dossier carries no payer — "the buyer is the spine of week one" — so this template prints
    for the packs with the LEAST established about them, and it was telling that reader to
    confirm a buyer the pack never named and then start building. A first week spent building
    on the least-verified pack in the catalogue is the wrong week. The one below spends it on
    the cheapest thing that can prove the pack wrong, which is talking to people, and it says
    plainly that stopping is a result rather than a failure.

    No other section of the pack is named here, deliberately. Naming one is how the previous
    generation of this copy broke: it sent buyers to `QA_Report.md`, a file the download had
    stopped containing, inside the first five minutes — which is when a refund gets decided.
    The two names this module can stand behind are `QA_SECTION` and `CHECKLIST_SECTION`, and
    they are pinned to `bridge._SECTION_TITLES` by test. A generic template has no business
    asserting more about a document it was reached from precisely because that document is thin.

    Claim-safe by construction: `title` and `who_pays` are the only fields interpolated, and
    nothing below asserts anything about the reader's market.
    """
    title = (getattr(candidate, "title", None) or "this opportunity").strip()
    who = (getattr(candidate, "who_pays", None) or "").strip()

    lines = [
        f"# First-week checklist — {title}",
        "",
        "Nothing in this pack is worth building on until somebody who has the problem tells "
        "you, in their own words, that they have it. That is this week: five conversations, a "
        "few hours in total, and it is the one week that can save you the year.",
        "",
    ]
    # The payer is a heading line when the dossier carries one, and FINDING them becomes the
    # week's first job when it does not. The old default printed "the stated buyer" — filler
    # standing exactly where the reader needed a name, inside the document that prints
    # precisely when no name exists.
    if who:
        lines += [f"**Who you are looking for:** {as_phrase(who)}", ""]
    else:
        lines += [
            "**Start by naming who you are looking for.** This pack could not settle it, which "
            "is the honest reason you are reading the general plan and not a specific one. "
            "Write down the narrowest group you can describe well enough to go and find five "
            "of them by Wednesday. Narrow is not a limitation here; it is the only thing that "
            "makes the rest of the week possible.",
            "",
        ]
    lines += [
        "## Monday and Tuesday — write down what you would be wrong about",
        "",
        "1. In one sentence, in their words rather than ours, write the problem you believe "
        "these people have. If you cannot write it without reusing the title above, you do not "
        "understand it yet — and day one is a good time to find that out.",
        "2. Underneath it, write the single fact that would make this a bad idea. You are going "
        "looking for that fact this week, not for encouragement. It is far cheaper to find now "
        "than in month six.",
        "",
        "## Wednesday to Friday — five conversations",
        "",
        "3. Find five people who fit the description and ask each of them how they handle this "
        "today. Not whether they would buy something — what they actually do on a Tuesday "
        "morning, and what it costs them to do it.",
        "4. Listen for what they already pay for: a tool, somebody's hours, a workaround they "
        "built themselves. Money already moving is the only evidence of demand that costs you "
        "nothing to collect, and it is worth more than any answer to a hypothetical.",
        "5. Ask each one what would have to be true before they changed it. Write the answers "
        "down word for word. That phrasing is your first outreach copy, and it will be better "
        "than anything you would have written for yourself.",
        "",
        "## Friday — decide, and be willing to stop",
        "",
        "6. If nobody named a cost, in money or in hours, stop here. That is a real result and "
        "it cost you a week instead of a year. The pack has done its job.",
        "7. If two or more of them described the same workaround, you have found the thing to "
        "build. Week two is one page and one price, offered to those same five people first — "
        "not a product, an offer. The rest of this pack is the long version of what to do once "
        "one of them says yes.",
        "",
    ]
    return "\n".join(lines)


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
