"""`manifest.jsonld` — the machine-readable half of a pack.

WHY THIS EXISTS
---------------
A pack ships as eight markdown files and an HTML reader. Both are for a human with eyes. An
increasing share of buyers meet this product through an agent: they hand a download to a model and
ask it to summarise, cross-examine, or act on it. Markdown survives that trip, but everything the
pack is actually SOLD on does not. The claim is "every figure is grounded in a retrievable source" —
and an agent handed eight prose files has to parse citations back out of English, in a format nobody
promised would stay stable, to check it. In practice it does not bother, and the pack degrades into
the same undifferentiated text any model could have written.

So the manifest is not metadata-for-completeness. It is the pack's argument, in the one form an
agent can act on without parsing prose:

  1. WHAT IS IN THE BOX      — every file, its sha256, its byte length, in reading order.
  2. WHAT WAS CHECKED        — every check, its verdict, its confidence, its rationale.
  3. WHAT IT WAS CHECKED AGAINST — every source, with its URL, its fetch date, and the exact
                                   passage the model was shown.

(3) is the part that makes this a different product class rather than a nicer download. Because the
passage travels WITH the pack, an agent can re-verify a ruling offline, against the same bytes the
verdict was formed from, without re-fetching a page that may since have changed or vanished. A URL
alone would only support "go and look again"; the passage supports "here is what it said, and here
is what we concluded from it — disagree if you can."

WHAT IS DELIBERATELY NOT IN HERE
--------------------------------
THE PRICE. `bridge.py` is the money rail, and the whole design of that rail is that one
`PriceDecision` mints the provider Price object AND writes the catalogue row so the two cannot
drift — a drift charges the buyer and then fails the fulfilment fence. A price copied into a zip is
a THIRD copy, one that lands on a buyer's disk permanently and that the engine can never correct
after a re-price. There is also no reader who needs it: the buyer has already paid, and fulfilment
reads the catalogue row. Nothing in this file may become a second source of truth about money.

WHY JSON-LD AND NOT A BARE JSON BLOB
------------------------------------
A bare blob would need this repo's own key names to be learned before anything could read it.
`ClaimReview` is the existing, standard vocabulary for exactly this shape (a claim, a rating, the
sources it was reviewed against), so a general-purpose agent can consume the evidence without
knowing what Prospector is. Everything with no standard term is namespaced under `prospector:`
rather than dropped into the schema.org namespace, so a strict JSON-LD processor expands the whole
document instead of silently discarding half of it.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

# The passage carried per source. This is not a display truncation chosen here: it is
# `verify.VERDICT_PASSAGE_TRUNCATE`, the exact number of characters the verdict prompt was given
# (verify.py:376). Shipping more would let an agent "re-verify" against evidence the ruling never
# saw, and conclude we were wrong on a paragraph we were never shown. Imported rather than
# duplicated so the two cannot drift.
from .verify import VERDICT_PASSAGE_TRUNCATE

MANIFEST_FILENAME = "manifest.jsonld"

# The vocabulary this document extends schema.org with. A URL, because JSON-LD terms are IRIs; it
# does not need to resolve for the document to expand correctly, and nothing here fetches it.
PROSPECTOR_NS = "https://mumchimp.com/ns/prospector#"

MANIFEST_VERSION = "pack-manifest-1"

_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]+")


def _frag(prefix: str, value: str) -> str:
    """A JSON-LD node id. Sanitised because source ids are derived from URLs upstream."""
    return f"#{prefix}-{_SAFE_ID.sub('-', value or 'unknown')}"


#: Media type per extension for the bonus files. A table rather than the `.html`-or-octet-stream
#: conditional it replaces: `application/octet-stream` is what a client is told when we do not
#: know, and telling an agent that of a PDF or a CSV — the two files most likely to be opened by
#: something other than a person — makes the manifest less useful than the filename it carries.
_MEDIA_TYPES = {
    ".html": "text/html",
    ".pdf": "application/pdf",
    ".csv": "text/csv",
    ".md": "text/markdown",
    ".json": "application/json",
    ".jsonld": "application/ld+json",
    ".txt": "text/plain",
}


def _as_bytes(content: Any) -> bytes:
    """Accepts `str` (the generator, which holds the text it is about to write) or `bytes` (the
    backfill, which holds the exact bytes already in a shipped zip).

    The backfill path MUST be able to pass bytes. It reads existing entries with
    `decode(errors="replace")` for rendering, and a digest taken over a replacement-character
    round-trip would not match the file it describes — a manifest whose whole job is to be
    verifiable, failing verification on any pack with one bad byte.
    """
    return content if isinstance(content, bytes) else str(content).encode("utf-8")


def _digest(content: Any) -> str:
    return hashlib.sha256(_as_bytes(content)).hexdigest()


def _source_node(src: Any) -> Dict[str, Any]:
    """One retrieved passage, as a citable WebPage.

    `prospector:passage` is the evidence itself, and it is the reason this manifest is worth
    shipping. `prospector:passageTruncatedAt` states the limit explicitly so a reader can tell a
    short passage from a clipped one — an agent that could not distinguish those would report a
    citation as incomplete every time the source happened to be brief.
    """
    text = getattr(src, "text", "") or ""
    node: Dict[str, Any] = {
        "@id": _frag("source", getattr(src, "source_id", "")),
        "@type": "WebPage",
        "url": getattr(src, "url", "") or "",
        "prospector:sourceId": getattr(src, "source_id", ""),
        "prospector:passage": text[:VERDICT_PASSAGE_TRUNCATE],
        "prospector:passageTruncatedAt": VERDICT_PASSAGE_TRUNCATE,
    }
    published = getattr(src, "published_at", None)
    if published:
        node["datePublished"] = published
    fetched = getattr(src, "fetched_at", None)
    if fetched:
        # When the passage was captured. An agent re-verifying a claim needs this to know how much
        # of any disagreement is our error and how much is the world moving.
        node["prospector:fetchedAt"] = fetched
    query = getattr(src, "query", None)
    if query:
        # The query that surfaced it. Publishing this is what lets someone reproduce the retrieval
        # rather than merely inspect its output.
        node["prospector:foundByQuery"] = query
    return node


def _check_node(check: Any, pack_ref: str) -> Dict[str, Any]:
    """One check, as a ClaimReview.

    The confidence rides in `reviewRating.ratingValue` on an explicit 0..1 scale, and the verdict
    word rides in `alternateName`, because the two are not interchangeable: `unverifiable` at 0.9
    means "we looked hard and the web does not say", which is a different fact from `supported` at
    0.3, and a single number cannot carry both.
    """
    verdict = getattr(check, "verdict", None)
    verdict_value = getattr(verdict, "value", verdict) or ""
    sources = list(getattr(check, "sources", []) or [])

    node: Dict[str, Any] = {
        "@id": _frag("check", getattr(check, "check_name", "")),
        "@type": "ClaimReview",
        "claimReviewed": getattr(check, "check_name", ""),
        "itemReviewed": {"@id": pack_ref},
        "reviewRating": {
            "@type": "Rating",
            "ratingValue": round(float(getattr(check, "confidence", 0.0) or 0.0), 3),
            "bestRating": 1,
            "worstRating": 0,
            "alternateName": verdict_value,
        },
        "reviewBody": getattr(check, "rationale", "") or "",
        "citation": [{"@id": _frag("source", getattr(s, "source_id", ""))} for s in sources],
        "prospector:verdict": verdict_value,
    }

    # THE HONESTY FLAGS. A check that could not be retrieved, or that was ruled by the cheap
    # fallback tail, is not the same object as a clean ruling, and an agent that treated them alike
    # would quote a degraded verdict as settled. These are emitted ONLY when true, so their
    # presence is the signal and a clean check stays clean.
    if getattr(check, "degraded", False):
        node["prospector:degraded"] = True
    if getattr(check, "retrieval_failed", False):
        node["prospector:retrievalFailed"] = True
    if getattr(check, "provisional", False):
        node["prospector:provisional"] = True
    provider = getattr(check, "provider", "") or ""
    if provider:
        node["prospector:ruledBy"] = provider
    return node


def _plain_mapping(value: Any) -> Dict[str, Any]:
    """A JSON-serialisable dict from either a real mapping or a SimpleNamespace.

    REGRESSION GUARD. `dossier_from_dict` rebuilds a stored dossier as nested SimpleNamespaces so
    the manifest can be rendered from any historical record without reconstructing dataclasses that
    may have gained fields since. That conversion is recursive, so `score.scores` — a plain
    Dict[str, float] on the live path — arrives as a NAMESPACE on the backfill path, and `dict()`
    raises `TypeError: 'types.SimpleNamespace' object is not iterable`.

    Every unit test built its dossier from the real dataclasses and so never saw it; it surfaced on
    the first real stored dossier the backfill touched. The two shapes are both legitimate inputs,
    so the reader accommodates both rather than the writer normalising one away.
    """
    if value is None:
        return {}
    if isinstance(value, SimpleNamespace):
        return dict(vars(value))
    return dict(value)


def render_manifest(
    dossier: Any,
    written: Dict[str, str],
    bundle_files: tuple,
    section_titles: Dict[str, str],
    pack_id: str,
    extra_files: Optional[Dict[str, str]] = None,
) -> str:
    """Render `manifest.jsonld` for one pack.

    `written` maps filename -> the exact string written into the zip, so the digests below are of
    the bytes that shipped rather than of some parallel re-render. `bundle_files` is passed in
    rather than imported to keep this module free of a circular import back into `bridge`, and
    because it is the reading-order contract: the manifest lists parts in the order the pack is
    meant to be read, not the order the zip happens to store them.
    """
    candidate = getattr(dossier, "candidate", None)
    checks = list(getattr(dossier, "checks", []) or [])
    all_files: Dict[str, str] = dict(written)
    if extra_files:
        all_files.update(extra_files)

    pack_ref = "#pack"
    parts: List[Dict[str, Any]] = []
    for position, name in enumerate(bundle_files, start=1):
        content = all_files.get(name)
        if content is None:
            # A partially-built bundle is held UNLISTED by the completeness gate; the manifest
            # describes what actually shipped rather than asserting a file that is not in the zip.
            continue
        parts.append({
            "@id": _frag("file", name),
            "@type": "DigitalDocument",
            "name": section_titles.get(name, name),
            # By suffix, not the hardcoded "text/markdown" this carried until 2026-08-15. The
            # promised deliverables were all .md then; they are now index.html, a PDF, an HTML
            # card, a CSV and a .txt, and a manifest that calls a PDF markdown is a machine-
            # readable file telling a machine something false.
            "encodingFormat": _MEDIA_TYPES.get(PurePosixPath(name).suffix.lower(),
                                               "application/octet-stream"),
            "contentUrl": name,
            "position": position,
            "contentSize": str(len(_as_bytes(content))),
            "prospector:sha256": _digest(content),
        })
    # Anything shipped that is not one of the promised deliverables (index.html today) is listed
    # too, and flagged, so an agent enumerating the zip finds every entry accounted for rather than
    # meeting a file the manifest denies exists.
    for name, content in all_files.items():
        if name in bundle_files or name == MANIFEST_FILENAME:
            continue
        parts.append({
            "@id": _frag("file", name),
            "@type": "DigitalDocument",
            "name": name,
            "encodingFormat": _MEDIA_TYPES.get(PurePosixPath(name).suffix.lower(),
                                               "application/octet-stream"),
            "contentUrl": name,
            "contentSize": str(len(_as_bytes(content))),
            "prospector:sha256": _digest(content),
            "prospector:promisedDeliverable": False,
        })

    # De-duplicated across checks: one node per source, referenced by id from each check that used
    # it. A source cited by four checks would otherwise ship its passage four times, and the zip
    # entry is uncompressed JSON.
    source_nodes: Dict[str, Dict[str, Any]] = {}
    for check in checks:
        for src in getattr(check, "sources", []) or []:
            sid = getattr(src, "source_id", "")
            if sid and sid not in source_nodes:
                source_nodes[sid] = _source_node(src)

    decision = getattr(dossier, "decision", None)
    decision_value = getattr(decision, "value", decision) or ""

    pack_node: Dict[str, Any] = {
        "@id": pack_ref,
        "@type": "Report",
        "identifier": pack_id,
        "name": getattr(candidate, "title", "") or "",
        "abstract": getattr(candidate, "one_liner", "") or "",
        "inLanguage": "en-GB",
        "hasPart": [{"@id": p["@id"]} for p in parts],
        "citation": [{"@id": n["@id"]} for n in source_nodes.values()],
        "prospector:decision": decision_value,
        "prospector:checkCount": len(checks),
        "prospector:sourceCount": len(source_nodes),
    }
    created_at = getattr(dossier, "created_at", "") or ""
    if created_at:
        pack_node["dateCreated"] = created_at
    reverify = getattr(dossier, "reverify_due_at", None)
    if reverify:
        # Every ruling here has a shelf life, and saying so is more honest than letting an agent
        # treat a year-old verdict as current.
        pack_node["prospector:reverifyDueAt"] = reverify
    provider_chain = getattr(dossier, "provider_chain", "") or ""
    if provider_chain:
        pack_node["prospector:providerChain"] = provider_chain
    if getattr(dossier, "provisional", False):
        pack_node["prospector:provisional"] = True
    score = getattr(dossier, "score", None)
    if score is not None and not getattr(score, "score_failed", False):
        pack_node["prospector:scores"] = _plain_mapping(getattr(score, "scores", None))
        pack_node["prospector:compositeScore"] = round(float(getattr(score, "composite", 0.0) or 0.0), 3)

    graph: List[Dict[str, Any]] = [pack_node] + parts
    graph.extend(_check_node(c, pack_ref) for c in checks)
    graph.extend(source_nodes.values())

    document = {
        "@context": ["https://schema.org", {"prospector": PROSPECTOR_NS}],
        "prospector:manifestVersion": MANIFEST_VERSION,
        # SELF-DESCRIBING ON PURPOSE. An agent reading `"alternateName": "unverifiable"` off a
        # rating has no way to know that it is a real third outcome here rather than a missing
        # value, and the difference is the entire product: "the web does not support this" is a
        # finding, not an absence. Stating the scale in the document costs three lines and removes
        # the guess.
        "prospector:verdictScale": {
            "supported": "The cited passages support the claim.",
            "refuted": "The cited passages contradict the claim.",
            "unverifiable": "Retrieval ran and no passage settled it. A finding, not a gap.",
        },
        "@graph": graph,
    }
    return json.dumps(document, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------------------------
# Reading a dossier that is already on disk.
# ---------------------------------------------------------------------------------------------

def _ns(value: Any) -> Any:
    """Recursively give a parsed-JSON structure attribute access.

    `render_manifest` reads its dossier through `getattr` throughout, which is what lets the
    generator hand it a live `Dossier` and the backfill hand it a `store/dossiers/<id>.pass.json`
    that was written months ago. The persisted key names ARE the dataclass field names
    (`Dossier.to_dict` is a field-for-field projection, models.py:384), so no mapping table is
    needed here — and no mapping table is the point, because a table would be a second place for
    a renamed field to have to be remembered.

    Deliberately NOT a `Dossier.from_dict`. Reconstructing the real dataclasses would mean
    resolving enums, defaults and required arguments for a record whose schema has moved since it
    was written, and failing on any historical row that predates a field — for a document that only
    ever reads values back out.
    """
    if isinstance(value, dict):
        return SimpleNamespace(**{k: _ns(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_ns(v) for v in value]
    return value


def dossier_from_dict(data: Dict[str, Any]) -> Any:
    """A stored dossier JSON, in the shape `render_manifest` reads."""
    return _ns(data)
