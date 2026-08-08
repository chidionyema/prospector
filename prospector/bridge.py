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
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Protocol, Tuple
from urllib.parse import urlparse

import requests

from . import facet_derive, indexnow
from . import facets as facets_mod
from .copy_lint import buyer_readable, is_prose_artifact
from .models import Decision, Dossier, ScoreResult
from .pack_linter import lint_pack
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
                 bundle_complete: bool, lint_ok: bool) -> bool:
    """The single AND that decides sellability. Each operand is an independent fence
    computed in publish_pass (upload, completeness, price, bundle audit, content lint);
    keeping the composition in one named function makes the seam testable without the
    whole publish machinery."""
    return bool(uploaded and pack_complete and priced and bundle_complete and lint_ok)


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
_MONEY_RE = re.compile(r"\*\*Month 1:\*\*.*?=\s*\*\*(£[\d,]+)\*\*")
_LTV_RE = re.compile(r"LTV:CAC Ratio\s*\n\s*-\s*\*\*([\d.]+×)\*\*")
_PAYBACK_RE = re.compile(r"Payback Period\s*\n\s*-\s*\*\*~?(\d+)\s*months?\*\*")


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
        snap["paybackMonths"] = f"{m.group(1)} months"
    return snap


# Every file a complete bundle must contain. Asserted after the zip is written, so a
# structurally incomplete pack fails loudly at build time instead of at a buyer's download.
#
# 120 bytes is a deliberately low bar: it catches the header-only class of failure (the
# 20-byte "# Marketing Assets\n\n") without second-guessing `validate_pack`, which remains the
# real sellability gate. The claim-safe financial-model stub is ~150 bytes and must pass.
_MIN_BUNDLE_ENTRY_BYTES = 120
BUNDLE_FILES = (
    "00_Executive_Summary.md",
    "01_Blueprint_BuildSpec.md",
    "02_Marketing_Plan_GTM.md",
    "03_Operations_Plan.md",
    "04_Financial_Model.md",
    "05_First_Week_Checklist.md",
    "Marketing_Assets.md",
    "QA_Report.md",
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
    "QA_Report.md": "The QA Report, with the receipts",
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


def _trust_fields(dossier: Dossier) -> Dict[str, Any]:
    """Trust signals from the moat-verified dossier: how many checks cleared and how many
    distinct sources were cited. This is real, not a marketing number."""
    checks = dossier.checks or []
    total = len(checks)
    cleared = sum(1 for c in checks if c.verdict.value in ("supported", "unverifiable"))
    sources = len(dossier.all_sources)
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

    def create_price(self, product_id: str, amount_pence: int, currency: str) -> str:
        """Returns the provider's price ID."""
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

    def publish_pass(self, dossier: Dossier) -> bool:
        """
        Execute Phase 2 of the Build Plan:
        PASS -> zip bundle -> Paddle API (Product/Price/Upload) -> Store API (Catalog).
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
        floor = self.cfg.thresholds.confidence_floor
        n_supported = sum(
            1 for c in getattr(dossier, "checks", []) or []
            if getattr(getattr(c, "verdict", None), "value", None) == "supported"
            and getattr(c, "confidence", 0.0) >= floor
        )
        if n_supported < 1:
            logger.error(
                f"EngineBridge: Refusing to publish {dossier.candidate.candidate_id} "
                f"({dossier.candidate.title}) — 0 grounded-supported checks (source-or-die). "
                "Ungrounded 'pass'; will NOT list.",
                extra={"candidate_id": dossier.candidate.candidate_id, "n_supported": 0},
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
        if len(one_liner) > 150:
            head = one_liner[:150].rstrip()
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
        # Drop empties so the payload (and the Store API) only ever see populated fields.
        catalog_meta = {k: v for k, v in catalog_meta.items() if v not in ("", [], {}, None)}

        # 2. Create the bundle (.zip)
        bundle_path = self._create_bundle(dossier, artifacts, marketing)
        if not bundle_path:
            logger.error(f"EngineBridge: Failed to create bundle for {candidate_id}")
            return False

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
        if reused is not None:
            provider_product_id, provider_price_id, applied_price_pence = reused
            if applied_price_pence != price.price_pence:
                # The decision record must not read as though the new rung was applied.
                candidate.tags["price_decision"]["applied"] = False
                candidate.tags["price_decision"]["live_price_pence"] = applied_price_pence

        if reused is not None:
            pass  # already provisioned; minting anything here is the defect itself
        elif prov:
            try:
                logger.info(f"EngineBridge: Creating {payment_provider} product for {candidate_id}")
                metadata = {
                    "dossier_ref": dossier_ref,
                    "candidate_id": candidate_id,
                    "pack_id": candidate_id,
                    "bundle_version": datetime.utcnow().isoformat()
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
                    amount_pence=price.price_pence
                )

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
        if pack_complete:
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
        # presence and audit_bundle proves the zip reached storage; neither reads the
        # content. The full pre-slice texts are recomputed here so the truncation check can
        # compare each final rendered field against its source.
        listing_cfg = self.cfg.listing if isinstance(getattr(self.cfg, "listing", None), dict) else {}
        store_dir = getattr(self.cfg, "store_dir", None)
        store_dir = Path(store_dir) if isinstance(store_dir, (str, Path)) else None
        one_liner_full = to_plain_text(candidate.one_liner, collapse=True) or to_plain_text(
            listing_copy, collapse=True
        )
        lint_report = lint_pack(
            artifacts=artifacts,
            listing_copy=listing_copy,
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
            house_fields={"title": nodash(to_plain_text(candidate.title, collapse=True))},
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
        is_listed = listing_gate(
            uploaded=uploaded, pack_complete=pack_complete, priced=priced,
            bundle_complete=bundle_complete, lint_ok=lint_ok,
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
            written: Dict[str, str] = {}

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
                self._add_to_zip(zipf, "01_Blueprint_BuildSpec.md", build_spec_md)
                written["01_Blueprint_BuildSpec.md"] = build_spec_md

                gtm_md = prose_pass_document(
                    artifacts.get("gtm_plan", "") or _held_back_md("Go-to-market plan"))
                self._add_to_zip(zipf, "02_Marketing_Plan_GTM.md", gtm_md)
                written["02_Marketing_Plan_GTM.md"] = gtm_md

                ops_md = prose_pass_document(
                    artifacts.get("ops_plan", "") or _held_back_md("Operations plan"))
                self._add_to_zip(zipf, "03_Operations_Plan.md", ops_md)
                written["03_Operations_Plan.md"] = ops_md

                # 4. Financial Model — its own file, with a provenance banner. The arithmetic is
                # Python-computed from verified inputs (no LLM math), which is a real trust
                # differentiator, so we say so where the buyer reads it.
                # The prose around the arithmetic is engine-authored; the arithmetic itself is
                # Python-computed and the pass never touches a number that is not a stray
                # confidence float attached to a gate name.
                financials = prose_pass_document(artifacts.get("financial_model", ""))
                if financials:
                    financials = (
                        "> All figures below are computed by Python from verified inputs. No "
                        "language model performed any calculation, so the arithmetic is exact.\n\n"
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
                self._add_to_zip(zipf, "04_Financial_Model.md", financials)
                written["04_Financial_Model.md"] = financials

                # 5. QA Report
                from .dossier import render_markdown
                # The ONE surface that keeps its confidence figures: in the QA report the
                # number is the subject, not a stray internal. `keep_confidence_figures=True`
                # also inserts `CONFIDENCE_SCALE_NOTE` once, so a buyer never meets a bare
                # "0.0" without the sentence that says what the scale means.
                qa_report = prose_pass_document(
                    render_markdown(dossier), keep_confidence_figures=True)
                self._add_to_zip(zipf, "QA_Report.md", qa_report)
                written["QA_Report.md"] = qa_report

                # 6. Marketing Assets (Social, Email, SEO) — never a bare header stub.
                # The old loop appended a `##` heading per piece even when `copy` was empty,
                # so a marketing list of empty pieces produced exactly "# Marketing Assets\n\n"
                # — the 20-byte file. Skip empty pieces, then assert we wrote something real.
                sections = [
                    f"## {str(m.get('type', 'asset')).replace('_', ' ').title()}\n\n"
                    f"{(m.get('copy') or '').strip()}\n"
                    for m in marketing
                    if (m.get("copy") or "").strip()
                ]
                if not sections:
                    # ensure_marketing_floor above should make this unreachable; if it ever is
                    # reached, synthesise the floor directly rather than ship a header stub.
                    from .pack_floors import claim_safe_marketing
                    sections = [
                        f"## Listing Page\n\n{m['copy'].strip()}\n"
                        for m in claim_safe_marketing(
                            dossier.candidate, getattr(dossier, "checks", []) or []
                        )
                        if (m.get("copy") or "").strip()
                    ]
                marketing_text = prose_pass_document(
                    "# Marketing Assets\n\n" + "\n".join(sections))
                self._add_to_zip(zipf, "Marketing_Assets.md", marketing_text)
                written["Marketing_Assets.md"] = marketing_text

                # 7–8. Epic C lite floors (deterministic, claim-safe)
                # Deterministic floors, but not id-free: they embed `check.rationale`, which is
                # verdict-brain prose and carries the same passage ids as everything else.
                exec_summary_content = prose_pass_document(
                    exec_summary_md(dossier.candidate, getattr(dossier, "checks", []) or []))
                self._add_to_zip(zipf, "00_Executive_Summary.md", exec_summary_content)
                written["00_Executive_Summary.md"] = exec_summary_content

                checklist_content = prose_pass_document(
                    first_week_checklist_md(dossier.candidate))
                self._add_to_zip(zipf, "05_First_Week_Checklist.md", checklist_content)
                written["05_First_Week_Checklist.md"] = checklist_content

                # 9. index.html — the ONE non-.md file in the bundle: the same eight
                # deliverables above, rendered to a single polished, self-contained reading
                # experience (pack_html.py). Deliberately NOT added to BUNDLE_FILES/audit_bundle
                # — that tuple is the sellability contract with the storefront's PackContents.tsx
                # (a drift test binds the two), and this file is a bonus convenience, not a
                # promised deliverable a missing copy of which should block listing.
                # Guarded because the sentence above must be TRUE at runtime, not just in
                # intent: an unguarded render exception here would fail _create_bundle and
                # block the listing — exactly what "bonus, not promised" forbids. Loud
                # (warning, never silent) so a broken renderer can't rot unnoticed.
                # Files shipped that are NOT promised deliverables. Populated only AFTER a
                # successful write, never from the intent to write: the manifest below states a
                # sha256 for every entry it lists, and listing an entry the zip does not contain
                # would make the one file whose job is to be machine-checkable the one file that
                # lies.
                extra_written: Dict[str, str] = {}
                try:
                    from . import pack_html
                    pack_meta = pack_html.PackMeta(
                        title=dossier.candidate.title,
                        one_liner=getattr(dossier.candidate, "one_liner", "") or "",
                        verified_at=getattr(dossier, "created_at", "") or "",
                        source_count=len(dossier.all_sources) if getattr(dossier, "all_sources", None) else None,
                        pack_id=candidate_id,
                    )
                    # The reading order, taken from the contract rather than from the order
                    # the files happened to be written in. `if name in written` keeps a
                    # partially-built bundle renderable — such a pack is held UNLISTED by the
                    # completeness gate below, and a bonus file must never be the thing that
                    # raises on the retry path.
                    md_entries: List[Tuple[str, str]] = [
                        (_SECTION_TITLES[name], written[name])
                        for name in BUNDLE_FILES
                        if name in written
                    ]
                    index_html = pack_html.render_pack_html(md_entries, pack_meta)
                    self._add_to_zip(zipf, "index.html", index_html)
                    if index_html:
                        extra_written["index.html"] = index_html
                except Exception as e:  # noqa: BLE001 — bonus file; the 8 .md deliverables ship regardless
                    logger.warning(
                        f"index.html render failed for {candidate_id}: {e}; "
                        "shipping the 8-file bundle without it")

                # 10. manifest.jsonld — the machine-readable half of the pack: every file with its
                # sha256, every check with its verdict and confidence, and every source with its
                # URL, its fetch date and the exact passage the verdict was formed from. See
                # pack_manifest.py for why the passage travels with the pack and why the PRICE
                # never does.
                #
                # A bonus file on exactly the same terms as index.html above, and for the same
                # reason: BUNDLE_FILES is the sellability contract that storefront's
                # PackContents.tsx is drift-tested against, and a manifest is not one of the eight
                # documents a buyer is promised. Guarded so that a renderer fault can never be the
                # thing that blocks a listing — and loud, so it cannot rot unnoticed either.
                #
                # Written LAST, after index.html, so it can describe index.html. It describes
                # itself by omission: `render_manifest` skips MANIFEST_FILENAME, because a file
                # cannot carry the digest of its own final bytes.
                try:
                    from . import pack_manifest
                    manifest_json = pack_manifest.render_manifest(
                        dossier,
                        written,
                        BUNDLE_FILES,
                        _SECTION_TITLES,
                        candidate_id,
                        extra_files=extra_written,
                    )
                    self._add_to_zip(zipf, pack_manifest.MANIFEST_FILENAME, manifest_json)
                except Exception as e:  # noqa: BLE001 — bonus file; the 8 .md deliverables ship regardless
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
                        metadata: Optional[Dict[str, Any]] = None) -> bool:
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

    def create_price(self, product_id: str, amount_pence: int, currency: str = "GBP") -> str:
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

    def create_price(self, product_id: str, amount_pence: int, currency: str = "gbp") -> str:
        """Create a Stripe Price. Returns price ID. (Product must already exist.) Idempotent on
        (product, amount, currency); Stripe errors re-raised as ProvisioningError."""
        try:
            price = self._stripe.Price.create(
                product=product_id,
                unit_amount=amount_pence,
                currency=currency,
                idempotency_key=f"prospector-price-{product_id}-{amount_pence}-{currency}",
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
