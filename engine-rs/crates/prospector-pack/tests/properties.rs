// Test code: a failed unwrap is the test failing, which is the point.
#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Rung 2 of the test ladder: properties that survive a rewrite.
//! (a) every claim and figure appears in every view; (b) rendering is byte-deterministic;
//! (c) the manifest digest ignores file order; (d) an unminted source is refused at load.
use chrono::NaiveDate;
use proptest::prelude::*;
use prospector_pack::ir::{
    Block, Claim, FetchLedger, FetchReceipt, Figure, Meta, Pack, Section, Support, Unit,
};
use rust_decimal::Decimal;

fn text() -> impl Strategy<Value = String> {
    "[A-Za-z0-9 ,.£%&<>'\"#*_\\[\\]-]{1,40}".prop_filter("non-blank", |s| !s.trim().is_empty())
}

fn date() -> impl Strategy<Value = NaiveDate> {
    (2020i32..2030, 1u32..13, 1u32..29)
        .prop_map(|(y, m, d)| NaiveDate::from_ymd_opt(y, m, d).unwrap())
}

fn unit() -> impl Strategy<Value = Unit> {
    prop_oneof![
        Just(Unit::GbpPerMonth),
        Just(Unit::Gbp),
        Just(Unit::Percent),
        Just(Unit::Count),
        Just(Unit::Hours),
        Just(Unit::Days)
    ]
}

fn receipt() -> impl Strategy<Value = FetchReceipt> {
    ("[a-z]{3,8}", date(), "[0-9a-f]{64}").prop_map(|(h, d, sha)| FetchReceipt {
        url: format!("https://{h}.example/{sha}"),
        fetched_at: d,
        body_sha256: sha,
    })
}

/// A pack plus the ledger that minted its sources. Built through the only door: `mint`.
fn pack() -> impl Strategy<Value = (Pack, FetchLedger)> {
    let block = (
        any::<u8>(),
        text(),
        prop::collection::vec(text(), 1..4),
        receipt(),
        any::<i64>(),
        unit(),
        date(),
        any::<bool>(),
    );
    (
        text(),
        text(),
        date(),
        prop::collection::vec((text(), prop::collection::vec(block, 1..6)), 1..4),
    )
        .prop_map(|(title, one, verified, secs)| {
            let mut ledger = FetchLedger::default();
            let mut n = 0u32;
            let sections = secs
                .into_iter()
                .map(|(st, blocks)| Section {
                    title: st,
                    blocks: blocks
                        .into_iter()
                        .map(|(kind, t, items, r, v, u, d, cited)| match kind % 5 {
                            0 => Block::Heading { text: t },
                            1 => Block::Paragraph { text: t },
                            2 => Block::Bullets { items },
                            3 => {
                                n += 1;
                                let support = if cited {
                                    Support::Cited {
                                        source: ledger.mint(r),
                                    }
                                } else {
                                    Support::Unverifiable
                                };
                                Block::Claim(Claim {
                                    id: format!("C{n:04}"),
                                    text: t,
                                    support,
                                })
                            }
                            _ => Block::Figures {
                                rows: vec![Figure::new(
                                    t,
                                    Decimal::new(v, 2),
                                    u,
                                    d,
                                    ledger.mint(r),
                                )],
                            },
                        })
                        .collect(),
                })
                .collect();
            (
                Pack {
                    meta: Meta {
                        pack_id: "p1".into(),
                        title,
                        one_liner: one,
                        verified_at: verified,
                    },
                    sections,
                },
                ledger,
            )
        })
}

proptest! {
    #![proptest_config(ProptestConfig { cases: 48, ..ProptestConfig::default() })]

    #[test]
    fn every_claim_and_figure_in_every_view_and_deterministic((p, _l) in pack()) {
        let (b1, _) = prospector_pack::build(&p).unwrap();          // the gate ran inside build
        let (b2, _) = prospector_pack::build(&p).unwrap();
        prop_assert_eq!(&b1, &b2);                                    // (b) byte-deterministic, PDF included
        prop_assert!(b1.contains_key("Complete_Pack.pdf") && b1["Complete_Pack.pdf"].starts_with(b"%PDF"));
    }

    #[test]
    fn manifest_digest_ignores_order((p, _l) in pack()) {
        let (bundle, _) = prospector_pack::build(&p).unwrap();
        let m1 = prospector_pack::manifest::build(&bundle);
        let reversed: prospector_pack::Bundle = bundle.iter().rev().map(|(k, v)| (k.clone(), v.clone())).collect();
        let m2 = prospector_pack::manifest::build(&reversed);
        prop_assert_eq!(m1.pack_digest, m2.pack_digest);              // (c)
    }

    #[test]
    fn unminted_source_is_refused((p, l) in pack()) {
        let json = serde_json::to_vec(&p).unwrap();
        prop_assert!(Pack::load(&json, &l).is_ok());
        if !p.sources().is_empty() {
            let empty = FetchLedger::default();
            let refused = matches!(Pack::load(&json, &empty), Err(prospector_pack::Error::UnmintedSource { .. }));
            prop_assert!(refused, "unminted source was accepted");   // (d)
        }
    }

    #[test]
    fn a_view_that_drops_a_claim_fails_the_gate((p, _l) in pack()) {
        let (mut bundle, _) = prospector_pack::build(&p).unwrap();
        if let Some(c) = p.claims().next() {
            let html = String::from_utf8(bundle["index.html"].clone()).unwrap().replace(&c.id, "");
            bundle.insert("index.html".into(), html.into_bytes());
            prop_assert!(prospector_pack::gate::check(&p, &bundle).is_err());   // the gate refuses, proved both ways
        }
    }
}
