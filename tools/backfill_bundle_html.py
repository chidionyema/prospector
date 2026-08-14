#!/usr/bin/env python3
"""Backfill (or correct) the two GENERATED files on already-listed packs: the in-zip HTML
reader, index.html, and the machine-readable manifest, manifest.jsonld.

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

The generated files (index.html, manifest.jsonld) are written or replaced freely.
The .md deliverables of record are copied byte-identical with exactly ONE
exception, taken deliberately and kept as narrow as a single line: the retired
`Evidence goes stale after: <ISO stamp>` footer (see `patched_md`). That line
printed an internal cron stamp as if it were a warranty expiry on a document
someone paid £49.99 for; leaving it in place is not neutrality, it is continuing
to make a promise we never priced. Every other byte of every deliverable is
untouched, and rewriting anything further is a different decision and not this
tool's to make.

manifest.jsonld carries the evidence (every check, verdict and cited passage),
which exists only in this repo's store/dossiers, never in the shipped zip. A pack
whose dossier is no longer on disk therefore gets its reader corrected and is
reported `no-dossier` — it is never given an EMPTY manifest, which an agent would
read as "this pack was never verified".

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
import json
import os
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prospector import dossier as dossier_render  # noqa: E402
from prospector import (  # noqa: E402
    models,
    pack_card,
    pack_checklist,
    pack_html,
    pack_manifest,
    pack_pdf,
    pack_reference,
    pack_table,
)
from prospector.bridge import _SECTION_TITLES, BUNDLE_FILES, BUNDLE_READING_ORDER  # noqa: E402

# Env-overridable so a backfill can be pointed at staging. This script PATCHes live
# catalogue rows; a hardcoded production constant means there is no way to rehearse
# one except against the real store.
DEFAULT_API_URL = os.environ.get("STORE_API_URL", "https://api.mumchimp.com")


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
        out = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        # A pack whose PDF failed to render is `already-correct` by the idempotence check
        # (`pdf_ok` is True when there is nothing to compare), which reads as done and is not.
        # Measured 2026-08-14: three packs reported already-correct while shipping no PDF at
        # all, because one `***triple asterisk***` asked for a font face that was not vendored.
        # The count is named here so a silent deliverable loss cannot hide inside a green run.
        if PDF_FAILURES:
            out += (f"\n  WITHOUT Complete_Pack.pdf: {len(PDF_FAILURES)} pack(s) — "
                    + ", ".join(sorted(PDF_FAILURES)))
        return out


#: Pack ids whose PDF render raised this run. Module-level because the render happens deep
#: inside `rebuild_zip_with_index`, whose return type says "the new zip or nothing to do" and
#: has no room for a third answer.
PDF_FAILURES: List[str] = []


def patched_md(name: str, raw: bytes) -> bytes:
    """The bytes to ship for one .md entry: usually the originals, unchanged.

    THE ONE DELIBERATE EXCEPTION to "every .md is copied byte-identical". A live pack's footer
    printed `Evidence goes stale after: <ISO stamp>` — `reverify_due_at`, an internal scheduling
    field (`run.py:813`) that tells the decay sweep when to look again. To a buyer it reads as a
    warranty with a cliff: bought on day 28, the document says three days left. The rewrite is
    the single shared renderer (`dossier.rewrite_legacy_shelf_life`), so a backfilled pack and a
    freshly generated one make exactly the same promise. Idempotent by construction: a pack
    already carrying the new wording does not match, and comes back unchanged.
    """
    if not name.endswith(".md"):
        return raw
    text = raw.decode("utf-8", errors="replace")
    rewritten = dossier_render.rewrite_legacy_shelf_life(text)
    return raw if rewritten is None else rewritten.encode("utf-8")


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
    payload = (
        {n: src.read(n) for n in src.namelist()}
        if hasattr(src, "namelist") else dict(src)
    )
    md = [n for n in payload if n.endswith(".md")]
    known = [n for n in BUNDLE_READING_ORDER if n in md]
    extra = [n for n in md if n not in set(BUNDLE_READING_ORDER)]
    return [
        (_SECTION_TITLES.get(n, n[:-3]),
         patched_md(n, payload[n]).decode("utf-8", errors="replace"))
        for n in known + extra
    ]


DOSSIER_DIR = Path(os.environ.get("PROSPECTOR_DOSSIER_DIR", "store/dossiers"))


def load_local_dossier(pack_id: str) -> Optional[Any]:
    """The stored dossier for a listed pack, in the shape `pack_manifest` reads, or None.

    The manifest's whole value is the EVIDENCE — every check with its verdict, and every source
    with its URL and the passage the verdict was formed from. None of that survives in the shipped
    zip: the .md files carry the prose conclusions, not the machine-readable record. So unlike
    index.html, which this tool can rebuild from the zip alone, a manifest can only be backfilled
    where the dossier that produced the pack is still on this disk.

    A pack whose dossier is missing is REPORTED and skipped for the manifest, never given an empty
    one. A manifest listing zero checks would read, to an agent, as a pack that was never verified —
    strictly worse than a pack that ships no manifest at all, because absence is honest and an empty
    evidence record is a false statement about the product.

    `.pass.json` first, because a listed pack is a survivor; the others are tried so a manually
    listed or re-vetted row still resolves rather than silently degrading.
    """
    for decision in ("pass", "defer", "kill"):
        path = DOSSIER_DIR / f"{pack_id}.{decision}.json"
        if path.exists():
            try:
                return pack_manifest.dossier_from_dict(json.loads(path.read_text()))
            except Exception:  # noqa: BLE001 — a corrupt record is a skip, never a wrong manifest
                return None
    return None


def _text(raw: Optional[bytes]) -> str:
    """Zip bytes as text. `errors="replace"` because this is a READ for rendering, never a
    write: a byte the codec cannot round-trip must not raise and take the whole backfill down
    with it, and the deliverable of record still ships as its original bytes."""
    return raw.decode("utf-8", errors="replace") if raw else ""


def rebuild_zip_with_index(
    zip_bytes: bytes,
    meta: pack_html.PackMeta,
    dossier: Any = None,
    pack_id: str = "",
) -> Optional[bytes]:
    """Return new zip bytes carrying a correct index.html and manifest.jsonld, or None if both
    are already correct.

    Every .md entry is copied byte-identical, in its original order, so the deliverables of
    record are untouched — only the two GENERATED files are written or replaced.

    Idempotency is by CONTENT, not by presence. The first version of this tool skipped any
    bundle that already had an index.html, which meant a pack backfilled with the old
    write-order reader could never be corrected: it was permanently "done" while opening on
    the wrong page. Rendering and comparing costs one render per pack and makes the tool safe
    to re-run after any reader change. The manifest is held to the same rule and for the same
    reason — and note the check is an AND: a pack with a correct reader and no manifest must
    convert, which a presence test on index.html alone would have skipped.

    `dossier` is optional. Without one the tool behaves exactly as it did before this feature
    (reader only), which is what keeps a pack whose evidence record is no longer on disk from
    being handed an empty manifest. See `load_local_dossier`.

    The manifest is rendered AFTER index.html so it can carry index.html's digest, and it is
    given the .md entries as BYTES read straight out of the source zip, so the digests it
    publishes are of the files that actually ship rather than of a decode round-trip.

    A dossier also buys `Evidence_and_Constraints.md` (P4): the shared evidence stated once,
    rendered from the same `pack_reference` the generator calls, so a backfilled pack and a
    freshly generated one carry the identical document. It is a BONUS file — no dossier, no
    document, and never a listing blocker.
    """
    src = zipfile.ZipFile(io.BytesIO(zip_bytes))
    names = src.namelist()
    # Rewritten from scratch every run rather than copied. The PDF joins them because it is
    # BINARY: `patched_md` decodes every other entry to look for the retired shelf-life line,
    # and a binary file taken through a lossy decode/encode round trip is a corrupted file.
    generated = {"index.html", pack_manifest.MANIFEST_FILENAME, pack_pdf.FILENAME}

    # Everything that will ship, keyed by name: the originals (with the one shelf-life rewrite)
    # plus any bonus document this run can add. Built ONCE and then used for the reader, the
    # manifest digests, the idempotency check and the write — four consumers that must agree.
    payload: Dict[str, bytes] = {
        n: patched_md(n, src.read(n)) for n in names if n not in generated}
    if dossier is not None:
        reference_md = pack_reference.render(dossier)
        if reference_md:
            payload[pack_reference.FILENAME] = reference_md.encode("utf-8")
        # The one DELIVERABLE this tool rewrites rather than copies. It is not a bonus file and
        # the rule above ("every .md entry is copied byte-identical") is broken here on purpose:
        # measured 2026-08-13, 127 of 127 bundles on disk shipped the same six-line template as
        # their action document, addressed to somebody auditing the engine rather than to the
        # buyer. Leaving it byte-identical would mean the fix reached new packs only, and the
        # founder's ask was explicitly both. Rendered by the module the generator now calls, so
        # a backfilled pack and a fresh one carry the identical checklist; where the pack gives
        # it nothing to point at, `render` returns "" and the original ships untouched.
        checklist_md = pack_checklist.render(
            dossier, {n: _text(b) for n, b in payload.items() if n.endswith(".md")})
        if checklist_md:
            payload[pack_checklist.FILENAME] = checklist_md.encode("utf-8")
        # P5. Both are deterministic projections of files ALREADY IN THIS ZIP plus the dossier,
        # which is the only reason a pack sold in June can be given them at all. Rendered by the
        # same two modules the generator calls, so a backfilled pack and a fresh one are
        # identical documents rather than two implementations that drift.
        card_html = pack_card.render(
            dossier,
            checklist_md=_text(payload.get("05_First_Week_Checklist.md")),
            financial_md=_text(payload.get("04_Financial_Model.md")),
            pack_id=pack_id,
        )
        if card_html:
            payload[pack_card.FILENAME] = card_html.encode("utf-8")
        table_csv = pack_table.render(dossier)
        if table_csv:
            payload[pack_table.FILENAME] = table_csv.encode("utf-8")

    index_html = pack_html.render_pack_html(ordered_md_entries(payload), meta)

    # The typeset edition, from the SAME sections the reader is built from, so a pack sold in
    # June gets the identical document a pack published today does. fpdf2 is an optional
    # dependency and the renderer is deterministic but not free (~1s a page), so a failure
    # here degrades to "this bundle keeps whatever PDF it already had" rather than aborting a
    # backfill that has real .md fixes to land.
    pdf_bytes: Optional[bytes] = None
    try:
        pdf_bytes = pack_pdf.render_pack_pdf(ordered_md_entries(payload), meta)
    except Exception as e:  # noqa: BLE001 — bonus file
        PDF_FAILURES.append(pack_id)
        print(f"  {pack_id}: Complete_Pack.pdf render failed ({e}); leaving it out", flush=True)

    manifest_json: Optional[str] = None
    if dossier is not None:
        # Every bonus file this run ships is declared to the manifest, not just the reader. A
        # manifest that omits an entry the zip contains is the same lie as one that lists an
        # entry the zip lacks — an agent enumerating the archive finds a file nothing accounts
        # for. `payload` carries the bytes; the manifest wants text, so decode here.
        extra = {"index.html": index_html}
        for name in (pack_card.FILENAME, pack_table.FILENAME):
            if name in payload:
                extra[name] = _text(payload[name])
        if pdf_bytes is not None:
            # Bytes, not text: `pack_manifest._as_bytes` takes either, and the digest has to be
            # of the bytes that shipped. A PDF decoded with errors="replace" would hash to
            # something no verifier could reproduce from the zip.
            extra[pack_pdf.FILENAME] = pdf_bytes
        manifest_json = pack_manifest.render_manifest(
            dossier, dict(payload), BUNDLE_FILES, _SECTION_TITLES, pack_id,
            extra_files=extra,
        )

    def current(name: str) -> Optional[str]:
        if name not in names:
            return None
        return src.read(name).decode("utf-8", errors="replace")

    reader_ok = current("index.html") == index_html
    # Compared as BYTES against the zip entry, which is only a meaningful test because
    # `render_pack_pdf` is byte-deterministic (`pack_pdf._pin_determinism`). Were the creation
    # date left to the clock this would be False on every pack on every run, and the backfill
    # would rewrite all 62 bought bundles nightly for no change.
    pdf_ok = pdf_bytes is None or (
        pack_pdf.FILENAME in names and src.read(pack_pdf.FILENAME) == pdf_bytes)
    manifest_ok = manifest_json is None or current(pack_manifest.MANIFEST_FILENAME) == manifest_json
    # A pack can be reader-correct and manifest-correct and STILL need rewriting, because a
    # DELIVERABLE changed: the retired shelf-life line, or a bonus document this pack does not
    # carry yet. Checking only the two generated files would have reported every already-
    # backfilled pack "already-correct" and left the buyer's own document saying its evidence
    # expires.
    deliverables_ok = all(
        name in names and payload[name] == src.read(name) for name in payload)
    if reader_ok and manifest_ok and deliverables_ok and pdf_ok:
        return None

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        # Original entry order first (the stale generated files are dropped here and rewritten
        # below, so a corrected bundle can never end up with two index.html members — zipfile
        # permits duplicates silently and readers disagree about which one wins), then anything
        # this run added, so an existing pack's entry order is never reshuffled by a new file.
        for name in names:
            if name in generated:
                continue
            dst.writestr(name, payload[name])
        for name in payload:
            if name not in names:
                dst.writestr(name, payload[name])
        dst.writestr("index.html", index_html)
        if pdf_bytes is not None:
            dst.writestr(pack_pdf.FILENAME, pdf_bytes)
        elif pack_pdf.FILENAME in names:
            # Same rule as the manifest below: the renderer failing this run must not delete a
            # file the buyer already has.
            dst.writestr(pack_pdf.FILENAME, src.read(pack_pdf.FILENAME))
        if manifest_json is not None:
            dst.writestr(pack_manifest.MANIFEST_FILENAME, manifest_json)
        elif pack_manifest.MANIFEST_FILENAME in names:
            # No dossier this run, but the pack already HAS a manifest: keep the one it has.
            # Dropping it would delete shipped evidence because a local file was missing, which
            # is a data loss disguised as a no-op.
            dst.writestr(pack_manifest.MANIFEST_FILENAME, src.read(pack_manifest.MANIFEST_FILENAME))
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
            # The manifest needs the evidence record, which lives only on this disk. A pack
            # whose dossier is gone still gets its reader corrected; it is reported as
            # `no-dossier` rather than being handed an empty evidence document.
            dossier = load_local_dossier(pid)

            # Counts come from the dossier when we have it, NOT from the API projection: the
            # stored `sourceCount` was minted before `all_sources` deduped by URL, so it is
            # the inflated number this backfill exists to correct. Without a local dossier we
            # keep the projection's figure rather than blanking a stat that is merely stale.
            source_count = d.get("sourceCount")
            claim_count = None
            if dossier is not None:
                # `dossier` here is `pack_manifest._ns`, a SimpleNamespace tree — not a
                # `Dossier` — so the counts come from the shared duck-typed helpers rather
                # than from properties this object does not have.
                checks = getattr(dossier, "checks", None) or []
                source_count = len(models.distinct_sources(checks)) or None
                claim_count = models.cited_claim_count(checks) or None
            meta = pack_html.PackMeta(
                title=d.get("title") or pack.get("title") or pid,
                one_liner=d.get("oneLine") or "",
                verified_at=d.get("verifiedAt") or "",
                source_count=source_count,
                pack_id=pid,
                claim_count=claim_count,
            )
            new_bytes = rebuild_zip_with_index(zip_bytes, meta, dossier, pid)
            if new_bytes is None:
                report.add(PackResult(pid, "already-correct", old_key.rsplit("/", 1)[-1]))
                continue

            new_hash = hashlib.sha256(new_bytes).hexdigest()
            new_key = f"packs/{pid}/{new_hash}.zip"
            delta = len(new_bytes) - len(zip_bytes)
            # Two different jobs under one action, worth telling apart in the log: a pack that
            # never had a reader is gaining one, a pack that had the write-order reader is
            # having it corrected. Only the second is a change to what an existing buyer sees.
            had = zipfile.ZipFile(io.BytesIO(zip_bytes)).namelist()
            parts = ["reordered reader" if "index.html" in had else "new reader"]
            if any(dossier_render.rewrite_legacy_shelf_life(
                    zipfile.ZipFile(io.BytesIO(zip_bytes)).read(n).decode("utf-8", "replace"))
                    for n in had if n.endswith(".md")):
                parts.append("shelf-life line retired")
            if dossier is None:
                parts.append("no-dossier: manifest SKIPPED")
            elif pack_manifest.MANIFEST_FILENAME in had:
                parts.append("manifest refreshed")
            else:
                parts.append("new manifest")
            kind = ", ".join(parts)
            sized = f"{len(zip_bytes)}B -> {len(new_bytes)}B ({delta:+d}B, {kind})"

            if not args.apply:
                report.add(PackResult(pid, "would-convert", sized, old_key, new_key, delta))
                continue

            s3.put_object(Bucket=bucket, Key=new_key, Body=new_bytes,
                          ContentType="application/zip")
            patch = requests.patch(
                f"{args.api_url}/internal/catalog/{pid}/content",
                json={"contentKey": new_key, "contentHash": new_hash,
                      "reason": "index.html reader + manifest.jsonld backfill (bundle format, no deliverable change)"},
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
