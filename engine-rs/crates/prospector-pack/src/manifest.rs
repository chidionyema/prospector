//! sha256 per file and one digest over the sorted (name, hash) list. A zip digest moves with
//! compression and entry order; this one does not, so it is the thing a buyer can quote back.

use sha2::{Digest, Sha256};

use crate::Bundle;

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct Entry {
    pub name: String,
    pub bytes: usize,
    pub sha256: String,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct Manifest {
    pub files: Vec<Entry>,
    pub pack_digest: String,
}

#[must_use]
pub fn sha256_hex(b: &[u8]) -> String {
    hex::encode(Sha256::digest(b))
}

#[must_use]
pub fn build(bundle: &Bundle) -> Manifest {
    let mut files: Vec<Entry> = bundle
        .iter()
        .map(|(name, bytes)| Entry {
            name: name.clone(),
            bytes: bytes.len(),
            sha256: sha256_hex(bytes),
        })
        .collect();
    files.sort_by(|a, b| a.name.cmp(&b.name));
    let mut h = Sha256::new();
    for f in &files {
        h.update(f.name.as_bytes());
        h.update(b"\0");
        h.update(f.sha256.as_bytes());
        h.update(b"\n");
    }
    Manifest {
        pack_digest: hex::encode(h.finalize()),
        files,
    }
}
