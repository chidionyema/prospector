"""What each marketing asset IS, in one place: its reader, its heading, and its shape.

Why this module exists (2026-08-14, founder read `8d5e24fbe6c1f5d3`): the section headed
**Launch Email** contained a product description and the section headed **Listing Page**
opened with `Subject:`. That reads as swapped labels. It was worse than swapped — the labels
were arbitrary. `prompts/content_gen.md` carried the line

    Type: {one of: listing_page | teaser_social | seo_preview | launch_email}

which is not a placeholder. `prompts.render` substitutes by literal `str.replace` of
`{type}`, so nothing was replaced: all four threads sent an IDENTICAL prompt, and
`artifacts._gen_one_content` stamped `{"type": t}` onto whichever draft came back. Four
drafts of the same paragraph, labelled in the order the threads were submitted.

Measured over the 557 dossiers on disk carrying marketing at that date: 177 of 177
`launch_email` pieces contained no `Subject:` line, i.e. not one email in the corpus was
shaped like an email; 19 dossiers carried a piece selling OUR pack ("opportunity pack",
"open the pack") where the buyer needed launch copy for THEIR business.

Type semantics live here, not in the prompt and not in the renderer, because three places
consume them — the generator (`artifacts.generate_content`), the pack renderer
(`bridge._add_to_zip` for `Marketing_Assets.md`) and the gate (`pack_linter.check_marketing`)
— and a heading that disagrees with the gate that grades it is how this defect stayed
invisible for 62 packs.
"""
from __future__ import annotations

import re
from typing import Dict, Tuple

#: Generation order, and the order the pack renders them in.
ASSET_TYPES: Tuple[str, ...] = (
    "listing_page", "teaser_social", "seo_preview", "launch_email",
)

#: The three pieces written AS THE BUSINESS, to the business's own customers. The
#: `listing_page` is the odd one out: it is our storefront copy, addressed to the person
#: buying the pack, and it is the only piece that may mention the pack at all.
BUSINESS_VOICE_TYPES = frozenset({"teaser_social", "seo_preview", "launch_email"})

#: type -> (buyer-facing heading, the line under it saying who it is for).
#: The old heading was `type.replace("_", " ").title()`, which shipped "Seo Preview" — our
#: internal enum, title-cased, in a £49.99 product — and told the reader nothing about who
#: the copy underneath was written for, which is the one fact that makes it usable.
LABELS: Dict[str, Tuple[str, str]] = {
    "listing_page": (
        "How to describe this to someone",
        "The pitch in plain words. Use it on a landing page, or when someone asks what "
        "you are building.",
    ),
    "teaser_social": (
        "Launch post",
        "Written as the business, for the people who would buy from it. Post it the day "
        "you open.",
    ),
    "seo_preview": (
        "Search listing",
        "The page title and the line under it that a search result shows. Written in the "
        "words a customer would type.",
    ),
    "launch_email": (
        "Launch email",
        "From the business to its first customers. Subject line included.",
    ),
}


def heading_for(asset_type: str) -> Tuple[str, str]:
    """Heading and audience line for an asset type; falls back without inventing a reader."""
    label = LABELS.get(str(asset_type or "").strip().lower())
    if label:
        return label
    pretty = str(asset_type or "asset").replace("_", " ").strip().title() or "Asset"
    return pretty, ""


#: Copy that is selling OUR product instead of the buyer's. Every phrase here is one a
#: business's own customer could never be the reader of. Deliberately narrow: "pack" alone
#: matches businesses that genuinely sell packs (a "launch pack for NHS nurses" is a real
#: candidate on the catalogue), and a gate that fires on those would be teaching the
#: generator to avoid a legitimate word.
PACK_VOICE_RE = re.compile(
    r"opportunity pack"
    r"|open the pack"
    r"|inside (?:this|the) pack"
    r"|this pack (?:shows|gives|contains|includes|is)"
    r"|(?:this|here) is the plan for"
    r"|the (?:verified )?evidence (?:behind|in) (?:this|the) (?:pack|idea|opportunity)",
    re.IGNORECASE,
)

#: An email that does not start with a subject line is not an email. Anchored to the first
#: non-blank line: `Subject:` buried in paragraph three is prose about an email.
SUBJECT_RE = re.compile(r"^\s*subject\s*:", re.IGNORECASE)


def has_subject_line(copy: str) -> bool:
    return bool(SUBJECT_RE.match(str(copy or "").lstrip()))
