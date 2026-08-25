//! index.html via Askama: the template is compiled, so a field the template names that the
//! value lacks is a build error, not a blank on a sold pack.
use askama::Template;

use crate::ir::{Block, Pack, Support};
use crate::Error;

#[derive(Template)]
#[template(path = "pack.html")]
struct PackPage<'a> {
    pack: &'a Pack,
    cited: usize,
    source_count: usize,
}

/// Askama cannot match on enums inside a `for` cleanly across versions, so blocks are flattened
/// to a small view struct the template iterates.
#[derive(Debug)]
pub struct BlockView {
    pub kind: &'static str,
    pub text: String,
    pub items: Vec<String>,
    pub rows: Vec<[String; 5]>,
    pub claim_id: String,
    pub support: String,
    pub url: String,
}

#[must_use]
pub fn view(b: &Block) -> BlockView {
    let empty = BlockView { kind: "", text: String::new(), items: vec![], rows: vec![], claim_id: String::new(), support: String::new(), url: String::new() };
    match b {
        Block::Heading { text } => BlockView { kind: "heading", text: text.clone(), ..empty },
        Block::Paragraph { text } => BlockView { kind: "paragraph", text: text.clone(), ..empty },
        Block::Bullets { items } => BlockView { kind: "bullets", items: items.clone(), ..empty },
        Block::Claim(c) => {
            let (support, url) = match &c.support {
                Support::Cited { source } => ("cited".to_owned(), source.url().to_owned()),
                Support::Unverifiable => ("unverifiable".to_owned(), String::new()),
            };
            BlockView { kind: "claim", text: c.text.clone(), claim_id: c.id.clone(), support, url, ..empty }
        }
        Block::Figures { rows } => BlockView {
            kind: "figures",
            rows: rows
                .iter()
                .map(|f| [f.label.clone(), f.value.to_string(), f.unit.label().to_owned(), f.as_of.to_string(), f.source.url().to_owned()])
                .collect(),
            ..empty
        },
    }
}

pub fn render(p: &Pack) -> Result<String, Error> {
    PackPage { pack: p, cited: p.cited_claim_count(), source_count: p.sources().len() }
        .render()
        .map_err(|e| Error::Template(e.to_string()))
}
