//! Verdicts, decisions, and the closed set of reasons that mean "not ruled".
//!
//! Ported from `prospector/models.py:25-66`.
//!
//! ## Why this is the first thing ported
//!
//! `build_dossier` decides KILL for any `gate_fired` it does not recognise. For a real gate
//! that is correct — an unknown gate name is still a gate that fired. For a *deferral* it is
//! silently catastrophic: a mistyped or newly-added defer reason mints an evidentiary KILL on
//! a candidate no check ever looked at. `store/dossiers/2102bacc6dd75cf9.kill.json` is that
//! defect on disk, and models.py records it happening twice more on 2026-08-21 when
//! `score_failed` and `adversarial_unrun` were found writing a finished decision out of a
//! component's own failure.
//!
//! In Python the closure is a `frozenset` and a comment asking the next author to add their
//! new reason next to the invariant. Here the closure is the type. A new defer reason cannot
//! be added without adding its wire string in the same `match`, because the compiler refuses
//! a non-exhaustive one — so the failure mode that produced that dossier is not a discipline
//! problem any more.

use serde::{Deserialize, Serialize};

/// What a single check concluded. `prospector/models.py:25`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Verdict {
    Supported,
    Refuted,
    Unverifiable,
}

/// What the engine decided about a candidate. `prospector/models.py:31`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Decision {
    Pass,
    Kill,
    /// Could not be ruled on (retrieval or infra failure) — re-vet later, **not** a kill.
    Defer,
}

/// The closed set of `gate_fired` values that mean "not ruled" rather than "ruled against".
///
/// `prospector/models.py:62` (`DEFER_REASONS`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DeferReason {
    /// A decisive check could not be retrieved. `models.py:39` calls this `DEFER_GATE`.
    RetrievalUnavailable,
    /// No trusted brain was available to rule.
    MoatExhausted,
    /// The tick's vetting clock ran out before this candidate started.
    VetBudgetSpent,
    /// A producer enqueued it; no consumer has taken it yet.
    QueuedForVetting,
    /// The scoring call errored. The all-zero fail-safe is not a low score.
    ScoreFailed,
    /// The adversarial pass raised; the final gate never ran.
    AdversarialUnrun,
}

impl DeferReason {
    /// Every variant, in declaration order. Exhaustive by construction: adding a variant
    /// without adding it here fails the `all_variants_are_listed` test below.
    pub const ALL: [Self; 6] = [
        Self::RetrievalUnavailable,
        Self::MoatExhausted,
        Self::VetBudgetSpent,
        Self::QueuedForVetting,
        Self::ScoreFailed,
        Self::AdversarialUnrun,
    ];

    /// The exact string written to `gate_fired` on disk and read by `ops/`, the ledger and
    /// the 3,585 existing dossiers. Changing one of these is a data migration, not a rename.
    #[must_use]
    pub const fn as_wire(self) -> &'static str {
        match self {
            Self::RetrievalUnavailable => "retrieval_unavailable",
            Self::MoatExhausted => "moat_exhausted",
            Self::VetBudgetSpent => "vet_budget_spent",
            Self::QueuedForVetting => "queued_for_vetting",
            Self::ScoreFailed => "score_failed",
            Self::AdversarialUnrun => "adversarial_unrun",
        }
    }

    /// Parse a `gate_fired` string. `None` means "this is a real gate", which is the branch
    /// that produces a KILL — so a caller can never accidentally treat an unknown string as
    /// a deferral, and can never treat a known deferral as a gate.
    #[must_use]
    pub fn from_wire(s: &str) -> Option<Self> {
        Self::ALL.into_iter().find(|r| r.as_wire() == s)
    }
}

/// The `gate_fired` -> `Decision` rule, ported from `build_dossier`.
///
/// `None` is "no gate fired", which is a PASS. A recognised defer reason is a DEFER.
/// Anything else is a real gate, and a real gate that fired is a KILL.
#[must_use]
pub fn decision_for_gate(gate_fired: Option<&str>) -> Decision {
    match gate_fired {
        None => Decision::Pass,
        Some(g) => match DeferReason::from_wire(g) {
            Some(_) => Decision::Defer,
            None => Decision::Kill,
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use proptest::prelude::*;

    /// The six strings in `models.py:62`, written out by hand rather than derived, so that a
    /// change on either side of the port has to be made deliberately on both.
    const PYTHON_DEFER_REASONS: [&str; 6] = [
        "retrieval_unavailable",
        "moat_exhausted",
        "vet_budget_spent",
        "queued_for_vetting",
        "score_failed",
        "adversarial_unrun",
    ];

    #[test]
    fn wire_strings_match_python_exactly() {
        let mut ours: Vec<&str> = DeferReason::ALL.iter().map(|r| r.as_wire()).collect();
        let mut theirs = PYTHON_DEFER_REASONS.to_vec();
        ours.sort_unstable();
        theirs.sort_unstable();
        assert_eq!(
            ours, theirs,
            "DEFER_REASONS drifted from prospector/models.py:62"
        );
    }

    #[test]
    fn all_variants_are_listed() {
        // If someone adds a variant and forgets ALL, from_wire stops seeing it and this
        // catches it before the missing entry can mint a KILL in production.
        assert_eq!(DeferReason::ALL.len(), PYTHON_DEFER_REASONS.len());
        for r in DeferReason::ALL {
            assert_eq!(DeferReason::from_wire(r.as_wire()), Some(r));
        }
    }

    #[test]
    fn every_defer_reason_defers_and_no_gate_passes() {
        assert_eq!(decision_for_gate(None), Decision::Pass);
        for r in DeferReason::ALL {
            assert_eq!(
                decision_for_gate(Some(r.as_wire())),
                Decision::Defer,
                "{} must defer, never kill",
                r.as_wire()
            );
        }
    }

    #[test]
    fn serde_uses_the_wire_strings() {
        for r in DeferReason::ALL {
            let json = serde_json::to_string(&r).unwrap();
            assert_eq!(json, format!("\"{}\"", r.as_wire()));
            assert_eq!(serde_json::from_str::<DeferReason>(&json).unwrap(), r);
        }
        assert_eq!(
            serde_json::to_string(&Decision::Defer).unwrap(),
            "\"defer\""
        );
        assert_eq!(
            serde_json::to_string(&Verdict::Unverifiable).unwrap(),
            "\"unverifiable\""
        );
    }

    proptest! {
        /// The invariant the Python comment asks the next author to preserve by hand:
        /// an unrecognised gate is a KILL, and it is a KILL *only* if it is unrecognised.
        #[test]
        fn unknown_gates_kill_and_known_ones_never_do(s in "\\PC{0,64}") {
            let expected = if DeferReason::from_wire(&s).is_some() {
                Decision::Defer
            } else {
                Decision::Kill
            };
            prop_assert_eq!(decision_for_gate(Some(&s)), expected);
        }
    }
}
