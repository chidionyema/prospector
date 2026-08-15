#!/usr/bin/env python3
"""Re-render an already-listed pack's zip from the Markdown it was built from, so the
archive holds the RENDERED pack (index.html, Complete_Pack.pdf, First_Fortnight.html,
Assumptions.csv, Marketing_Assets.txt, manifest.jsonld) and not the render input.

WHAT THIS TOOL DOES CHANGED ON 2026-08-15, and the old behaviour is worth stating
because most of this file was written for it. It used to ADD index.html and
manifest.jsonld beside the eight .md deliverables, copying those .md bytes into the
new zip byte-identical. It now uses them and DROPS them: they are the render input,
and shipping them beside the render output is what put fourteen entries in a £49
download. Measured across the 59 live packs, 0 of 853 headings, 0 of 208 table cells
and 0 of 6,743 prose runs in the .md were absent from index.html — they were pure
duplication. Founder's verdict: "why do we need 14 files? ... i dont like md files at
all, we are not selling to developers".

Still true, and still the point: WITHOUT REGENERATING ANY CONTENT. The .md are read
out of the pack's existing zip in R2 and rendered locally — zero model calls, zero new
claims, no re-vet. (Deliberately NOT `publish --reuse-artifacts`, which silently
regenerates — model calls and a live publish — whenever validate_pack is incomplete.)

Measured on pack 0bf4d472ef2b90ad, 2026-08-15: 14 entries -> 6, -40,697 bytes (-15.4%),
no .md remaining, and a second pass over the new zip is a no-op.

THE CONVERSION IS ONE-WAY, and two guards exist for it:
  * A source zip with NO .md returns None immediately. There is nothing left to render
    a reader FROM, so a second run would otherwise write an EMPTY index.html over a
    good pack. This is what makes the tool safe to re-run.
  * `dossier is None` returns None too. Without the dossier there is no manifest, and
    carrying the OLD manifest forward would assert sha256s for eight entries that are
    no longer in the zip; dropping it would ship a pack that fails audit_bundle. Such a
    pack is reported `no-dossier` and left exactly as it is. (Measured 2026-08-15: 0 of
    the 59 live packs are in this state, so it is a guard, not a gap.)
The old object is never overwritten (content-addressed keys, below), so the
pre-conversion zip remains fetchable if a conversion ever needs undoing.

It also CORRECTS a reader that is present but wrong. The reader used to be built from
the zip's own entry order, and the bundle is written 01, 02, 03, 04, QA, Marketing, 00,
05 — so the reader opened on the build spec, buried the executive summary seventh, and
put the first-week checklist, the one document that tells a buyer what to do, last. The
generator was fixed to take its order from the contract instead (now
BUNDLE_READING_ORDER, which is PACK_DOCUMENTS with the evidence document inserted
before the QA report); this tool does the same.

The .md text reaches the rendered output with exactly ONE edit, taken deliberately and
kept as narrow as a single line: the retired `Evidence goes stale after: <ISO stamp>`
footer (see `patched_md`). That line printed an internal cron stamp as if it were a
warranty expiry on a document someone paid £49.99 for; leaving it in place is not
neutrality, it is continuing to make a promise we never priced. Every other word is
carried through unchanged, and rewriting anything further is a different decision and
not this tool's to make.

manifest.jsonld carries the evidence (every check, verdict and cited passage), which
exists only in this repo's store/dossiers, never in the shipped zip. It is regenerated
here rather than copied, because it asserts a sha256 per entry and the entries change.

Content storage is content-addressed (packs/<id>/<sha256-of-zip>.zip,
bridge.py:_sha256/content_key), so the new zip lands at a NEW object key and the
listing must be repointed. That uses the narrow door built for exactly this:
PATCH /internal/catalog/{id}/content — which can reach only the content pointer,
never price/provider/listing state. The old object is left in place: any
presigned download URL already in a buyer's hands keeps working.

Safety model:
  * --dry-run (default): fetch, rebuild, report. No upload, no PATCH.
  * --apply: upload new zip, then PATCH the listing. Requires STORE_INTERNAL_API_KEY.
  * A pack whose zip holds no .md is skipped, and that IS the idempotency check
    (see the one-way note above): no .md means the pack is already converted and
    there is nothing to render it from. It is a check on SHAPE, not on content. The
    content comparison this tool used to run is gone -- while the conversion was
    additive it correctly caught a pack that already had the right reader, but a
    subtractive conversion changes every input that reaches it, so it could not fire.
  * A pack with several objects under packs/<id>/ is AMBIGUOUS (the API does not
    expose the current contentKey): skipped unless --take-newest, which uses the
    most recently modified object and says so in the report.

Env: R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET (storage);
STORE_INTERNAL_API_KEY (--apply only). API base via --api-url.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
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
    plain_text,  # noqa: E402
)
from prospector.bridge import (  # noqa: E402
    _FILE_TITLES,
    _SECTION_TITLES,
    BUNDLE_BONUS_FILES,
    BUNDLE_FILES,
    BUNDLE_READING_ORDER,
)

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

    Reading order comes from ``BUNDLE_READING_ORDER``, exactly as the generator now takes it
    (bridge.py, the `md_entries` comprehension feeding render_pack_html) — deliberately NOT
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
    """Return new zip bytes holding the RENDERED pack, or None if there is nothing to do.

    The source zip's .md entries are the render INPUT. They are read, patched by `patched_md`,
    composed into index.html / Complete_Pack.pdf / First_Fortnight.html / Assumptions.csv /
    Marketing_Assets.txt, and then NOT carried into the output. Before 2026-08-15 they were
    copied through byte-identical beside the rendered files, which is what made a £49 download
    fourteen entries of which eight were duplicates of a ninth.

    Returns None in three cases, and the first two are the one-way-conversion guards:
      * no .md in the source  — already converted; there is nothing to render FROM, and
        proceeding would write an EMPTY reader over a good pack.
      * `dossier is None`     — no evidence record on disk, so no manifest can be minted.
        Carrying the old one forward would assert sha256s for entries that no longer exist,
        and omitting it entirely would ship a pack that fails `audit_bundle` and is delisted.
        Reported `no-dossier`; the pack is left exactly as it is.

    There used to be a third: the rebuilt archive equalling the source zip's contents
    byte-for-byte. That was the idempotency check while the conversion was ADDITIVE. It is gone,
    because since the conversion became subtractive it can never be true — reaching it means the
    source held a .md, and the output never does. Idempotency is now decided by the FIRST case
    above, and the comment at the site where the comparison used to be states the cost: a reader
    change can no longer be backfilled in place onto a converted pack.

    The manifest is rendered LAST so it can carry every other entry's digest, and it is given
    the archive as BYTES, so the digests it publishes are of the files that actually ship
    rather than of a decode round-trip.

    A dossier also buys `Evidence_and_Constraints.md` (P4): the shared evidence stated once,
    rendered from the same `pack_reference` the generator calls, so a backfilled pack and a
    freshly generated one carry the identical document. It is a BONUS file — no dossier, no
    document, and never a listing blocker.
    """
    src = zipfile.ZipFile(io.BytesIO(zip_bytes))
    names = src.namelist()

    # The composed DOCUMENTS, read out of the source zip. Since 2026-08-15 these are the render
    # INPUT and are not written back: the founder's brief ("i dont like md files at all, we are
    # not selling to developers") took markdown out of the buyer's archive entirely.
    #
    # CONVERSION IS ONE-WAY, and this guard is what keeps it safe. A pack already converted has
    # no .md left, so there is nothing to render a reader FROM — without this the tool would
    # render an empty index.html over a perfectly good pack on its second run. Returning None
    # makes an already-converted pack a no-op rather than a casualty.
    #
    # The cost of that is real and worth stating: once a pack is converted, this tool can no
    # longer re-render its reader. The escape hatch is that R2 keys are content-addressed
    # (bridge.py, `content_key = f"packs/{candidate_id}/{content_hash}.zip"`), so the
    # PRE-CONVERSION object carrying the .md is never overwritten and stays fetchable — a future
    # reader change re-renders from that object, not from the converted one.
    documents: Dict[str, bytes] = {
        n: patched_md(n, src.read(n)) for n in names if n.endswith(".md")}
    if not documents:
        return None

    # Six entries are rewritten from scratch every run rather than copied — index.html, the
    # manifest, the PDF, the card, the table and Marketing_Assets.txt. Each is written into
    # `archive` explicitly below, so this is the enumeration, not a filter. The PDF is one of
    # them because it is BINARY: `patched_md` decodes every other entry to look for the retired
    # shelf-life line, and a binary file taken through a lossy decode/encode round trip is a
    # corrupted file.

    # What the OUTPUT archive will hold. Built once and then used for the manifest digests, the
    # idempotency check and the write — three consumers that must agree.
    archive: Dict[str, bytes] = {}
    payload = documents  # name kept: `ordered_md_entries` and pack_checklist both read it
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

        # THE FIVE NARRATIVE SECTIONS (2026-08-15), backfilled onto packs already sold.
        #
        # Without this block the restructure is a fix for FUTURE buyers only: the 145 bundles
        # under publish/ keep the old shape forever, because these sections are appended after
        # the .md the pack was built from and nothing re-derives them. They can be backfilled
        # at all for exactly the reason the generator's own comment gives — all five render
        # from the dossier with NO model call, so a re-render here is not a regeneration.
        #
        # This mirrors bridge.py `_create_bundle` (the `for module_name, kwargs in (` loop)
        # deliberately line for line, INCLUDING the order and the position: it runs after the
        # checklist and BEFORE the card/table below, so `pack_card` is handed the financial
        # model AFTER the bear case has absorbed its weaknesses, exactly as in the generator.
        # Two implementations that drift is the defect `pack_reference` and `pack_checklist`
        # are both written to avoid, and this loop is the third instance of the same promise.
        #
        # Guarded INDIVIDUALLY, like the generator: one section that raises costs that section
        # and nothing else, never the backfill of the pack, and never an exception on the apply
        # path. `""` is not a failure — `pack_field` and `pack_bear_case` legitimately return it
        # on a thin dossier (no incumbency sources; nothing refuted or unproven), and "" means
        # OMIT THE SECTION. The reader picks whatever survives up out of `payload` via
        # `ordered_md_entries`, since all five names are in BUNDLE_READING_ORDER.
        for module_name, kwargs in (
            ("pack_offer", {}),
            ("pack_field", {}),
            ("pack_bear_case",
             {"financial_md": _text(payload.get("04_Financial_Model.md"))}),
            ("pack_toolkit", {}),
            ("pack_kicker", {}),
        ):
            try:
                module = importlib.import_module(f"prospector.{module_name}")
                body = module.render(dossier, **kwargs)
                if body:
                    # The prose pass, for the same reason the generator applies it: it is pure
                    # Python (`plain_text.publish_pass_document`, no model call), so it is safe
                    # on a backfill, and SKIPPING it here is what would make a backfilled pack
                    # differ byte-for-byte from a freshly generated one.
                    body = plain_text.publish_pass_document(body)
                    payload[module.FILENAME] = body.encode("utf-8")
                    # The bear case lifted two blocks out of the financial model verbatim, so
                    # the model now hands them over and keeps a pointer — otherwise the buyer
                    # reads the same fifteen sentences in two sections, which is the exact
                    # duplication this branch exists to remove. Only on success: a render that
                    # returned "" or raised absorbed nothing, and the model keeps its own.
                    # The title comes from `_SECTION_TITLES`, never a literal, so the pointer
                    # names the section the reader will actually see.
                    if module_name == "pack_bear_case" and payload.get("04_Financial_Model.md"):
                        payload["04_Financial_Model.md"] = module.financial_md_after_absorbing(
                            _text(payload["04_Financial_Model.md"]),
                            _SECTION_TITLES.get(module.FILENAME, "the bear case"),
                        ).encode("utf-8")
            except Exception as e:  # noqa: BLE001 — one section, never the pack
                print(f"  {pack_id}: {module_name} render failed ({e}); "
                      "converting the pack without that section", flush=True)

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
            archive[pack_card.FILENAME] = card_html.encode("utf-8")
        table_csv = pack_table.render(dossier)
        if table_csv:
            archive[pack_table.FILENAME] = table_csv.encode("utf-8")

    # The one document a buyer EDITS, kept in a form they can paste from. Same renderer and same
    # `keep_link_urls=True` as the generator (bridge.py, section 8a), so a backfilled pack and a
    # freshly generated one carry the identical file rather than two implementations that drift.
    marketing_txt = plain_text.to_plain_text(
        _text(payload.get("Marketing_Assets.md")), keep_link_urls=True)
    if marketing_txt:
        archive["Marketing_Assets.txt"] = marketing_txt.encode("utf-8")

    index_html = pack_html.render_pack_html(ordered_md_entries(payload), meta)
    archive["index.html"] = index_html.encode("utf-8")

    # The typeset edition, from the SAME sections the reader is built from, so a pack sold in
    # June gets the identical document a pack published today does. fpdf2 is an optional
    # dependency and the renderer is deterministic but not free (~1s a page), so a failure
    # here degrades to "this bundle keeps whatever PDF it already had" rather than aborting a
    # backfill that has real .md fixes to land.
    pdf_bytes: Optional[bytes] = None
    try:
        pdf_bytes = pack_pdf.render_pack_pdf(ordered_md_entries(payload), meta)
    except Exception as e:  # noqa: BLE001 — reported, and the pack keeps the PDF it already had
        PDF_FAILURES.append(pack_id)
        print(f"  {pack_id}: Complete_Pack.pdf render failed ({e}); leaving it out", flush=True)
    if pdf_bytes is not None:
        archive[pack_pdf.FILENAME] = pdf_bytes
    elif pack_pdf.FILENAME in names:
        # The renderer failing this run must not delete a file the buyer already has.
        archive[pack_pdf.FILENAME] = src.read(pack_pdf.FILENAME)

    # No dossier means no conversion, full stop — and that is stricter than the rule this tool
    # used to follow. Two independent reasons, either of which is sufficient:
    #
    #   1. Without a dossier there is no First_Fortnight.html and no Assumptions.csv, and both
    #      are in BUNDLE_FILES now. A converted pack missing them fails `audit_bundle` and is
    #      held UNLISTED — the tool would be delisting packs that currently sell.
    #   2. Carrying the pack's EXISTING manifest forward would leave it asserting a sha256 for
    #      eight .md entries this run just removed. A manifest that lists an entry the zip lacks
    #      is the one failure mode manifest.jsonld exists to make impossible.
    #
    # So a pack whose evidence record is no longer on this disk is reported and left exactly as
    # it is, which is the honest outcome: it keeps selling in its old shape.
    if dossier is None:
        return None
    manifest_json = pack_manifest.render_manifest(
        dossier, dict(archive), BUNDLE_FILES, _FILE_TITLES, pack_id)
    archive[pack_manifest.MANIFEST_FILENAME] = manifest_json.encode("utf-8")

    # There is deliberately NO content comparison here, and there used to be one:
    #
    #     if {n: src.read(n) for n in names} == archive: return None
    #
    # It was the idempotency check while the .md were archive entries and the conversion was
    # additive — a pack that already had a correct reader compared equal and was skipped. Since
    # the conversion became SUBTRACTIVE it cannot fire: reaching this line means the source held
    # at least one .md (the `not documents` guard above returns first otherwise) and `archive`
    # holds only rendered output, so the two dicts differ by construction on every input that
    # gets here. Leaving it in place would have been harmless but dishonest — it read as the
    # thing deciding idempotency when the `not documents` fence had quietly taken that job.
    #
    # So idempotency is now by SHAPE, decided at that fence: a converted pack has no .md, and no
    # .md means nothing to render from, which is a no-op. The consequence is that a reader change
    # can no longer be backfilled onto an already-converted pack in place — re-render it from its
    # pre-conversion R2 object, which content-addressed keys guarantee still exists.
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        # Contract order first, then the bonus file, then anything else this pack happens to
        # carry — a stable order that does not depend on the source zip's, because the source
        # order was the legacy .md sequence and none of those entries survive.
        for name in list(BUNDLE_FILES) + list(BUNDLE_BONUS_FILES):
            if name in archive:
                dst.writestr(name, archive[name])
        for name in archive:
            if name not in BUNDLE_FILES and name not in BUNDLE_BONUS_FILES:
                dst.writestr(name, archive[name])
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
