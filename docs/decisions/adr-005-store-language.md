# ADR-005: Rust for Storage Engine

**Status:** Accepted  
**Date:** 2026-04-15

## Context

The storage engine is the most critical component: correctness and performance are non-negotiable. It handles:
- Writing columnar buckets to NVMe (GPUDirect Storage)
- Raft-based replication
- Retention policy enforcement
- Bloom filter index management

Requirements: memory safety (no data corruption), predictable latency, zero GC pauses.

## Decision

Use **Rust** for `services/store/`.

CUDA bindings via `cudarc` crate or direct `unsafe` FFI for GDS (cuFile) operations.

## Consequences

**Good:**
- Memory safety: no buffer overflows, no use-after-free in the component that holds customer data
- Zero GC pauses: predictable write latency (critical for ingest SLA)
- `tokio` async runtime: async I/O without threads-per-connection overhead
- `openraft` crate: production-quality Raft implementation
- `arrow-rs` crate: Apache Arrow in Rust, zero-copy from storage to cuDF
- `object-store` crate: S3/GCS/Blob with unified API

**Bad:**
- Steeper learning curve for team members new to Rust
- CUDA FFI in Rust is `unsafe` — requires careful review
- Longer compile times

## Alternatives Considered

| Language | Rejected reason |
|---|---|
| C++ | Memory safety issues at storage layer are catastrophic; Rust gives the same performance with safety |
| Go | GC pauses unacceptable for storage layer write path latency |
| Python | Not suitable for systems-level storage engine |
