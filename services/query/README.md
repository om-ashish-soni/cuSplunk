# cuSplunk Query Service

**Language:** Python + RAPIDS cuDF  
**Epic:** [E3 — QUERY](../../docs/epics/e3-query.md)  
**Owner:** P3

## Components

- `spl_parser/` — ANTLR4 SPL grammar + AST builder
- `planner/` — Logical plan optimizer
- `executor/` — cuDF GPU physical executor
- `router/` — Time-range router (GPU store vs Bridge)
- `scheduler/` — Priority-based query scheduler
- `cache/` — Redis-backed result cache

## Quick Start

```bash
pip install -r requirements.txt
python -m cusplunk.query --config config.yaml
```

## Environment

```bash
CUDA_VISIBLE_DEVICES=0
STORE_GRPC_ADDR=store-service:50051
BRIDGE_GRPC_ADDR=bridge-service:50052
REDIS_URL=redis://localhost:6379
CUTOVER_DATE=2025-06-01T00:00:00Z
```
