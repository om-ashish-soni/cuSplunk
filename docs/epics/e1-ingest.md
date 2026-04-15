# E1 — INGEST: GPU-Native Log Ingestion Engine

**Owner:** P1  
**Service:** `services/ingest/` (Go)  
**Milestone:** M1  
**Status:** Planning

## Goal

Be a drop-in replacement for every Splunk indexer. Enterprise redirects Universal Forwarders to cuSplunk IP — nothing else changes. Ingest target: **1M events/sec sustained on single A10G.**

## Stories

### S1.1 — S2S Protocol Server
Implement Splunk-to-Splunk (S2S) wire protocol. Universal Forwarders use this on port 9997.
- Parse S2S framing, handshake, ack protocol
- Support compressed and uncompressed streams
- Connection pooling for multiple forwarders
- Acceptance criteria: `outputs.conf` pointing at cuSplunk works without error

### S1.2 — HEC Server (HTTP Event Collector)
Splunk-compatible HEC endpoint at port 8088.
- `POST /services/collector/event` — single event
- `POST /services/collector/raw` — raw text
- Token-based auth (same format as Splunk)
- Batch acknowledgement (`/services/collector/ack`)
- Acceptance criteria: Splunk HEC SDK clients work unchanged

### S1.3 — Syslog Receiver
- UDP syslog (RFC 3164) on port 514
- TCP syslog (RFC 5424) on port 514
- TLS syslog on port 6514
- Structured data parsing (SD-ID extraction)

### S1.4 — Kafka Consumer
- Native Kafka consumer (confluent-kafka-go)
- Configurable topic-to-index mapping
- Consumer group support
- At-least-once delivery guarantee

### S1.5 — GPU Parse Queue
- CUDA pinned memory ring buffer
- Batch accumulator: flush at 10,000 events OR 100ms timeout (whichever first)
- Backpressure: slow ingest path if GPU queue full
- GPU utilization target: >80% during sustained ingest

### S1.6 — GPU Log Parser (cuDF)
- Timestamp extraction: `strptime` on GPU for common formats (ISO8601, epoch, syslog)
- Field extraction: `host`, `source`, `sourcetype`, `index` from S2S metadata
- cyBERT integration for unstructured log normalization
- Windows Event Log field extraction (EventCode, SubjectUserName, etc.)

### S1.7 — nvCOMP Compression
- LZ4 compression on `_raw` column via nvCOMP
- Compression happens on GPU, no CPU involvement
- Target: 5–8× compression ratio on typical log data
- Decompression on query also on GPU

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
