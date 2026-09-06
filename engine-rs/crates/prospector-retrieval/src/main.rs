//! `retrieve <url>` -- print what the engine would read from a page, as JSON.
//!
//! The output shape is deliberately the parity harness's input: one JSON object per URL, so
//! the Python and the Rust can be diffed by a script rather than by eye.

use std::time::Duration;

use serde::Serialize;

#[derive(Serialize, Debug)]
struct Out {
    url: String,
    text: Option<String>,
    chars: usize,
    error: Option<String>,
}

fn main() -> std::process::ExitCode {
    let Some(url) = std::env::args().nth(1) else {
        eprintln!("usage: retrieve <url>");
        return std::process::ExitCode::from(2);
    };

    let (text, error) = match prospector_retrieval::fetch_page(&url, Duration::from_secs(8)) {
        Ok(t) => (t, None),
        Err(e) => (None, Some(e.to_string())),
    };

    let out = Out {
        url,
        chars: text.as_ref().map_or(0, |t| t.chars().count()),
        text,
        error,
    };

    match serde_json::to_string(&out) {
        Ok(s) => {
            println!("{s}");
            std::process::ExitCode::SUCCESS
        }
        Err(e) => {
            eprintln!("could not serialise: {e}");
            std::process::ExitCode::FAILURE
        }
    }
}
