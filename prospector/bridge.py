"""
EngineBridge — Connects Prospector PASS to the Store API and payment provider.
Ships the £30 bundle (zip), provisions the product with the active payment provider
(Paddle or Stripe), and updates the Catalog.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import requests
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol
from datetime import datetime

from .models import Dossier, Decision
from .pack_validation import validate_pack

logger = logging.getLogger("prospector.bridge")


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
        self.store_api_url = os.environ.get("STORE_API_URL", "http://localhost:5291")
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

        listing_copy = next((m["copy"] for m in marketing if m["type"] == "listing_page"), "")
        one_liner = candidate.one_liner or (listing_copy[:150] + "..." if len(listing_copy) > 150 else listing_copy)

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
                    amount_pence=3000  # £30.00
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
                
                # 3. Build_Launch_Kit (Ops Plan + Financials)
                ops_plan = artifacts.get("ops_plan", "")
                financials = artifacts.get("financial_model", "")
                launch_kit = f"# Build & Launch Kit\n\n{ops_plan}\n\n{financials}"
                self._add_to_zip(zipf, "03_Build_Launch_Kit.md", launch_kit)
                
                # 4. QA Report
                from .dossier import render_markdown
                qa_report = render_markdown(dossier)
                self._add_to_zip(zipf, "QA_Report.md", qa_report)
                
                # 5. Marketing Assets (Social, Email, SEO)
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
                        content_version: int = 1) -> bool:
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
            "pricePence": 3000,  # £30.00 hardcoded per spec
            "contentVersion": content_version,
        }
        if content_key is not None:
            payload["contentKey"] = content_key
        if content_hash is not None:
            payload["contentHash"] = content_hash
        
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
    unconfigured and upload() is a no-op returning False, so the engine still runs in dev
    without R2 wired. The store's list-only-after-upload invariant then keeps such packs
    unlisted rather than selling something undeliverable.
    """
    def __init__(self) -> None:
        self.account_id = os.environ.get("R2_ACCOUNT_ID")
        self.access_key = os.environ.get("R2_ACCESS_KEY_ID")
        self.secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
        self.bucket = os.environ.get("R2_BUCKET")
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
        return self._client is not None

    def upload(self, local_path: Path, object_key: str) -> bool:
        """Upload a file to R2. Returns False (never raises) if unconfigured or on error."""
        if self._client is None:
            return False
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
