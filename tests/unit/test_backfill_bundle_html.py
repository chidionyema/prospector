"""The backfill's one transformation, proven on bytes: index.html is strictly additive.

The tool's promise to buyers and to the catalogue is that a converted bundle differs from the
original by EXACTLY one new file — every pre-existing entry survives byte-identical, in order.
Everything else in tools/backfill_bundle_html.py is plumbing around this function.
"""

import io
import zipfile

from prospector.pack_html import PackMeta
from tools.backfill_bundle_html import rebuild_zip_with_index

META = PackMeta(title="T", one_liner="o", verified_at="2026-07-31", source_count=3, pack_id="x")


def _zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in entries:
            z.writestr(name, content)
    return buf.getvalue()


def test_adds_index_html_and_keeps_every_entry_byte_identical():
    entries = [
        ("01_Playbook.md", "# One\n**bold** stays *markdown* in the .md"),
        ("QA_Report.md", "| a | b |\n|---|---|\n| 1 | 2 |"),
    ]
    out = rebuild_zip_with_index(_zip(entries), META)

    src = zipfile.ZipFile(io.BytesIO(out))
    assert src.namelist() == ["01_Playbook.md", "QA_Report.md", "index.html"]
    for name, content in entries:
        assert src.read(name) == content.encode("utf-8")
    html = src.read("index.html").decode("utf-8")
    assert "<strong>bold</strong>" in html


def test_returns_none_when_index_html_already_present():
    already = _zip([("01_Playbook.md", "x"), ("index.html", "<p>done</p>")])
    assert rebuild_zip_with_index(already, META) is None


def test_entry_order_is_preserved_so_sections_keep_bundle_order():
    # bridge writes the .md files in a deliberate reading order; the zip carries that order
    # and the rebuilt reader must follow it, not alphabetize it.
    entries = [("02_B.md", "b"), ("01_A.md", "a"), ("00_C.md", "c")]
    out = rebuild_zip_with_index(_zip(entries), META)
    html = zipfile.ZipFile(io.BytesIO(out)).read("index.html").decode("utf-8")
    assert html.index("02_B") < html.index("01_A") < html.index("00_C")
