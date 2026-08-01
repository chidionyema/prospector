#!/usr/bin/env python3
"""Backfill (or correct) the in-zip HTML reader, index.html, on already-listed packs.

Packs bundled before prospector/pack_html.py shipped contain only the eight .md
deliverables. This tool retrofits index.html WITHOUT regenerating anything: the
.md bytes are read out of the pack's existing zip in R2 and copied into the new
zip byte-identical — zero model calls, zero content changes. (Deliberately NOT
`publish --reuse-artifacts`, which silently regenerates — model calls and a live
publish — whenever validate_pack is incomplete.)

It also CORRECTS a reader that is present but wrong, which is the case for every
pack listed today. The reader used to be built from the zip's own entry order,
and the bundle is written 01, 02, 03, 04, QA, Marketing, 00, 05 — so the reader
opened on the build spec, buried the executive summary seventh, and put the
first-week checklist, the one document that tells a buyer what to do, last. The
generator was fixed to take its order from the BUNDLE_FILES contract instead;
this tool now does the same, so the shelf can be brought in line with it.

Only the generated index.html is ever written or replaced. The .md deliverables
of record are never rewritten — that would be editing a document someone already
paid for, which is a different decision and not this tool's to make.

Content storage is content-addressed (packs/<id>/<sha256-of-zip>.zip,
bridge.py:_sha256/content_key), so the new zip lands at a NEW object key and the
listing must be repointed. That uses the narrow door built for exactly this:
PATCH /internal/catalog/{id}/content — which can reach only the content pointer,
never price/provider/listing state. The old object is left in place: any
presigned download URL already in a buyer's hands keeps working.

Safety model:
  * --dry-run (default): fetch, rebuild, report. No upload, no PATCH.
  * --apply: upload new zip, then PATCH the listing. Requires STORE_INTERNAL_API_KEY.
  * A pack whose index.html already renders exactly what this tool would write is
    skipped. Idempotency is by CONTENT, not by presence — a pack carrying the old
    write-order reader is corrected, not treated as already done.
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
from prospector.bridge import BUNDLE_FILES, _SECTION_TITLES  # noqa: E402

DEFAULT_API_URL = "https://api.mumchimp.com"


@dataclass
class PackResult:
    pack_id: str
    action: str  # converted | would-convert | already-correct | ambiguous | no-object | error
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


def ordered_md_entries(src: zipfile.ZipFile) -> List[Tuple[str, str]]:
    """The zip's .md files as ``(display_title, markdown)``, in READING order.

    Reading order comes from the ``BUNDLE_FILES`` contract, exactly as the generator now takes
    it (bridge.py, the `md_entries` comprehension feeding render_pack_html) — deliberately NOT
    from the zip's own entry order. Those two are not the same thing: the bundle is written
    01, 02, 03, 04, QA, Marketing, 00, 05, so a reader built from write order opens on the
    build spec and buries the executive summary seventh and the checklist last. That is the
    defect this function exists to stop repeating on already-listed packs.

    Titles come from the same `_SECTION_TITLES` map the generator uses, so a backfilled reader
    and a freshly generated one label the same file identically ("Executive Summary", not
    "00_Executive_Summary").

    Any .md not in the contract keeps its original relative position at the end rather than
    being dropped: this tool's whole promise is that it does not lose content, and a legacy
    bundle with an extra file must still render all of it.
    """
    names = src.namelist()
    md = [n for n in names if n.endswith(".md")]
    known = [n for n in BUNDLE_FILES if n in md]
    extra = [n for n in md if n not in set(BUNDLE_FILES)]
    return [
        (_SECTION_TITLES.get(n, n[:-3]), src.read(n).decode("utf-8", errors="replace"))
        for n in known + extra
    ]


def rebuild_zip_with_index(zip_bytes: bytes, meta: pack_html.PackMeta) -> Optional[bytes]:
    """Return new zip bytes carrying a correct index.html, or None if it is already correct.

    Every .md entry is copied byte-identical, in its original order, so the deliverables of
    record are untouched — only the generated index.html is written or replaced.

    Idempotency is by CONTENT, not by presence. The first version of this tool skipped any
    bundle that already had an index.html, which meant a pack backfilled with the old
    write-order reader could never be corrected: it was permanently "done" while opening on
    the wrong page. Rendering and comparing costs one render per pack and makes the tool safe
    to re-run after any reader change.
    """
    src = zipfile.ZipFile(io.BytesIO(zip_bytes))
    names = src.namelist()
    index_html = pack_html.render_pack_html(ordered_md_entries(src), meta)

    if "index.html" in names and src.read("index.html").decode("utf-8", errors="replace") == index_html:
        return None

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for name in names:
            # The stale reader is dropped here and rewritten below, so a corrected bundle can
            # never end up with two index.html members (zipfile permits duplicates silently,
            # and readers disagree about which one wins).
            if name == "index.html":
                continue
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
                report.add(PackResult(pid, "already-correct", old_key.rsplit("/", 1)[-1]))
                continue

            new_hash = hashlib.sha256(new_bytes).hexdigest()
            new_key = f"packs/{pid}/{new_hash}.zip"
            delta = len(new_bytes) - len(zip_bytes)
            # Two different jobs under one action, worth telling apart in the log: a pack that
            # never had a reader is gaining one, a pack that had the write-order reader is
            # having it corrected. Only the second is a change to what an existing buyer sees.
            kind = "reordered reader" if "index.html" in zipfile.ZipFile(
                io.BytesIO(zip_bytes)).namelist() else "new reader"
            sized = f"{len(zip_bytes)}B -> {len(new_bytes)}B ({delta:+d}B, {kind})"

            if not args.apply:
                report.add(PackResult(pid, "would-convert", sized, old_key, new_key, delta))
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

            report.add(PackResult(pid, "converted", f"{delta:+d}B, {kind} -> {new_key}",
                                  old_key, new_key, delta))
        except Exception as e:  # noqa: BLE001 — per-pack isolation: one failure never stops the sweep
            report.add(PackResult(pid, "error", str(e)))

    print(f"\n{mode} complete: {report.summary()}")
    errors = sum(1 for r in report.results if r.action in ("error", "no-object"))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
