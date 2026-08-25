//! The typed value a pack *is*. Every view is a pure function of one `Pack`.
//!
//! Two rules are types here, not checks:
//! - `Support` has exactly two arms. A third arm, "true because the model knows it", was refused
//!   in ADR 0010 because it re-admits prior knowledge into a verdict-from-retrieval-only system.
//! - `Figure` has no constructor without a `SourceRef`, and `SourceRef` has no public constructor
//!   at all: it comes from `FetchLedger::mint`, which is the fetch path (ADR 0011). A pack loaded
//!   from JSON re-checks every source against the ledger before the value exists.

use std::collections::BTreeSet;

use chrono::NaiveDate;
use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};

/// A page as it was fetched: the URL, the moment, and the hash of the bytes. This is the record
/// the fetch path writes and the only thing a `SourceRef` can be minted from.
#[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
pub struct FetchReceipt {
    pub url: String,
    pub fetched_at: NaiveDate,
    pub body_sha256: String,
}

/// The set of receipts the fetch path produced for this candidate.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct FetchLedger {
    receipts: BTreeSet<FetchReceipt>,
}

impl FetchLedger {
    #[must_use]
    pub fn new(receipts: impl IntoIterator<Item = FetchReceipt>) -> Self {
        Self { receipts: receipts.into_iter().collect() }
    }

    /// The fetch path mints a reference by recording the fetch. There is no other way.
    pub fn mint(&mut self, receipt: FetchReceipt) -> SourceRef {
        let r = SourceRef { url: receipt.url.clone(), fetched_at: receipt.fetched_at, body_sha256: receipt.body_sha256.clone() };
        self.receipts.insert(receipt);
        r
    }

    #[must_use]
    pub fn holds(&self, s: &SourceRef) -> bool {
        self.receipts.contains(&FetchReceipt { url: s.url.clone(), fetched_at: s.fetched_at, body_sha256: s.body_sha256.clone() })
    }
}

/// A citation. Fields are private; `Deserialize` exists so a pack can cross a process boundary,
/// and `Pack::load` refuses any reference the ledger did not mint.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct SourceRef {
    url: String,
    fetched_at: NaiveDate,
    body_sha256: String,
}

impl SourceRef {
    #[must_use]
    pub fn url(&self) -> &str {
        &self.url
    }
    #[must_use]
    pub fn fetched_at(&self) -> NaiveDate {
        self.fetched_at
    }
    #[must_use]
    pub fn body_sha256(&self) -> &str {
        &self.body_sha256
    }
    /// The file name the archived snapshot ships under, `sources/<sha>.html`.
    #[must_use]
    pub fn snapshot_name(&self) -> String {
        format!("sources/{}.html", self.body_sha256)
    }
}

/// Sealed. Exactly two arms. See the module docs.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "lowercase")]
pub enum Support {
    Cited { source: SourceRef },
    Unverifiable,
}

/// A unit a figure is measured in. Closed so a renderer cannot meet a unit it has no glyph for.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Unit {
    GbpPerMonth,
    Gbp,
    Percent,
    Count,
    Hours,
    Days,
}

impl Unit {
    #[must_use]
    pub fn label(self) -> &'static str {
        match self {
            Self::GbpPerMonth => "£/month",
            Self::Gbp => "£",
            Self::Percent => "%",
            Self::Count => "",
            Self::Hours => "h",
            Self::Days => "days",
        }
    }
}

/// A number a buyer can check. `Decimal`, never a float, and never without a source.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Figure {
    pub label: String,
    pub value: Decimal,
    pub unit: Unit,
    pub as_of: NaiveDate,
    pub source: SourceRef,
}

impl Figure {
    /// The only constructor, and it takes the source.
    #[must_use]
    pub fn new(label: impl Into<String>, value: Decimal, unit: Unit, as_of: NaiveDate, source: SourceRef) -> Self {
        Self { label: label.into(), value, unit, as_of, source }
    }
    /// The exact text every view must carry, so the gate can look for one string.
    #[must_use]
    pub fn display(&self) -> String {
        match self.unit {
            Unit::GbpPerMonth | Unit::Gbp => format!("£{}{}", self.value, if self.unit == Unit::GbpPerMonth { "/month" } else { "" }),
            Unit::Percent => format!("{}%", self.value),
            Unit::Count => self.value.to_string(),
            Unit::Hours => format!("{} h", self.value),
            Unit::Days => format!("{} days", self.value),
        }
    }
}

/// One statement the pack makes, with what it rests on.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Claim {
    pub id: String,
    pub text: String,
    pub support: Support,
}

/// What a section is made of. Closed: a renderer matches exhaustively.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Block {
    Heading { text: String },
    Paragraph { text: String },
    Bullets { items: Vec<String> },
    Claim(Claim),
    Figures { rows: Vec<Figure> },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Section {
    pub title: String,
    pub blocks: Vec<Block>,
}

/// Cover fields. Everything but `title` is optional and an absent stat is not printed.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Meta {
    pub pack_id: String,
    pub title: String,
    #[serde(default)]
    pub one_liner: String,
    pub verified_at: NaiveDate,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Pack {
    pub meta: Meta,
    pub sections: Vec<Section>,
}

impl Pack {
    /// Parse and admit a pack. Every `SourceRef` must be in `ledger` or the pack does not exist.
    pub fn load(json: &[u8], ledger: &FetchLedger) -> Result<Self, crate::Error> {
        let pack: Self = serde_json::from_slice(json)?;
        for s in pack.sources() {
            if !ledger.holds(s) {
                return Err(crate::Error::UnmintedSource { url: s.url.clone(), sha256: s.body_sha256.clone() });
            }
        }
        Ok(pack)
    }

    pub fn claims(&self) -> impl Iterator<Item = &Claim> {
        self.sections.iter().flat_map(|s| s.blocks.iter()).filter_map(|b| match b {
            Block::Claim(c) => Some(c),
            _ => None,
        })
    }

    pub fn figures(&self) -> impl Iterator<Item = &Figure> {
        self.sections.iter().flat_map(|s| s.blocks.iter()).filter_map(|b| match b {
            Block::Figures { rows } => Some(rows.iter()),
            _ => None,
        }).flatten()
    }

    /// Every distinct source the pack cites, in a fixed order.
    #[must_use]
    pub fn sources(&self) -> Vec<&SourceRef> {
        let mut v: Vec<&SourceRef> = self
            .claims()
            .filter_map(|c| match &c.support {
                Support::Cited { source } => Some(source),
                Support::Unverifiable => None,
            })
            .chain(self.figures().map(|f| &f.source))
            .collect();
        v.sort_by(|a, b| (a.url(), a.body_sha256()).cmp(&(b.url(), b.body_sha256())));
        v.dedup();
        v
    }

    #[must_use]
    pub fn cited_claim_count(&self) -> usize {
        self.claims().filter(|c| matches!(c.support, Support::Cited { .. })).count()
    }
}
