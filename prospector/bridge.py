"""
EngineBridge — Connects Prospector PASS to the Store API and payment provider.
Ships the £30 bundle (zip), provisions the product with the active payment provider
(Paddle or Stripe), and updates the Catalog.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Protocol, Tuple
from urllib.parse import urlparse

import requests

from . import facet_derive, indexnow
from . import facets as facets_mod
from .archive import archive_sources
from .copy_lint import buyer_readable, is_prose_artifact
from .marketing_assets import heading_for
from .models import Decision, Dossier, ScoreResult
from .pack_linter import TITLE_BLOCK_ON_BREACH_DEFAULT, lint_pack
from .pack_validation import validate_pack

# Aliased on import: `EngineBridge.publish_pass` below is the whole publish ROUTINE (upload,
# price, list), and two unrelated things called `publish_pass` in one file is how a reader ends
# up misreading both. `prose_pass` is the text gate; `publish_pass` is the money rail.
from .plain_text import nodash, plain_lines, to_plain_text
from .plain_text import publish_pass as prose_pass
from .plain_text import publish_pass_document as prose_pass_document
from .price_comparables import anchors_from_tags
from .price_rationale import write_rationale
from .pricing import price_for

logger = logging.getLogger("prospector.bridge")


def listing_gate(*, uploaded: bool, pack_complete: bool, priced: bool,
                 bundle_complete: bool, lint_ok: bool,
                 figures_verified: bool = True) -> bool:
    """The single AND that decides sellability. Each operand is an independent fence
    computed in publish_pass (upload, completeness, price, bundle audit, content lint);
    keeping the composition in one named function makes the seam testable without the
    whole publish machinery.

    `figures_verified` is the §33 figure fence (item 33-D/33-G) and defaults to True — i.e. OFF —
    because barring untraceable packs is a revenue action on up to 30% of the catalogue and is the
    founder's decision, not the engine's. `publish_pass` computes it only when
    `config.yaml listing.require_figure_verification` is on; see `human_review.py`."""
    return bool(uploaded and pack_complete and priced and bundle_complete and lint_ok
                and figures_verified)


# ---------------------------------------------------------------------------
# Catalog metadata extraction — turns the generated pack into the per-pack data the
# storefront needs to sell each pack specifically (sample excerpt, proof point, economics
# teaser, trust signals) instead of generic chips. All extraction, no new generation.
# ---------------------------------------------------------------------------

def _card_field(raw: Any) -> str:
    """Markdown-strip, publish-pass, then house-normalise one single-line catalogue field.

    Three gates, in this order and all mandatory. `to_plain_text` takes the markup off (the
    storefront has no markdown parser). `prose_pass` takes off what was never meant to be
    published at all: passage ids, empty citation markers, raw confidence floats and the
    register denylist — see prospector/plain_text.py for the measured defect classes.

    `nodash` runs HERE, before the caller's [:140]/[:280] slice, for two reasons. The slice
    must count the characters that actually ship — an em-dash becomes ", ", so normalising
    after it can push a capped field one character past its cap. And the pack lint reads
    these values: grading a field the storefront never receives is what unlisted two live
    packs on 2026-08-08 (13d41ccee9e96e2d, 3e72d5a5f1a60068) for an em-dash in `headline`
    that `_normalise_catalog_payload` had already removed by the time the row was written.
    The same title passed the same check as `title` (normalised at its call site, :832) and
    failed as `headline` (not) — one string, two verdicts. `_update_catalog`'s choke point
    still runs and `nodash` is idempotent, so it remains the backstop for every field that
    does not come through here.

    `sentences=False` deliberately: a card line or a headline legitimately ends on a noun, and
    the strict form would empty the whole shelf. It still repairs a TRUNCATED field, and
    returns "" when nothing publishable survives so the caller can omit it and fall back.
    """
    return nodash(prose_pass(to_plain_text(raw, collapse=True)))


def _cap_words(text: str, cap: int) -> str:
    """Cap a single-line catalogue field at `cap` chars WITHOUT cutting a word in half.

    A bare `text[:cap]` ends wherever the cap happens to land. On 2026-08-08 that shipped a
    subhead ending "to a true hourly wag" (pack 8ce5270ade208070). `check_truncation`
    (pack_linter.py:229) is built to catch precisely that shape — `len(final) == cap` with a
    word character on both sides of the cut — so a hard slice does not merely read badly, it
    is GUARANTEED to unlist the pack. `cardLine` above takes the stricter route this repo
    prefers, drop rather than truncate, because the card can fall back to the pack title.
    `headline` and `subhead` have no fallback, so the better failure is a clean short line.

    Cut back to the last word boundary and drop the punctuation the cut exposes. A single
    token longer than the whole cap has no boundary to retreat to; it keeps the hard slice and
    stays visible to the linter rather than being silently disguised.
    """
    t = (text or "").strip()
    if len(t) <= cap:
        return t
    head = t[:cap]
    cut = head.rfind(" ")
    if cut <= 0:
        return head
    return head[:cut].rstrip(" ,;:")


# Catalogue keys that are IDENTIFIERS, ENUMS or NUMBERS rather than prose. They pass
# through the choke point untouched.
#
# `nodash` would in fact leave most of them unchanged — it only rewrites em/en-dashes,
# digit ranges and space-surrounded hyphens, none of which occur in a Stripe price id or a
# hex hash. But the money rail is the wrong place to depend on "in fact": `providerPriceId`
# and `contentHash` are read by the fulfilment fence, and a normaliser that ever altered
# one would charge a buyer and then refuse delivery (see `_update_catalog`'s docstring).
# Excluding them by name makes that impossible rather than merely unlikely.
_NON_PROSE_CATALOG_KEYS = frozenset({
    "id", "dossierRef", "paymentProvider", "providerProductId", "providerPriceId",
    "isListed", "pricePence", "contentKey", "contentHash", "contentVersion",
    "verifiedAt", "market", "effortTag", "automatability", "segment", "rung",
    "priceRung", "priceSegment", "sourceUrl", "url",
})


def _normalise_catalog_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Apply the house copy rule to every engine-authored string in the catalogue payload.

    THIS IS A CHOKE POINT, AND THAT IS THE WHOLE POINT. The defect it closes was not a
    missing `nodash()` call — it was that normalisation lived at each call site, so the one
    buyer-facing field that didn't come through `_card_field` (`title`) silently carried
    71 em/en-dashes into 68 of 72 live listings against a standing rule that the catalogue
    carries none. Measured control: 15 raw one_liners contained a dash and 0 published ones
    did, proving the normaliser works; 73 raw titles contained one and 71 published ones
    did, proving title never reached it.

    A per-field rule is correct only while every future contributor remembers it. A choke
    point is correct by construction: a field added to `payload` or to `metadata` tomorrow
    is covered without anyone deciding to cover it.
    """
    def norm(value: Any) -> Any:
        if isinstance(value, str):
            return nodash(value)
        if isinstance(value, list):
            return [norm(v) for v in value]
        if isinstance(value, dict):
            return {k: (v if k in _NON_PROSE_CATALOG_KEYS else norm(v))
                    for k, v in value.items()}
        return value

    return {k: (v if k in _NON_PROSE_CATALOG_KEYS else norm(v))
            for k, v in payload.items()}


# A line is "cited" if it carries a source marker or a year alongside a number — safe to show
# pre-purchase because it demonstrates the research is real without revealing the how-to.
_CITED_RE = re.compile(r"\(source\b|https?://|\b20\d\d\b", re.IGNORECASE)
# These three parse the document `artifacts._render_financial_model` writes, so they are one
# half of a two-sided contract with a renderer in another module, and each carries the
# pre-2026-08-14 header as well as the plain-speech one that replaced it. A snapshot is the
# headline economics shown BEFORE purchase and it fails by returning {} — so a regex that
# silently stopped matching would blank the teaser on every new pack with nothing going red,
# while every pack already on the shelf still carries the old headers.
# `tests/unit/test_pack_render_defects.py` renders and then parses, so a heading change
# cannot quietly empty the snapshot again.
#
# The currency class is `[£$€]`, not a hardcoded £: until 2026-08-14 it was the pound alone,
# which is why no US pack ever carried a month-1 revenue on the storefront.
_MONEY_RE = re.compile(r"\*\*Month 1:\*\*.*?=\s*\*\*([£$€][\d,]+)\*\*")
_LTV_RE = re.compile(
    r"(?:LTV:CAC Ratio|Worth against cost)\s*\n\s*-\s*\*\*([\d.]+×)\*\*")
# Payback moved from a section of its own into a bullet under "What it costs to win a …",
# so the new form is matched on the bullet alone. The derived branch prints one decimal
# (`{cac / margin_per_unit:.1f}`), which the old integer-only capture would have truncated.
_PAYBACK_RE = re.compile(
    r"(?:Payback Period\s*\n\s*-\s*\*\*~?([\d.]+)\s*months?\*\*"
    r"|\*\*Paid back in:\s*~?([\d.]+)\s*months?\*\*)")


def _sample_excerpts(build_spec: str, proof_point: str, max_items: int = 3) -> List[str]:
    """A safe pre-purchase 'look inside': verbatim cited lines mined from the Blueprint, with
    the claim-checked proof_point as a backstop when the Blueprint yields too few. Shows what
    the research looks like, never the build steps (the how-to is the paid product)."""
    out: List[str] = []
    for raw in re.split(r"(?<=[.!?])\s+|\n", build_spec or ""):
        # Detect on the RAW line (a citation may be a markdown link), emit the plain-text
        # form — the storefront prints these verbatim, so leftover `**` reaches the buyer.
        # keep_link_urls preserves the cited target, which is the whole point of an excerpt.
        if not _CITED_RE.search(raw):
            continue
        line = to_plain_text(raw, collapse=True, keep_link_urls=True)
        if not (40 <= len(line) <= 320):
            continue
        if any(ch.isdigit() for ch in line) and line not in out:
            out.append(line)
        if len(out) >= max_items:
            break
    proof = to_plain_text(proof_point, collapse=True)
    if len(out) < 2 and proof and proof not in out:
        out.append(proof)
    return out[:max_items]


#: The one key the storefront's card ladder can actually lead with. `Store.Web
#: src/lib/packStat.ts` ranks month-1 revenue against the pack's own price to print a
#: price-back multiple, and falls through to the cited source count when it cannot. `ltvCac`
#: and `paybackMonths` are deliberately NOT in this set: the founder deleted both from the
#: product page on 2026-08-13 as engine language, so their presence does not save a card.
_SNAPSHOT_LEAD_KEY = "month1Revenue"


def _snapshot_gap(snapshot: Optional[Dict[str, str]]) -> Optional[str]:
    """Why this pack's card cannot lead with a number, or None if it can.

    Extracted as a pure function so the condition is testable without standing up a publish.

    THE FAILURE THIS EXISTS TO CATCH. `_financial_snapshot` is REGEX extraction over rendered
    prose and returns `{}` on anything it does not recognise — by design, since inventing a
    figure is worse. But the publish path then drops empty values from the payload before it is
    sent, so an unparsed model left no trace anywhere: the pack listed, the API stored nothing,
    the card silently fell back to its source count, and no test went red. Measured against
    production on 2026-08-14, 4 of 59 live packs carried no snapshot at all and 18 more carried
    one with no `month1Revenue` — 22 of 59 cards leading with the same class of fact, none of it
    reported at publish time.

    It returns a REASON rather than a bool because the two gaps have different fixes: nothing
    parsed at all points at the financial model's shape, a partial parse points at the money
    regex. A caller that only needs a yes/no can still test truthiness.
    """
    if not snapshot:
        return "no financial snapshot parsed from the model at all"
    if not snapshot.get(_SNAPSHOT_LEAD_KEY):
        return (f"snapshot parsed {sorted(snapshot)} but no {_SNAPSHOT_LEAD_KEY}")
    return None


def _financial_snapshot(fin_text: str) -> Dict[str, str]:
    """Pull the Python-computed headline economics (Month 1 revenue, LTV:CAC, payback) from
    the rendered financial model. These are arithmetically exact, so they are safe to surface
    pre-purchase as a credible teaser. Returns {} when the model is sparse/unparseable."""
    t = fin_text or ""
    snap: Dict[str, str] = {}
    m = _MONEY_RE.search(t)
    if m:
        snap["month1Revenue"] = m.group(1)
    m = _LTV_RE.search(t)
    if m:
        snap["ltvCac"] = m.group(1)
    m = _PAYBACK_RE.search(t)
    if m:
        # Two alternations, so exactly one group carries the figure: legacy header form
        # first, plain-speech bullet second.
        snap["paybackMonths"] = f"{m.group(1) or m.group(2)} months"
    return snap


# Every file a complete bundle must contain. Asserted after the zip is written, so a
# structurally incomplete pack fails loudly at build time instead of at a buyer's download.
#
# 120 bytes is a deliberately low bar: it catches the header-only class of failure (the
# 20-byte "# Marketing Assets\n\n") without second-guessing `validate_pack`, which remains the
# real sellability gate. The claim-safe financial-model stub is ~150 bytes and must pass.
_MIN_BUNDLE_ENTRY_BYTES = 120

# The documents the engine COMPOSES. Until 2026-08-15 this tuple was `BUNDLE_FILES` and each
# entry was also a zip entry; the founder's brief killed that — "i dont like md files at all,
# we are not selling to developers". These are now the render INPUT and nothing else: the
# reader (`index.html`), the typeset edition (`Complete_Pack.pdf`) and the machine index all
# draw their sections from here, and none of them reaches the buyer as markdown.
#
# Deleting them from the archive costs a buyer nothing readable, and that is measured, not
# assumed: across a 12-pack sample, 0 of 853 headings, 0 of 208 table cells and 0 of 6,743
# prose runs of eight words or more were absent from `index.html`
# (docs/HANDOFF_PACK_CONTENTS_REVIEW.md). The one thing markdown carried that a rendered page
# does not is EDITABILITY, and that is why `Marketing_Assets.txt` exists below — the marketing
# copy is the document a buyer pastes elsewhere, so it keeps a plain-text form.
PACK_DOCUMENTS = (
    "00_Executive_Summary.md",
    "01_Blueprint_BuildSpec.md",
    "02_Marketing_Plan_GTM.md",
    "03_Operations_Plan.md",
    "04_Financial_Model.md",
    "05_First_Week_Checklist.md",
    "Marketing_Assets.md",
    "QA_Report.md",
)

