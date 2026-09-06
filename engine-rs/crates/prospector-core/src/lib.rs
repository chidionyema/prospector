//! The engine's domain types. serde only, no I/O.
//!
//! Ported from `prospector/models.py`. Wire strings are the same strings, because the
//! Python brain sidecar, the existing ledger and 3,585 dossiers on disk all speak them.

pub mod decision;

pub use decision::{decision_for_gate, Decision, DeferReason, Verdict};
