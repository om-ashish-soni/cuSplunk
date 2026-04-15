# E2 — STORE: GPU-Native Columnar Storage Engine

**Owner:** P2  
**Service:** `services/store/` (Rust + CUDA)  
**Milestone:** M1  
**Status:** Planning

## Goal

Store logs faster and smaller than Splunk. Enable GPU-direct reads that eliminate the CPU decompression bottleneck. Target: **read 1 TB of warm data in <30s.**

## Stories

### S2.1 — Columnar Bucket Format
Design and implement the on-disk bucket format.
- Each bucket = 1-hour time window per index
- Columns: `_time` (int64 nanosec), `_raw` (binary), `host`, `source`, `sourcetype` (dict-encoded)
- Apache Arrow IPC format for GPU compatibility
- Bucket naming: `bucket_<index>_<start>_<end>_<uuid>/`
- Acceptance criteria: cuDF can load a bucket in one `read_parquet()` call

### S2.2 — Hot Tier (GPU Memory)
- In-GPU-memory ring buffer, last 5 minutes
- Implemented as cuDF DataFrame pool
- Sub-millisecond query latency for live data
- Eviction policy: oldest bucket moves to warm tier on overflow

### S2.3 — Warm Tier (NVMe + GPUDirect Storage)
- NVMe-Direct reads via cuFile (GPUDirect Storage)
- Data goes NVMe → GPU without CPU copy
- Covers last 30 days
- Async write-behind from hot tier

### S2.4 — Cold Tier (Object Storage)
- Automatic tiering at 30 days
- S3, GCS, Azure Blob support (object-store Rust crate)
- Parquet format for cold data (Zstd compression)
- Transparent to query layer — scan API abstracts tier

### S2.5 — Bloom Filter Index
- Per-bucket bloom filter over all token hashes
- Enables fast skip: "does this bucket contain this value?"
- False positive rate target: <1%
- Stored in `bloom.bin` alongside bucket data

### S2.6 — Retention Engine
- Configurable retention per index (default: 90 days)
- Tombstone files for async deletion
- Background cleanup worker
- Retention policy API (`PUT /api/v1/indexes/{name}/retention`)

### S2.7 — Replication
- Async replication factor=2 across store nodes
- Raft-based leader election (openraft crate)
- Replication lag metric: `cusplunk_store_replication_lag_ms`
- Read from replica on leader unavailability

### S2.8 — Store gRPC API
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
