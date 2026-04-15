# cuSplunk Store — C2 Checkpoint

**Last updated:** 2026-04-15  
**Engineer:** C2  
**Test status:** `cargo test` — 46 passed, 0 failed

---

## Completed

### R1 — Foundation
| Deliverable | File(s) | Notes |
|---|---|---|
| Columnar bucket format | `src/bucket/` | Arrow IPC per column, dict-encoded strings |
| BucketWriter | `src/bucket/writer.rs` | Writes _time, _raw, host, source, sourcetype + bloom.bin + meta.json |
| BucketReader | `src/bucket/reader.rs` | Single column or projected multi-column read |
| BucketMeta serde | `src/bucket/meta.rs` | UUID, dir_name(), JSON roundtrip |
| Bloom filter | `src/bloom/mod.rs` | xxh3 k-hash, configurable FPR, serialize/deserialize |
| Store gRPC proto | `libs/proto/store.proto` | Write, Scan (stream), Delete, BucketList |
| tonic server skeleton | `src/server/mod.rs` | Write functional; Scan Unimplemented |
| Config | `src/config.rs` | YAML, defaults |
| Error types | `src/error.rs` | StoreError → tonic::Status |
| Vendored protoc | `build.rs` | No system protoc required |

### R2 — Core Engine
| Deliverable | File(s) | Notes |
|---|---|---|
| Hot tier | `src/hot/mod.rs` | In-memory ring buffer, LRU eviction, column projection |
| events_to_record_batch | `src/hot/mod.rs` | Converts ingest events to Arrow RecordBatch |
| Warm tier | `src/warm/mod.rs` | Disk scan, column projection, tombstone/hard-delete |
| decode_dict_columns | `src/warm/mod.rs` | Casts dict arrays to Utf8 for clean IPC streaming |
| IPC helpers | `src/warm/mod.rs` | batch_to_ipc_bytes / ipc_bytes_to_batch |
| Cold tier stub | `src/cold/mod.rs` | API defined, returns Unimplemented |
| Bucket catalog | `src/catalog/mod.rs` | In-memory, rebuilt from disk on startup, tombstone tracking |
| Retention engine | `src/retention/mod.rs` | Background task, 24 h grace period, per-index override |
| Tier-aware server | `src/server/mod.rs` | Write → hot+warm; Scan → hot then warm stream; Delete; BucketList |
| Catalog persistence | `src/server/mod.rs` | Rebuilt from warm dir on every startup |
| main.rs | `src/main.rs` | Spawns retention engine background task |

---

## R3-C2 — What's next

| Story | Work |
|---|---|
| S2.5 — Bloom scan integration | Wire `BucketReader::bloom_contains()` into warm scan path to skip non-matching buckets |
| S2.7 — Replication | openraft integration: leader election, log replication, replica reads |
| Integration test | `TestReplication_LeaderFailover` |
| Benchmark | Replication lag < 500ms at 1M events/sec |

**Already ready for R3:**
- `openraft` dep in `Cargo.toml` behind `replication` feature flag
- `BloomFilter::from_bytes()` + `BucketReader::bloom_contains()` — just needs wiring into scan loop
- Catalog supports multi-node extension

---

## Known deferred items

| Item | Deferred to |
|---|---|
| nvCOMP compression on `_raw` column | R2-C1 (GPU ingest pipeline) |
| cuFile / GPUDirect Storage reads | R3 (when CUDA env available) |
| Cold tier S3/GCS upload + fetch | R3 |
| Retention API endpoint | R4 (API service) |
| Prometheus metrics | R4 (platform layer) |
