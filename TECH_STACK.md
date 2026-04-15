# cuSplunk — Tech Stack (Locked)

All version choices are intentional. Do not upgrade without an ADR.

---

## Languages

| Service | Language | Version | Why |
|---|---|---|---|
| `services/ingest` | Go | 1.22+ | 10K concurrent TCP connections, fast binary protocol parsing, tiny Docker image |
| `services/store` | Rust | 1.80+ | Zero GC pauses on write path, memory safety for the component that holds customer data |
| `services/query` | Python | 3.11+ | cuDF/RAPIDS native Python API, fastest path to GPU analytics |
| `services/detect` | Python | 3.11+ | NVIDIA Morpheus is Python-native, Triton client is Python |
| `services/bridge` | Go | 1.22+ | Same as ingest — async HTTP client + gRPC, concurrency for fan-out |
| `services/api` | Go | 1.22+ | REST + gRPC gateway, same runtime as ingest/bridge |
| `libs/spl-parser` | Python + ANTLR4 | ANTLR4 4.13 | Grammar tooling, visitor pattern for AST, Python runtime for query service |
| `libs/gpu-kernels` | CUDA C++ | CUDA 12.4+ | Custom kernels: time-window join, HybridSA regex, bloom filter ops |
| `ui` | TypeScript | 5.4+ | Type safety for complex SPL autocomplete + dashboard state |

---

## GPU / CUDA Stack

| Component | Version | Purpose |
|---|---|---|
| CUDA Toolkit | 12.4+ | Base GPU runtime |
| NVIDIA RAPIDS cuDF | 24.10+ | GPU DataFrame operations (filter, groupby, join, string ops) |
| NVIDIA RAPIDS cuStreamz | 24.10+ | GPU streaming DataFrames for detection pipeline |
| NVIDIA RAPIDS cuVS | 24.10+ | GPU vector search (semantic log search, E5+) |
| NVIDIA Morpheus | PB 25h1 (May 2025) | GPU AI pipeline framework for detection service |
| NVIDIA Triton Inference Server | 25.01 | ML model serving (DGA, phishing, UEBA, cyBERT) |
| RAPIDS Memory Manager (RMM) | 24.10+ | GPU memory pool allocator — eliminates alloc latency in hot path |
| nvCOMP | 4.0+ | GPU-native compression (LZ4, Zstd, Snappy) for `_raw` column |
| cuFile (GPUDirect Storage) | 1.9+ | NVMe → GPU direct path, bypasses CPU for warm tier reads |
| NVIDIA DOCA RegEx | 1.5+ | Optional: hardware regex on BlueField DPU (future) |

**Minimum GPU:** NVIDIA A10G (24 GB VRAM), CUDA Compute Capability 8.0+  
**Recommended:** A100 80GB or H100  
**Dev fallback:** NVIDIA T4 16GB (most tests pass, some benchmarks differ)

---

## Frameworks + Libraries

### Go services (ingest, bridge, api)

| Library | Version | Purpose |
|---|---|---|
| `google.golang.org/grpc` | 1.64+ | Internal service communication |
| `google.golang.org/protobuf` | 1.34+ | Protobuf serialization |
| `github.com/gin-gonic/gin` | 1.10+ | REST API (api service) |
| `github.com/prometheus/client_golang` | 1.19+ | Metrics exposition |
| `github.com/confluentinc/confluent-kafka-go` | 2.4+ | Kafka consumer (ingest) |
| `github.com/stretchr/testify` | 1.9+ | Test assertions |
| `go.uber.org/zap` | 1.27+ | Structured logging |
| `github.com/spf13/viper` | 1.19+ | Config management |
| `golang.org/x/crypto` | latest | TLS, bcrypt for auth |

### Rust (store)

| Crate | Version | Purpose |
|---|---|---|
| `tokio` | 1.38+ | Async runtime |
| `tonic` | 0.12+ | gRPC server |
| `arrow-rs` | 52+ | Apache Arrow columnar format |
| `parquet` | 52+ | Cold tier Parquet files |
| `object_store` | 0.10+ | S3/GCS/Blob unified API |
| `openraft` | 0.9+ | Raft consensus for replication |
| `xxhash-rust` | 0.8+ | Bloom filter hashing |
| `serde` + `serde_json` | 1.0+ | Bucket metadata serialization |
| `tracing` | 0.1+ | Structured logging + spans |
| `criterion` | 0.5+ | Benchmarks |

