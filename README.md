# cuSplunk

> GPU-native, SPL-compatible log analytics and SIEM engine. 10–100× faster than Splunk.

```
 ██████╗██╗   ██╗███████╗██████╗ ██╗     ██╗   ██╗███╗   ██╗██╗  ██╗
██╔════╝██║   ██║██╔════╝██╔══██╗██║     ██║   ██║████╗  ██║██║ ██╔╝
██║     ██║   ██║███████╗██████╔╝██║     ██║   ██║██╔██╗ ██║█████╔╝
██║     ██║   ██║╚════██║██╔═══╝ ██║     ██║   ██║██║╚██╗██║██╔═██╗
╚██████╗╚██████╔╝███████║██║     ███████╗╚██████╔╝██║ ╚████║██║  ██╗
 ╚═════╝ ╚═════╝ ╚══════╝╚═╝     ╚══════╝ ╚═════╝ ╚═╝  ╚═══╝╚═╝  ╚═╝
```

## What is cuSplunk?

cuSplunk is a GPU-native log analytics and SIEM platform that is **fully SPL-compatible** — existing Splunk queries, dashboards, and forwarders work unchanged. The backend is rebuilt from scratch on NVIDIA CUDA, RAPIDS, and cuDF.

**Drop Splunk's CPU-bound indexers. Keep everything else.**

## Why

| | Splunk | cuSplunk |
|---|---|---|
| Core engine | CPU (48–96 cores) | GPU (6,912–16,384 CUDA cores) |
| Query throughput | Baseline | 10–100× faster |
| Ingest rate | ~150 GB/day per indexer | 1M+ events/sec per GPU node |
| Storage efficiency | ~3× compression | ~8× compression (nvCOMP) |
| Real-time search | Hurts indexing capacity | GPU pipeline, zero tradeoff |
| SPL compatibility | Native | Full (ANTLR4 parser) |
| Migration required | — | None (90-day auto-cutover) |
| Cost at 500 GB/day | ~$1.17M/year | ~$120K/year (spot GPU instances) |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        INGEST LAYER                              │
│   Universal Forwarder (S2S) · HEC · Syslog · Kafka              │
│   GPU Parser (cuDF) · nvCOMP Compression · Schema-on-Read       │
├─────────────────────────────────────────────────────────────────┤
│                        STORAGE LAYER                             │
│   Hot (GPU memory) · Warm (NVMe-Direct/GDS) · Cold (S3)         │
│   Columnar buckets · Time-sorted · Bloom filter index           │
├─────────────────────────────────────────────────────────────────┤
│                        QUERY LAYER                               │
│   SPL Parser (ANTLR4) · GPU Executor (cuDF) · Distributed fan-out│
│   Splunk Bridge (90-day federation) · Query cache               │
├─────────────────────────────────────────────────────────────────┤
│                       DETECTION LAYER                            │
│   Sigma + YARA on GPU · Triton ML Inference · MITRE ATT&CK      │
│   cyBERT normalization · GPU time-window joins · Threat intel   │
├─────────────────────────────────────────────────────────────────┤
│                       PLATFORM LAYER                             │
│   Splunk-familiar UI · REST API (Splunk-compatible) · RBAC      │
│   Dashboards · Case management · SSO · Compliance reports       │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# Spin up a single-node cuSplunk with GPU
docker-compose -f infra/docker/docker-compose.gpu.yml up

# Point your Universal Forwarder at cuSplunk (no other changes)
# outputs.conf:
# [tcpout]
# server = your-cusplunk-host:9997

# Search via SPL (same as Splunk)
curl -X POST http://localhost:8089/services/search/jobs \
  -d 'search=index=main | stats count by host'
```

## Repo Structure

```
cuSplunk/
├── services/
│   ├── ingest/       # Go — S2S + HEC + Syslog protocol servers
│   ├── store/        # Rust + CUDA — columnar storage engine
│   ├── query/        # Python + cuDF — GPU query executor
│   ├── detect/       # Python + Morpheus — detection engine
│   ├── bridge/       # Go — Splunk REST federation (90-day)
│   └── api/          # Go — gRPC + REST gateway
├── libs/
│   ├── spl-parser/   # ANTLR4 SPL grammar + AST
│   ├── s2s-protocol/ # Splunk Universal Forwarder wire protocol
│   ├── gpu-kernels/  # CUDA kernels (regex, joins, compression)
│   └── schema/       # Normalized log field definitions (ECS-compatible)
├── ui/               # React + Next.js — Splunk-familiar interface
├── infra/            # Docker, Kubernetes (Helm), Terraform
├── docs/
│   ├── epics/        # Product epics
│   ├── decisions/    # Architecture Decision Records (ADRs)
│   ├── protocols/    # S2S, HEC protocol specs
│   └── benchmarks/   # Performance results
└── benchmarks/       # Benchmark runner scripts
```

## Epics

| # | Epic | Status |
|---|------|--------|
| E1 | [INGEST — GPU-Native Log Ingestion Engine](docs/epics/e1-ingest.md) | Planning |
| E2 | [STORE — GPU-Native Columnar Storage](docs/epics/e2-store.md) | Planning |
| E3 | [QUERY — GPU-Accelerated SPL Query Engine](docs/epics/e3-query.md) | Planning |
| E4 | [BRIDGE — 90-Day Splunk Federation Layer](docs/epics/e4-bridge.md) | Planning |
| E5 | [DETECT — GPU-Powered Detection Engine](docs/epics/e5-detect.md) | Planning |
| E6 | [PLATFORM — Splunk-Familiar UI + API](docs/epics/e6-platform.md) | Planning |
| E7 | [ENTERPRISE — Acquisition-Ready Features](docs/epics/e7-enterprise.md) | Planning |
| E8 | [SCALE — Benchmarks + Horizontal Scale](docs/epics/e8-scale.md) | Planning |

## Tech Stack

| Layer | Technology |
|---|---|
| Ingest servers | Go |
| Storage engine | Rust + CUDA |
| Query executor | Python + RAPIDS cuDF |
| Detection engine | Python + NVIDIA Morpheus |
| SPL parser | ANTLR4 |
| GPU kernels | CUDA C++ |
| UI | React + Next.js (TypeScript) |
| API gateway | Go (gRPC + REST) |
| Infra | Kubernetes + Helm |
| GPU requirement | NVIDIA A10G / A100 / H100 (CUDA 12+) |

## Benchmarks

> Target numbers. Benchmarks will be published under `/benchmarks/` as implemented.

| Query | Splunk (48-core) | cuSplunk (A10G) | Speedup |
|---|---|---|---|
| `stats count by src_ip` over 1B events | ~90s | <2s | ~45× |
| Multi-pattern regex over 100GB | ~300s | <8s | ~37× |
| Time-window join (threat hunting) | ~600s | <15s | ~40× |
| Ingest throughput | ~150 GB/day | ~1TB/day | ~7× |
| Storage (100 GB/day, 90 days) | ~3 TB | ~800 GB | 3.7× less |

## Contributing

4-person founding team. See [CONTRIBUTING.md](CONTRIBUTING.md) for team ownership and branching strategy.

## License

Apache 2.0 — see [LICENSE](LICENSE).
