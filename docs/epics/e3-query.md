# E3 — QUERY: GPU-Accelerated SPL Query Engine

**Owner:** P3  
**Service:** `services/query/` (Python + cuDF), `libs/spl-parser/` (ANTLR4)  
**Milestone:** M1  
**Status:** Planning

## Goal

Execute SPL queries 10–100× faster than Splunk. Full SPL compatibility — existing saved searches run unchanged. Target: **`stats count by src_ip` over 1B events in <2s.**

## Stories

### S3.1 — SPL Grammar (ANTLR4)
Implement complete SPL grammar covering 100% of common commands.
- ANTLR4 grammar file: `libs/spl-parser/SPL.g4`
- Commands: `search`, `stats`, `eval`, `rex`, `join`, `timechart`, `tstats`, `table`, `fields`, `where`, `dedup`, `sort`, `head`, `tail`, `rename`, `lookup`, `inputlookup`, `transaction`, `bucket`, `streamstats`, `eventstats`
- Macro expansion (`\`macro_name\``)
- Subsearch support (`[search ...]`)
- Acceptance criteria: parse 1000 real Splunk SPL queries without error

### S3.2 — AST → Logical Plan
- Walk ANTLR4 AST → operator tree
- Logical operators: Scan, Filter, Project, Aggregate, Join, Sort, Limit, Eval, Extract
- Push-down optimization: move filters as close to scan as possible
- Predicate pushdown into bloom filter skip logic
- Cardinality estimation

### S3.3 — GPU Physical Executor (cuDF)
Map logical plan → cuDF operations. Each operator:

| Logical Op | cuDF Implementation |
|---|---|
| Scan | `store.Scan()` → cuDF DataFrame |
| Filter (`search`) | `df[boolean_mask]` on GPU |
| Aggregate (`stats`) | `df.groupby().agg()` on GPU |
| Eval | `df.assign()` with expression evaluator |
| Rex | `df['field'].str.extract(pattern)` GPU regex |
| Sort | `df.sort_values()` on GPU |
| Join | `cudf.merge()` GPU hash join |
| Timechart | `df.groupby(time_bucket)` GPU |
| Tstats | Direct columnar scan (skip raw decompression) |

### S3.4 — GPU Time-Window Join (Transaction)
SPL `transaction` command requires joining events within a time window — most expensive operation in Splunk.
- Custom CUDA kernel: sort by key, then sweep time window
- `transaction maxspan=5m maxpause=30s` support
- Target: 100× faster than Splunk CPU join
- Implementation in `libs/gpu-kernels/time_window_join.cu`

### S3.5 — Distributed Query Fan-Out
- Query coordinator fans out scan to all indexer nodes
- Each node executes filter + partial aggregation on local GPU
- Coordinator merges partial results
- Consistent hash ring for index-to-node mapping
- gRPC streaming for partial result delivery

### S3.6 — Time-Range Router
- Parse time range from every SPL query (`earliest`, `latest`, time picker)
- Route: before cutover → Bridge service; after cutover → GPU store; spanning → fan-out both
- Merge logic: sort merged result by `_time`, dedup on `_time+_raw` hash

### S3.7 — Query Scheduler
- Priority queues: `interactive` (user-initiated), `scheduled` (saved searches), `background` (exports)
- GPU time-slice: interactive gets 70%, scheduled 25%, background 5%
- Queue depth limit per priority
- Search job API: `POST /services/search/jobs` → job ID → `GET /services/search/jobs/{id}/results`

### S3.8 — Query Result Cache
- LRU cache keyed on (SPL_hash, time_range)
- GPU-resident for dashboard refresh (same query, last 60s)
- Redis-backed for cross-node cache sharing
- Cache hit logged in `cusplunk_query_cache_hits_total`

### S3.9 — Explain Plan
`| explain` appends query plan to results:
```
Stage 1: Scan index=firewall [bloom skip: 42%]  GPU: 120ms
Stage 2: Filter src_ip != "0.0.0.0"             GPU: 8ms
Stage 3: Aggregate stats count by src_ip         GPU: 45ms
Stage 4: Sort -count                             GPU: 12ms
Total GPU time: 185ms  |  Result rows: 1,247
```

### S3.10 — SPL Autocomplete API
`GET /api/v1/spl/autocomplete?q=index%3Dmain+%7C+st`  
Returns: `["stats", "streamstats", "strcat"]`  
Used by UI search bar.

## SPL Coverage Target

| Category | Commands | Target Coverage |
|---|---|---|
| Search | search, where, head, tail, dedup | 100% |
| Stats | stats, timechart, chart, eventstats, streamstats | 100% |
| Eval | eval + all eval functions | 95% |
| Extract | rex, extract, kvform | 100% |
| Lookup | lookup, inputlookup, outputlookup | 100% |
| Transform | sort, table, fields, rename | 100% |
| Join | join, append, union, appendcols | 90% |
| Transaction | transaction | 100% (GPU-accelerated) |
| Tstats | tstats | 100% |

## Benchmark Target

| Query | Target |
|---|---|
| `stats count by src_ip` over 1B events | <2s |
| `rex` extraction over 100M events | <5s |
| `transaction` over 10M events | <15s |
| `timechart span=1h count` over 90 days | <3s |
| 100 concurrent searches | <p99 10s |

## Dependencies

- ANTLR4 (Python runtime)
- RAPIDS cuDF
- NVIDIA Triton (for ML commands)
- Redis (query cache)
- gRPC (distributed fan-out)
