//! The differential gate: every claim and every figure in the value appears in every view.
//! This is what stops the PDF and the web page disagreeing. It runs before the bundle exists.
//!
//! The PDF is checked through its Typst source, which is the pure function the PDF is compiled
//! from; the compiled bytes are compressed and are not searched. Residual: a Typst layout bug
//! that drops text would pass this gate. Outside the crate, the pypdf oracle in the bench chain
//! reads the compiled PDF back (claims 112 missing 0; figures 224 missing 0); CI does not run it.

use crate::ir::Pack;
use crate::{Bundle, Error};

const TEXT_VIEWS: [&str; 5] = [
    "index.html",
    "Complete_Pack.typ",
    "claims.csv",
    "figures.csv",
    "pack.json",
];

fn view_has(bundle: &Bundle, view: &str, needle: &str) -> bool {
    bundle.get(view).is_some_and(|b| {
        let s = String::from_utf8_lossy(b);
        s.contains(needle)
            || s.contains(&html_escape(needle))
            || s.contains(&json_escape(needle))
            || s.contains(&crate::render::typst::esc(needle))
            || s.contains(&needle.replace('"', "\"\""))
    })
}

fn html_escape(s: &str) -> String {
    // Askama's own escaper, so the gate can never disagree with the template about entities.
    match askama::filters::escape(s, askama::filters::Html) {
        Ok(v) => v.to_string(),
        Err(never) => match never {},
    }
}

fn json_escape(s: &str) -> String {
    serde_json::to_string(s)
        .map(|q| q.trim_matches('"').to_owned())
        .unwrap_or_default()
}

pub fn check(pack: &Pack, bundle: &Bundle) -> Result<(), Error> {
    for view in TEXT_VIEWS {
        let claims_view = view != "figures.csv";
        let figures_view = view != "claims.csv";
        if claims_view {
            for c in pack.claims() {
                if !view_has(bundle, view, &c.id) {
                    return Err(Error::ViewDisagrees {
                        view: view.into(),
                        what: "claim id".into(),
                        value: c.id.clone(),
                    });
                }
                if !view_has(bundle, view, &c.text) {
                    return Err(Error::ViewDisagrees {
                        view: view.into(),
                        what: "claim text".into(),
                        value: c.text.clone(),
                    });
                }
            }
        }
        if figures_view {
            for f in pack.figures() {
                let v = f.value.to_string();
                if !view_has(bundle, view, &v) {
                    return Err(Error::ViewDisagrees {
                        view: view.into(),
                        what: "figure value".into(),
                        value: v,
                    });
                }
                if !view_has(bundle, view, f.source.url()) {
                    return Err(Error::ViewDisagrees {
                        view: view.into(),
                        what: "figure source".into(),
                        value: f.source.url().into(),
                    });
                }
            }
        }
    }
    Ok(())
}
