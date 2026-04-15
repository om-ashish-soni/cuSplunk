# cuSplunk — Architecture

## Design Principles

1. **GPU-first, CPU-fallback** — every hot-path operation targets GPU. CPU is only used for coordination and control plane.
2. **SPL compatibility is non-negotiable** — existing Splunk searches must work unchanged.
3. **Zero-migration deployment** — S2S/HEC protocol compatibility means no forwarder changes. 90-day auto-cutover means no manual data migration.
4. **Schema-on-read** — ingest raw, extract on query. GPUs make this viable at scale.
5. **Measure everything** — every layer exposes Prometheus metrics. Benchmarks are first-class citizens.

---

## System Diagram

```
┌───────────────────────────────────────────────────────────────────┐
│                         DATA SOURCES                               │
│  Universal Forwarder  │  HEC clients  │  Syslog  │  Kafka         │
└──────────┬────────────┴───────┬───────┴────┬─────┴────────────────┘
           │ S2S (port 9997)    │ HTTP 8088  │ Syslog 514/6514
           ▼                    ▼            ▼
┌───────────────────────────────────────────────────────────────────┐
│                    INGEST SERVICE  (Go)                            │
│  Protocol parsers → GPU parse queue → cuDF batch processor        │
│  nvCOMP compression → write to Store gRPC                         │
└───────────────────────────────┬───────────────────────────────────┘
                                │ gRPC WriteRequest
                                ▼
┌───────────────────────────────────────────────────────────────────┐
│                    STORE SERVICE  (Rust + CUDA)                    │
│  ┌──────────────┐  ┌─────────────────┐  ┌──────────────────────┐ │
│  │  HOT TIER    │  │   WARM TIER     │  │    COLD TIER         │ │
│  │  GPU memory  │  │  NVMe (GDS)     │  │    S3/GCS/Blob       │ │
│  │  last 5 min  │  │  last 30 days   │  │    30–90 days        │ │
│  └──────────────┘  └─────────────────┘  └──────────────────────┘ │
│  Columnar buckets · Bloom filters · Retention engine              │
└───────────────────────────────┬───────────────────────────────────┘
                                │ gRPC ScanRequest
                                ▼
┌───────────────────────────────────────────────────────────────────┐
│                    QUERY SERVICE  (Python + cuDF)                  │
│  SPL → ANTLR4 AST → Logical Plan → GPU Physical Plan             │
│  cuDF executor · Distributed fan-out · Query cache               │
│                         │                                         │
│                         │ time-range router                       │
│                         ▼                                         │
│              ┌──────────────────────┐                            │
│              │   BRIDGE SERVICE     │  (Go)                      │
│              │   Splunk REST client │                            │
│              │   Days 0–90 only     │                            │
│              └──────────────────────┘                            │
└───────────────────────────────┬───────────────────────────────────┘
                                │
           ┌────────────────────┼───────────────────┐
           ▼                    ▼                   ▼
┌─────────────────┐  ┌──────────────────┐  ┌────────────────────┐
│  DETECT SERVICE │  │   API SERVICE    │  │   UI  (React)      │
│  Python+Morpheus│  │   Go gRPC+REST   │  │   Next.js          │
│  Sigma/YARA/ML  │  │   Splunk API     │  │   SPL search bar   │
│  MITRE ATT&CK   │  │   compatible     │  │   Dashboards       │
└─────────────────┘  └──────────────────┘  └────────────────────┘
```

---

## Data Flow: Ingest Path

```
Universal Forwarder
       │
       │ TCP S2S (port 9997, Splunk wire protocol)
       ▼
  Ingest Service (Go)
       │
       │ decode S2S frames → raw event batches ([]byte)
       ▼
  GPU Parse Queue (CUDA pinned memory ring buffer)
       │
       │ batch size: 10,000 events or 100ms timeout
       ▼
  cuDF Batch Processor (Python)
       │ cuDF string ops:
       │   - extract _time (strptime on GPU)
       │   - extract host, source, sourcetype
       │   - cyBERT: unstructured → structured fields
       │   - nvCOMP: compress raw column
       ▼
  Store gRPC WriteRequest
       │
       │ columnar Arrow batch
       ▼
  Store Service (Rust)
       │ → hot tier (GPU memory)
       │ → warm tier (GDS NVMe write)
       │ → update bloom filter + bucket metadata
       ▼
  ACK to Ingest Service
       │
       ▼
  ACK to Universal Forwarder (S2S ack)
```

## Data Flow: Query Path

```
User: index=firewall | stats count by src_ip | sort -count | head 10

       │
       ▼
  API Service (Go)
       │ POST /services/search/jobs
       ▼
  Query Service (Python)
       │
       ├─ SPL Parser (ANTLR4)
       │    → AST: [Search(index=firewall), Stats(count, by=src_ip), Sort(-count), Head(10)]
       │
       ├─ Logical Plan optimizer
       │    → push index filter to scan, estimate cardinality
       │
       ├─ Time Range Router
       │    ├─ after cutover → GPU Store only
       │    ├─ before cutover → Bridge (Splunk REST)
       │    └─ spanning both → fan out, merge results
       │
       ├─ GPU Physical Executor (cuDF)
       │    → Store.Scan(index=firewall, timerange)  → cuDF DataFrame
       │    → df.groupby('src_ip').agg({'count': 'sum'})
       │    → df.sort_values('count', ascending=False)
       │    → df.head(10)
       │
       └─ Result serialization → JSON response
```

---

