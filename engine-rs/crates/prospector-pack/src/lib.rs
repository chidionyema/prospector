//! The pack generator. ADR 0010: generate one typed value, render every format from it.
//!
//! A pack sells for £2,000 to £27,000. This crate makes the three failures that destroy one
//! unrepresentable rather than caught: a figure with no source cannot be built (`Figure::new`
//! takes a `SourceRef`), a source nobody fetched cannot enter a pack (`Pack::load` checks every
//! `SourceRef` against the fetch ledger, ADR 0011), and the PDF cannot disagree with the HTML
//! (`gate::check` asserts every claim and figure appears in every view before the bundle exists).
pub mod gate;
pub mod ir;
pub mod manifest;
pub mod render;

use std::collections::BTreeMap;

use rayon::prelude::*;

use crate::ir::Pack;

/// File name to bytes. `BTreeMap` so iteration order, and therefore the manifest, is fixed.
pub type Bundle = BTreeMap<String, Vec<u8>>;

/// Everything that can stop a bundle being built. None of these are recoverable by retrying.
#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("pack json: {0}")]
    Json(#[from] serde_json::Error),
    #[error("source not minted by the fetch path (ADR 0011): {url} sha256={sha256}")]
    UnmintedSource { url: String, sha256: String },
    #[error("html template: {0}")]
    Template(String),
    #[error("typst: {0}")]
    Typst(String),
    #[error("csv: {0}")]
    Csv(String),
    #[error("view {view} is missing {what}: {value}")]
    ViewDisagrees { view: String, what: String, value: String },
}

/// Timings per format, milliseconds, for the bench receipt.
#[derive(Debug, Clone, serde::Serialize)]
pub struct Timings {
    pub html_ms: f64,
    pub pdf_ms: f64,
    pub csv_ms: f64,
    pub json_ms: f64,
    pub total_ms: f64,
}

/// Render every view of `pack` in parallel, gate them against the value, and return the bundle
/// with its manifest. Pure: the same `Pack` yields the same bytes.
/// One view of the pack.
type Renderer = fn(&Pack) -> Result<Vec<u8>, Error>;
/// Rendered bytes and the milliseconds they took.
type Rendered = (Vec<u8>, f64);

pub fn build(pack: &Pack) -> Result<(Bundle, Timings), Error> {
    let t0 = std::time::Instant::now();
    let jobs: Vec<(&str, Renderer)> = vec![
        ("index.html", |p| render::html::render(p).map(String::into_bytes)),
        ("Complete_Pack.pdf", render::typst::render_pdf),
        ("figures.csv", render::csv::figures),
        ("claims.csv", render::csv::claims),
        ("pack.json", render::json::render),
        ("Complete_Pack.typ", |p| Ok(render::typst::source(p).into_bytes())),
    ];
    let results: Vec<(String, Result<Rendered, Error>)> = jobs
        .into_par_iter()
        .map(|(name, f)| {
            let t = std::time::Instant::now();
            let r = f(pack).map(|b| (b, t.elapsed().as_secs_f64() * 1000.0));
            (name.to_owned(), r)
        })
        .collect();
    let mut bundle = Bundle::new();
    let mut ms = BTreeMap::new();
    for (name, r) in results {
        let (bytes, t) = r?;
        ms.insert(name.clone(), t);
        bundle.insert(name, bytes);
    }
    gate::check(pack, &bundle)?;
    let m = manifest::build(&bundle);
    bundle.insert("manifest.json".to_owned(), serde_json::to_vec_pretty(&m)?);
    let get = |k: &str| ms.get(k).copied().unwrap_or(0.0);
    Ok((
        bundle,
        Timings {
            html_ms: get("index.html"),
            pdf_ms: get("Complete_Pack.pdf"),
            csv_ms: get("figures.csv") + get("claims.csv"),
            json_ms: get("pack.json"),
            total_ms: t0.elapsed().as_secs_f64() * 1000.0,
        },
    ))
}
