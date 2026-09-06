//! Each view is a pure function `&Pack -> bytes`. No view reads another view.
pub mod csv;
pub mod html;
pub mod json;
pub mod typst;
