//! The value itself, pretty-printed. The machine-readable edition of the pack.
use crate::ir::Pack;
use crate::Error;

pub fn render(p: &Pack) -> Result<Vec<u8>, Error> {
    Ok(serde_json::to_vec_pretty(p)?)
}
