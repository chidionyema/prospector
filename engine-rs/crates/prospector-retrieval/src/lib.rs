//! Read a web page the way `prospector/retrieval.py:fetch_page` reads one.
//!
//! This is a port, not a redesign. The Python it replaces is load-bearing and every rule in
//! it was paid for: the furniture strip exists because a bare text dump returned "Skip
//! Navigation Personal Business Find a store Ver en espanol Shop Deals" as the longest
//! "upgraded" passage of a live batch, and the 200-character floor exists because a 404 body
//! ("Page not found - `GeekWire`", 25 chars) was otherwise handed to the verdict brain as
//! evidence. A rewrite that quietly drops either would look faster and grade worse.
//!
//! So the ladder here is deliberately identical, in the same order, with the same constants:
//!
//!   1. strip script/style/nav/header/footer/aside/form/svg/iframe/button/select/template,
//!      and the text that trails each of them, before reading any text at all;
//!   2. try `<main>`, `<article>`, `[role=main]`, `#content` in that order, and take the
//!      first whose collapsed text is at least 200 characters;
//!   3. otherwise take the whole document;
//!   4. under 200 characters after all that is NO passage, not a short one -- the caller
//!      keeps the search snippet, which averages 222 characters and is strictly better than
//!      a page title.
//!
//! What is NOT ported: the trafilatura fallback. It is a second parser for the case where
//! the cheap path returns a title and nothing else, and the Python comment measures what it
//! buys -- one passage in twelve. Porting it means porting a different extraction algorithm
//! wholesale, so this crate returns the cheap path's answer and the Python side keeps its
//! fallback until the parity numbers say what the gap actually costs.

use std::io::Read as _;
use std::time::Duration;

use ego_tree::NodeRef;
use encoding_rs::{Encoding, UTF_8};
use scraper::{Html, Node, Selector};

/// A page yielding fewer characters than this is no passage at all.
///
/// `prospector/retrieval.py:641`. Keep the two in step or the shadow disagrees for a reason
/// that has nothing to do with extraction.
pub const MIN_PAGE_TEXT: usize = 200;

/// `prospector/retrieval.py:155`. A default reqwest agent is blocked by enough hosts to
/// change which pages the engine can read, so the string is part of the behaviour.
pub const RESOLVE_UA: &str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) \
                              AppleWebKit/537.36 (KHTML, like Gecko) \
                              Chrome/124.0.0.0 Safari/537.36";

/// Stop reading a response after this many bytes. A page bigger than this is not a page we
/// want a passage from, and the cap is what stops one hostile URL from eating the box.
pub const MAX_BYTES: usize = 400_000;

/// The Python reads the body with `iter_content(8192)`. The bite size decides where an
/// oversized body actually gets cut, so it is part of the port, not an implementation detail.
const CHUNK: usize = 8192;

/// How far into the body to look for a `<meta charset>`. HTML5 requires the declaration in
/// the first 1024 bytes; 4096 covers pages that ignore that and costs nothing.
const CHARSET_SNIFF_BYTES: usize = 4096;

/// Characters a charset label is allowed to contain. Anything else ends the label.
fn is_label_byte(b: u8) -> bool {
    b.is_ascii_alphanumeric() || matches!(b, b'_' | b'.' | b':' | b'-')
}

/// Pull the value out of a `charset=...` that starts at `from` in `haystack`.
fn charset_value(haystack: &[u8], from: usize) -> Option<String> {
    let rest = haystack.get(from + "charset".len()..)?;
    let mut it = rest.iter().copied().skip_while(u8::is_ascii_whitespace);
    if it.next()? != b'=' {
        return None;
    }
    let label: Vec<u8> = it
        .skip_while(|b| b.is_ascii_whitespace() || *b == b'"' || *b == b'\'')
        .take_while(|b| is_label_byte(*b))
        .collect();
    if label.is_empty() {
        return None;
    }
    String::from_utf8(label).ok()
}

/// The charset a `<meta>` tag in `head` declares, if one does.
fn charset_from_markup(head: &[u8]) -> Option<String> {
    let lower = head.to_ascii_lowercase();
    let mut at = 0;
    while let Some(off) = lower.get(at..)?.windows(5).position(|w| w == b"<meta") {
        let tag_start = at + off;
        let tag_end = lower
            .get(tag_start..)
            .and_then(|r| r.iter().position(|b| *b == b'>'))
            .map_or(lower.len(), |e| tag_start + e);
        let tag = lower.get(tag_start..tag_end)?;
        if let Some(cs) = tag.windows(7).position(|w| w == b"charset") {
            if let Some(v) = charset_value(tag, cs) {
                return Some(v);
            }
        }
        at = tag_end.max(tag_start + 1);
    }
    None
}

