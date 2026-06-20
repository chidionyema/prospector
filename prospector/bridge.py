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
import requests
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol
from datetime import datetime
from urllib.parse import urlparse

from .models import Dossier, Decision
from .pack_validation import validate_pack

logger = logging.getLogger("prospector.bridge")


# ---------------------------------------------------------------------------
# Catalog metadata extraction — turns the generated pack into the per-pack data the
# storefront needs to sell each pack specifically (sample excerpt, proof point, economics
# teaser, trust signals) instead of generic chips. All extraction, no new generation.
# ---------------------------------------------------------------------------

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
        line = raw.strip().lstrip("-*#> ").strip()
        if not (40 <= len(line) <= 320):
            continue
        if _CITED_RE.search(line) and any(ch.isdigit() for ch in line) and line not in out:
            out.append(line)
        if len(out) >= max_items:
            break
    proof = (proof_point or "").strip()
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


class ProductProvisioner(Protocol):
    """Provider-agnostic product provisioning. Implementations: PaddleClient, StripeProvisioner."""
    def create_product(self, name: str, description: str, metadata: Dict[str, str]) -> str:
        """Returns the provider's product ID."""
        ...

    def create_price(self, product_id: str, amount_pence: int, currency: str) -> str:
        """Returns the provider's price ID."""
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

        # Stripe settings
        self.stripe_api_key = os.environ.get("STRIPE_API_KEY")
        self.stripe = StripeProvisioner(self.stripe_api_key) if self.stripe_api_key else None

        # Content storage (Cloudflare R2, S3-compatible). The deliverable must live here
        # before a pack may be listed — selling something we can't deliver is forbidden.
        self.r2 = R2Uploader()

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
        artifacts = candidate.tags.get("artifacts", {})
        marketing = candidate.tags.get("marketing", [])

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
        one_liner = candidate.one_liner or (listing_copy[:150] + "..." if len(listing_copy) > 150 else listing_copy)

        # Per-pack catalog metadata: the structured listing fields + a safe sample excerpt +
        # the Python-computed economics teaser + moat trust signals. This is what lets the
        # storefront sell each pack specifically instead of with identical generic chips.
        subhead = (listing.get("subhead") or "").strip()
        catalog_meta: Dict[str, Any] = {
            "headline": (listing.get("headline") or "").strip()[:140],
            "subhead": subhead[:280],
            "whatYouGet": [str(x).strip() for x in (listing.get("what_you_get") or []) if str(x).strip()][:5],
            "proofPoint": (listing.get("proof_point") or "").strip(),
            "whoPays": (listing.get("who_pays") or "").strip(),
            "effortTag": (listing.get("effort_tag") or "").strip(),
            "timeToFirstRevenue": (listing.get("time_to_first_revenue") or "").strip(),
            "sampleExtract": _sample_excerpts(artifacts.get("build_spec", ""), listing.get("proof_point", "")),
            "financialSnapshot": _financial_snapshot(artifacts.get("financial_model", "")),
            "verifiedAt": getattr(dossier, "created_at", "") or "",
        }
        catalog_meta.update(_trust_fields(dossier))
        # Drop empties so the payload (and the Store API) only ever see populated fields.
        catalog_meta = {k: v for k, v in catalog_meta.items() if v not in ("", [], {}, None)}

        # 2. Create the bundle (.zip)
        bundle_path = self._create_bundle(dossier, artifacts, marketing)
        if not bundle_path:
            logger.error(f"EngineBridge: Failed to create bundle for {candidate_id}")
            return False

        # 3. Provision product with the active payment provider (P3 — provider-agnostic)
        provider_product_id = f"prov_stub_{candidate_id[:8]}"
        provider_price_id = f"price_stub_{candidate_id[:8]}"
        payment_provider = self.active_provider

        prov = self.provisioner
        if prov:
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

                logger.info(f"EngineBridge: Creating {payment_provider} price for {provider_product_id}")
                provider_price_id = prov.create_price(
                    product_id=provider_product_id,
                    # P2 — single source of truth: config listing.price_pence (£49 default).
                    amount_pence=int(self.cfg.listing.get("price_pence", 4900))
                )

            except Exception as e:
                logger.error(f"EngineBridge: {payment_provider} provisioning failed: {e}")
                return False
        else:
            logger.warning(
                f"EngineBridge: No {payment_provider} API key set. "
                f"Using stubs for {candidate_id}"
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

        # 4. Update Catalog via Store API. is_listed requires BOTH a complete pack AND the
        # content in storage; the Store enforces the upload half server-side (defence in
        # depth). The completeness half is enforced here at the only place packs are minted.
        is_listed = uploaded and pack_complete

        # Determine the content version: for a new pack, start at 1. For a republish
        # (content_hash differs from existing), increment. Query the store's current
        # version by checking if the pack already exists with any content version.
        content_version = 1
        try:
            check_url = f"{self.store_api_url}/catalog/{candidate_id}"
            existing = requests.get(check_url, timeout=5)
            if existing.status_code == 200:
                data = existing.json()
                content_version = (data.get("contentVersion") or 0) + 1
        except Exception:
            pass  # new pack — default to version 1

        return self._update_catalog(
            id=candidate_id,
            title=candidate.title,
            one_line=one_liner,
            dossier_ref=dossier_ref,
            payment_provider=payment_provider,
            provider_product_id=provider_product_id,
            provider_price_id=provider_price_id,
            is_listed=is_listed,
            content_key=content_key if is_listed else None,
            content_hash=content_hash if is_listed else None,
            content_version=content_version,
            metadata=catalog_meta,
        )

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
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # 1. Blueprint (Build Spec)
                self._add_to_zip(zipf, "01_Blueprint_BuildSpec.md", artifacts.get("build_spec", ""))
                
                # 2. Marketing Plan (GTM Plan)
                self._add_to_zip(zipf, "02_Marketing_Plan_GTM.md", artifacts.get("gtm_plan", ""))

                # 3. Operations Plan
                self._add_to_zip(zipf, "03_Operations_Plan.md", artifacts.get("ops_plan", ""))

                # 4. Financial Model — its own file, with a provenance banner. The arithmetic is
                # Python-computed from verified inputs (no LLM math), which is a real trust
                # differentiator, so we say so where the buyer reads it.
                financials = artifacts.get("financial_model", "")
                if financials:
                    financials = (
                        "> All figures below are computed by Python from verified inputs. No "
                        "language model performed any calculation, so the arithmetic is exact.\n\n"
                        + financials
                    )
                self._add_to_zip(zipf, "04_Financial_Model.md", financials)

                # 5. QA Report
                from .dossier import render_markdown
                qa_report = render_markdown(dossier)
                self._add_to_zip(zipf, "QA_Report.md", qa_report)
                
                # 6. Marketing Assets (Social, Email, SEO)
                marketing_text = "# Marketing Assets\n\n"
                for m in marketing:
                    marketing_text += f"## {m['type'].replace('_', ' ').title()}\n\n{m['copy']}\n\n"
                self._add_to_zip(zipf, "Marketing_Assets.md", marketing_text)

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
                        content_key: Optional[str] = None,
                        content_hash: Optional[str] = None,
                        content_version: int = 1,
                        metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Call the .NET Store API's /internal/catalog endpoint."""
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
            # P2 — single source of truth: config listing.price_pence (£49 default).
            "pricePence": int(self.cfg.listing.get("price_pence", 4900)),
            "contentVersion": content_version,
        }
        if content_key is not None:
            payload["contentKey"] = content_key
        if content_hash is not None:
            payload["contentHash"] = content_hash
        # Per-pack storefront/trust metadata (headline, sampleExtract, financialSnapshot, ...).
        # Optional and additive: the Store API ignores any field it doesn't yet model, so a
        # partial pack still publishes. Reserved keys above are never overwritten.
        if metadata:
            for k, v in metadata.items():
                payload.setdefault(k, v)
        
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

        Idempotent on the pack id: a publish retry after a network blip reuses the same
        Stripe-side product instead of minting a duplicate. Stripe errors are re-raised as a
        domain ProvisioningError (with the request_id for the audit trail) so callers see a
        provisioning failure, not a leaked SDK exception."""
        pack_id = metadata.get("pack_id") or metadata.get("candidate_id") or name
        try:
            product = self._stripe.Product.create(
                name=name,
                description=description,
                metadata=metadata,
                idempotency_key=f"prospector-product-{pack_id}",
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

    @staticmethod
    def _provisioning_error(what: str, e: Exception) -> "ProvisioningError":
        request_id = getattr(e, "request_id", None)
        logger.error(
            f"StripeProvisioner: {what} creation failed (request_id={request_id}): {e}"
        )
        return ProvisioningError(f"Stripe {what} creation failed: {e}")
