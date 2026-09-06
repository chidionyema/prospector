//! The extraction ladder, held to the rules the Python states.
//!
//! These are the cases the Python's own comments name as the ones it was changed to handle,
//! so a rewrite that regresses any of them regresses a measured incident, not a preference.

use prospector_retrieval::{extract_text, MIN_PAGE_TEXT};

fn filler(n: usize) -> String {
    "lorem ipsum dolor sit amet ".repeat(n)
}

#[test]
fn a_page_shorter_than_the_floor_is_no_passage_at_all() {
    // "Page not found - GeekWire", 25 chars. The caller keeps its search snippet.
    assert_eq!(
        extract_text("<html><body><p>Page not found - GeekWire</p></body></html>"),
        None
    );
}

#[test]
fn navigation_never_reaches_the_passage() {
    let html = format!(
        "<html><body><nav>Skip Navigation Personal Business Find a store Shop Deals</nav>\
         <main><p>{}</p></main></body></html>",
        filler(20)
    );
    let text = extract_text(&html).unwrap_or_default();
    assert!(
        !text.contains("Skip Navigation"),
        "nav leaked into the passage: {text}"
    );
    assert!(text.contains("lorem ipsum"));
}

#[test]
fn the_text_trailing_a_stripped_element_goes_with_it() {
    // lxml's strip_elements(..., with_tail=False). Without it the crumbs survive.
    let html = format!(
        "<html><body><nav>menu</nav> | Home | About <main><p>{}</p></main></body></html>",
        filler(20)
    );
    let text = extract_text(&html).unwrap_or_default();
    assert!(
        !text.contains("Home"),
        "tail text survived the strip: {text}"
    );
}

#[test]
fn main_wins_over_the_whole_document() {
    let html = format!(
        "<html><body><div>{}</div><main><p>THE ARTICLE {}</p></main></body></html>",
        filler(30),
        filler(20)
    );
    let text = extract_text(&html).unwrap_or_default();
    assert!(text.starts_with("THE ARTICLE"), "landmark ignored: {text}");
}

#[test]
fn a_landmark_too_short_to_be_a_passage_falls_through_to_the_document() {
    // gov.uk-style pages carry the body outside every landmark. Refusing those re-creates
    // the false-drop the Python spent a long time removing.
    let html = format!(
        "<html><body><main>short</main><div>{}</div></body></html>",
        filler(30)
    );
    let text = extract_text(&html).unwrap_or_default();
    assert!(text.chars().count() >= MIN_PAGE_TEXT);
    assert!(text.contains("lorem ipsum"));
}

#[test]
fn script_bodies_are_not_prose() {
    let html = format!(
        "<html><body><script>var x = 'lorem ipsum tracking pixel';</script>\
         <div>{}</div></body></html>",
        filler(30)
    );
    let text = extract_text(&html).unwrap_or_default();
    assert!(
        !text.contains("tracking pixel"),
        "script body leaked: {text}"
    );
}

#[test]
fn whitespace_is_collapsed_the_way_python_collapses_it() {
    let html = format!(
        "<html><body><div>  a\n\n\tb   {}  </div></body></html>",
        filler(30)
    );
    let text = extract_text(&html).unwrap_or_default();
    assert!(text.starts_with("a b lorem"), "{text}");
    assert!(!text.contains("  "));
}