# Every file a complete bundle must contain — the sellability contract, drift-tested against
# the storefront's PackContents.tsx.
#
# What changed on 2026-08-15: this tuple used to name the eight markdown documents, and the
# rendered artefacts sat in BUNDLE_BONUS_FILES where a missing one could not block a listing.
# That was the right shape while the renderers were new and unproven. They are no longer
# unproven: all 59 live packs carry index.html, Complete_Pack.pdf, First_Fortnight.html and
# Assumptions.csv (measured against the objects R2 actually serves, NOT against
# publish/bundles/ — see memory `publish-bundles-is-not-the-shelf`). So the rendered pack is
# now the product and the contract says so.
#
# The consequence is deliberate and is the point of the change: if the PDF fails to render,
# the pack does not list. Previously it listed anyway, silently short. `audit_bundle` is what
# enforces that, and the renderers stay individually guarded so a fault is a WARNING plus an
# unlisted pack rather than an exception on the retry path.
BUNDLE_FILES = (
    "index.html",            # the reader — every document above, in reading order
    "Complete_Pack.pdf",     # the typeset edition (pack_pdf.FILENAME)
    "First_Fortnight.html",  # the one printable page (pack_card.FILENAME)
    "Assumptions.csv",       # the assumptions register a spreadsheet opens (pack_table.FILENAME)
    "Marketing_Assets.txt",  # the one document a buyer EDITS, so it stays plain text
)

# Files a bundle MAY additionally contain. Bonus, never contract: a missing one must not block a
# listing, which is exactly why they sit outside BUNDLE_FILES and outside `audit_bundle`.
#
# The registry exists because that deliberate blindness went unmeasured for months. `audit_bundle`
# iterates BUNDLE_FILES asking "did it arrive?", so an entry in NEITHER list is invisible to it by
# construction — and `tests/unit/test_bundle_index_html.py` pins that blindness on purpose. Nothing
# ever compared the written archive against what the shop says is inside it, so the storefront read
# "8 files" while (measured 2026-08-08, 45 live packs) 33 bundles held nine entries or ten.
#
# Declaring them converts a silent extra into a failing test: `undeclared_bundle_entries` names
# anything shipped that neither list claims, so adding a third bonus file forces a decision about
# the buyer-facing count instead of quietly making it false again.
#
# "manifest.jsonld" is duplicated from `pack_manifest.MANIFEST_FILENAME` rather than imported —
# pack_manifest is imported lazily inside `_create_bundle` to keep this module's import graph flat,
# and a module-level import here would reverse that. The duplication is pinned by
# `tests/unit/test_bundle_declared_entries.py`, so it cannot drift silently.
BUNDLE_BONUS_FILES = (
    "manifest.jsonld",               # the machine-readable half (pack_manifest.MANIFEST_FILENAME)
)

# Reading order for the in-bundle reader. `Evidence_and_Constraints.md` is composed like the
# eight above but is not one of them, and it has a place in the read: immediately before the QA
# report — the two evidence documents together, after the plans that apply them. Defined once
# here because the generator and `tools/backfill_bundle_html.py` both order the reader, and two
# orderings is how a backfilled pack comes to open on a different page from a freshly
# generated one.
#
# Derived from PACK_DOCUMENTS, not from BUNDLE_FILES: since 2026-08-15 those are different
# lists — one is what the pack SAYS, the other is what the archive HOLDS.
BUNDLE_READING_ORDER = tuple(
    x for name in PACK_DOCUMENTS
    for x in (("Evidence_and_Constraints.md", name) if name == "QA_Report.md" else (name,))
)

# Human-readable section titles for the in-bundle index.html reading experience
# (see pack_html.py). Mirrors the `title` field of store_platform's PackContents.tsx for the
# same filenames — kept as a plain dict rather than imported (that file is TypeScript); a
# drift between the two is cosmetic (both label the same file) and NOT the sellability
# drift the BUNDLE_FILES/PackContents pairing's own test guards, so it isn't pinned here.
_SECTION_TITLES = {
    "00_Executive_Summary.md": "Executive Summary",
    "01_Blueprint_BuildSpec.md": "The Blueprint (Build Spec)",
    "02_Marketing_Plan_GTM.md": "The Go-To-Market Plan",
    "03_Operations_Plan.md": "The Operations Plan",
    "04_Financial_Model.md": "The Financial Model",
    "05_First_Week_Checklist.md": "First-Week Checklist",
    "Marketing_Assets.md": "Marketing Assets",
    "Evidence_and_Constraints.md": "Evidence and Constraints",
    "QA_Report.md": "The QA Report, with the receipts",
}

# Titles for the ARCHIVE entries, which since 2026-08-15 are a different list from the
# documents above. `manifest.jsonld` describes the zip, so it needs a name for each thing the
# zip actually holds; `_SECTION_TITLES` names the sections INSIDE the reader and cannot serve
# both jobs without one of them being wrong.
_FILE_TITLES = {
    "index.html": "The pack, readable",
    "Complete_Pack.pdf": "The pack, typeset for print",
    "First_Fortnight.html": "Your first fortnight, on one page",
    "Assumptions.csv": "Every assumption, as a spreadsheet",
    "Marketing_Assets.txt": "Marketing copy, ready to paste",
    "manifest.jsonld": "Machine-readable index",
}


def audit_bundle(zip_path: str) -> tuple[list[str], list[str]]:
    """Structural audit of a written bundle: ``(missing, stubs)``, both empty when complete.

    Reads the artefact we actually wrote rather than the inputs we think we passed. That
    distinction is the whole point: ``validate_pack`` inspects the in-memory artifacts and
    marketing dicts, so it cannot see a file that failed to reach the zip. A pack could — and
    did — clear ``validate_pack`` and still ship three files, one of them a 20-byte header.

    Unreadable or absent zip counts as wholly missing rather than raising: the caller uses this
    to decide whether a pack may be LISTED, and an audit that throws would take down the
    register-unlisted retry path it exists to protect.
    """
    try:
        with zipfile.ZipFile(zip_path) as check:
            written = {i.filename: i.file_size for i in check.infolist()}
    except (OSError, zipfile.BadZipFile):
        return list(BUNDLE_FILES), []
    missing = [f for f in BUNDLE_FILES if f not in written]
    stubs = [
        f"{f}={written[f]}b"
        for f in BUNDLE_FILES
        if f in written and written[f] < _MIN_BUNDLE_ENTRY_BYTES
    ]
    return missing, stubs


def undeclared_bundle_entries(zip_path: str) -> list[str]:
    """Entries a written bundle contains that neither BUNDLE_FILES nor BUNDLE_BONUS_FILES claims.

    `audit_bundle` cannot answer this and is not meant to: it iterates BUNDLE_FILES asking "did it
    arrive?", so anything in neither list is invisible to it. This function iterates the ARCHIVE
    instead — the only direction in which an unexpected file can be seen at all.

    Sorted names, so a log line is stable; empty means every entry is a promised deliverable or a
    declared bonus.

    Deliberately NOT wired into `is_listed`. An extra file is a claim problem (the storefront may
    be counting wrong), never a fulfilment defect: the buyer received everything promised plus
    more. Delisting a complete, paid pack over a surplus file would be a worse failure than the
    inaccuracy it protects against, so this informs a human and a test, and gates nothing.

    An unreadable or absent zip yields [] rather than raising, matching `audit_bundle`'s contract:
    this runs on the register-unlisted retry path, and a diagnostic that throws takes down the
    thing it exists to observe. "Missing zip" is already `audit_bundle`'s answer to give.
    """
    try:
        with zipfile.ZipFile(zip_path) as check:
            names = [i.filename for i in check.infolist()]
    except (OSError, zipfile.BadZipFile):
        return []
    declared = set(BUNDLE_FILES) | set(BUNDLE_BONUS_FILES)
    return sorted(n for n in names if n not in declared)


def _held_back_md(artifact_label: str) -> str:
    """Placeholder for an artifact that generation failed to produce.

    Claim-safe by construction: it states an absence and invents nothing. A pack containing
    one of these cannot pass `validate_pack`, so it is registered UNLISTED and never sold.
    """
    return (
        f"# {artifact_label} — not generated\n\n"
        "Generation did not return this document, so there is nothing to show here. "
        "Prospector does not substitute invented content for a missing artifact.\n\n"
        "This pack therefore fails the completeness gate and is held back from sale until "
        "the document is regenerated.\n"
    )


def _source_count(dossier: Dossier) -> int:
    """The one definition of "how many sources this pack cites".

    Two things read it and they must never disagree: the ``sourceCount`` the buyer sees on
    the row, and — since 2026-08-15 — the rung that number prices the pack at
    (``pricing.price_for``). A price justified by a count the page does not show is exactly
    the un-intuitable pricing the depth ladder exists to end, so both callers come through
    here rather than each writing ``len(dossier.all_sources)`` and drifting later.
    """
    return len(dossier.all_sources)


def _trust_fields(dossier: Dossier) -> Dict[str, Any]:
    """Trust signals from the moat-verified dossier: how many checks cleared and how many
    distinct sources were cited. This is real, not a marketing number."""
    checks = dossier.checks or []
    total = len(checks)
    cleared = sum(1 for c in checks if c.verdict.value in ("supported", "unverifiable"))
    sources = _source_count(dossier)
    out: Dict[str, Any] = {"sourceCount": sources}
    if total:
        out["qaVerdictSummary"] = f"{cleared}/{total} checks cleared · {sources} sources cited"
    return out


def _validate_store_api_url(url: str) -> str:
    """Refuse a STORE_API_URL that points anywhere dangerous before we ever forward the
    internal/entitlements keys to it (SSRF + credential-leak guard). Allows ordinary http(s)
    hosts (localhost in dev, the private or public store host in prod) but rejects the cloud
    metadata address and other link-local/unspecified/reserved targets. Fail closed: a
    misconfigured URL raises here and stops the publish rather than leaking secrets."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"STORE_API_URL must be http(s), got '{parsed.scheme or url}'")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("STORE_API_URL has no host")
    if "metadata" in host:
        raise ValueError(f"STORE_API_URL host looks like a metadata endpoint: {host}")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None  # a hostname, not a literal IP — allowed
    if ip is not None and (ip.is_link_local or ip.is_unspecified
                           or ip.is_multicast or ip.is_reserved):
        raise ValueError(f"STORE_API_URL points at a disallowed address: {host}")
    return url


class ProvisioningError(Exception):
    """A payment provider rejected product/price provisioning. Raised instead of letting a
    raw provider-SDK exception leak to the publish path, so callers get a stable, domain-level
    failure to handle."""


class ExistingPrice(NamedTuple):
    """A price object that already exists at the provider, as the PROVIDER reports it.

    Not as the catalogue remembers it: the whole point of looking it up is that the two can
    disagree, and the provider is the one that actually charges the card.
    """
    product_id: str
    amount_pence: int
    currency: str


class ProductProvisioner(Protocol):
    """Provider-agnostic product provisioning. Implementations: PaddleClient, StripeProvisioner."""
    def create_product(self, name: str, description: str, metadata: Dict[str, str]) -> str:
        """Returns the provider's product ID."""
        ...

    def create_price(self, product_id: str, amount_pence: int, currency: str,
                     usd_cents: Optional[int] = None) -> str:
        """Returns the provider's price ID.

        `usd_cents` asks for the SAME price object to also be billable in US dollars at a
        declared amount (never a converted one). Optional with a None default so an
        implementation that cannot do it — or a caller that has no USD rung — is unchanged.
        """
        ...

    def describe_price(self, price_id: str) -> Optional[ExistingPrice]:
        """Resolve an already-minted price. None when it cannot be established.

        This is what makes a republish safe. `create_*` is idempotent only inside the
        provider's idempotency window (Stripe: 24 hours), so a pack republished weeks after
        it first went live mints a BRAND NEW product and price — see `_resolve_money_rail`.
        """
        ...