### Python services (query, detect)

| Package | Version | Purpose |
|---|---|---|
| `cudf-cu12` | 24.10+ | GPU DataFrames |
| `cuml-cu12` | 24.10+ | GPU ML (clustering, anomaly) |
| `rapids-morpheus` | PB 25h1 | GPU detection pipeline |
| `tritonclient[grpc]` | 2.45+ | Triton Inference Server client |
| `antlr4-python3-runtime` | 4.13+ | SPL parser runtime |
| `grpcio` | 1.64+ | gRPC client to store service |
| `redis` | 5.0+ | Query cache client |
| `pyyaml` | 6.0+ | Sigma rule parsing |
| `stix2` | 3.0+ | Threat intel STIX feeds |
| `fastapi` | 0.111+ | Internal HTTP endpoints |
| `pytest` | 8.2+ | Test runner |
| `hypothesis` | 6.100+ | Property-based testing |

### UI (React / Next.js)

| Package | Version | Purpose |
|---|---|---|
| `next` | 14.2+ | React framework, App Router |
| `react` | 18.3+ | UI framework |
| `typescript` | 5.4+ | Type safety |
| `@monaco-editor/react` | 4.6+ | SPL code editor with syntax highlighting |
| `echarts-for-react` | 3.0+ | Charts (timechart, bar, pie, heatmap) |
| `tailwindcss` | 3.4+ | Styling |
| `swr` | 2.2+ | Data fetching + cache invalidation |
| `zustand` | 4.5+ | Client state management |
| `@tanstack/react-table` | 8.17+ | Virtual-scroll results table (10K rows) |
| `vitest` | 1.6+ | Unit test runner |
| `@testing-library/react` | 16+ | Component testing |
| `playwright` | 1.44+ | E2E browser tests |

---

## Infrastructure

| Component | Technology | Version | Purpose |
|---|---|---|---|
| Container runtime | Docker | 26+ | Dev + CI |
| Orchestration | Kubernetes | 1.30+ | Production cluster |
| Package manager | Helm | 3.15+ | K8s deployments |
| Operator framework | controller-runtime | 0.18+ | cuSplunk K8s Operator |
| Metrics | Prometheus | 2.52+ | All services expose `:9090/metrics` |
| Dashboards | Grafana | 10.4+ | Ops dashboards |
| Tracing | OpenTelemetry | 1.3+ | Distributed traces across services |
| Log aggregation | (cuSplunk itself) | — | We eat our own dogfood |
| CI/CD | GitHub Actions | — | Build, test, benchmark, publish |
| Secret management | HashiCorp Vault | 1.17+ | API tokens, TLS certs, S3 credentials |

---

## Data Storage (non-GPU)

| Component | Technology | Version | Purpose |
|---|---|---|---|
| Metadata DB | PostgreSQL | 16+ | Users, roles, saved searches, alerts, cases, audit log |
| Cache | Redis | 7.2+ | Query result cache, query plan cache, session store |
| Internal messaging | gRPC streams | — | Service-to-service (no Kafka internally) |
| External ingest | Kafka | 3.7+ | Customer log pipelines (optional) |
| Object storage | S3/GCS/Blob | — | Cold tier, backup |

---

## API Protocols

| Protocol | Used by | Standard |
|---|---|---|
| S2S (Splunk-to-Splunk) | Universal Forwarder → ingest | Splunk proprietary (reverse-engineered) |
| HEC (HTTP Event Collector) | Any HEC client → ingest | Splunk de-facto standard |
| Syslog | Network devices → ingest | RFC 3164 + RFC 5424 |
| gRPC | All internal services | Protobuf 3 |
| REST/JSON | External API, UI | OpenAPI 3.0 |
| Prometheus scrape | Grafana → all services | Prometheus exposition format |
| OTLP | Traces → collector | OpenTelemetry |
| STIX/TAXII | Threat intel feeds → detect | STIX 2.1 / TAXII 2.1 |

---

## GPU Driver Requirements

```
NVIDIA driver: 535.104+ (required for CUDA 12.4)
nvidia-container-toolkit: 1.14+ (for Docker GPU passthrough)
GPUDirect Storage driver: 2.7+ (for NVMe direct path)
```

Verify with: `nvidia-smi`, `nvidia-ctk --version`