/// Decide how to decode a page body: declared header, then declared markup, then UTF-8.
///
/// THE DEFECT THIS MIRRORS. The Python used to hand the body to `requests`' own guess, and
/// `requests` follows RFC 2616: any `text/*` with no charset parameter is reported as
/// ISO-8859-1. A UTF-8 page served as bare `text/html` was therefore decoded as Latin-1 and
/// every non-ASCII character became mojibake -- 32 corrupted characters in 5,504 on
/// `doc.rust-lang.org/book/ch01-01-installation.html`. This port decoding as UTF-8 is what
/// exposed it. Both sides now run this same ladder, so the parity harness grades extraction
/// rather than two different guesses about bytes.
fn body_encoding(content_type: &str, head: &[u8]) -> &'static Encoding {
    let lower = content_type.to_ascii_lowercase();
    let declared = lower
        .as_bytes()
        .windows(7)
        .position(|w| w == b"charset")
        .and_then(|at| charset_value(lower.as_bytes(), at));
    for name in declared.into_iter().chain(charset_from_markup(head)) {
        if let Some(enc) = Encoding::for_label(name.as_bytes()) {
            return enc;
        }
    }
    UTF_8
}

/// Page furniture. Not prose, and worse than nothing: nav text inflates the question/passage
/// word overlap that `verify.py:138` scores confidence on, so leaving it in makes grounding
/// look better while making it worse.
const FURNITURE: &[&str] = &[
    "script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg", "iframe",
    "button", "select", "template",
];

/// The regions a page may declare as its own content, in preference order.
const LANDMARKS: &[&str] = &["main", "article", "[role='main']", "#content"];

#[derive(Debug, thiserror::Error)]
pub enum RetrieveError {
    #[error("http status {0}")]
    Status(u16),
    #[error("content-type {0} is not markup")]
    ContentType(String),
    #[error("transport: {0}")]
    Transport(String),
}

