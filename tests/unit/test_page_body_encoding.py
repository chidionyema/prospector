"""A page body is decoded by what it declares, not by what RFC 2616 defaults to.

THE DEFECT THESE CLOSE. `fetch_page` decoded with `resp.encoding or "utf-8"`. `requests`
follows RFC 2616 and reports ISO-8859-1 for any `text/*` that carries no charset parameter,
so a UTF-8 page served as bare `text/html` came back as mojibake: the three bytes of a
right single quote were read as three Latin-1 characters, so `we\u2019ll` arrived as
`we\u00e2\u0080\u0099ll`. Measured on doc.rust-lang.org/book/ch01-01-installation.html --
32 corrupted characters in 5,504. Nothing in the suite could see it, because the corruption
is still well-formed text; it was found by diffing against the Rust port, which decodes as
UTF-8.

The corrupted string is what the verdict brain reads and what we cite, so this is a grounding
defect, not a cosmetic one.
"""
import pytest

from prospector.retrieval import _body_encoding


def test_a_bare_text_html_page_is_utf8_not_latin1():
    """The exact case that was corrupting live passages."""
    assert _body_encoding("text/html", b"<html><head><title>x</title>") == "utf-8"


def test_the_header_charset_wins_when_the_page_declares_one():
    assert _body_encoding("text/html; charset=windows-1252", b"") == "windows-1252"


@pytest.mark.parametrize("markup", [
    b'<html><head><meta charset="iso-8859-2">',
    b"<html><head><meta charset='iso-8859-2'>",
    b"<html><head><meta charset=iso-8859-2>",
    b'<html><head><meta http-equiv="Content-Type" content="text/html; charset=iso-8859-2">',
])
def test_a_meta_declaration_is_read_when_the_headers_are_silent(markup):
    """Both spellings of the declaration, quoted and not. A page that says nothing in its
    headers still says something in its markup, and it is the only truth available."""
    assert _body_encoding("text/html", markup) == "iso-8859-2"


def test_the_header_outranks_the_markup():
    assert _body_encoding("text/html; charset=utf-8",
                          b'<meta charset="windows-1252">') == "utf-8"


def test_a_charset_python_cannot_load_falls_back_rather_than_raising():
    """`fetch_page` promises never to raise. An unknown label reaching `.decode()` would
    throw `LookupError`, which none of its handlers catch."""
    assert _body_encoding("text/html; charset=bogus-9000", b"") == "utf-8"
    assert _body_encoding("text/html", b'<meta charset="bogus-9000">') == "utf-8"


def test_a_declared_charset_that_is_loadable_is_returned_verbatim():
    """Guards the fallback above from swallowing a real, unusual encoding."""
    assert _body_encoding("text/html; charset=shift_jis", b"") == "shift_jis"
