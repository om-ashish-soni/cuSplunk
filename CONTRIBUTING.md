# Contributing to cuSplunk

## Team Ownership

| Person | Owns | Services | Languages |
|---|---|---|---|
| P1 | E1 INGEST + E4 BRIDGE | `services/ingest/`, `services/bridge/`, `libs/s2s-protocol/` | Go |
| P2 | E2 STORE + E8 SCALE | `services/store/`, `libs/gpu-kernels/`, `infra/` | Rust + CUDA |
| P3 | E3 QUERY + SPL Parser | `services/query/`, `libs/spl-parser/` | Python + ANTLR4 |
| P4 | E5 DETECT + E6 PLATFORM | `services/detect/`, `services/api/`, `ui/` | Python + Go + React |

E7 ENTERPRISE is shared — each person adds enterprise features to their own layer.

## Branching Strategy

```
main          ← always deployable, protected
  └─ epic/e1-ingest
       └─ feat/e1-s2s-protocol
       └─ feat/e1-hec-server
  └─ epic/e2-store
       └─ feat/e2-columnar-bucket
  └─ epic/e3-query
  ...
```

- Branch from `main` into your epic branch
- Feature branches off your epic branch
- PR → epic branch (code review by anyone on team)
- Epic branch → `main` when milestone ready

## PR Rules

1. Every PR links to a story (e.g., `Closes S1.1`)
2. Tests required for non-trivial logic
3. Benchmarks required for performance-critical paths
4. One approval minimum before merge
5. No force-push to `main` or epic branches

## Commit Convention

```
feat(ingest): implement S2S wire protocol handshake
fix(store): correct bloom filter false positive rate
perf(query): cuDF groupby 2x faster with dict encoding
docs(arch): add sequence diagram for ingest path
test(bridge): add time-range router unit tests
```

## Dev Setup

```bash
# Clone
git clone https://github.com/om-ashish-soni/cuSplunk
cd cuSplunk

# GPU dev environment (requires NVIDIA Docker)
docker-compose -f infra/docker/docker-compose.gpu.yml up

# Or run individual services
cd services/ingest && go run ./cmd/ingest
cd services/store && cargo run --release
cd services/query && python -m cusplunk.query
```

## GPU Requirements

Minimum: NVIDIA A10G (24 GB VRAM), CUDA 12.0+  
Dev alternative: NVIDIA T4 (16 GB) — most operations work, some benchmarks differ  
Cloud: AWS `g5.xlarge` (A10G, ~$1.00/hr) or `g5.12xlarge` (4× A10G)