class EngineBridge:
    def __init__(self, cfg: Any):
        self.cfg = cfg
        # Store API settings
        self.store_api_url = _validate_store_api_url(
            os.environ.get("STORE_API_URL", "http://localhost:5291"))
        # No default: a committed fallback key in a public repo is a credential anyone can
        # use. Unset -> None, and _update_catalog refuses to publish (fail-closed), mirroring
        # the Store's own 503-when-unconfigured behaviour.
        self.internal_api_key = os.environ.get("STORE_INTERNAL_API_KEY")

        # Entitlements API key: use config value (which reads from config.yaml or
        # PROSPECTOR_ENTITLEMENTS_API_KEY env var). Empty = fail-closed.
        self.entitlements_api_key = getattr(cfg, "entitlements_api_key", "")

        # Active provider selection (config-driven, matches .NET MoneyRailConfigGate)
        self.active_provider = getattr(cfg, "store_payments", {}).get("active_provider", "paddle") if hasattr(cfg, "store_payments") else \
            os.environ.get("PAYMENTS_ACTIVE_PROVIDER", "paddle")

        # Paddle settings (kept for backward compat + fallback)
        self.paddle_api_key = os.environ.get("PADDLE_API_KEY")
        self.paddle_env = os.environ.get("PADDLE_ENVIRONMENT", "sandbox")
        self.paddle = PaddleClient(self.paddle_api_key, self.paddle_env) if self.paddle_api_key else None

        # Stripe settings. The key must belong to the SAME Stripe account the deployed Store
        # bills through: a price minted anywhere else does not exist as far as checkout is
        # concerned, so the pack lists and every buy button returns HTTP 500. That is not
        # hypothetical — on 2026-07-31 `STRIPE_API_KEY` was a sandbox test key while the Store
        # billed live, and 10 packs went on sale unbuyable. Mode is the part we can check here;
        # the Store verifies the price is truly billable before it will list it.
        self.stripe_api_key, self.stripe_key_reason = self._select_stripe_key()
        self.stripe = StripeProvisioner(self.stripe_api_key) if self.stripe_api_key else None

        # Content storage (Cloudflare R2, S3-compatible). The deliverable must live here
        # before a pack may be listed — selling something we can't deliver is forbidden.
        self.r2 = R2Uploader()

    @staticmethod
    def _store_is_local(url: str) -> bool:
        """True when the catalogue we publish into is a developer's own machine."""
        host = (urlparse(url).hostname or "").lower()
        return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local")

    def _select_stripe_key(self) -> tuple[Optional[str], str]:
        """The Stripe key whose mode matches the catalogue being published into.

        A remote catalogue is a real shopfront and may only be priced with a live key. Picking
        the key by target — rather than reading one fixed env var and hoping it matches — is
        what stops a sandbox key from minting prices the deployed Store cannot bill. Returning
        None on a mismatch is deliberate: `provisioner` then yields None, the `priced` guard
        below refuses to list, and the pack is published UNLISTED instead of unbuyable.
        """
        live_key = os.environ.get("STRIPE_LIVE_API_KEY")
        generic = os.environ.get("STRIPE_API_KEY")

        if self._store_is_local(self.store_api_url):
            # A local store bills through whatever the operator configured; a test key here is
            # the normal case, not a fault.
            chosen = generic or live_key
            return chosen, "local store — any key mode accepted"

        for name, key in (("STRIPE_LIVE_API_KEY", live_key), ("STRIPE_API_KEY", generic)):
            if key and "_live_" in key:
                return key, f"{name} (live) for remote catalogue {self.store_api_url}"

        held = [n for n, k in (("STRIPE_LIVE_API_KEY", live_key), ("STRIPE_API_KEY", generic)) if k]
        return None, (
            f"refusing to price the remote catalogue {self.store_api_url} without a live key; "
            f"keys held: {held or 'none'} (a test-mode price cannot be billed by the live Store)"
        )

    @property
    def provisioner(self) -> Optional[ProductProvisioner]:
        """Returns the active product provisioner, or None if unconfigured."""
        if self.active_provider == "stripe":
            return self.stripe
        return self.paddle

    def publish_pass(self, dossier: Dossier, *, dry_run: bool = False) -> bool:
        """
        Execute Phase 2 of the Build Plan:
        PASS -> zip bundle -> Paddle API (Product/Price/Upload) -> Store API (Catalog).

        ``dry_run=True`` runs every DETERMINISTIC gate — the guards above, the zip build,
        ``validate_pack``, ``audit_bundle`` and ``lint_pack`` — writes the usual
        ``<id>.lint.json`` receipt, and then returns ``content_ok`` WITHOUT minting a
        provider object, uploading the zip, or touching the catalogue.

        Why this exists. A pack that will not sell is blocked by one of those gates, but
        the verdict was only ever produced as a side effect of a real publish, so the
        reason stayed invisible unless you were willing to run the money rail: on
        2026-08-09, 9 of the 17 republishable PASS dossiers had no lint receipt at all and
        their blocker was simply unknown. Asking "why is this pack not selling?" must not
        cost a Stripe object. It can only ever do LESS than a publish — there is no branch
        below that a dry run reaches and a real publish does not.

        The one network call a dry run still makes is ``entitlements_check`` (:1124), a
        POST that creates nothing and only answers whether this engine may publish at all.
        It stays IN on purpose: a rehearsal that skipped it would be clean on a route the
        real publish can fail.
        """
        if dossier.decision != Decision.PASS:
            logger.warning(f"EngineBridge: Skipping non-PASS dossier {dossier.candidate.candidate_id}")
            return False

        # PROVISIONAL GUARD (P0 — trust-critical): a dossier whose ruling was served by
        # the cheap emergency fallback tail (moat exhausted) is stamped provisional=true.
        # A provisional PASS is a real-but-untrusted decision: the candidate may be valid,
        # but the ruling was made by a model that is NOT cleared to decide truth in the
        # moat. Refuse publication; auto re-vet by the trusted moat on `vet --resume`.
        if getattr(dossier, "provisional", False):
            logger.warning(
                f"EngineBridge: Refusing to publish provisional dossier "
                f"{dossier.candidate.candidate_id} ({dossier.candidate.title}) — "
                "ruled by emergency fallback brain; must re-vet before publishing.",
                extra={"candidate_id": dossier.candidate.candidate_id, "provisional": True},
            )
            return False

        # SOURCE-OR-DIE GUARD (P0 — moat integrity, last-mile backstop): a PASS dossier must
        # rest on actual grounded evidence. The decision layer (dossier.py) now enforces this,
        # but a dossier minted BEFORE that fix — or hand-fed via tools.publish_offline — can
        # still carry decision=PASS with zero grounding. That is exactly the class that put an
        # ungrounded "Probate Locker" pack live (every check unverifiable, conf 0.0, 0 sources).
        # Publishing one ships on silence — forbidden. Fail closed.
        # This runs the DECISION LAYER'S OWN arithmetic (`dossier.grounded_support`), not a
        # second, looser copy of it. The looser copy was the bypass: it required only
        # `n_supported >= 1` and never checked `moat_grounded`, so a hand-fed dossier with one
        # incidental supported check cleared a backstop the real gate KILLs as
        # `moat_ungrounded`.
        from .dossier import grounded_support
        # LANE RESOLUTION IS PART OF THE ARITHMETIC, not a detail. `moat_critical_checks` is
        # LANE-DECLARED (config.yaml: [buyer_intent], [payer_solvency], [payer_solvency,
        # distribution]) and `run.py:942` resolves `cfg.for_lane(cand.ambition_tier)` BEFORE
        # build_dossier rules. EngineBridge is constructed with the BASE config
        # (publish/publish.py:58,81), whose default is [value_durability, incumbency] — so
        # asking `self.cfg` here demands a DIFFERENT lane's evidence than the dossier was ruled
        # under, and refuses a correctly-grounded smb pack for lacking a check its lane never
        # runs. That is exactly the structural unreachability config.py:150-154 records for the
        # decision layer (Martyn's Law, 2026-06-28), reintroduced one layer down. A backstop
        # must re-ask the SAME question, in the same lane, or it is a second gate wearing the
        # first one's name. `for_lane("")` returns self unchanged, so the default lane is a
        # no-op; `getattr` keeps this safe for a cfg stub that predates for_lane.
        _lane = getattr(getattr(dossier, "candidate", None), "ambition_tier", "") or ""
        _for_lane = getattr(self.cfg, "for_lane", None)
        # Only resolve for a real, non-empty lane NAME. `for_lane("")` returns self by
        # contract (config.py:550), so skipping the call is identical for the default lane —
        # and it keeps a stubbed cfg, whose `for_lane` returns an unrelated mock, from
        # silently discarding thresholds the caller set explicitly.
        lane_cfg = self.cfg
        if _lane and isinstance(_lane, str) and callable(_for_lane):
            lane_cfg = _for_lane(_lane)
        # Fail CLOSED, not loud — the same rule this guard applies to a malformed check
        # (dossier.grounded_support). A backstop that raises inside the publish path turns a
        # refusal into a crash, and the caller cannot tell the two apart. Type-tested rather
        # than coerced, for the reason spelled out in grounded_support: int() succeeds on a
        # stub, so a try/except would accept a fabricated bar instead of the declared default.
        _min = getattr(lane_cfg.thresholds, "min_supported_to_pass", 1)
        min_supported = _min if isinstance(_min, int) and not isinstance(_min, bool) else 1
        n_supported, moat_grounded, moat_checks = grounded_support(
            getattr(dossier, "checks", []) or [], lane_cfg)
        if n_supported < min_supported or moat_grounded < 1:
            logger.error(
                f"EngineBridge: Refusing to publish {dossier.candidate.candidate_id} "
                f"({dossier.candidate.title}) — source-or-die: {n_supported} "
                f"grounded-supported check(s) (need {min_supported}), {moat_grounded} on the "
                f"lane's decisive check(s) ({', '.join(moat_checks)}; need 1, lane "
                f"{_lane or 'default'!r}). "
                "Ungrounded 'pass'; will NOT list.",
                extra={"candidate_id": dossier.candidate.candidate_id,
                       "n_supported": n_supported, "moat_grounded": moat_grounded},
            )
            return False

        candidate = dossier.candidate
        candidate_id = candidate.candidate_id

        # ENTITLEMENTS CHECK (P0): Before spending time/credits on bundling and
        # provisioning, verify that the engine is entitled to publish this pack.
        # Fail-closed — missing or invalid key blocks publication entirely.
        if not self.entitlements_check(candidate_id):
            logger.error(
                f"EngineBridge: Entitlements check failed for {candidate_id}; "
                "refusing to publish."
            )
            return False

        # UPLOAD PROVENANCE CHECK (FENCED)
        # We MUST have a dossier reference to list. No ref = no grounding = no sale.
        dossier_ref = f"dossier:{candidate_id}"
        if not dossier_ref:
            logger.error(f"EngineBridge: Missing dossier_ref for {candidate_id}. Aborting.")
            return False

        logger.info(f"EngineBridge: Publishing {candidate_id} ({candidate.title})")

        # 1. Prepare pack files
        # THE CHOKE POINT for schema identifiers in prose. `_render_financial_model` also
        # normalises at generation time, but that only reaches packs generated after today;
        # 30 live packs already hold rendered markdown naming `estimated_cac_gbp` in the
        # sentences a buyer pays for. Normalising HERE covers both, because everything
        # downstream — the zip (`_create_bundle`), the catalogue row and the lint gate —
        # reads this dict. Data artifacts (.csv/.json/.svg) are passed through untouched:
        # their snake_case IS the format, which is the same reason the linter excludes them.
        artifacts = {
            k: (buyer_readable(v) if isinstance(v, str) and is_prose_artifact(k, v) else v)
            for k, v in (candidate.tags.get("artifacts", {}) or {}).items()
        }
        candidate.tags["artifacts"] = artifacts
        marketing = candidate.tags.get("marketing", [])
        # Epic C lite: claim-safe listing floor so catalog metadata is never an empty stub
        # when content_gen dropped marketing. validate_pack still requires real artifacts.
        from .pack_floors import ensure_marketing_floor
        marketing = ensure_marketing_floor(
            marketing, candidate, getattr(dossier, "checks", []) or []
        )
        candidate.tags["marketing"] = marketing

        # AUTO-VERIFICATION GATE (FENCED): a pack may only be LISTED when its deliverable
        # is actually complete. Generation is non-critical and flaky — a tier can return
        # empty/unparseable output or hit a quota wall — so without this gate a half-empty
        # pack would still zip, upload, and list. We compute completeness here and AND it
        # into is_listed below; an incomplete pack is registered UNLISTED for retry, never
        # sold. This mirrors the list-only-after-upload invariant: list only when sellable.
        pack_complete, pack_problems = validate_pack(artifacts, marketing)
        if not pack_complete:
            logger.error(
                f"EngineBridge: pack {candidate_id} FAILED completeness gate; "
                f"will register UNLISTED. Problems: {pack_problems}"
            )

        listing = next((m for m in marketing if m.get("type") == "listing_page"), {})
        listing_copy = listing.get("copy", "")
        # `copy` is markdown (it starts with `# <title>`), and oneLine is rendered as literal
        # text on the storefront card — take the markup off before it becomes the fallback.
        # `_card_field` = markdown strip + publish pass. It runs BEFORE the 150-char cut
        # below, so the truncation repair sees the full sentence and the deliberate `…` this
        # code adds afterwards is the only ellipsis a buyer ever sees.
        one_liner = _card_field(candidate.one_liner) or _card_field(listing_copy)
        # Cut on a WORD BOUNDARY, not a character index.
        #
        # This was `one_liner[:150] + "..."`, and measured against the live catalogue on
        # 2026-08-06 it had cut 34 of the 63 listed packs -- 54% of the shelf -- with several
        # landing inside a word: "for a flat fee per applicat...", "keeps you on ...". Those
        # strings are printed verbatim as the card description AND as the lead paragraph of the
        # pack page, directly above the buy button. A storefront whose whole claim is that its
        # numbers are checked cannot ship a product description that stops mid-word.
        #
        # `rsplit` on the last space of the 150-char window is the entire fix: the result is
        # never longer than 150, and never ends part-way through a word. `…` rather than "..."
        # because it is one character, so it cannot wrap onto a line of its own, and a screen
        # reader announces it once instead of as three full stops.
        #
        # The 34 rows already published are NOT repaired by this -- only a re-publish would do
        # that, and that is a money-rail operation with its own hazards. The storefront repairs
        # what it is handed (`store_platform/src/Store.Web/src/lib/copy.ts`); this stops any
        # further row being written broken in the first place.
        # CUT ON A SENTENCE, AND ONLY WHEN THE STRING IS GENUINELY LONG.
        #
        # The word-boundary fix above stopped the cut landing mid-word, but it left the far more
        # common defect in place: a product description that stops mid-SENTENCE and trails off.
        # Audited on 2026-08-13, 29 of the 50 live packs ended in `…`, and the live page prints
        # that string three times ("…into a priced, dated change note the client…"). Median full
        # length is 154 characters, so a 150 cap truncated most of the shelf by one or two words.
        #
        # 150 was never a display constraint. The card that renders this already clamps to two
        # lines in CSS (`store_platform/src/Store.Web/src/components/discovery/DossierCard.tsx:57`,
        # `line-clamp-2`), so the browser was going to elide it anyway. Truncating in the DATA
        # bought nothing and mutilated the pack page, where the same string is the lead paragraph
        # and has room for all of it. Clamp visually, store whole.
        #
        # 280 rather than "no limit" because a payload field still needs a bound. At 280 only 5
        # of 50 exceeded it, all single runaway sentences that were rewritten by hand.
        if len(one_liner) > 280:
            kept = ""
            for sentence in re.split(r"(?<=[.!?])\s+", one_liner):
                if len(kept) + len(sentence) + 1 > 280:
                    break
                kept = f"{kept} {sentence}".strip()
            if kept:
                one_liner = kept
            else:
                # No sentence boundary inside the cap: fall back to the word-boundary cut, which
                # is the only case that may still ship a `…`.
                head = one_liner[:280].rstrip()
                cut = head.rsplit(" ", 1)[0] if " " in head else head
                one_liner = cut.rstrip(" ,;:-–—") + "…"

        # Per-pack catalog metadata: the structured listing fields + a safe sample excerpt +
        # the Python-computed economics teaser + moat trust signals. This is what lets the
        # storefront sell each pack specifically instead of with identical generic chips.
        # EVERY string below is printed by the storefront without a markdown parser (see
        # Store.Web pack/[id].tsx), so each one goes through to_plain_text. Sanitising here —
        # at the single boundary where the payload is built — covers operator-generated
        # listings too, not just the deterministic floors in pack_floors.
        subhead = _card_field(listing.get("subhead"))
        # `Candidate.audience` (models.py) is the single normaliser, shared with the SQLite
        # index in Store.save — see the note on the catalog_meta entry below.
        audience = getattr(candidate, "audience", "") or ""
        catalog_meta: Dict[str, Any] = {
            # The shelf heading. Already length-enforced by artifacts._card_line (drop, never
            # truncate), so no [:n] slice here — a slice would reintroduce exactly the
            # mid-clause cut that enforcement exists to prevent. "" when the operator could
            # not write a truthful short line; the card then falls back to the pack title.
            "cardLine": _card_field(listing.get("card_line")),
            "headline": _cap_words(_card_field(listing.get("headline")), 140),
            "subhead": _cap_words(subhead, 280),
            # Empties dropped AFTER the pass as well as before it: a bullet that was nothing
            # but a passage id has no words left, and an empty chip on the card is worse than
            # one fewer chip.
            "whatYouGet": [x for x in
                           (prose_pass(x) for x in plain_lines(listing.get("what_you_get")))
                           if x][:5],
            "proofPoint": _card_field(listing.get("proof_point")),
            "whoPays": _card_field(listing.get("who_pays")),
            "effortTag": (listing.get("effort_tag") or "").strip(),
            "timeToFirstRevenue": _card_field(listing.get("time_to_first_revenue")),
            "sampleExtract": _sample_excerpts(artifacts.get("build_spec", ""), listing.get("proof_point", "")),
            "financialSnapshot": _financial_snapshot(artifacts.get("financial_model", "")),
            "verifiedAt": getattr(dossier, "created_at", "") or "",
            # The jurisdiction the OPPORTUNITY is in — a browse facet and a disclosure,
            # never a pricing input. The pack still sells for £49 through the same rail.
            "market": getattr(candidate, "market", "") or "",
            # Who generation wrote this pack FOR (`candidate.tags["audience"]`,
            # generate.py:552 — one of config.yaml `generation.audience_forms`). Every dossier
            # carried it and the publish boundary dropped it, so the catalogue could say what a
            # pack is but never who it was aimed at, and no per-persona conversion question was
            # answerable on the sold side.
            #
            # Deliberately NOT a discovery facet. `facets.ADVANTAGE` already contains a member
            # spelled "audience", and it means the opposite end of the transaction — "the buyer
            # already HAS an audience". Routing this through facets_mod would collide two
            # unrelated meanings in one word, and it would also put an 8-value list under the
            # closed-vocabulary contract that has to be kept in sync across three deploy units.
            # This is a metadata disclosure like `market` above, on the same terms.
            #
            # Omitted rather than sent empty when absent: the Store's publish apply block only
            # overwrites what it was sent, so "" would be a value that erases a stored one on a
            # metadata-light republish, while absent leaves it alone.
            **({"audience": audience} if audience else {}),
        }
        # Discovery facets — the closed vocabulary the storefront routes buyers on. Already
        # validated by artifacts._normalize_listing, so anything the operator invented is
        # gone by here; to_wire drops the empties so a facet-light republish never untags a
        # pack the backfill tagged (the Store API only overwrites what it was sent).
        pack_facets = facets_mod.normalize(listing.get("facets"))
        # Fill the holes generation left — but only for the two facets whose value restates a
        # dossier field rather than making a judgement (`facet_derive.DERIVABLE` is exactly
        # ("effort", "mechanism"); sector, payer, commitment and advantages are refused there and
        # stay hand-resolved). Generation always outranks derivation: an asserted value is never
        # overwritten, which is the same authority order tools/backfill_facets.py uses.
        #
        # Without this the mechanical half of the 2026-08-01 backfill is a one-off patch. It
        # filled effort on 14 live packs by reading `automatability` and `structural_form` — two
        # fields the publish path never looked at — so the identical hole would reopen on the very
        # next pack whose generation dropped the facets block, and nothing here would notice.
        derivation_source = {
            "automatability": getattr(candidate, "automatability", None),
            "structural_form": getattr(candidate, "structural_form", "") or "",
        }
        for facet_name, derived in facet_derive.derive(derivation_source).items():
            if pack_facets.get(facet_name):
                continue
            pack_facets[facet_name] = derived.value
            logger.info(
                f"EngineBridge: {candidate_id} derived {facet_name}={derived.value} "
                f"({derived.evidence})",
                extra={"candidate_id": candidate_id, "facet": facet_name},
            )
        catalog_meta.update(facets_mod.to_wire(pack_facets))
        # A sector-less pack is publishable — guessing one is worse, and the vocabulary has an
        # explicit `other` for "none of the eleven fit", so a missing sector means generation
        # dropped the facets block, not that the idea defies classification. But it is a real
        # cost: sector drives the browse filter and the card's colour, so an untagged pack sits
        # on the shelf reachable only by search. It went unnoticed until four of the twenty-six
        # packs live on 2026-07-31 (CureSafe Strip, SpatWindow, StrikeShield, SailCert) turned
        # out to carry no facets at all, because nothing anywhere said so out loud. This does
        # not block the publish; it makes the omission visible in the run log the same day it
        # happens, so it can be resolved by hand in store_platform/data/facets-backfill.json.
        if not pack_facets.get("sector"):
            absent = sorted(k for k, v in pack_facets.items() if not v)
            logger.warning(
                f"EngineBridge: {candidate_id} ({candidate.title}) is being registered with NO "
                f"sector — it will render without a category and be missing from every sector "
                f"filter. Absent facets: {absent}. Generation returned "
                f"facets={listing.get('facets')!r}; resolve by hand in "
                f"store_platform/data/facets-backfill.json (never by guessing here).",
                extra={"candidate_id": candidate_id, "absent_facets": absent},
            )
        catalog_meta.update(_trust_fields(dossier))
        # A pack whose card cannot lead with a number is publishable — the same rule as the
        # sector warning above, and for a stronger reason: the figure is extracted by regex from
        # rendered prose, so its absence is a fact about the TEXT, never about the idea. Killing
        # a validated, sellable pack over a failed match would be the engine punishing a buyer
        # for its own parser.
        #
        # But silence here is what let it spread. The comprehension on the next line drops empty
        # values, so an unparsed snapshot vanished from the payload with nothing said, and the
        # storefront's fallback made the result look intentional: the card printed its source
        # count and read as a design choice rather than a miss. This makes the omission visible
        # in the run log on the day it happens, which is the only window in which the financial
        # model that produced it is still the current one.
        _gap = _snapshot_gap(catalog_meta.get("financialSnapshot"))
        if _gap:
            logger.warning(
                f"EngineBridge: {candidate_id} ({candidate.title}) is being registered with no "
                f"lead figure — {_gap}. Its card will fall back to the cited source count, the "
                f"same fact every other card shows. This does NOT block the listing. Fix the "
                f"financial model's shape or the money pattern in _financial_snapshot "
                f"(bridge.py), never by typing a number in here.",
                extra={"candidate_id": candidate_id, "snapshot_gap": _gap},
            )
        # Drop empties so the payload (and the Store API) only ever see populated fields.
        catalog_meta = {k: v for k, v in catalog_meta.items() if v not in ("", [], {}, None)}

        # 1b. ARCHIVE THE CITATIONS, before the bundle is built from them.
        #
        # A pack is generated once and sold indefinitely, so its evidence decays after the
        # sale: measured 2026-08-09, 12 of 14 dead citations blocking packs were genuinely
        # 404 on a GET. The passage text is already durable (`Source.text`, quoted to the
        # buyer in the QA report), so only the POINTER rots. This mints a second one.
        #
        # Ordering is the whole point of putting it here: `_create_bundle` renders the QA
        # report from these Source objects on the next line, so the memento has to be on them
        # BEFORE that call or it would be a field nobody reads. Strictly additive and never
        # raises (see archive.archive_sources) — the Internet Archive being slow is our
        # convenience failing, not a reason a paid-for pack fails to ship.
        archive_cfg = self.cfg.listing if isinstance(getattr(self.cfg, "listing", None), dict) else {}
        if archive_cfg.get("archive_citations", False):
            _store_dir = getattr(self.cfg, "store_dir", None)
            n_archived = archive_sources(
                dossier.all_sources,
                cache_path=(Path(_store_dir) / "citation_archive.json")
                if isinstance(_store_dir, (str, Path)) else None,
                save_new=bool(archive_cfg.get("archive_save_new", True)),
                timeout_s=float(archive_cfg.get("archive_lookup_timeout_s", 10.0)),
                save_timeout_s=float(archive_cfg.get("archive_save_timeout_s", 30.0)),
                max_urls=int(archive_cfg.get("archive_max_urls", 30)),
            )
            logger.info(f"EngineBridge: {candidate_id} archived {n_archived}/"
                        f"{len(dossier.all_sources)} citation(s)")

        # 2. Create the bundle (.zip)
        bundle_path = self._create_bundle(dossier, artifacts, marketing)
        if not bundle_path:
            logger.error(f"EngineBridge: Failed to create bundle for {candidate_id}")
            return False

        # 2c. THE CONTENT GATES, DECIDED BEFORE ANYTHING IS MINTED.
        #
        # These three operands of `listing_gate` — completeness, the bundle audit and the Q2
        # lint — are pure functions of the pack we have already built. None of them can
        # change based on a Stripe object or an R2 key. Running them after provisioning (as
        # this did until 2026-08-08) meant a pack that could never list still minted a
        # Product and a Price and uploaded its zip first: four orphan Stripe products in one
        # afternoon, and the same leak on every retry. Deciding here makes provisioning
        # conditional on the pack being sellable at all.
        #
        # `_resolve_money_rail` below still runs unconditionally — it only READS
        # (describe_price) and a republish must keep the ids it is already sold with. It is
        # the MINT that is gated, not the money rail's resolution.
        # The storefront tells buyers exactly which documents are in the download
        # (Store.Web PackContents.tsx, bound to BUNDLE_FILES by a drift test). That claim is
        # only honest if an incomplete bundle cannot be listed, and `pack_complete` alone does
        # not carry it: `validate_pack` reads the in-memory artifacts, so it cannot see a file
        # that never reached the zip. a03a2ba029b408a7 is the proof — it shipped 3 of 8 files
        # with a 20-byte Marketing_Assets.md and was listed for sale anyway.
        bundle_gaps, bundle_stubs = audit_bundle(bundle_path)
        bundle_complete = not bundle_gaps and not bundle_stubs
        if not bundle_complete:
            logger.error(
                f"EngineBridge: {candidate_id} bundle fails the structural audit "
                f"(missing={bundle_gaps or '-'}, stubs={bundle_stubs or '-'}); "
                f"publishing UNLISTED — the storefront promises every file in BUNDLE_FILES."
            )
        # Q2 LINT GATE: the deterministic quality floor on what a buyer actually SEES —
        # currency consistent with the market, computed lines whose arithmetic re-checks,
        # no mid-word cuts in storefront copy, citations that resolve. validate_pack proves
        # presence and audit_bundle proves the zip's shape; neither reads the content. The
        # full pre-slice texts are recomputed here so the truncation check can compare each
        # final rendered field against its source.
        listing_cfg = self.cfg.listing if isinstance(getattr(self.cfg, "listing", None), dict) else {}
        store_dir = getattr(self.cfg, "store_dir", None)
        store_dir = Path(store_dir) if isinstance(store_dir, (str, Path)) else None
        one_liner_full = to_plain_text(candidate.one_liner, collapse=True) or to_plain_text(
            listing_copy, collapse=True
        )
        lint_report = lint_pack(
            artifacts=artifacts,
            listing_copy=listing_copy,
            # The same list `_create_bundle` renders into Marketing_Assets.md, after
            # `ensure_marketing_floor`, so what is graded is what ships.
            marketing=marketing,
            listing_texts={
                # Rendered half and source half must stay in the SAME normalisation space.
                # `check_truncation` decides "cut mid-word" with `source.startswith(final)`,
                # so normalising only the rendered half would not make that check wrong — it
                # would make it silently vacuous, which is the more expensive failure. The
                # rendered halves are normalised by `_card_field`; these sources bypass it,
                # so they are normalised here.
                "oneLine": (one_liner, nodash(one_liner_full)),
                "headline": (catalog_meta.get("headline", ""),
                             nodash(to_plain_text(listing.get("headline"), collapse=True))),
                "subhead": (catalog_meta.get("subhead", ""), subhead),
            },
            truncation_caps={"headline": 140, "subhead": 280},
            market=getattr(candidate, "market", "") or "",
            check_urls_enabled=bool(listing_cfg.get("lint_check_urls", False)),
            url_cache_path=(store_dir / "lint_url_cache.json") if store_dir else None,
            # `title` lints the value that ACTUALLY SHIPS — i.e. after the catalogue choke
            # point. That makes this a regression guard on the choke point itself: if the
            # normalisation is ever bypassed again, this errors instead of going quiet, and
            # a quiet bypass is exactly how 71 dashes reached 68 of 72 live listings.
            house_fields={
                "title": nodash(to_plain_text(candidate.title, collapse=True)),
                # `cardLine` is the whole of the shelf card and was linted by NOTHING until
                # 2026-08-13: it has no truncation source to pair with, so it never entered
                # `listing_texts`, and no check took it by name. That is how "£180 a claim,
                # filed on the platform's own cover" reached the live shelf. It ships the
                # value AFTER `_card_field`, so what is graded is what a visitor reads.
                "cardLine": catalog_meta.get("cardLine", ""),
            },
            shelf_copy_block_on_breach=bool(
                listing_cfg.get("shelf_copy_block_on_breach", False)),
            # Built AFTER `archive_sources` above has populated the field, so a citation that
            # died since publish warns (with its memento named) instead of blocking the pack.
            # Empty when archiving is off or found nothing, which restores the old behaviour
            # exactly: no memento, no downgrade.
            archived_urls={
                s.url: s.archived_url
                for s in (dossier.all_sources or [])
                if getattr(s, "url", "") and getattr(s, "archived_url", "")
            },
            # Same field, second question: `check_house_dashes` asks whether the title is
            # punctuated in house style; `check_title` asks whether it is a marketing
            # headline a buyer can read on a card. Both defaults are code-side and SAFE: a
            # missing config key must not silently unbind the only thing standing between a
            # breaching title and a buyer. See check_title for why the actuator flipped on
            # 2026-08-14 — the config line that switched it on lived uncommitted in a file a
            # concurrent session owned, so one checkout would have undone it invisibly.
            title_max_chars=int(listing_cfg.get("title_max_chars", 60) or 60),
            title_block_on_breach=bool(listing_cfg.get(
                "title_block_on_breach", TITLE_BLOCK_ON_BREACH_DEFAULT)),
            grammar_enabled=bool(listing_cfg.get("lint_grammar", False)),
            max_grammar_defects_per_1k=float(
                listing_cfg.get("max_grammar_defects_per_1k", 0.0) or 0.0),
        )
        lint_ok = bool(lint_report.get("ok"))
        if not lint_ok:
            lint_errors = [p["detail"] for p in lint_report["problems"]
                           if p["severity"] == "error"]
            logger.error(
                f"EngineBridge: {candidate_id} FAILED the pack lint ({lint_errors}); "
                f"publishing UNLISTED — wrong currency or wrong arithmetic must not sell."
            )
        # The receipt: the full report (lint + completeness + bundle audit) lives next to
        # the dossier, machine-readable, pass or fail.
        if store_dir is not None:
            report_path = store_dir / "dossiers" / f"{candidate_id}.lint.json"
            try:
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(json.dumps({
                    **lint_report,
                    "pack_complete": pack_complete,
                    "completeness_problems": pack_problems,
                    "bundle_missing": bundle_gaps,
                    "bundle_stubs": bundle_stubs,
                }, indent=2, ensure_ascii=False))
            except OSError as exc:
                logger.warning(
                    f"EngineBridge: could not write lint report for {candidate_id}: {exc}"
                )

        # Everything decidable without touching a payment provider or object storage. When
        # this is False the pack CANNOT list however provisioning goes, so minting for it
        # would only ever produce an orphan.
        content_ok = pack_complete and bundle_complete and lint_ok

        # GATE-ONLY EXIT. Deliberately placed HERE and not one line later: `price_for` below
        # is the first step of the money rail, and everything after it — the provider Price
        # object, the R2 upload, the catalogue row — is outward-facing. Returning on this
        # line is what makes "a dry run cannot mint an orphan" a property of the control
        # flow rather than of a caller remembering to pass the right flag.
        if dry_run:
            logger.info(
                f"EngineBridge: DRY RUN for {candidate_id} — content_ok={content_ok} "
                f"(complete={pack_complete}, bundle={bundle_complete}, lint={lint_ok}); "
                f"no price minted, no upload, no catalogue write.",
                extra={"candidate_id": candidate_id, "dry_run": True,
                       "content_ok": content_ok, "pack_complete": pack_complete,
                       "bundle_complete": bundle_complete, "lint_ok": lint_ok},
            )
            return bool(content_ok)

        # 2b. Decide the price ONCE, here (C2). Two things downstream need it — the
        # provider Price object and the catalogue row — and they must not be able to
        # disagree: the fulfilment fence compares what the buyer paid against the
        # catalogue's floor, so a Stripe Price minted at one number and a row written at
        # another is a pack that charges correctly and refuses to deliver. Both read
        # `price` below, so drift is structurally impossible rather than merely unlikely.
        #
        # Until a pack carries an ambition_tier this resolves to exactly the old flat
        # 4900 (pricing.price_for's unclassified default), so C2 is a no-op on today's
        # catalogue and a live ladder the moment lanes start tagging candidates.
        price = price_for(
            candidate,
            getattr(dossier, "score", None) or ScoreResult(scores={}, justification={}),
            self.cfg,
            anchors=anchors_from_tags(candidate),
            # The SAME integer the row publishes as `sourceCount` (via `_trust_fields`,
            # which reads this helper too). Passing it here is what makes the price
            # derivable from the page: a buyer comparing two rows sees the number that
            # chose the rung. Where config declares no bands this is inert and the tier
            # ladder decides, exactly as before.
            source_count=_source_count(dossier),
        )
        logger.info(
            f"EngineBridge: {candidate_id} priced at {price.price_pence}p — {price.rationale}",
            extra={"candidate_id": candidate_id, "price_pence": price.price_pence,
                   "rung": price.rung, "segment": price.segment,
                   "price_evidence": price.evidence},
        )
        candidate.tags["price_decision"] = {
            "price_pence": price.price_pence, "rung": price.rung,
            "segment": price.segment, "rationale": price.rationale,
            "evidence": price.evidence,
        }

        # D3 — the derivation record. Every price decision leaves one, not only the ones
        # taken by a re-pricing PATCH, or the publish path would be the one money-moving
        # act in the system with no auditable provenance.
        #
        # Non-fatal by design: this is an audit artifact, and a full disk or a read-only
        # `store/` must not stop a pack from publishing at a price that was correctly
        # decided. The failure is logged loudly and the ref is simply absent.
        try:
            candidate.tags["price_rationale_ref"] = write_rationale(
                candidate_id, price, self.cfg,
                actor="price-engine", source="prospector/bridge.py")
        except Exception as e:  # pragma: no cover - filesystem failure path
            logger.error(f"EngineBridge: could not write price rationale for "
                         f"{candidate_id}: {e}")

        # 3. Provision product with the active payment provider (P3 — provider-agnostic)
        provider_product_id = f"prov_stub_{candidate_id[:8]}"
        provider_price_id = f"price_stub_{candidate_id[:8]}"
        payment_provider = self.active_provider

        # The row we are about to overwrite. Read once, used for both the money rail and the
        # content version below.
        existing_row = self._existing_listing(candidate_id)

        prov = self.provisioner

        # A pack that is already on sale keeps the exact product and price it is sold with.
        # Minting on every publish is what a provider idempotency key only appears to
        # prevent: Stripe's expires after 24h, so a republish a day later repoints checkout
        # at a new price while the catalogue's fulfilment floor keeps the old number. See
        # _resolve_money_rail.
        try:
            reused = self._resolve_money_rail(
                candidate_id, existing_row, price.price_pence, prov)
        except ProvisioningError as e:
            logger.error(f"EngineBridge: {e}")
            return False

        applied_price_pence = price.price_pence
        # The USD amount actually MINTED onto the provider Price in this call, not the one the
        # ladder decided. It stays None on every path that does not mint — a reused live price
        # (whose currency_options we did not write and cannot inspect from here), a Paddle rail,
        # a missing provisioner — because the catalogue's USD figure is what the fulfilment fence
        # bills against, and recording a price the provider was never told about is how a buyer
        # is charged in a currency the rail then refuses. None costs a US buyer a GBP checkout;
        # a wrong number costs them a failed purchase.
        minted_usd_cents: Optional[int] = None
        if reused is not None:
            provider_product_id, provider_price_id, applied_price_pence = reused
            if applied_price_pence != price.price_pence:
                # The decision record must not read as though the new rung was applied.
                candidate.tags["price_decision"]["applied"] = False
                candidate.tags["price_decision"]["live_price_pence"] = applied_price_pence

        if reused is not None:
            pass  # already provisioned; minting anything here is the defect itself
        elif not content_ok:
            # The pack has already failed a content gate, so `listing_gate` returns False no
            # matter what we mint. Minting anyway is how four unsellable Stripe products were
            # created on 2026-08-08 — one per publish attempt, none reachable by a buyer,
            # none cleaned up. The pack still registers UNLISTED below with its stub ids, so
            # the operator sees it and a later republish provisions it properly.
            logger.error(
                f"EngineBridge: {candidate_id} failed a content gate "
                f"(complete={pack_complete}, bundle={bundle_complete}, lint={lint_ok}); "
                f"SKIPPING {payment_provider} provisioning — it could not list either way, "
                f"and a product minted for an unlistable pack is an orphan."
            )
        elif prov:
            try:
                logger.info(f"EngineBridge: Creating {payment_provider} product for {candidate_id}")
                metadata = {
                    "dossier_ref": dossier_ref,
                    "candidate_id": candidate_id,
                    "pack_id": candidate_id,
                    # DETERMINISTIC per logical publish. This was
                    # `datetime.utcnow().isoformat()`, and this whole dict is hashed into
                    # `create_product`'s idempotency-key fingerprint (:1744) — so the key
                    # differed on every single call and could NEVER repeat, defeating the
                    # method's own documented purpose ("a publish retry after a network blip
                    # replays an identical request under the same key and reuses the
                    # Stripe-side product"). A blip after Stripe accepts create_product but
                    # before the client sees the response, then a retry, minted a permanently
                    # orphaned second product.
                    #
                    # Excluding it from the fingerprint instead would be WORSE: same key,
                    # different params is a hard Stripe error, the exact failure that left
                    # 13795bea31feee47 and 2abc23c3c0d05bab unlistable on 2026-08-08. The
                    # value has to be stable, so it is derived from the pack, not the clock.
                    "bundle_version": _bundle_version(dossier, candidate),
                }
                provider_product_id = prov.create_product(
                    name=candidate.title,
                    description=one_liner,
                    metadata=metadata
                )

                logger.info(f"EngineBridge: Creating {payment_provider} price for "
                            f"{provider_product_id} at {price.price_pence}p ({price.rung})")
                provider_price_id = prov.create_price(
                    product_id=provider_product_id,
                    # C2 — the L1 ladder decides, not a flat constant. The SAME
                    # PriceDecision feeds the catalogue write below; see `price` above.
                    amount_pence=price.price_pence,
                    # The same rung read off the USD ladder (config.yaml
                    # listing.pricing.usd_rungs), never a conversion of the pence. None when
                    # the ladder declares no USD rung, which leaves the pack GBP-only.
                    usd_cents=price.price_usd_cents,
                )
                # Recorded only AFTER create_price returned: the two must land together, or
                # the catalogue advertises a USD price on a provider price that has no USD
                # option and every US checkout 400s at Stripe.
                minted_usd_cents = price.price_usd_cents

            except Exception as e:
                logger.error(f"EngineBridge: {payment_provider} provisioning failed: {e}")
                return False
        else:
            # No provisioner for the active provider (no API key, or active_provider names
            # a rail we hold no key for). The pack keeps its `price_stub_*` id, which the
            # Store's checkout cannot bill against — so it must NOT go live. See the
            # `priced` guard below; this branch only records why.
            logger.error(
                f"EngineBridge: No {payment_provider} provisioner available for "
                f"{candidate_id} (keys: stripe={'set' if self.stripe_api_key else 'unset'}, "
                f"paddle={'set' if self.paddle_api_key else 'unset'}). Pack will be "
                f"published UNLISTED — a stub price id cannot take money. "
                f"Stripe key selection: {self.stripe_key_reason}"
            )

        # 3.5 Upload the deliverable to R2 (content-addressed by hash, so a later republish
        # writes a NEW object and never overwrites content an existing buyer is entitled to).
        # We skip the upload entirely for an incomplete pack — no point storing a broken zip.
        content_hash: Optional[str] = None
        content_key: Optional[str] = None
        uploaded = False
        if content_ok:
            content_hash = self._sha256(bundle_path)
            content_key = f"packs/{candidate_id}/{content_hash}.zip"
            uploaded = self.r2.upload(bundle_path, content_key)
            if not uploaded:
                # List-only-after-upload: if the content isn't in storage, the pack must not
                # go live. We still register the record (unlisted) so the operator can retry.
                logger.error(
                    f"EngineBridge: R2 upload failed/unconfigured for {candidate_id}; "
                    f"publishing UNLISTED (no deliverable in storage)."
                )

        # 4. Update Catalog via Store API. is_listed requires a complete pack, the content
        # in storage, AND a real provider price id; the Store enforces the upload half
        # server-side (defence in depth). The other halves are enforced here at the only
        # place packs are minted.
        #
        # The `priced` half is not theoretical: checkout builds a Stripe Checkout Session
        # from ProviderPriceId, so a `price_stub_*` pack renders a buy button that returns
        # HTTP 500. Listing an unbuyable pack is strictly worse than not listing it — the
        # buyer's trust is spent before they learn we can't sell them anything. Same
        # fail-closed rule as "no deliverable in storage".
        priced = bool(provider_price_id) and not provider_price_id.startswith("price_stub_")
        if not priced:
            logger.error(
                f"EngineBridge: {candidate_id} has no billable price id "
                f"({provider_price_id!r}); publishing UNLISTED."
            )

        # 4b. THE FIGURE FENCE (§33 / items 33-D, 33-G). Default OFF, and the default is a
        # decision, not an oversight: 15 of the 50 packs on sale carry a figure found in no
        # retrieved passage, so switching this on delists ~30% of the catalogue. That is the
        # founder's call. What the engine owes is the switch, the receipt and the honest copy —
        # which is why `pricing.tsx` and `faqContent.ts` no longer promise per-figure sourcing
        # regardless of whether this flag is on.
        figures_verified = True
        _listing_cfg = getattr(self.cfg, "listing", None) or {}
        if bool(_listing_cfg.get("require_figure_verification") or False):
            from . import human_review
            _fig_status, _outstanding = human_review.status_for_checks(
                candidate_id, getattr(dossier, "checks", []) or [],
                root=human_review.root_for(self.cfg))
            figures_verified = _fig_status in human_review.SELLABLE
            if not figures_verified:
                logger.error(
                    f"EngineBridge: {candidate_id} figure verification is "
                    f"{_fig_status!r} ({len(_outstanding)} outstanding); publishing UNLISTED. "
                    f"Run the review queue, or turn off listing.require_figure_verification.",
                    extra={"candidate_id": candidate_id, "figure_status": _fig_status,
                           "outstanding": _outstanding})

        is_listed = listing_gate(
            uploaded=uploaded, pack_complete=pack_complete, priced=priced,
            bundle_complete=bundle_complete, lint_ok=lint_ok,
            figures_verified=figures_verified,
        )

        # The content version is the STORE's counter, and we send one only when we can actually
        # read the current value. No GET projection returns contentVersion, so computing
        # `(existing_row.get("contentVersion") or 0) + 1` sent 1 on every republish and knocked a
        # pack on its fourth revision back to its first — a number FulfilmentService stamps onto
        # the buyer's record, so the same version would then describe two different bundles.
        # Omitting it is a no-op at the Store, which increments its own counter when the content
        # hash actually changed. If a future projection does expose the field, this reads it from
        # the same snapshot the money rail was resolved from (_existing_listing) rather than a
        # second GET: two reads of one row can straddle a concurrent write, and the version would
        # then describe a row the price decision was never made against.
        known_version = existing_row.get("contentVersion")
        content_version = (known_version + 1) if isinstance(known_version, int) else None

        return self._update_catalog(
            id=candidate_id,
            title=to_plain_text(candidate.title, collapse=True),
            one_line=one_liner,
            dossier_ref=dossier_ref,
            payment_provider=payment_provider,
            provider_product_id=provider_product_id,
            provider_price_id=provider_price_id,
            is_listed=is_listed,
            content_key=content_key if is_listed else None,
            content_hash=content_hash if is_listed else None,
            content_version=content_version,
            # The amount the price object the buyer is charged against ACTUALLY charges —
            # which is the ladder's decision on a first publish, and the live price on a
            # republish. Sending the decided number while reusing a live price at a
            # different amount is the exact disagreement the fulfilment fence turns into a
            # charged-but-undelivered order.
            price_pence=applied_price_pence,
            # Same rule, in the currency the fence reads second: only the USD amount actually
            # written onto the provider Price above. See `minted_usd_cents`.
            price_usd_cents=minted_usd_cents,
            metadata=catalog_meta,
        )

    # ---- money-rail reuse (2026-08-08) -------------------------------------------------
    _STUB_PREFIXES = ("prov_stub_", "price_stub_")

    def _existing_listing(self, candidate_id: str) -> Dict[str, Any]:
        """The catalogue row this publish is about to overwrite; {} when there is none.

        Fetched ONCE per publish and used for both the money-rail decision and the content
        version, so those two can never be read from different snapshots of the same row.
        """
        try:
            resp = requests.get(f"{self.store_api_url}/catalog/{candidate_id}", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    return data
        except Exception as e:
            logger.warning(
                f"EngineBridge: could not read the existing catalogue row for "
                f"{candidate_id}: {e}"
            )
        return {}

    def _resolve_money_rail(
        self, candidate_id: str, existing: Dict[str, Any], decided_pence: int,
        prov: Optional[ProductProvisioner],
    ) -> Optional[Tuple[str, str, int]]:
        """Reuse the provider objects this pack is ALREADY sold with, or None to mint fresh.

        Returns (product_id, price_id, amount_pence_to_record), or None meaning "no live
        money rail exists for this pack — mint one". Raises ProvisioningError when a live
        rail exists but cannot be established, because the only alternatives at that point
        are minting a duplicate or writing an id we did not verify.

        THE DEFECT THIS CLOSES. `publish_pass` minted a new provider Product and Price on
        EVERY publish, relying on the provider's idempotency key to deduplicate. Stripe's
        idempotency keys expire after 24 hours, so a pack republished a day or more after it
        first went live gets genuinely new objects. The catalogue upsert then assigns
        ProviderPriceId unconditionally on the update path (Store.Api Program.cs:490) while
        that same path never reassigns PricePence (Program.cs:477-482, which sets only
        Title/OneLine/DossierRef). So checkout starts minting sessions against the NEW price
        while the fulfilment floor keeps the OLD number, and FulfilmentService.cs:88
        (`item.AmountPence < pack.PricePence`) refuses delivery to anything paying under the
        floor: on any republish that lowers the rung, the buyer is charged and gets nothing.

        The Store already treats a published price as immutable. This makes the engine
        honour the same invariant rather than silently contradicting it. A genuine reprice
        has its own audited door — PATCH /internal/catalog/{id}/price (Program.cs:924), which
        re-checks billability and writes price history — and that door is the only way a live
        pack's price may move.
        """
        price_id = str(existing.get("providerPriceId") or "")
        if not price_id or price_id.startswith(self._STUB_PREFIXES):
            # First publish, or a pack that never had a billable rail. Nothing to preserve.
            return None

        if prov is None:
            raise ProvisioningError(
                f"{candidate_id} is already sold with provider price {price_id}, but no "
                f"provisioner is configured to verify it. Refusing to republish: writing "
                f"a stub id here would overwrite a LIVE pack's money rail and unlist it."
            )

        found = prov.describe_price(price_id)
        if found is None:
            raise ProvisioningError(
                f"{candidate_id} is already sold with provider price {price_id}, but the "
                f"provider could not confirm it. Refusing to republish: minting a "
                f"replacement would repoint checkout at a price the fulfilment floor does "
                f"not match."
            )

        if found.amount_pence != decided_pence:
            # The ladder moved under a pack that is already on sale. Reusing the live price
            # is the ONLY safe answer here: repointing charges the new amount while the
            # floor stays at the old one. Recording the live amount (not the decided one)
            # keeps the catalogue's number equal to what the price object actually charges.
            logger.error(
                f"EngineBridge: REPRICE REQUIRED for {candidate_id} — the ladder decided "
                f"{decided_pence}p but the live price {price_id} charges "
                f"{found.amount_pence}p. Keeping the live price; the new rung is NOT "
                f"applied. Move it through PATCH /internal/catalog/{candidate_id}/price, "
                f"the audited door that re-checks billability and writes price history."
            )
        else:
            logger.info(
                f"EngineBridge: reusing the live money rail for {candidate_id} "
                f"(product {found.product_id}, price {price_id} at {found.amount_pence}p) "
                f"— republish mints nothing."
            )
        return found.product_id, price_id, found.amount_pence

    @staticmethod
    def _sha256(path: Path) -> str:
        """SHA-256 of the bundle, used as the content-addressed storage key."""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def entitlements_check(self, candidate_id: str) -> bool:
        """Verify that the engine is entitled to publish candidate_id.

        Calls POST /entitlements with the configured API key (Bearer token).
        Fail-closed: returns False when the key is unset or the endpoint
        rejects the request, never silently using a stub credential.
        """
        if not self.entitlements_api_key:
            logger.error(
                f"EngineBridge: PROSPECTOR_ENTITLEMENTS_API_KEY not set; "
                f"refusing to publish {candidate_id}."
            )
            return False

        url = f"{self.store_api_url}/entitlements"
        headers = {
            "Authorization": f"Bearer {self.entitlements_api_key}",
            "Content-Type": "application/json",
        }
        payload = {"candidate_id": candidate_id}

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code == 200:
                logger.info(
                    f"EngineBridge: Entitlements check passed for {candidate_id}"
                )
                return True
            else:
                logger.error(
                    f"EngineBridge: Entitlements check failed for {candidate_id}: "
                    f"{response.status_code} {response.text}"
                )
                return False
        except Exception as e:
            logger.error(
                f"EngineBridge: Entitlements endpoint unreachable at {url}: {e}"
            )
            return False

    def _create_bundle(self, dossier: Dossier, artifacts: Dict[str, str], marketing: List[Dict[str, str]]) -> Optional[Path]:
        """Bundle the pack files into a zip."""
        candidate_id = dossier.candidate.candidate_id
        publish_dir = Path("publish") / "bundles" / candidate_id
        publish_dir.mkdir(parents=True, exist_ok=True)
        
        zip_path = publish_dir / f"prospector_pack_{candidate_id[:8]}.zip"
        
        try:
            from .pack_floors import (
                ensure_marketing_floor,
                exec_summary_md,
                first_week_checklist_md,
            )
            marketing = ensure_marketing_floor(
                marketing, dossier.candidate, getattr(dossier, "checks", []) or []
            )

            # Content by filename, for the index.html reading experience. Keyed rather than
            # appended, because the order this is WRITTEN in is not the order it should be READ
            # in, and for a long time it was.
            #
            # The zip is built cheapest-first: the three prose artifacts, financials, QA,
            # marketing, and only then the two deterministic floors (00 and 05), which need
            # `dossier.checks` in hand. An ordered list appended alongside those writes
            # therefore handed pack_html a running order of 01, 02, 03, 04, QA, Marketing, 00,
            # 05 — so a buyer opening the pack landed on the build spec, met the Executive
            # Summary seventh of eight, and found the First-Week Checklist, the only file that
            # says what to DO, dead last. Proven on a shipped bundle
            # (publish/bundles/fbd10d6bdfcd5e31): "Executive Summary" appears at char 5212 and
            # "The Blueprint (Build Spec)" at 4806.
            #
            # Nobody chose that order; it fell out of the write sequence. The right order was
            # already written down twice — `BUNDLE_FILES` below, and PackContents.tsx on the
            # storefront, which packContents.test.ts pins to it with an ORDERED toEqual. So the
            # reading order is now derived from that same tuple at render time rather than
            # accumulated here, which means adding a file or re-sequencing a write cannot
            # silently reorder what the buyer reads. Reordering the pack now requires editing
            # the contract, which is the only place it should ever have been editable.
            # `written` is the DOCUMENTS (PACK_DOCUMENTS + the evidence reference). Since
            # 2026-08-15 none of these is a zip entry: they are composed here, then rendered
            # into the files the buyer actually gets. Keeping them keyed by their old .md name
            # is deliberate — `_SECTION_TITLES`, `BUNDLE_READING_ORDER`, `pack_checklist`,
            # `pack_card` and `pack_manifest` all address them by that name, and renaming the
            # keys would be a rename with no reader-visible effect and five call sites to miss.
            written: Dict[str, str] = {}
            # What the ARCHIVE actually holds, name -> exact content written. Populated only
            # AFTER a successful write, never from the intent to write: manifest.jsonld states a
            # sha256 for every entry it lists, and listing an entry the zip does not contain
            # would make the one file whose job is to be machine-checkable the one file that
            # lies. Typed Any, not str: `Complete_Pack.pdf` is bytes.
            zip_written: Dict[str, Any] = {}

            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # 1-3. The prose deliverable. `_add_to_zip` writes nothing for empty content, so
                # a tier that silently returned "" used to produce a zip with the file simply
                # ABSENT (proven: publish/bundles/af1647af.../*.zip has no 01/02/03). The
                # completeness gate correctly keeps such a pack UNLISTED, but a structurally
                # incomplete zip is still worse than an honest placeholder — a missing file
                # reads as an oversight, a stub says what happened and why nothing is for sale.
                # THE PACK PROSE PASS. Every engine-authored document below goes through
                # `prose_pass_document` before it enters the zip — the same five repairs the
                # storefront gets, applied here because a pack `.md` is opened OFFLINE from a
                # downloaded zip, where no web-side fix can ever reach it. The document form is
                # line-wise and markdown-preserving: headings, list nesting and fenced code
                # come out untouched, and a line is only truncation-repaired when it actually
                # ends in an ellipsis.
                build_spec_md = prose_pass_document(
                    artifacts.get("build_spec", "") or _held_back_md("Blueprint / build spec"))
                written["01_Blueprint_BuildSpec.md"] = build_spec_md

                gtm_md = prose_pass_document(
                    artifacts.get("gtm_plan", "") or _held_back_md("Go-to-market plan"))
                written["02_Marketing_Plan_GTM.md"] = gtm_md

                ops_md = prose_pass_document(
                    artifacts.get("ops_plan", "") or _held_back_md("Operations plan"))
                written["03_Operations_Plan.md"] = ops_md

                # 4. Financial Model — its own file, with a provenance banner. The arithmetic is
                # Python-computed (no LLM math), which is a real trust differentiator, so we say so
                # where the buyer reads it.
                #
                # The banner said "from verified inputs" until 2026-08-13. It is not true and the
                # receipt is one line: `_render_financial_model` (artifacts.py:152) takes the
                # `claims` list as a parameter and never reads it, and every input is rendered as a
                # bare number (artifacts.py:190, 227-228). The inputs are ASSUMPTIONS, printed as
                # assumptions further down the same document. Claiming provenance the code does not
                # provide is the §33 failure in miniature — an exact calculation over an unsourced
                # input is exactly as wrong as the input, and saying "verified" invites the buyer to
                # skip the assumptions section that is the honest disclosure.
                # The prose around the arithmetic is engine-authored; the arithmetic itself is
                # Python-computed and the pass never touches a number that is not a stray
                # confidence float attached to a gate name.
                financials = prose_pass_document(artifacts.get("financial_model", ""))
                if financials:
                    financials = (
                        "> Every figure below is computed by Python from the assumptions listed at "
                        "the end of this document. No language model performed any calculation, so "
                        "the arithmetic is exact — the arithmetic, not the assumptions. Read those "
                        "before you rely on any number here.\n\n"
                        + financials
                    )
                else:
                    # Claim-safe stub: never invent unit economics. Completeness gate still
                    # refuses to LIST empty financials; this only prevents a 0-byte zip entry
                    # when registering an unlisted retry bundle.
                    financials = (
                        "# Financial model\n\n"
                        "_No verified numeric inputs were available to compute a model. "
                        "Prospector does not invent revenue, cost, or TAM figures._\n"
                    )
                written["04_Financial_Model.md"] = financials

                # 5. QA Report
                from .dossier import render_markdown
                # The ONE surface that keeps its confidence figures: in the QA report the
                # number is the subject, not a stray internal. `keep_confidence_figures=True`
                # also inserts `CONFIDENCE_SCALE_NOTE` once, so a buyer never meets a bare
                # "0.0" without the sentence that says what the scale means.
                qa_report = prose_pass_document(
                    render_markdown(dossier), keep_confidence_figures=True)
                written["QA_Report.md"] = qa_report

                # 6. Marketing Assets (Social, Email, SEO) — never a bare header stub.
                # The old loop appended a `##` heading per piece even when `copy` was empty,
                # so a marketing list of empty pieces produced exactly "# Marketing Assets\n\n"
                # — the 20-byte file. Skip empty pieces, then assert we wrote something real.
                # The heading names the READER, not our enum: `marketing_assets.LABELS` is
                # the one definition of what each piece is for, shared with the generator
                # and with the lint that grades it. It used to be
                # `type.replace("_", " ").title()`, which shipped "Seo Preview" and told a
                # buyer nothing about who the copy underneath was written for.
                sections = []
                for m in marketing:
                    body = (m.get("copy") or "").strip()
                    if not body:
                        continue
                    head, who = heading_for(m.get("type", "asset"))
                    sections.append(f"## {head}\n\n" + (f"_{who}_\n\n" if who else "")
                                    + f"{body}\n")
                if not sections:
                    # ensure_marketing_floor above should make this unreachable; if it ever is
                    # reached, synthesise the floor directly rather than ship a header stub.
                    from .pack_floors import claim_safe_marketing
                    sections = [
                        f"## {heading_for(m.get('type', 'listing_page'))[0]}\n\n"
                        f"{m['copy'].strip()}\n"
                        for m in claim_safe_marketing(
                            dossier.candidate, getattr(dossier, "checks", []) or []
                        )
                        if (m.get("copy") or "").strip()
                    ]
                marketing_text = prose_pass_document(
                    "# Marketing Assets\n\n" + "\n".join(sections))
                written["Marketing_Assets.md"] = marketing_text

                # 7–8. Epic C lite floors (deterministic, claim-safe)
                # Deterministic floors, but not id-free: they embed `check.rationale`, which is
                # verdict-brain prose and carries the same passage ids as everything else.
                exec_summary_content = prose_pass_document(
                    exec_summary_md(dossier.candidate, getattr(dossier, "checks", []) or []))
                written["00_Executive_Summary.md"] = exec_summary_content

                # The action document. `pack_checklist.render` is preferred and the six-line
                # floor is the fallback, never the default — measured 2026-08-13, the floor was
                # the document in 127 of 127 bundles on disk because it was wired
                # unconditionally here.
                #
                # It deliberately does NOT get a prose pass. The derived text is already in the
                # pack's voice, and the backfill that puts this same document into already-sold
                # packs cannot make a model call at all: routing one through a rewrite here
                # would mean a pack bought today and the same pack re-rendered tomorrow carry
                # two different checklists, which is the drift `pack_reference` and
                # `pack_card` are both built to avoid.
                from . import pack_checklist
                checklist_content = pack_checklist.render(dossier, dict(written))
                if not checklist_content:
                    checklist_content = prose_pass_document(
                        first_week_checklist_md(dossier.candidate))
                written["05_First_Week_Checklist.md"] = checklist_content

                # 8a. Marketing_Assets.txt — the one document a buyer EDITS. Everything else in
                # this pack is something to read; the marketing copy is something to paste into
                # an ad account, a mail tool or a landing page, and a rendered page is a worse
                # carrier for that than plain text. This is the single concession to the
                # "where did my editable files go" objection, and it is a concession made on
                # purpose rather than by leaving all eight .md in place.
                #
                # `keep_link_urls=True` because a cited URL in marketing copy is the evidence
                # behind the claim: dropping the target would leave a sentence asserting
                # something with its receipt silently removed.
                from .plain_text import to_plain_text
                marketing_txt = to_plain_text(
                    written.get("Marketing_Assets.md", ""), keep_link_urls=True)
                if marketing_txt:
                    self._add_to_zip(zipf, "Marketing_Assets.txt", marketing_txt)
                    zip_written["Marketing_Assets.txt"] = marketing_txt

                # 8b. Evidence_and_Constraints.md — P4: the shared evidence, stated ONCE.
                # Measured 2026-08-14 over 62 live packs: the same cited source is leaned on by
                # all three plan files a median of 11 times per pack (max 29), and near-duplicate
                # paragraphs across files run to 3.5% of the corpus. This document is where that
                # evidence lives now. Rendered with no model call and no prose pass, straight
                # from the dossier, which is what lets the same renderer backfill packs already
                # sold. Bonus on the same terms as index.html: guarded, and never a listing
                # blocker. It is written BEFORE index.html so the reader can include it.
                # It is a DOCUMENT, not an archive entry: it goes into `written` so the reader
                # and the PDF both carry it (BUNDLE_READING_ORDER places it immediately before
                # the QA report), and it is no longer a .md file in the zip.
                try:
                    from . import pack_reference
                    reference_md = pack_reference.render(dossier)
                    if reference_md:
                        written[pack_reference.FILENAME] = reference_md
                except Exception as e:  # noqa: BLE001 — one section of the read, not the whole pack
                    logger.warning(
                        f"{pack_reference.FILENAME} render failed for {candidate_id}: {e}; "
                        "shipping the bundle without it")

                # 8c. First_Fortnight.html + Assumptions.csv — P5: "markdown files is not the
                # one." Eight .md files in a zip reads as an AI output dump; these are the two
                # artefacts the programme doc asks for that a pack can actually carry. The card
                # is the one printable page a buyer pins up; the CSV is the assumptions register
                # in a form a spreadsheet opens. Both are deterministic projections of files
                # already written above, so the SAME renderers backfill packs already sold.
                # Guarded and bonus, on the same terms as everything else in this block.
                try:
                    from . import pack_card, pack_table
                    card_html = pack_card.render(
                        dossier,
                        checklist_md=written.get("05_First_Week_Checklist.md", ""),
                        financial_md=written.get("04_Financial_Model.md", ""),
                        pack_id=candidate_id,
                    )
                    if card_html:
                        self._add_to_zip(zipf, pack_card.FILENAME, card_html)
                        zip_written[pack_card.FILENAME] = card_html
                    table_csv = pack_table.render(dossier)
                    if table_csv:
                        self._add_to_zip(zipf, pack_table.FILENAME, table_csv)
                        zip_written[pack_table.FILENAME] = table_csv
                # Still guarded, but the consequence changed on 2026-08-15: both files are in
                # BUNDLE_FILES now, so a failure here no longer means "ships without them" — it
                # means `audit_bundle` finds them missing and the pack is held UNLISTED. The
                # guard exists so that outcome arrives as a warning plus an unlisted row rather
                # than as an exception on the register-unlisted retry path.
                except Exception as e:  # noqa: BLE001 — warn + let audit_bundle hold the listing
                    logger.warning(
                        f"P5 card/table render failed for {candidate_id}: {e}; "
                        "the pack cannot list without them")

                try:
                    from . import pack_html
                    pack_meta = pack_html.PackMeta(
                        title=dossier.candidate.title,
                        one_liner=getattr(dossier.candidate, "one_liner", "") or "",
                        verified_at=getattr(dossier, "created_at", "") or "",
                        source_count=len(dossier.all_sources) if getattr(dossier, "all_sources", None) else None,
                        pack_id=candidate_id,
                        # Leads the cover stat: claims are what a buyer can act on, sources
                        # are only the volume behind them. `or None` so a dossier with no
                        # cited ruling falls back to the old source-only line rather than
                        # printing "Checked 0 claims" on a pack we did check.
                        claim_count=getattr(dossier, "cited_claim_count", 0) or None,
                    )
                    # The reading order, taken from the contract rather than from the order
                    # the files happened to be written in. `if name in written` keeps a
                    # partially-built bundle renderable — such a pack is held UNLISTED by the
                    # completeness gate below, and a bonus file must never be the thing that
                    # raises on the retry path.
                    # `written` holds every composed document. The reader draws from it in the
                    # shared reading order, and only from what was actually composed, so a
                    # partially-built bundle stays renderable and a document that failed to
                    # render simply is not in the read.
                    md_entries: List[Tuple[str, str]] = [
                        (_SECTION_TITLES[name], written[name])
                        for name in BUNDLE_READING_ORDER
                        if name in written
                    ]
                    index_html = pack_html.render_pack_html(md_entries, pack_meta)
                    self._add_to_zip(zipf, "index.html", index_html)
                    if index_html:
                        zip_written["index.html"] = index_html

                    # 9b. Complete_Pack.pdf — the same eight sections, typeset. index.html
                    # answers "I want to read this now"; the PDF answers "I want to read this
                    # on a train, print it, or send it to my accountant", which is the half of
                    # the experience a folder of .md files never had. Nested try of its own:
                    # fpdf2 is an optional dependency and a PDF failure must not be reported
                    # as (or cost us) the reader that already succeeded above.
                    try:
                        from . import pack_pdf
                        pdf_bytes = pack_pdf.render_pack_pdf(md_entries, pack_meta)
                        if pdf_bytes:
                            zipf.writestr(pack_pdf.FILENAME, pdf_bytes)
                            # Recorded, so the manifest accounts for it. It was left out until
                            # 2026-08-14 on the belief that a bytes value would reach a renderer
                            # expecting str; it does not — `readable` above takes only `.md`, and
                            # the manifest hashes through `_as_bytes`, which the BACKFILL has
                            # always fed bytes. The cost of the omission was a bundle carrying a
                            # file its own machine-readable index denied existed, which is the
                            # one failure mode manifest.jsonld exists to make impossible.
                            zip_written[pack_pdf.FILENAME] = pdf_bytes
                    except Exception as e:  # noqa: BLE001 — warn + let audit_bundle hold the listing
                        logger.warning(
                            f"Complete_Pack.pdf render failed for {candidate_id}: {e}; "
                            "the pack cannot list without it")
                # index.html is the pack now — a failure here leaves an archive with no readable
                # edition at all, which `audit_bundle` catches and holds UNLISTED. Caught rather
                # than raised for the same reason as above: the retry path must still register.
                except Exception as e:  # noqa: BLE001 — warn + let audit_bundle hold the listing
                    logger.warning(
                        f"index.html render failed for {candidate_id}: {e}; "
                        "the pack cannot list without it")

                # 10. manifest.jsonld — the machine-readable half of the pack: every file with its
                # sha256, every check with its verdict and confidence, and every source with its
                # URL, its fetch date and the exact passage the verdict was formed from. See
                # pack_manifest.py for why the passage travels with the pack and why the PRICE
                # never does.
                #
                # The one file still in BUNDLE_BONUS_FILES, and the only one that belongs there:
                # a buyer never opens it, so a missing copy is not a short delivery and must not
                # block a listing. Guarded so a renderer fault can never be that block — and
                # loud, so it cannot rot unnoticed either.
                #
                # Fed `zip_written`, NOT `written`: since 2026-08-15 those differ, and the
                # manifest's entire job is to describe the ARCHIVE. Handing it the composed
                # documents would make it assert a sha256 for eight files the zip does not
                # contain — the exact failure this file exists to make impossible.
                #
                # Written LAST, after index.html, so it can describe index.html. It describes
                # itself by omission: `render_manifest` skips MANIFEST_FILENAME, because a file
                # cannot carry the digest of its own final bytes.
                try:
                    from . import pack_manifest
                    manifest_json = pack_manifest.render_manifest(
                        dossier,
                        zip_written,
                        BUNDLE_FILES,
                        _FILE_TITLES,
                        candidate_id,
                    )
                    self._add_to_zip(zipf, pack_manifest.MANIFEST_FILENAME, manifest_json)
                except Exception as e:  # noqa: BLE001 — bonus file; the pack ships regardless
                    logger.warning(
                        f"manifest.jsonld render failed for {candidate_id}: {e}; "
                        "shipping the bundle without it")

            # Structural check on the artefact we actually wrote — not on the inputs we think
            # we passed. This is the assertion that would have caught the 5-file bundles and
            # the 20-byte Marketing_Assets.md at build time.
            gaps, stubs = audit_bundle(zip_path)
            if gaps or stubs:
                # Deliberately NOT fatal HERE: an incomplete pack is still registered so it can
                # be retried, and failing this call would silently drop that retry record. The
                # sellability half is enforced by the caller, which re-runs this audit and ANDs
                # it into `is_listed` — this log is the diagnostic, not the gate.
                logger.error(
                    f"EngineBridge: bundle {candidate_id} is structurally incomplete "
                    f"(missing={gaps or '-'}, stubs={stubs or '-'}) — registering UNLISTED"
                )

            # The other direction: not "did the promised files arrive" but "did anything else".
            # Warning, not a gate — see `undeclared_bundle_entries`. The buyer is not short-changed
            # by a surplus file; the SHOP is, if its count still says otherwise.
            undeclared = undeclared_bundle_entries(zip_path)
            if undeclared:
                logger.warning(
                    f"EngineBridge: bundle {candidate_id} ships {undeclared}, declared in neither "
                    f"BUNDLE_FILES nor BUNDLE_BONUS_FILES. Listability is unaffected. Add it to "
                    f"BUNDLE_BONUS_FILES, and re-read PackContents.tsx: the count beside the list "
                    f"describes DELIVERABLES, and it must not become a claim about the archive."
                )

            return zip_path
        except Exception as e:
            logger.error(f"EngineBridge: Error zipping bundle: {e}")
            return None

    def _add_to_zip(self, zipf: zipfile.ZipFile, filename: str, content: str):
        if content:
            zipf.writestr(filename, content)

    def _update_catalog(self, id: str, title: str, one_line: str, dossier_ref: str,
                        payment_provider: str, provider_product_id: str, provider_price_id: str,
                        is_listed: bool,
                        price_pence: int,
                        content_key: Optional[str] = None,
                        content_hash: Optional[str] = None,
                        content_version: int = 1,
                        metadata: Optional[Dict[str, Any]] = None,
                        price_usd_cents: Optional[int] = None) -> bool:
        """Call the .NET Store API's /internal/catalog endpoint.

        `price_pence` is REQUIRED and has no default on purpose (C2). A default here would
        be a second source of truth for the price, silently disagreeing with the provider
        Price object the caller already minted — and the fulfilment fence reads the
        catalogue's number, so that disagreement charges a buyer and then refuses delivery.
        The caller passes the one `PriceDecision` it used for both.
        """
        url = f"{self.store_api_url}/internal/catalog"
        payload = {
            "id": id,
            "title": title,
            "oneLine": one_line,
            "dossierRef": dossier_ref,
            "paymentProvider": payment_provider,
            "providerProductId": provider_product_id,
            "providerPriceId": provider_price_id,
            "isListed": is_listed,
            # C2 — the caller's PriceDecision, the same one the provider Price was minted
            # at. Never re-derived here (see the docstring).
            "pricePence": int(price_pence),
            "contentVersion": content_version,
        }
        # OMITTED, not null, when there is no minted USD amount. The Store's PATCH contract
        # reads an omitted priceUsdCents as "unchanged" (PricePatchRequest), so sending an
        # explicit null on a republish that reused a live price would be indistinguishable
        # from a deliberate clear — taking US billability off a pack as a side effect of a
        # republish that never touched the currency at all.
        if price_usd_cents is not None:
            payload["priceUsdCents"] = int(price_usd_cents)
        if content_key is not None:
            payload["contentKey"] = content_key
        if content_hash is not None:
            payload["contentHash"] = content_hash
        # ---- house-copy choke point (2026-08-08) --------------------------------------
        # Applied after the metadata merge below, so it covers EVERY string reaching the
        # catalogue. See _normalise_catalog_payload for why this is a choke point and not
        # another call site.
        # Per-pack storefront/trust metadata (headline, sampleExtract, financialSnapshot, ...).
        # Optional and additive: the Store API ignores any field it doesn't yet model, so a
        # partial pack still publishes. Reserved keys above are never overwritten.
        if metadata:
            for k, v in metadata.items():
                payload.setdefault(k, v)

        payload = _normalise_catalog_payload(payload)

        # Fail closed: never publish without a configured key. The Store also 503s when its
        # key is unset; refusing here removes any reliance on a default credential and avoids
        # a pointless unauthenticated round-trip.
        if not self.internal_api_key:
            logger.error(
                f"EngineBridge: STORE_INTERNAL_API_KEY not set; refusing to publish {id}."
            )
            return False

        try:
            # Authenticate to the Store's internal endpoint. The server compares this
            # against its configured key in fixed time and rejects (401) on mismatch.
            headers = {"X-Internal-Key": self.internal_api_key}
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code == 200:
                logger.info(f"EngineBridge: Successfully updated Catalog for {id}")
                # Push the new URL to the IndexNow engines. Only for a LISTED pack: an unlisted
                # one is unbuyable (Program.cs:206 / CheckoutEndpoints.cs:271), so submitting it
                # would ask an index to fetch a page that cannot be sold from.
                #
                # Deliberately after the success branch and deliberately unchecked: this is a
                # discovery optimisation, and a search engine being unreachable must never turn a
                # completed publish into a failed one. `indexnow.submit` raises nothing and
                # no-ops when unconfigured, which is every machine without INDEXNOW_KEY set.
                if is_listed:
                    indexnow.submit_pack(id)
                return True
            else:
                logger.error(f"EngineBridge: Store API returned {response.status_code}: {response.text}")
                return False
        except Exception as e:
            logger.error(f"EngineBridge: Failed to connect to Store API at {url}: {e}")
            return False

class R2Uploader:
    """
    Uploads deliverables to Cloudflare R2 (S3-compatible) via boto3. Mirrors the .NET
    R2ContentStorage: if any credential is missing — or boto3 isn't installed — it stays
    unconfigured and the R2 path is skipped.

    Local dev fallback: when R2 is unconfigured but CONTENT_LOCAL_DIR is set, upload() copies
    the deliverable into that directory (keyed by the same object_key the Store serves from
    via LocalContentStorage). This keeps the list-only-after-upload invariant HONEST in dev —
    the content really is in the shared store the .NET API can deliver — instead of forcing
    every local pack to publish unlisted. With neither R2 nor a local dir, upload() is a no-op
    returning False and the invariant keeps the pack unlisted (never sell what we can't deliver).
    """
    def __init__(self) -> None:
        self.account_id = os.environ.get("R2_ACCOUNT_ID")
        self.access_key = os.environ.get("R2_ACCESS_KEY_ID")
        self.secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
        self.bucket = os.environ.get("R2_BUCKET")
        # Dev fallback content dir, shared with the .NET LocalContentStorage (Content:LocalDir).
        self.local_dir = os.environ.get("CONTENT_LOCAL_DIR")
        self._client = None

        if not all([self.account_id, self.access_key, self.secret_key, self.bucket]):
            return

        try:
            import boto3  # lazy: optional dependency, only needed when R2 is configured
            from botocore.config import Config as BotoConfig

            self._client = boto3.client(
                "s3",
                endpoint_url=f"https://{self.account_id}.r2.cloudflarestorage.com",
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                config=BotoConfig(signature_version="s3v4", region_name="auto"),
            )
        except ImportError:
            logger.error("R2Uploader: boto3 not installed; uploads disabled (pip install boto3).")
            self._client = None

    @property
    def is_configured(self) -> bool:
        return self._client is not None or bool(self.local_dir)

    def upload(self, local_path: Path, object_key: str) -> bool:
        """Upload a file to content storage. Returns False (never raises) if unconfigured or
        on error. Uses R2 when configured; otherwise the CONTENT_LOCAL_DIR dev fallback."""
        if self._client is not None:
            try:
                self._client.upload_file(
                    str(local_path), self.bucket, object_key,
                    ExtraArgs={"ContentType": "application/zip"},
                )
                logger.info(f"R2Uploader: Uploaded {object_key} to bucket {self.bucket}")
                return True
            except Exception as e:
                logger.error(f"R2Uploader: Upload of {object_key} failed: {e}")
                return False

        if self.local_dir:
            try:
                import shutil
                dest = Path(self.local_dir) / object_key
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(local_path, dest)
                logger.info(f"R2Uploader: Wrote {object_key} to local content dir {self.local_dir}")
                return True
            except Exception as e:
                logger.error(f"R2Uploader: Local content write of {object_key} failed: {e}")
                return False

        return False


class PaddleClient:
    """Minimal Paddle Billing API client."""
    def __init__(self, api_key: str, environment: str = "sandbox"):
        self.api_key = api_key
        self.base_url = "https://sandbox-api.paddle.com" if environment == "sandbox" else "https://api.paddle.com"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    def create_product(self, name: str, description: str, metadata: Dict[str, str]) -> str:
        url = f"{self.base_url}/products"
        payload = {
            "name": name,
            "tax_category": "digital-goods",
            "description": description,
            "custom_data": metadata
        }
        resp = requests.post(url, json=payload, headers=self.headers)
        resp.raise_for_status()
        return resp.json()["data"]["id"]

    def create_price(self, product_id: str, amount_pence: int, currency: str = "GBP",
                     usd_cents: Optional[int] = None) -> str:
        """`usd_cents` is accepted to satisfy the ProductProvisioner protocol and DELIBERATELY
        ignored: Paddle prices a product per-currency through its own overrides API, which this
        client does not call. Ignoring it is safe because the catalogue only records a USD price
        when the provisioner returns one (see EngineBridge's `minted_usd_cents`), so a Paddle
        pack simply stays GBP-only and the fulfilment fence refuses USD for it — rather than the
        pack being advertised in a currency Paddle was never told about.
        """
        url = f"{self.base_url}/prices"
        payload = {
            "product_id": product_id,
            "description": "One-off Pack Purchase",
            "unit_price": {
                "amount": str(amount_pence),
                "currency_code": currency
            },
            "quantity": {"minimum": 1, "maximum": 1}
        }
        resp = requests.post(url, json=payload, headers=self.headers)
        resp.raise_for_status()
        return resp.json()["data"]["id"]

    def describe_price(self, price_id: str) -> Optional[ExistingPrice]:
        """Resolve a live Paddle price to its product, amount and currency.

        Paddle has no idempotency keys on these endpoints at all, so it does not even have
        Stripe's 24-hour grace: EVERY republish would mint a duplicate without this lookup.
        Returns None on any failure — the caller reads that as "cannot verify" and reuses the
        catalogue's ids rather than minting.
        """
        try:
            resp = requests.get(f"{self.base_url}/prices/{price_id}",
                                headers=self.headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()["data"]
            unit = data["unit_price"]
            return ExistingPrice(str(data["product_id"]), int(unit["amount"]),
                                 str(unit.get("currency_code", "GBP")))
        except Exception as e:
            logger.error(f"PaddleClient: could not retrieve price {price_id}: {e}")
            return None


def _bundle_version(dossier, candidate) -> str:
    """A bundle version that is stable for the same logical publish of the same pack.

    Feeds Stripe product metadata, which is hashed into the idempotency-key fingerprint, so
    this MUST NOT be a wall clock. Prefers the dossier's own `created_at` (one dossier = one
    logical publish; a re-vet mints a new one and correctly earns a new key). Falls back to a
    content hash of the pack artifacts for dossiers that carry no timestamp — still stable
    for identical content, still changing when the content does, exactly like the `name` and
    `description` already in that fingerprint. Nothing downstream reads this value: grep for
    `bundle_version` finds this write and no reader.
    """
    created = str(getattr(dossier, "created_at", "") or "").strip()
    if created:
        return created
    arts = (getattr(candidate, "tags", {}) or {}).get("artifacts", {}) or {}
    digest = hashlib.sha256(
        json.dumps(arts, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()[:16]
    return f"sha256:{digest}"


class StripeProvisioner:
    """Stripe Product + Price provisioning for the publish path.
    Mirror of the .NET StripeProvider.CreateProductAsync — creates a one-off
    fixed-price digital product in Stripe (test or live) for the storefront.
    """
    def __init__(self, api_key: str):
        import stripe
        stripe.api_key = api_key
        self._stripe = stripe

    def create_product(self, name: str, description: str, metadata: Dict[str, str]) -> str:
        """Create a Stripe Product. Returns product ID. The Price is created separately by
        create_price (called once from publish_pass) so each product gets exactly one Price —
        creating one here too orphaned a Price in Stripe on every publish.

        Idempotent on (pack id, request parameters): a publish retry after a network blip
        replays an identical request under the same key and reuses the Stripe-side product
        instead of minting a duplicate. Stripe errors are re-raised as a domain
        ProvisioningError (with the request_id for the audit trail) so callers see a
        provisioning failure, not a leaked SDK exception.

        The parameter fingerprint is load-bearing, and keying on the pack id ALONE was a
        defect. A Stripe idempotency key is remembered for 24h and replaying it with
        different parameters is a hard error, not a no-op — and this product's `name` and
        `description` ARE the pack's copy. So any copy fix inside that window made the pack
        permanently unprovisionable instead of idempotent: measured 2026-08-08, both
        13795bea31feee47 and 2abc23c3c0d05bab failed with "Keys for idempotent requests can
        only be used with the same parameters they were first used with", leaving two packs
        that could never list. `create_price` has always keyed on (product, amount,
        currency); this makes the product key consistent with it. The property that matters
        is preserved exactly — an identical request never mints twice — and a duplicate on
        CHANGED copy is not reachable from here, because `publish_pass` only calls this when
        the catalogue holds no product id for the pack (:706 reuses the live rail otherwise).
        """
        pack_id = metadata.get("pack_id") or metadata.get("candidate_id") or name
        fingerprint = hashlib.sha256(json.dumps(
            {"name": name, "description": description, "metadata": metadata},
            sort_keys=True, ensure_ascii=False,
        ).encode("utf-8")).hexdigest()[:16]
        try:
            product = self._stripe.Product.create(
                name=name,
                description=description,
                metadata=metadata,
                idempotency_key=f"prospector-product-{pack_id}-{fingerprint}",
            )
        except self._stripe.error.StripeError as e:
            raise self._provisioning_error("product", e) from e
        logger.info(f"StripeProvisioner: Created product {product.id}")
        return product.id

    def create_price(self, product_id: str, amount_pence: int, currency: str = "gbp",
                     usd_cents: Optional[int] = None) -> str:
        """Create a Stripe Price. Returns price ID. (Product must already exist.) Idempotent on
        (product, amount, currency, usd_cents); Stripe errors re-raised as ProvisioningError.

        `usd_cents` adds a USD `currency_options` entry to the SAME Price object rather than
        minting a second Price. A second Price would give the pack two ids, and the catalogue
        stores one — so the fulfilment fence would be reading the floor of a price object the
        buyer was not charged against, which is the exact charged-then-refused failure the
        one-decision rule in this module exists to prevent. The checkout session picks between
        the entries by setting its own currency (StripeProvider.BuildSessionOptions).

        It is part of the idempotency key because Stripe rejects a replayed key with changed
        parameters outright: without it, the first republish that added a USD amount to a pack
        priced within the 24h window would fail the whole publish rather than mint the option.
        """
        options: dict[str, Any] = {}
        if usd_cents is not None:
            options["usd"] = {"unit_amount": int(usd_cents)}
        try:
            price = self._stripe.Price.create(
                product=product_id,
                unit_amount=amount_pence,
                currency=currency,
                idempotency_key=(
                    f"prospector-price-{product_id}-{amount_pence}-{currency}"
                    + (f"-usd{int(usd_cents)}" if usd_cents is not None else "")
                ),
                **({"currency_options": options} if options else {}),
            )
        except self._stripe.error.StripeError as e:
            raise self._provisioning_error("price", e) from e
        logger.info(f"StripeProvisioner: Created price {price.id} for product {product_id}")
        return price.id

    def describe_price(self, price_id: str) -> Optional[ExistingPrice]:
        """Resolve a live Stripe Price to its product, amount and currency.

        `Price.retrieve` rather than a metadata search on purpose: retrieve is immediately
        consistent and exact, where Stripe's search index lags object creation by up to a
        minute — and a lag here reads as "no existing price", which is precisely the answer
        that mints a duplicate.

        Returns None on any Stripe error rather than raising: a failed LOOKUP must not fail a
        publish. The caller treats None as "cannot verify" and reuses the catalogue's ids
        untouched, which is strictly safer than minting.
        """
        try:
            price = self._stripe.Price.retrieve(price_id)
        except self._stripe.error.StripeError as e:
            logger.error(f"StripeProvisioner: could not retrieve price {price_id}: {e}")
            return None
        product = price.get("product") if hasattr(price, "get") else getattr(price, "product", None)
        # An expanded price carries the Product object; an unexpanded one carries its id.
        if isinstance(product, dict):
            product = product.get("id")
        elif product is not None and not isinstance(product, str):
            product = getattr(product, "id", None)
        amount = price.get("unit_amount") if hasattr(price, "get") else getattr(price, "unit_amount", None)
        currency = price.get("currency") if hasattr(price, "get") else getattr(price, "currency", None)
        if not product or amount is None:
            logger.error(
                f"StripeProvisioner: price {price_id} has no product/unit_amount "
                f"(product={product!r}, unit_amount={amount!r}); cannot verify."
            )
            return None
        return ExistingPrice(str(product), int(amount), str(currency or "gbp"))

    @staticmethod
    def _provisioning_error(what: str, e: Exception) -> "ProvisioningError":
        request_id = getattr(e, "request_id", None)
        logger.error(
            f"StripeProvisioner: {what} creation failed (request_id={request_id}): {e}"
        )
        return ProvisioningError(f"Stripe {what} creation failed: {e}")
