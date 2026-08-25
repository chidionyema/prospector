//! figures.csv and claims.csv, one row per value, every row with its source.
use crate::ir::{Pack, Support};
use crate::Error;

fn finish(w: csv::Writer<Vec<u8>>) -> Result<Vec<u8>, Error> {
    w.into_inner().map_err(|e| Error::Csv(e.to_string()))
}

pub fn figures(p: &Pack) -> Result<Vec<u8>, Error> {
    let mut w = csv::Writer::from_writer(Vec::new());
    w.write_record(["label", "value", "unit", "as_of", "source_url", "source_fetched_at", "source_sha256"]).map_err(|e| Error::Csv(e.to_string()))?;
    for f in p.figures() {
        w.write_record([
            f.label.as_str(),
            &f.value.to_string(),
            f.unit.label(),
            &f.as_of.to_string(),
            f.source.url(),
            &f.source.fetched_at().to_string(),
            f.source.body_sha256(),
        ])
        .map_err(|e| Error::Csv(e.to_string()))?;
    }
    finish(w)
}

pub fn claims(p: &Pack) -> Result<Vec<u8>, Error> {
    let mut w = csv::Writer::from_writer(Vec::new());
    w.write_record(["id", "text", "support", "source_url", "source_fetched_at", "source_sha256"]).map_err(|e| Error::Csv(e.to_string()))?;
    for c in p.claims() {
        let (kind, url, at, sha) = match &c.support {
            Support::Cited { source } => ("cited", source.url().to_owned(), source.fetched_at().to_string(), source.body_sha256().to_owned()),
            Support::Unverifiable => ("unverifiable", String::new(), String::new(), String::new()),
        };
        w.write_record([c.id.as_str(), c.text.as_str(), kind, &url, &at, &sha]).map_err(|e| Error::Csv(e.to_string()))?;
    }
    finish(w)
}
