#!/usr/bin/env python3
"""Backfill the in-zip HTML reader (index.html) into already-listed packs.

Packs bundled before prospector/pack_html.py shipped contain only the eight .md
deliverables. This tool retrofits index.html WITHOUT regenerating anything: the
.md bytes are read out of the pack's existing zip in R2 and copied into the new
zip byte-identical — zero model calls, zero content changes. (Deliberately NOT
`publish --reuse-artifacts`, which silently regenerates — model calls and a live
publish — whenever validate_pack is incomplete.)

Content storage is content-addressed (packs/<id>/<sha256-of-zip>.zip,
bridge.py:_sha256/content_key), so the new zip lands at a NEW object key and the
listing must be repointed. That uses the narrow door built for exactly this:
PATCH /internal/catalog/{id}/content — which can reach only the content pointer,
never price/provider/listing state. The old object is left in place: any
presigned download URL already in a buyer's hands keeps working.

Safety model:
  * --dry-run (default): fetch, rebuild, report. No upload, no PATCH.
  * --apply: upload new zip, then PATCH the listing. Requires STORE_INTERNAL_API_KEY.
  * A pack whose zip already contains index.html is skipped (idempotent).
  * A pack with several objects under packs/<id>/ is AMBIGUOUS (the API does not
    expose the current contentKey): skipped unless --take-newest, which uses the
    most recently modified object and says so in the report.

Env: R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET (storage);
STORE_INTERNAL_API_KEY (--apply only). API base via --api-url.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import sys
import zipfile
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prospector import pack_html  # noqa: E402

DEFAULT_API_URL = "https://api.mumchimp.com"


@dataclass
class PackResult:
    pack_id: str
    action: str  # converted | would-convert | already-has-html | ambiguous | no-object | error
    detail: str = ""
    old_key: str = ""
    new_key: str = ""
    size_delta: int = 0


@dataclass
class Report:
    results: List[PackResult] = field(default_factory=list)

    def add(self, r: PackResult) -> None:
        self.results.append(r)
        print(f"  [{r.action:>16}] {r.pack_id}  {r.detail}")

    def summary(self) -> str:
        counts: dict = {}
        for r in self.results:
            counts[r.action] = counts.get(r.action, 0) + 1
        return ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))


def rebuild_zip_with_index(zip_bytes: bytes, meta: pack_html.PackMeta) -> Optional[bytes]:
    """Return new zip bytes with index.html appended, or None if it is already there.

    Every existing entry is copied byte-identical, in its original order, so the
    .md deliverables of record are untouched — index.html is strictly additive.
    """
    src = zipfile.ZipFile(io.BytesIO(zip_bytes))
    names = src.namelist()
    if "index.html" in names:
        return None

    md_entries: List[Tuple[str, str]] = [
        (name[:-3], src.read(name).decode("utf-8", errors="replace"))
        for name in names
        if name.endswith(".md")
    ]
    index_html = pack_html.render_pack_html(md_entries, meta)

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for name in names:
            dst.writestr(name, src.read(name))
        dst.writestr("index.html", index_html)
    return out.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--api-url", default=DEFAULT_API_URL)
    ap.add_argument("--apply", action="store_true",
                    help="upload new zips and repoint listings (default: dry-run report only)")
    ap.add_argument("--take-newest", action="store_true",
                    help="when a pack has several stored objects, use the most recent instead of skipping")
    ap.add_argument("--only", metavar="PACK_ID", action="append",
                    help="restrict to specific pack id(s); repeatable")
    args = ap.parse_args()

    import boto3  # deferred: only needed at run time, mirrors bridge.R2Uploader
    import requests
    from botocore.config import Config as BotoConfig

    account_id = os.environ.get("R2_ACCOUNT_ID")
    bucket = os.environ.get("R2_BUCKET")
    if not all([account_id, os.environ.get("R2_ACCESS_KEY_ID"),
                os.environ.get("R2_SECRET_ACCESS_KEY"), bucket]):
        print("R2_* env not fully configured; cannot read or write content storage.", file=sys.stderr)
        return 2

    internal_key = os.environ.get("STORE_INTERNAL_API_KEY")
    if args.apply and not internal_key:
        print("--apply needs STORE_INTERNAL_API_KEY to repoint listings; refusing.", file=sys.stderr)
        return 2

    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        config=BotoConfig(signature_version="s3v4", region_name="auto"),
    )

    catalog = requests.get(f"{args.api_url}/catalog", timeout=15)
    catalog.raise_for_status()
    packs = catalog.json()
    if args.only:
        packs = [p for p in packs if p.get("id") in set(args.only)]
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"{mode}: {len(packs)} listed pack(s) from {args.api_url}/catalog\n")

    def current_key(pid: str) -> Tuple[Optional[str], str]:
        """The object key this listing actually serves, and how we know.

        Authority order: the internal content endpoint (the database's own pointer),
        then an unambiguous single stored object, then --take-newest as an explicit
        operator override. Newest-by-LastModified alone is wrong exactly when a past
        upload succeeded but its catalog update failed — the orphan looks current.
        """
        if internal_key:
            r = requests.get(f"{args.api_url}/internal/catalog/{pid}/content",
                             headers={"X-Internal-Key": internal_key}, timeout=15)
            if r.status_code == 200 and r.json().get("contentKey"):
                return r.json()["contentKey"], "db-pointer"
        listing = s3.list_objects_v2(Bucket=bucket, Prefix=f"packs/{pid}/")
        objects = listing.get("Contents", [])
        if not objects:
            return None, "no-object"
        if len(objects) == 1:
            return objects[0]["Key"], "single-object"
        if args.take_newest:
            objects.sort(key=lambda o: o["LastModified"], reverse=True)
            return objects[0]["Key"], "take-newest"
        keys = ", ".join(o["Key"].rsplit("/", 1)[-1] for o in objects)
        return None, f"{len(objects)} objects ({keys})"

    report = Report()
    for pack in packs:
        pid = pack.get("id", "")
        try:
            old_key, how = current_key(pid)
            if old_key is None:
                if how == "no-object":
                    report.add(PackResult(pid, "no-object",
                                          "listed but nothing under its prefix — investigate before touching"))
                else:
                    report.add(PackResult(pid, "ambiguous",
                                          f"{how}; no db pointer available — deploy the content "
                                          "endpoint (or --take-newest to override)"))
                continue

            zip_bytes = s3.get_object(Bucket=bucket, Key=old_key)["Body"].read()

            # Details endpoint carries the metadata the reader's header shows. Fields the
            # projection lacks stay blank rather than being guessed.
            details = requests.get(f"{args.api_url}/catalog/{pid}", timeout=15)
            details.raise_for_status()
            d = details.json()
            meta = pack_html.PackMeta(
                title=d.get("title") or pack.get("title") or pid,
                one_liner=d.get("oneLine") or "",
                verified_at=d.get("verifiedAt") or "",
                source_count=d.get("sourceCount"),
                pack_id=pid,
            )

            new_bytes = rebuild_zip_with_index(zip_bytes, meta)
            if new_bytes is None:
                report.add(PackResult(pid, "already-has-html", old_key.rsplit("/", 1)[-1]))
                continue

            new_hash = hashlib.sha256(new_bytes).hexdigest()
            new_key = f"packs/{pid}/{new_hash}.zip"
            delta = len(new_bytes) - len(zip_bytes)

            if not args.apply:
                report.add(PackResult(pid, "would-convert",
                                      f"{len(zip_bytes)}B -> {len(new_bytes)}B (+{delta}B)",
                                      old_key, new_key, delta))
                continue

            s3.put_object(Bucket=bucket, Key=new_key, Body=new_bytes,
                          ContentType="application/zip")
            patch = requests.patch(
                f"{args.api_url}/internal/catalog/{pid}/content",
                json={"contentKey": new_key, "contentHash": new_hash,
                      "reason": "index.html reader backfill (bundle format, no content change)"},
                headers={"X-Internal-Key": internal_key},
                timeout=15,
            )
            if patch.status_code != 200:
                # Upload succeeded but the repoint failed: the listing still serves the OLD
                # zip, so nothing is broken — the new object is just unreferenced. Loud so
                # the operator retries rather than assuming conversion.
                report.add(PackResult(pid, "error",
                                      f"uploaded {new_key} but PATCH returned {patch.status_code}: {patch.text[:200]}"))
                continue

            report.add(PackResult(pid, "converted", f"+{delta}B -> {new_key}",
                                  old_key, new_key, delta))
        except Exception as e:  # noqa: BLE001 — per-pack isolation: one failure never stops the sweep
            report.add(PackResult(pid, "error", str(e)))

    print(f"\n{mode} complete: {report.summary()}")
    errors = sum(1 for r in report.results if r.action in ("error", "no-object"))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
