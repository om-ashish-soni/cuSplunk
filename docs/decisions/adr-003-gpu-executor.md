# ADR-003: RAPIDS cuDF as Primary GPU Executor

**Status:** Accepted  
**Date:** 2026-04-15

## Context

We need a GPU execution engine for the query layer. Requirements:
1. Must handle DataFrame operations: filter, group-by, sort, join, string ops
2. Must work with Apache Arrow (zero-copy from storage layer)
3. Must support distributed execution across nodes
4. Must be production-ready with active maintenance

## Decision

Use **NVIDIA RAPIDS cuDF** as the primary GPU query executor.

Custom CUDA kernels (`libs/gpu-kernels/`) for operations cuDF doesn't cover:
- Time-window join (`transaction` command)
- Multi-pattern regex (HybridSA approach for Sigma rules)
- Bloom filter operations

## cuDF → SPL Mapping

| SPL | cuDF |
|---|---|
| `stats count by X` | `df.groupby('X').agg({'_count': 'count'})` |
| `search X=Y` | `df[df['X'] == 'Y']` |
| `rex "(?P<f>p)"` | `df['f'] = df['_raw'].str.extract('p')` |
| `eval X=Y+Z` | `df['X'] = df['Y'] + df['Z']` |
| `sort -X` | `df.sort_values('X', ascending=False)` |
| `join` | `cudf.merge(left, right, on=key, how=type)` |
| `timechart span=1h` | `df.groupby(pd.Grouper(freq='1h'))` |

## Consequences

**Good:**
- 10–150× faster than pandas on log analytics workloads
- Zero-copy Arrow ingestion from storage layer
- `cudf.pandas` mode: CPU fallback for unsupported operations is automatic
- Active NVIDIA maintenance, GTC announcements, production deployments at Databricks/Snowflake/Spark
- Integrates with Morpheus (detection) and cuVS (vector search)

**Bad:**
- Python runtime overhead for non-GPU paths
- cuDF API not 100% pandas-compatible (some edge cases)
- Requires CUDA 12+, limits deployment to NVIDIA GPUs only

## Alternatives Considered

| Approach | Rejected reason |
|---|---|
| Sirius (DuckDB GPU extension) | Research prototype, not production, single-node only |
| Custom CUDA C++ engine | 2+ years to build; cuDF already exists |
| Velox + cuDF | Overkill for MVP; adds complexity |
| CPU pandas with GPU fallback | Wrong direction — GPU-first is the product |
