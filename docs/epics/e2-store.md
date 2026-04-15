# E2 — STORE: GPU-Native Columnar Storage Engine

**Owner:** P2  
**Service:** `services/store/` (Rust + CUDA)  
**Milestone:** M1  
**Status:** R1 ✅ (bucket/bloom/gRPC skeleton) — R2 tiers on disk, uncommitted — R3 not started

## Goal

Store logs faster and smaller than Splunk. Enable GPU-direct reads that eliminate the CPU decompression bottleneck. Target: **read 1 TB of warm data in <30s.**

## Stories

### S2.1 — Columnar Bucket Format ✅ (R1)
Design and implement the on-disk bucket format.
- Each bucket = 1-hour time window per index
- Columns: `_time` (int64 nanosec), `_raw` (binary), `host`, `source`, `sourcetype` (dict-encoded)
- Apache Arrow IPC format for GPU compatibility
- Bucket naming: `bucket_<index>_<start>_<end>_<uuid>/`
- Acceptance criteria: cuDF can load a bucket in one `read_parquet()` call

### S2.2 — Hot Tier (GPU Memory) ✅ (R2)
- In-memory ring buffer (512 MB default, configurable), last 5 minutes
- Backed by Arrow RecordBatches; GPU memory pool wired in R3 when cuDF FFI lands
- Sub-millisecond query latency for live data
- LRU eviction: oldest batch evicted when capacity exceeded; `evict_older_than()` for age-based expiry
- Column projection support; fill ratio metric for backpressure

### S2.3 — Warm Tier (NVMe + GPUDirect Storage) ✅ (R2)
- NVMe-backed bucket store using R1 columnar format
- Write path: events sorted → BucketWriter → disk → catalog entry
- Read path: catalog range query → BucketReader per bucket → column projection → Arrow IPC stream
- GDS flag in config (wired in R3 when cuFile available); fallback to standard read(2)
- Dict-encoded columns decoded to plain Utf8 for clean IPC streaming

### S2.4 — Cold Tier (Object Storage) — API stub ✅ (R2), implementation R3
- `ColdTierConfig` (provider/bucket/prefix/region) in config
- `ColdTier::scan()` and `tier_bucket()` return `Unimplemented` until R3
- S3/GCS/Azure Blob via `object_store` crate (dep declared, feature-gated)

### S2.5 — Bloom Filter Index ✅ (R1 — basic; R3 integrates with scan)
- Per-bucket bloom filter over all token hashes
- Enables fast skip: "does this bucket contain this value?"
- False positive rate target: <1%
- Stored in `bloom.bin` alongside bucket data

### S2.6 — Retention Engine ✅ (R2)
- Configurable retention per index (default: 90 days); per-index override map
- Phase 1: tombstone (`tombstone.json`) written when bucket exceeds retention window
- Phase 2: hard delete after 24 h grace period
- Background tokio task; runs every `check_interval_hours`
- `RetentionStats` (tombstoned / hard_deleted / events_deleted) logged each sweep
- Retention policy API (`PUT /api/v1/indexes/{name}/retention`) — R4

### S2.7 — Replication
- Async replication factor=2 across store nodes
- Raft-based leader election (openraft crate)
- Replication lag metric: `cusplunk_store_replication_lag_ms`
- Read from replica on leader unavailability

### S2.8 — Store gRPC API ✅ (R2 — all four RPCs functional)
Internal API consumed by query and ingest services.
```protobuf
service Store {
  rpc Write(WriteRequest) returns (WriteResponse);
  rpc Scan(ScanRequest) returns (stream ScanResponse);
  rpc Delete(DeleteRequest) returns (DeleteResponse);
  rpc BucketList(BucketListRequest) returns (BucketListResponse);
}
```

## Bucket Format Detail

```
bucket_<index>_<start_epoch>_<end_epoch>_<uuid>/
├── meta.json       # event_count, size_bytes, time_range, schema_version
├── _time.col       # int64[] sorted ascending, Arrow format
├── _raw.col        # binary[] nvCOMP-compressed
├── host.col        # dict32 encoded
├── source.col      # dict32 encoded
├── sourcetype.col  # dict32 encoded
├── extracted/      # populated lazily on first query
│   └── *.col
└── bloom.bin       # xxhash-based bloom filter
```

## Benchmark Target

| Metric | Target |
|---|---|
| Write throughput | 5 GB/sec to NVMe |
| Warm scan (1 TB) | <30s on A10G |
| Compression ratio | 8× on typical logs |
| Bloom filter skip rate | >90% for sparse queries |
| Retention accuracy | ±1 hour of configured TTL |

## Dependencies

- Rust (tokio async runtime)
- CUDA / cuFile (GPUDirect Storage)
- Apache Arrow (arrow-rs crate)
- openraft (Raft consensus)
- object-store crate (S3/GCS/Blob)
- xxhash (bloom filter)
