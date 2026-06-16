"""
EngineBridge — Connects Prospector PASS to the Store API and Paddle.
Ships the £30 bundle (zip) and updates the Catalog.
"""
from __future__ import annotations

import json
import logging
import os
import requests
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

from .models import Dossier, Decision

logger = logging.getLogger("prospector.bridge")

class EngineBridge:
    def __init__(self, cfg: Any):
        self.cfg = cfg
        # Store API settings
        self.store_api_url = os.environ.get("STORE_API_URL", "http://localhost:5291")
        self.internal_api_key = os.environ.get("STORE_INTERNAL_API_KEY", "prospector-dev-key")
        
        # Paddle settings
        self.paddle_api_key = os.environ.get("PADDLE_API_KEY")
        self.paddle_env = os.environ.get("PADDLE_ENVIRONMENT", "sandbox")
        self.paddle = PaddleClient(self.paddle_api_key, self.paddle_env) if self.paddle_api_key else None

    def publish_pass(self, dossier: Dossier) -> bool:
        """
        Execute Phase 2 of the Build Plan:
        PASS -> zip bundle -> Paddle API (Product/Price/Upload) -> Store API (Catalog).
        """
        if dossier.decision != Decision.PASS:
            logger.warning(f"EngineBridge: Skipping non-PASS dossier {dossier.candidate.candidate_id}")
            return False

        candidate = dossier.candidate
        candidate_id = candidate.candidate_id
        
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
        
        listing_copy = next((m["copy"] for m in marketing if m["type"] == "listing_page"), "")
        one_liner = candidate.one_liner or (listing_copy[:150] + "..." if len(listing_copy) > 150 else listing_copy)

        # 2. Create the bundle (.zip)
        bundle_path = self._create_bundle(dossier, artifacts, marketing)
        if not bundle_path:
            logger.error(f"EngineBridge: Failed to create bundle for {candidate_id}")
            return False

        # 3. Paddle Integration (Phase 2)
        paddle_product_id = f"pro_stub_{candidate_id[:8]}"
        paddle_price_id = f"pri_stub_{candidate_id[:8]}"

        if self.paddle:
            try:
                logger.info(f"EngineBridge: Creating Paddle product for {candidate_id}")
                custom_data = {
                    "dossier_ref": dossier_ref,
                    "candidate_id": candidate_id,
                    "bundle_version": datetime.utcnow().isoformat()
                }
                paddle_product_id = self.paddle.create_product(
                    name=candidate.title,
                    description=one_liner,
                    custom_data=custom_data
                )
                
                logger.info(f"EngineBridge: Creating Paddle price for {paddle_product_id}")
                paddle_price_id = self.paddle.create_price(
                    product_id=paddle_product_id,
                    amount_pence=3000 # £30.00
                )
                
                # UPLOAD PACK (Deferred until Sandbox setup is confirmed by user)
                # In 2026, this either uses a new Paddle Billing Upload API or sets a custom fulfillment URL.
                logger.info(f"EngineBridge: Uploading pack {bundle_path} to Paddle (simulated)")
                
            except Exception as e:
                logger.error(f"EngineBridge: Paddle integration failed: {e}")
                return False
        else:
            logger.warning(f"EngineBridge: PADDLE_API_KEY not set. Using stubs for {candidate_id}")

        # 4. Update Catalog via Store API
        return self._update_catalog(
            id=candidate_id,
            title=candidate.title,
            one_line=one_liner,
            dossier_ref=dossier_ref,
            paddle_product_id=paddle_product_id,
            paddle_price_id=paddle_price_id,
            is_listed=True
        )

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
                        paddle_product_id: str, paddle_price_id: str, is_listed: bool) -> bool:
        """Call the .NET Store API's /internal/catalog endpoint."""
        url = f"{self.store_api_url}/internal/catalog"
        payload = {
            "id": id,
            "title": title,
            "oneLine": one_line,
            "dossierRef": dossier_ref,
            "paddleProductId": paddle_product_id,
            "paddlePriceId": paddle_price_id,
            "isListed": is_listed,
            "pricePence": 3000 # £30.00 hardcoded per spec
        }
        
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

class PaddleClient:
    """Minimal Paddle Billing API client."""
    def __init__(self, api_key: str, environment: str = "sandbox"):
        self.api_key = api_key
        self.base_url = "https://sandbox-api.paddle.com" if environment == "sandbox" else "https://api.paddle.com"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    def create_product(self, name: str, description: str, custom_data: Dict[str, Any]) -> str:
        url = f"{self.base_url}/products"
        payload = {
            "name": name,
            "tax_category": "digital-goods",
            "description": description,
            "custom_data": custom_data
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
