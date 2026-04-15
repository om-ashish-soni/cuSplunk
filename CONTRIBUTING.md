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

---

## GPU Fallback — Coding Rules (mandatory)

`make test` must pass on a laptop with no GPU. Every Python service must follow these rules so the CPU fallback path works correctly.

### Rule 1 — Never use `import cudf` directly in service code

`import cudf` is the native cuDF API. It raises `ImportError` with no GPU. Use the `cudf.pandas` proxy instead — it falls back to pandas automatically via `CUDF_PANDAS_FALLBACK_MODE=1`.

```python
# WRONG — crashes with no GPU
import cudf
df = cudf.DataFrame(data)

# CORRECT — falls back to pandas when no GPU
import cudf.pandas as pd
df = pd.DataFrame(data)
```

The `cudf.pandas` API is a 1:1 pandas superset. All groupby, merge, str ops, etc. work identically. The only exception is `tstats` direct columnar scan (S3.3) — that path calls the store gRPC directly and never creates a cuDF DataFrame.

### Rule 2 — Morpheus / Triton must be behind an abstract interface

Morpheus and Triton have no CPU simulation. Any code that touches them must be behind a protocol/interface so the `docker-compose.dev.yml` stub can be swapped in:

```python
# services/detect/cusplunk/pipeline.py

class DetectionBackend(Protocol):
    def run_batch(self, df: pd.DataFrame) -> list[Alert]: ...

class MorpheusPipeline(DetectionBackend):
    """Real implementation — requires GPU + Morpheus."""
    ...

class StubPipeline(DetectionBackend):
    """CPU stub for local dev and unit tests. Returns no alerts."""
    def run_batch(self, df):
        return []
```

Select via env var:
```python
backend = MorpheusPipeline() if os.getenv("CUSPLUNK_GPU") else StubPipeline()
```

### Rule 3 — Numba CUDA kernels must compile under CUDASIM

If you write a Numba `@cuda.jit` kernel, test it under `NUMBA_ENABLE_CUDASIM=1` before opening a PR. The simulator runs kernels thread-by-thread on CPU — it catches logic bugs but not performance issues.

### Rule 4 — CUDA C++ kernels (`libs/gpu-kernels/`) need a CPU reference

For every `.cu` kernel, write a matching `*_ref.py` (pure numpy/Python) used by unit tests. The `.cu` file is only compiled and tested in GPU CI.

```
libs/gpu-kernels/
├── time_window_join.cu        # GPU implementation
└── time_window_join_ref.py    # CPU reference for unit tests
```