/// Collapse runs of whitespace to single spaces, and trim. Python's `" ".join(s.split())`.
fn collapse(s: &str) -> String {
    s.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// All text under `node`, in document order, skipping furniture subtrees and the text that
/// trails them.
///
/// The trailing-text rule is what `with_tail=False` means in lxml, and it is not cosmetic:
/// `<nav>...</nav> | Home | About` leaves the pipe-separated crumbs behind without it, which
/// is exactly the boilerplate the strip exists to remove.
fn text_content(node: NodeRef<'_, Node>) -> String {
    let mut out = String::new();
    let mut skip_next_text = false;
    for child in node.children() {
        match child.value() {
            Node::Text(t) => {
                if skip_next_text {
                    skip_next_text = false;
                } else {
                    out.push_str(t.as_ref());
                }
            }
            Node::Element(e) => {
                skip_next_text = false;
                if FURNITURE.contains(&e.name()) {
                    // The element goes, and so does the text immediately after it.
                    skip_next_text = true;
                } else {
                    out.push_str(&text_content(child));
                }
            }
            _ => {}
        }
    }
    out
}

/// The readable text of an HTML document, or `None` if it has none worth calling a passage.
///
/// Deterministic and offline: this is the half of `fetch_page` that a parity harness can
/// grade without a network, so it is where the Python and the Rust are held to agreeing.
#[must_use]
pub fn extract_text(html: &str) -> Option<String> {
    let doc = Html::parse_document(html);

    for landmark in LANDMARKS {
        let Ok(sel) = Selector::parse(landmark) else {
            continue;
        };
        let Some(node) = doc.select(&sel).next() else {
            continue;
        };
        let candidate = collapse(&text_content(*node));
        if candidate.chars().count() >= MIN_PAGE_TEXT {
            return Some(candidate);
        }
    }

    let whole = collapse(&text_content(doc.tree.root()));
    if whole.chars().count() < MIN_PAGE_TEXT {
        return None;
    }
    Some(whole)
}

/// GET a URL and return its readable text.
///
/// Mirrors the Python's refusals rather than inventing its own: a status at or above 400 is
/// no page, a declared content-type that is not markup is no page, and an ABSENT
/// content-type is treated as HTML. That last one looks like sloppiness and is not -- the
/// parse below is the real gate, and dropping a page for a missing header re-introduces the
/// false-drop this code path spent a long time removing.
///
/// # Errors
/// Returns [`RetrieveError`] when the host refuses, the status is an error, or the declared
/// content-type is not markup. A fetch failing is our convenience failing: the caller keeps
/// whatever passage it already had.
pub fn fetch_page(url: &str, timeout: Duration) -> Result<Option<String>, RetrieveError> {
    let agent = ureq::AgentBuilder::new()
        .timeout(timeout)
        .user_agent(RESOLVE_UA)
        .build();

    let resp = match agent.get(url).call() {
        Ok(r) => r,
        Err(ureq::Error::Status(code, _)) => return Err(RetrieveError::Status(code)),
        Err(e) => return Err(RetrieveError::Transport(e.to_string())),
    };

    let raw_ctype = resp.header("Content-Type").unwrap_or_default().to_owned();
    let ctype = resp.content_type().to_lowercase();
    if !(ctype.is_empty()
        || ctype.contains("html")
        || ctype.contains("xml")
        || ctype.contains("text/plain"))
    {
        return Err(RetrieveError::ContentType(ctype));
    }

    // Read in CHUNK-sized bites and stop on the FIRST bite that reaches MAX_BYTES, which
    // overshoots the cap by up to CHUNK-1 bytes. That overshoot is not sloppiness: the Python
    // does `for chunk in resp.iter_content(8192): ... if len(buf) >= max_bytes: break`, so it
    // keeps 401,408 bytes, not 400,000. Cutting at exactly MAX_BYTES instead truncates the
    // markup 1,408 bytes earlier and the extracted text ends on a different word -- measured
    // on en.wikipedia.org/wiki/Rust_(programming_language), a clean `.take(400_000)` lost the
    // trailing "[note 6]" and nothing else, which was the entire diff between the two ports.
    let mut buf: Vec<u8> = Vec::with_capacity(MAX_BYTES + CHUNK);
    let mut reader = resp.into_reader();
    let mut chunk = [0_u8; CHUNK];
    while buf.len() < MAX_BYTES {
        let mut filled = 0;
        while let Some(dst) = chunk.get_mut(filled..).filter(|d| !d.is_empty()) {
            match reader.read(dst) {
                Ok(0) => break,
                Ok(n) => filled += n,
                Err(e) => return Err(RetrieveError::Transport(e.to_string())),
            }
        }
        let Some(taken) = chunk.get(..filled).filter(|t| !t.is_empty()) else {
            break;
        };
        buf.extend_from_slice(taken);
        if filled < CHUNK {
            break;
        }
    }
    if buf.is_empty() {
        return Ok(None);
    }
    let head = buf.get(..CHARSET_SNIFF_BYTES).unwrap_or(&buf);
    let (raw, _, _) = body_encoding(&raw_ctype, head).decode(&buf);
    Ok(extract_text(&raw))
}

#[cfg(test)]
mod charset_ladder {
    //! The same facts `tests/unit/test_page_body_encoding.py` pins on the Python side. Both
    //! implementations decode the same bytes the same way, or the parity harness is grading
    //! two different guesses about bytes rather than two extractors.
    use super::{body_encoding, UTF_8};

    #[test]
    fn a_bare_text_html_page_is_utf8_not_latin1() {
        assert_eq!(body_encoding("text/html", b"<html><head>"), UTF_8);
    }

    #[test]
    fn the_header_charset_wins_when_the_page_declares_one() {
        let enc = body_encoding("text/html; charset=windows-1252", b"");
        assert_eq!(enc.name(), "windows-1252");
    }

    #[test]
    fn a_meta_declaration_is_read_when_the_headers_are_silent() {
        for markup in [
            &br#"<html><head><meta charset="iso-8859-2">"#[..],
            &br"<html><head><meta charset='iso-8859-2'>"[..],
            &br"<html><head><meta charset=iso-8859-2>"[..],
            &br#"<head><meta http-equiv="Content-Type" content="text/html; charset=iso-8859-2">"#[..],
        ] {
            assert_eq!(body_encoding("text/html", markup).name(), "ISO-8859-2");
        }
    }

    #[test]
    fn the_header_outranks_the_markup() {
        let enc = body_encoding(
            "text/html; charset=utf-8",
            br#"<meta charset="windows-1252">"#,
        );
        assert_eq!(enc, UTF_8);
    }

    #[test]
    fn a_charset_nobody_can_load_falls_back_rather_than_failing() {
        assert_eq!(body_encoding("text/html; charset=bogus-9000", b""), UTF_8);
        assert_eq!(
            body_encoding("text/html", br#"<meta charset="bogus-9000">"#),
            UTF_8
        );
    }

    #[test]
    fn a_meta_tag_that_declares_nothing_does_not_stop_the_scan() {
        // The first `<meta>` on most pages is a viewport or a description. Reading only the
        // first one would miss the declaration on nearly every real page.
        let markup =
            br#"<meta name="viewport" content="width=device-width"><meta charset="shift_jis">"#;
        assert_eq!(body_encoding("text/html", markup).name(), "Shift_JIS");
    }
}