## Storage Format: Columnar Bucket

Each bucket covers a time range (e.g., 1 hour) and stores all events for one index.

```
bucket_<index>_<start_epoch>_<end_epoch>_<id>/
├── meta.json          # bucket metadata: time range, event count, size, bloom filter
├── _time.col          # int64[] — Unix nanoseconds, sorted ascending
├── _raw.col           # binary[] — nvCOMP-compressed raw event strings
├── host.col           # dict-encoded string column
├── source.col         # dict-encoded string column
├── sourcetype.col     # dict-encoded string column
├── extracted/         # lazily populated on first query
│   ├── src_ip.col
│   ├── dst_ip.col
│   └── ...
└── bloom.bin          # Bloom filter over all token hashes (fast skip)
```

**Why columnar:** GPU scans a single column contiguously — memory bandwidth is the bottleneck, not compute. Columnar layout maximizes effective bandwidth utilization.

**Why dict-encoded strings:** `host`, `sourcetype` have low cardinality. Dict encoding compresses 100:1 and enables GPU group-by as integer comparison.

---

## SPL Compatibility Strategy

Full SPL grammar implemented in ANTLR4. Each SPL command maps to a cuDF operation:

| SPL Command | cuDF Operation |
|---|---|
| `search field=value` | `df[df['field'] == value]` |
| `stats count by X` | `df.groupby('X').agg({'_count': 'count'})` |
| `eval new=expr` | `df['new'] = eval_expr(df)` |
| `rex field=X "(?P<name>pattern)"` | `df['name'] = df['X'].str.extract(pattern)` |
| `sort -field` | `df.sort_values('field', ascending=False)` |
| `join type=left X [...]` | `cudf.merge(df, subquery, on='X', how='left')` |
| `timechart span=1h count` | `df.groupby(time_bucket('_time', '1h')).count()` |
| `tstats count where index=X` | Direct columnar scan (no raw decompression) |
| `transaction maxspan=5m` | GPU time-window join (custom CUDA kernel) |

Commands not yet GPU-accelerated fall back to CPU pandas (transparent, logged).

---

## 90-Day Bridge: Splunk Federation

```
Query arrives with time range: [T-120d, now]
                │
                ▼
    split at cutover_date
         /            \
[T-120d, cutover]    [cutover, now]
        │                    │
        ▼                    ▼
  Splunk REST API       GPU Store
  /search/jobs          cuDF executor
        │                    │
        └──────┬─────────────┘
               ▼
          merge + sort by _time
               │
               ▼
          unified result
```

Bridge configuration (`bridge/config.yaml`):
```yaml
splunk:
  url: https://your-splunk:8089
  token: ${SPLUNK_TOKEN}
cutover_date: "2025-06-01T00:00:00Z"   # set at deployment
auto_sunset_days: 90                    # bridge disabled after this
```

---

## Detection Architecture

```
Live event stream (from ingest)
        │
        ▼
  Detection Service (Python + Morpheus)
        │
        ├─ Sigma rules → GPU regex pipeline
        │    HybridSA multi-pattern matching
        │    10,000 rules × 1M events/sec
        │
        ├─ YARA rules → GPU string matching
        │
        ├─ ML models (Triton Inference Server)
        │    ├─ DGA detection (DNS logs)
        │    ├─ Phishing detection (email logs)
        │    ├─ UEBA (user behavior anomaly)
        │    └─ cyBERT (log normalization)
        │
        └─ Alert output
             ├─ MITRE ATT&CK enrichment
             ├─ Threat intel join (cuDF left join on IP/domain)
             └─ Alert API → PagerDuty / Slack / JIRA
```

---

## Network Ports

| Port | Protocol | Service | Compatible with |
|---|---|---|---|
| 9997 | TCP | S2S (forwarder input) | Splunk Universal Forwarder |
| 8088 | HTTPS | HEC (HTTP Event Collector) | Splunk HEC clients |
| 514 | UDP/TCP | Syslog | All syslog senders |
| 6514 | TLS | Syslog TLS | Secure syslog |
| 8089 | HTTPS | REST API / Search API | Splunk SDK, curl |
| 9090 | HTTP | Prometheus metrics | Grafana, Prometheus |
| 50051 | gRPC | Internal service mesh | Internal only |

---

## Hardware Requirements

### Minimum (dev / small deployment)
- 1× NVIDIA A10G (24 GB VRAM)
- 32 GB RAM
- 2 TB NVMe SSD
- 10 Gbps NIC

### Recommended (100 GB/day production)
- 2× NVIDIA A100 (80 GB VRAM each)
- 256 GB RAM
- 10 TB NVMe (GPUDirect Storage capable)
- 25 Gbps NIC

### Enterprise (500 GB/day+)
- 4-node cluster, 2× H100 per node
- NVMe-oF fabric for shared storage
- 100 Gbps RDMA NIC

---

## ADRs

| # | Decision | Status |
|---|---|---|
| [ADR-001](docs/decisions/adr-001-storage-format.md) | Columnar Arrow format for bucket storage | Accepted |
| [ADR-002](docs/decisions/adr-002-spl-parser.md) | ANTLR4 for SPL grammar | Accepted |
| [ADR-003](docs/decisions/adr-003-gpu-executor.md) | cuDF as primary GPU executor | Accepted |
| [ADR-004](docs/decisions/adr-004-ingest-language.md) | Go for ingest/API services | Accepted |
| [ADR-005](docs/decisions/adr-005-store-language.md) | Rust for storage engine | Accepted |
