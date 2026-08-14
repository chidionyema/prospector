"""P5: the machine-readable table — `Assumptions.csv`.

THE ASK, AND THE ONE COLUMN THAT IS NOT IN IT
---------------------------------------------
The programme doc asks for "one machine-readable table (assumption, cost to confirm, test,
cost of test)". Three of those four are on disk and are columns below. The money is not:
nothing the engine retrieved prices what a test costs, so a `cost_to_confirm` column would be
a number we made up, in the one file a buyer is most likely to paste into a spreadsheet and
total. `source-or-die` forbids it. The column that replaces it is `how_to_settle` — the
searches the engine actually ran for that check, which is a real answer to "what would it take
to find out" and is retrievable.

WHY CSV AND NOT THE MANIFEST
----------------------------
`manifest.jsonld` already states every check, verdict and citation for an AGENT. This file is
for a person with a spreadsheet: sort by status, filter to the assumptions, add their own
columns. Two audiences, two formats, one source of truth — both are projections of the same
dossier, and neither is authored separately.

Written with `csv.writer`, never string joins: a rationale contains commas, quotes and the odd
newline, and a hand-rolled CSV that shifts a buyer's columns is worse than no CSV.
"""
from __future__ import annotations

import csv
import io
from typing import Any, List

FILENAME = "Assumptions.csv"

HEADER = (
    "check",              # the buyer-facing question, same wording as every other document
    "status",             # proven | disproven | assumption
    "confidence",         # 0-1, as the verdict brain scored it
    "what_we_found",      # the rationale, verbatim
    "how_to_settle",      # the searches actually run — replaces the invented cost column
    "sources",            # every URL cited for this check, space-separated
)

_STATUS = {
    "supported": "proven",
    "refuted": "disproven",
    "unverifiable": "assumption",
}


def _verdict(chk: Any) -> str:
    return str(getattr(getattr(chk, "verdict", None), "value", getattr(chk, "verdict", "")) or
               "").strip().lower()


def render(dossier: Any) -> str:
    """The table as CSV text, or "" when the dossier holds no checks.

    "" means "do not ship this file". A header row with nothing under it, in a file called
    `Assumptions.csv`, reads as "we checked nothing" — the same trap the empty manifest and the
    empty evidence document are both guarded against.
    """
    from .dossier import check_label

    checks = list(getattr(dossier, "checks", None) or [])
    if not checks:
        return ""

    buf = io.StringIO(newline="")
    # QUOTE_MINIMAL with the default dialect: Excel, Numbers, LibreOffice and pandas all read
    # it without being told anything. \r\n because that is what the CSV RFC specifies and what
    # Excel expects; every reader in that list handles it.
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow(HEADER)
    for chk in checks:
        verdict = _verdict(chk)
        writer.writerow((
            check_label(str(getattr(chk, "check_name", "") or "")),
            _STATUS.get(verdict, verdict or "unknown"),
            _confidence(chk),
            _one_line(str(getattr(chk, "rationale", "") or "")),
            " | ".join(_queries(chk)),
            " ".join(_urls(chk)),
        ))
    return buf.getvalue()


def _confidence(chk: Any) -> str:
    """The score as written, or "" — never a default.

    `0.0` and "we did not score this" are different facts, and a CSV that prints 0 for the
    second one tells a buyer the engine had no confidence when in truth it had no opinion.
    """
    raw = getattr(chk, "confidence", None)
    try:
        return f"{float(raw):.2f}"
    except (TypeError, ValueError):
        return ""


def _one_line(text: str) -> str:
    """Collapse the rationale to one line. The value is still quoted by `csv.writer`, so an
    embedded newline would be legal CSV — and would still break every buyer who opens the file
    in a text editor or pipes it through `cut`."""
    return " ".join(str(text or "").split())


def _queries(chk: Any) -> List[str]:
    return [" ".join(str(q).split()) for q in (getattr(chk, "queries", None) or []) if str(q).strip()]


def _urls(chk: Any) -> List[str]:
    seen: List[str] = []
    for src in (getattr(chk, "sources", None) or []):
        url = str(getattr(src, "url", "") or "").strip()
        if url and url not in seen:
            seen.append(url)
    return seen
