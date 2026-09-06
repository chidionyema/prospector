//! `Complete_Pack.pdf`: the value is written as Typst markup, then compiled in-process by an engine
//! built once per process with the fonts Typst embeds. No system font search, so the same input
//! yields the same PDF on any machine, and the font set is loaded once rather than per pack.
use std::fmt::Write as _;
use std::sync::OnceLock;

use typst_as_lib::typst_kit_options::TypstKitFontOptions;
use typst_as_lib::TypstEngine;
use typst_as_lib::TypstTemplateCollection;

use crate::ir::{Block, Pack, Support};
use crate::Error;

/// The fixed frame: page, fonts, numbering. The pack body arrives as `sys.inputs.body` and is
/// evaluated as markup, so the engine and its font set are shared across every pack.
const FRAME: &str = r##"#import sys: inputs
#set page(paper: "a4", margin: 2cm, numbering: "1")
#set text(font: "Libertinus Serif", size: 10.5pt)
#set par(justify: true)
#set heading(numbering: "1.1")
#show link: set text(fill: rgb("#0f6e6e"))
#eval(inputs.body, mode: "markup")
"##;

fn engine() -> &'static TypstEngine<TypstTemplateCollection> {
    static ENGINE: OnceLock<TypstEngine<TypstTemplateCollection>> = OnceLock::new();
    ENGINE.get_or_init(|| {
        TypstEngine::builder()
            .with_static_source_file_resolver([("frame.typ", FRAME)])
            .search_fonts_with(
                TypstKitFontOptions::default()
                    .include_system_fonts(false)
                    .include_embedded_fonts(true),
            )
            .build()
    })
}

/// Escape the characters Typst treats as markup inside text.
/// Typst markup escaping; also used by the gate so the two cannot drift.
pub(crate) fn esc(s: &str) -> String {
    let mut o = String::with_capacity(s.len() + 8);
    for ch in s.chars() {
        match ch {
            '\\' | '#' | '*' | '_' | '`' | '$' | '<' | '>' | '@' | '[' | ']' | '~' | '/' | '"'
            | '\'' => {
                o.push('\\');
                o.push(ch);
            }
            _ => o.push(ch),
        }
    }
    o
}

/// The Typst markup for a pack body. A pure function; it is what the gate reads.
#[must_use]
pub fn source(p: &Pack) -> String {
    let mut t = String::with_capacity(64 * 1024);
    let _ = writeln!(
        t,
        "#align(center)[#text(size: 22pt, weight: \"bold\")[{}]]",
        esc(&p.meta.title)
    );
    if !p.meta.one_liner.is_empty() {
        let _ = writeln!(t, "#align(center)[{}]", esc(&p.meta.one_liner));
    }
    let _ = write!(t,
        "#align(center)[#text(size: 9pt, fill: gray)[Pack {} · verified {} · {} cited claims · {} sources]]\n#v(1em)\n#outline()\n#pagebreak()\n",
        esc(&p.meta.pack_id),
        p.meta.verified_at,
        p.cited_claim_count(),
        p.sources().len()
    );
    for s in &p.sections {
        let _ = writeln!(t, "= {}", esc(&s.title));
        for b in &s.blocks {
            match b {
                Block::Heading { text } => {
                    let _ = writeln!(t, "== {}", esc(text));
                }
                Block::Paragraph { text } => {
                    let _ = write!(t, "{}\n\n", esc(text));
                }
                Block::Bullets { items } => {
                    for i in items {
                        let _ = writeln!(t, "- {}", esc(i));
                    }
                    t.push('\n');
                }
                Block::Claim(c) => {
                    let (tag, src) = match &c.support {
                        Support::Cited { source } => (
                            "cited",
                            format!(" · #link(\"{}\")[{}]", source.url(), esc(source.url())),
                        ),
                        Support::Unverifiable => ("unverifiable", String::new()),
                    };
                    let _ = write!(t,
                        "#block(stroke: (left: 2pt + rgb(\"#0f6e6e\")), inset: (left: 8pt, y: 4pt))[{} #linebreak() #text(size: 8pt, fill: gray)[{} · {}{}]]\n\n",
                        esc(&c.text),
                        esc(&c.id),
                        tag,
                        src
                    );
                }
                Block::Figures { rows } => {
                    t.push_str("#table(columns: (auto, auto, auto, auto, 1fr), stroke: 0.4pt + luma(200), [*Figure*], [*Value*], [*Unit*], [*As of*], [*Source*],\n");
                    for f in rows {
                        let _ = writeln!(
                            t,
                            "[{}], [{}], [{}], [{}], [#link(\"{}\")[{}]],",
                            esc(&f.label),
                            esc(&f.value.to_string()),
                            esc(f.unit.label()),
                            f.as_of,
                            f.source.url(),
                            esc(f.source.url())
                        );
                    }
                    t.push_str(")\n\n");
                }
            }
        }
    }
    t
}

/// Compile and export. Set `PACK_TRACE=1` to print where the milliseconds go.
pub fn render_pdf(p: &Pack) -> Result<Vec<u8>, Error> {
    let trace = std::env::var_os("PACK_TRACE").is_some();
    let t0 = std::time::Instant::now();
    let body = source(p);
    let t1 = std::time::Instant::now();
    let eng = engine();
    let t2 = std::time::Instant::now();
    let mut inputs = typst::foundations::Dict::new();
    inputs.insert(
        "body".into(),
        typst::foundations::IntoValue::into_value(body),
    );
    let doc: typst_layout::PagedDocument = eng
        .compile_with_input("frame.typ", inputs)
        .output
        .map_err(|e| Error::Typst(format!("{e:?}")))?;
    let t3 = std::time::Instant::now();
    let pdf = typst_pdf::pdf(
        &doc,
        &typst_pdf::PdfOptions {
            // Tagged PDF added 4,982 StructElem objects (435 KB of a 1.09 MB file) on the
            // bench fixture; the pack's accessibility surface is index.html.
            tagged: false,
            ident: typst::foundations::Smart::Custom(p.meta.pack_id.clone()),
            ..typst_pdf::PdfOptions::default()
        },
    )
    .map_err(|e| Error::Typst(format!("{e:?}")))?;
    if trace {
        eprintln!(
            "PACK_TRACE source={:.1}ms engine={:.1}ms compile={:.1}ms pdf={:.1}ms pages={}",
            (t1 - t0).as_secs_f64() * 1000.0,
            (t2 - t1).as_secs_f64() * 1000.0,
            (t3 - t2).as_secs_f64() * 1000.0,
            t3.elapsed().as_secs_f64() * 1000.0,
            doc.pages().len()
        );
    }
    Ok(pdf)
}
