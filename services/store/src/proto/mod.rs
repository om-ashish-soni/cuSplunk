//! Re-exports of prost/tonic generated types from `store.proto`.
//!
//! The generated file is emitted to `$OUT_DIR/store.rs` by `build.rs`.

// tonic-build / prost-build writes to OUT_DIR/store.rs.
// The `include!` macro splices it in at compile time.
tonic::include_proto!("store");
