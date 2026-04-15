# E8 — SCALE: Benchmarks + Horizontal Scale

**Owner:** P2 (infra), all for benchmarks  
**Milestone:** M6  
**Status:** Planning

## Goal

Publish undeniable benchmarks. Be provably faster than Splunk, ClickHouse, and Elastic on identical hardware. Numbers that Cisco's engineering team cannot ignore.

## Stories

### S8.1 — Benchmark Suite
Automated benchmark runner comparing cuSplunk vs Splunk vs ClickHouse vs Elastic:

Queries benchmarked:
```sql
-- B1: High-cardinality aggregation
index=firewall | stats count by src_ip

-- B2: Multi-field aggregation
index=auth | stats count by user, src_ip, action | sort -count

-- B3: Regex extraction
index=web | rex "(?P<status>\d{3})" | stats count by status

-- B4: Time-window join (threat hunting)
index=process | transaction pid maxspan=5m | where duration > 60

-- B5: Rare term search
index=* "malware" OR "ransomware" OR "c2-domain.evil"

-- B6: Timechart (dashboard load)
index=network | timechart span=1h sum(bytes) by src_ip limit=10

-- B7: Tstats (fast aggregation)
| tstats count where index=main by _time span=1h

-- B8: Large join
index=events | join type=left user [search index=users | table user, department]
```

Hardware: identical — 1× A10G, 48-core CPU, 256 GB RAM, 4 TB NVMe.  
Output: markdown table + charts committed to `benchmarks/results/`.

### S8.2 — Multi-GPU Horizontal Indexer Scale
- Consistent hash ring: index name → indexer node
- Add node: rebalance ring, migrate ~1/N buckets
- Remove node: drain buckets, update ring
- Linear throughput target: 2× nodes = 1.9× throughput
- Rebalance with zero query downtime

### S8.3 — Search Head Clustering
- Multiple query service instances behind load balancer
- Distributed query cache (Redis cluster)
- Session stickiness for long-running searches
- Coordinator election: any query node can fan out to all indexers
- Failure: in-flight searches transparently retried on other node

### S8.4 — GPU Memory Manager
- RAPIDS Memory Manager (RMM) pool allocator
- Pre-allocated GPU memory pool at startup (avoid alloc latency in hot path)
- Memory pressure handler: evict hot tier to warm when GPU memory >80%
- OOM guard: search killed gracefully if GPU memory exhausted
- Metric: `cusplunk_gpu_memory_used_bytes`, `cusplunk_gpu_memory_pool_fragmentation`

### S8.5 — Query Plan Cache
- Physical execution plans cached by (SPL_normalized_hash, index, schema_version)
- Invalidated on schema change or new fields
- Cache hit target: >60% for dashboard refresh patterns
- Saved in Redis with 5-minute TTL

### S8.6 — Load Testing
- k6 script: 1,000 concurrent users, mixed read/write workload
- Scenarios: dashboard refresh (70%), ad-hoc search (20%), export (10%)
- SLO targets: p50 <200ms, p95 <2s, p99 <10s for interactive searches
- Results committed to `benchmarks/load-test/`

### S8.7 — Chaos Engineering
Test failure scenarios:
- Kill one indexer node → queries degrade gracefully, no data loss
- GPU OOM → search returns error, ingest continues
- NVMe fill to 95% → retention engine kicks in, drops oldest buckets
- Network partition between nodes → Raft re-elects, service resumes
- Splunk bridge timeout → query returns GPU-only results, logs warning

Tool: `chaostoolkit` with custom cuSplunk driver.

### S8.8 — Cost Benchmark
Publish total cost of ownership vs Splunk at 3 data volumes:

| Volume | Splunk (cloud) | cuSplunk (spot GPU) | Savings |
|---|---|---|---|
| 100 GB/day | ~$240K/yr | ~$28K/yr | 8.5× cheaper |
| 500 GB/day | ~$1.17M/yr | ~$120K/yr | 9.7× cheaper |
| 1 TB/day | ~$2.1M/yr | ~$220K/yr | 9.5× cheaper |

Methodology documented. AWS spot pricing used (A10G spot).

## Benchmark Publication Plan

1. Run benchmarks on reproducible AWS hardware
2. Commit raw results + methodology to `benchmarks/`
3. Publish blog post: "cuSplunk vs Splunk: 10B events, 1 GPU, 45× faster"
4. Submit to ClickBench (https://benchmark.clickhouse.com) under "cuSplunk" entry
5. Share on Hacker News, r/netsec, r/sysadmin

## Scale Targets

| Metric | Single Node | 10-Node Cluster |
|---|---|---|
| Ingest | 1M events/sec | 10M events/sec |
| Storage | 1 TB/day (compressed) | 10 TB/day |
| Concurrent searches | 50 | 500 |
| Index count | 1,000 | 10,000 |
| Total retention | 9 TB (90d @ 100GB/day) | 90 TB |
