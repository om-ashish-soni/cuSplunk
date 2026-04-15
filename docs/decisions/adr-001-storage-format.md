# ADR-001: Columnar Apache Arrow Format for Bucket Storage

**Status:** Accepted  
**Date:** 2026-04-15

## Context

We need a storage format for log buckets that:
1. Can be loaded directly into GPU memory (cuDF)
2. Is compact on disk
3. Supports partial column reads (skip `_raw` if only querying `src_ip`)
4. Works with GPUDirect Storage (NVMe → GPU without CPU copy)

## Decision

Use **Apache Arrow IPC format** (columnar) for bucket files.

- Each column stored as a separate `.col` file
- Dict-encoded for low-cardinality string columns (`host`, `sourcetype`)
- `_raw` column separately nvCOMP-compressed (LZ4)
- Arrow schema stored in `meta.json`

## Consequences

**Good:**
- `cudf.read_parquet()` / Arrow IPC loads directly to GPU in one call
- Column pruning: only load columns needed by query
- Dict encoding: 100:1 compression on `sourcetype`, enables GPU integer group-by
- GDS-compatible: Arrow file is a flat binary, readable with cuFile

**Bad:**
- Not a standard Parquet file (slightly more complex tooling)
- Schema evolution requires migration for old buckets (mitigated by schema_version in meta.json)

## Alternatives Considered

| Format | Rejected reason |
|---|---|
| Parquet | Row group overhead not ideal for GPU scan; less control over compression |
| Raw JSON | No columnar benefit; terrible GPU performance |
| Splunk .tsidx | Proprietary, can't read; not GPU-friendly |
| HDF5 | Complex, not GPU-native |
