# cuSplunk Store Service

**Language:** Rust + CUDA  
**Epic:** [E2 — STORE](../../docs/epics/e2-store.md)  
**Owner:** P2

## Storage Tiers

| Tier | Technology | Retention | Access Pattern |
|---|---|---|---|
| Hot | GPU memory (cuDF) | Last 5 min | Sub-ms query |
| Warm | NVMe + GPUDirect (GDS) | Last 30 days | <30s / TB |
| Cold | S3/GCS/Blob | 30–90 days | Minutes |

## Quick Start

```bash
cargo run --release --bin store -- --config config.yaml
```

## Config

```yaml
hot_tier:
  gpu_memory_mb: 8192

warm_tier:
  path: /nvme/cusplunk/warm
  gds_enabled: true

cold_tier:
  provider: s3
  bucket: cusplunk-cold
  prefix: logs/
  region: us-east-1

retention:
  default_days: 90
  check_interval_hours: 1

replication:
  factor: 2
  peers:
    - "store-node-2:50051"
    - "store-node-3:50051"

grpc:
  port: 50051
```
