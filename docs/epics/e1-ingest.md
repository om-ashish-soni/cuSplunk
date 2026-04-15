# E1 — INGEST: GPU-Native Log Ingestion Engine

**Owner:** P1  
**Service:** `services/ingest/` (Go)  
**Milestone:** M1  
**Status:** R2 Complete (S1.1–S1.3 R1 ✅, S1.5–S1.7 R2 ✅ — uncommitted to branch)

## Goal

Be a drop-in replacement for every Splunk indexer. Enterprise redirects Universal Forwarders to cuSplunk IP — nothing else changes. Ingest target: **1M events/sec sustained on single A10G.**

## Stories

### S1.1 — S2S Protocol Server ✅
Implement Splunk-to-Splunk (S2S) wire protocol. Universal Forwarders use this on port 9997.
- [x] Parse S2S framing, handshake, ack protocol
- [x] Support uncompressed streams (compressed R2)
- [x] Connection pooling for multiple forwarders (max_connections enforced)
- [x] Unit tests: frame parse, handshake, server, max-connections, parse error metrics
- `services/ingest/internal/s2s/`

### S1.2 — HEC Server (HTTP Event Collector) ✅
Splunk-compatible HEC endpoint at port 8088.
- [x] `POST /services/collector/event` — single + batched JSON events
- [x] `POST /services/collector/raw` — raw text
- [x] Token-based auth (Splunk + Bearer schemes)
- [x] Batch acknowledgement (`/services/collector/ack`)
- [x] `GET /services/collector/health`
- [x] Unit tests: auth, tokens, batch, defaults, health
- `services/ingest/internal/hec/`

### S1.3 — Syslog Receiver ✅
- [x] UDP syslog (RFC 3164) on port 514
- [x] TCP syslog (RFC 5424) on port 514
- [x] TLS syslog on port 6514 (cert/key config)
- [x] Full RFC 3164 and RFC 5424 parsers
- [x] Structured data parsing (SD-ID extraction with escaped values)
- [x] Unit tests: 25 parser tests, 6 server integration tests
- `services/ingest/internal/syslog/`

### S1.4 — Kafka Consumer
- Native Kafka consumer (confluent-kafka-go)
- Configurable topic-to-index mapping
- Consumer group support
- At-least-once delivery guarantee

### S1.5 — GPU Parse Queue ✅
- Unix socket IPC ring buffer (Go→Python, length-prefixed JSON batches)
- Batch accumulator: flush at 10,000 events OR 100ms timeout (whichever first)
- Backpressure: semaphore (MaxInFlight=10) blocks Enqueue when GPU falls behind
- Wire format: `[4-byte length][JSON events array]` ↔ `[4-byte length][JSON ack]`
- `services/ingest/internal/gpuqueue/` — 8 tests passing
- `cmd/ingest/main.go` wires GPUQueue when `CUSPLUNK_GPU_QUEUE=1`

### S1.6 — GPU Log Parser (cuDF) ✅
- `services/query/cusplunk/ingest/processor.py` — Unix socket server
- `parse_batch(events)`: timestamp conversion, field extraction, LZ4 compress `_raw`
- cuDF GPU path: enabled when CUDF_PANDAS_FALLBACK_MODE ≠ 1
- CPU fallback: pandas (CUDF_PANDAS_FALLBACK_MODE=1 or CUSPLUNK_FORCE_CPU=1)
- `services/query/cusplunk/ingest/store_grpc.py` — gRPC Write to store service
- 18 Python tests passing (1 skipped: lz4 not installed in test env)

### S1.7 — nvCOMP Compression ✅ (partial)
- LZ4 compression in `compress_raw()` via `lz4.frame` Python package
- nvCOMP GPU path stubbed (TODO R3: device-to-device with store accepting nvCOMP)
- Falls back to `lz4.frame` on CPU or when nvCOMP unavailable
- Decompression by the store service (receives lz4-compressed bytes)

### S1.8 — Ingest Metrics
- Prometheus endpoint at `:9090/metrics`
- Metrics: `cusplunk_ingest_events_total`, `cusplunk_ingest_bytes_total`, `cusplunk_ingest_parse_errors_total`, `cusplunk_gpu_queue_depth`, `cusplunk_gpu_utilization_pct`

## Benchmark Target

| Metric | Target |
|---|---|
| Single A10G throughput | 1M events/sec |
| Parse latency (p99) | <50ms per batch |
| S2S protocol compatibility | 100% UF compat |
| Compression ratio | 5× minimum |

## Dependencies

- NVIDIA RAPIDS cuDF (Python)
- nvCOMP (CUDA)
- confluent-kafka-go
- ANTLR4 Go runtime (for syslog structured data)
