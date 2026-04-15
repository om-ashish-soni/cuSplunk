# cuSplunk — Parallel Claude Workplan

4 Claudes (C1/C2/C3/C4) work in parallel each round.
Each Claude picks up its round assignment, implements fully, opens a PR to the epic branch.
Do NOT start a round until all PRs from the previous round are merged.

---

## Round Map

```
R1: Foundation       (C1+C2+C3+C4 independent — start immediately)
R2: Core Engine      (depends on R1)
R3: Integration      (depends on R2)
R4: Platform         (depends on R3)
R5: Enterprise+Scale (depends on R4)
R6: Beta Prep        (depends on R5)
```

---

## R1 — Foundation (all 4 independent, no dependencies)

### C1 — Ingest Protocol Servers
**Branch:** `epic/e1-ingest` → `feat/r1-c1-protocols`  
**Epic:** E1 stories S1.1, S1.2, S1.3

**Deliver:**
- `services/ingest/cmd/ingest/main.go` — entry point, config loading
- `services/ingest/internal/s2s/` — S2S protocol parser + server (TCP port 9997)
  - Frame decoder (length-prefix + magic bytes)
  - Handshake handler
  - Connection pool (up to 10,000 concurrent)
  - Ack sender
- `services/ingest/internal/hec/` — HEC HTTP server (port 8088)
  - `POST /services/collector/event`
  - `POST /services/collector/raw`
  - Token validation middleware
  - Batch ack endpoint
- `services/ingest/internal/syslog/` — Syslog UDP/TCP/TLS (port 514/6514)
- Unit tests for all protocol parsers (table-driven)
- `services/ingest/go.mod` with all deps pinned

**Test:** `go test ./services/ingest/... -v` must pass  
**Not needed yet:** GPU queue, store gRPC client (stub it with a channel)

---

### C2 — Storage Bucket Format + Store Service Skeleton
**Branch:** `epic/e2-store` → `feat/r1-c2-store-skeleton`  
**Epic:** E2 stories S2.1, S2.8

**Deliver:**
- `services/store/` — Rust project with `Cargo.toml` deps pinned
- `services/store/src/bucket/` — columnar bucket format
  - `Bucket` struct: metadata, column files, bloom filter
  - `BucketWriter`: appends events to columns, dict-encodes strings
  - `BucketReader`: reads columns by name, returns Arrow RecordBatch
  - `meta.json` schema + serde
- `services/store/src/bloom/` — bloom filter (xxhash, configurable FPR)
- `services/store/src/proto/` — gRPC proto definitions
  - `WriteRequest`, `WriteResponse`
  - `ScanRequest` (time range, index, columns, filter), `ScanResponse` (stream of RecordBatch)
  - `BucketListRequest/Response`
- `services/store/src/server.rs` — tonic gRPC server skeleton (handlers return TODO errors for now)
- Unit tests: bucket write/read roundtrip, bloom filter correctness
- `proto/store.proto` in `libs/` (shared with other services)

**Test:** `cargo test` must pass  
**Not needed yet:** hot/warm/cold tiers, replication, retention (R2)

---

### C3 — SPL Parser (ANTLR4 Grammar)
**Branch:** `epic/e3-query` → `feat/r1-c3-spl-parser`  
**Epic:** E3 story S3.1

**Deliver:**
- `libs/spl-parser/SPL.g4` — complete ANTLR4 grammar for SPL
  - All commands: search, stats, eval, rex, join, timechart, tstats, table, fields,
    where, dedup, sort, head, tail, rename, lookup, inputlookup, transaction, bucket,
    streamstats, eventstats, append, union, appendcols
  - Subsearch: `[search ...]`
  - Macro syntax: `` `macro_name` ``, `` `macro_name(arg1, arg2)` ``
  - Eval functions: all math, string, time, conditional functions
  - Boolean expressions: AND, OR, NOT, parentheses
- `libs/spl-parser/cusplunk/spl/` — Python package
  - `parser.py` — `SPLParser.parse(spl: str) -> AST`
  - `ast.py` — AST node types (SearchNode, StatsNode, EvalNode, etc.)
  - `visitor.py` — base visitor class for AST walking
- `libs/spl-parser/tests/` — pytest test suite
  - `test_corpus.py` — parse all queries in `corpus/basic.txt` (500 hand-crafted queries)
  - `test_edge_cases.py` — nested subsearch, escaped quotes, multiline SPL
  - `test_hypothesis.py` — property-based: generated SPL never panics parser
- `libs/spl-parser/corpus/basic.txt` — 500 representative SPL queries

**Test:** `pytest libs/spl-parser/ -v` — zero parse errors on corpus  
**Not needed yet:** logical plan, GPU executor (R2)

---

### C4 — CI/CD + Dev Environment + Testing Infrastructure
**Branch:** `feat/r1-c4-devenv`  
**Epic:** Foundation for all testing

**Deliver:**
- `.github/workflows/ci.yml` — GitHub Actions pipeline
  - `unit-tests` job: go test + cargo test + pytest + npm test (runs on every push/PR)
  - `spl-compat` job: pytest tests/spl-compat/ (every push)
  - `integration-tests` job: runs on `epic/*` merge, requires `[self-hosted, gpu]` runner
  - `benchmarks` job: weekly cron, `[self-hosted, gpu]` runner
  - `e2e-tests` job: nightly, `[self-hosted, gpu]` runner
- `.github/workflows/release.yml` — tag → build Docker images → push to GHCR
- `infra/docker/docker-compose.dev.yml` — CPU-only dev stack (no GPU required for unit tests)
  - mock-store service (in-memory, returns fixture data)
  - mock-ingest that writes to file
  - redis, postgres
- `infra/docker/docker-compose.gpu.yml` — already exists, update with correct build contexts
- `tests/fixtures/` — shared test data
  - `fixtures/events/windows_event_log_1000.json` — 1000 WinEvent log samples
  - `fixtures/events/firewall_100k.json` — 100k firewall events
  - `fixtures/spl/golden_results.json` — 50 SPL queries with expected results (stub, expand in R3)
  - `fixtures/sigma/test_rules/` — 10 Sigma rules for integration tests
- `Makefile` — developer shortcuts
  ```makefile
  make dev          # start CPU dev stack
  make dev-gpu      # start GPU dev stack
  make test         # run all unit tests
  make test-int     # run integration tests
  make test-e2e     # run E2E tests
  make bench        # run benchmarks
  make lint         # golangci-lint + clippy + ruff + eslint
  ```
- `scripts/setup-dev.sh` — installs all dependencies, verifies GPU, sets up git hooks
- `docs/dev-setup.md` — step-by-step local dev guide (CPU path + GPU path)

**Test:** `make test` runs successfully on a fresh checkout with no GPU  
**Verify:** CI pipeline triggers on a test PR and all jobs turn green

---

## R2 — Core Engine (depends on R1)

All branches from `main` after R1 merges.

### C1 — GPU Parse Queue + cuDF Ingest Pipeline
**Branch:** `epic/e1-ingest` → `feat/r2-c1-gpu-parse`  
**Epic:** E1 stories S1.5, S1.6, S1.7

**Deliver:**
- `services/ingest/internal/gpuqueue/` — GPU parse queue
  - CUDA pinned memory ring buffer (via Python subprocess or shared memory)
  - Batch accumulator: flush at 10,000 events OR 100ms
  - Backpressure: block ingest if queue depth > 10 batches
- `services/query/cusplunk/ingest/` — Python cuDF batch processor
  - Consumes batches from Go ingest service (via Unix socket or shared memory)
  - `parse_batch(raw_events: List[bytes]) -> cudf.DataFrame`
    - Extract `_time`, `host`, `source`, `sourcetype` on GPU
    - Apply cyBERT for unstructured logs
  - nvCOMP LZ4 compression on `_raw` column
  - Forward compressed Arrow batch to store gRPC `Write()`
- `services/ingest/internal/store_client/` — gRPC client to store service
  - Replace stub channel from R1 with real gRPC WriteRequest
- Integration test: `TestIngestS2S_EventsArrivedInStore` passing with real GPU

**Benchmark:** `make bench-ingest` — must show >500K events/sec on A10G

---

### C2 — Hot/Warm/Cold Tiers + Retention
**Branch:** `epic/e2-store` → `feat/r2-c2-tiers`  
**Epic:** E2 stories S2.2, S2.3, S2.4, S2.6

**Deliver:**
- `services/store/src/hot/` — GPU memory hot tier
  - In-memory cuDF DataFrame pool (via Python interop or C FFI)
  - Ring buffer: evict oldest bucket when GPU memory >80%
  - Sub-millisecond scan for `_time > now - 5min`
- `services/store/src/warm/` — NVMe warm tier
  - Write columnar buckets to `WARM_TIER_PATH`
  - Read via cuFile (GPUDirect Storage) if available, fallback to mmap
  - Async write-behind from hot tier eviction
- `services/store/src/cold/` — object storage cold tier
  - Tiering job: move buckets older than 30 days to S3/GCS/Blob
  - Uses `object_store` crate
  - Lazy fetch: download cold bucket on first query, cache to warm
- `services/store/src/retention/` — retention engine
  - Parse retention policy per index (default 90 days)
  - Background task: runs every hour, tombstones expired buckets
  - Hard delete after tombstone + 24h grace period
  - Retention metrics: `cusplunk_store_retention_deleted_events_total`
- Full `ScanRequest` handler: routes to hot/warm/cold by time range, returns Arrow stream
- Tests: tier promotion, retention eviction, cold fetch

---

### C3 — GPU Query Executor (cuDF) + Logical Planner
**Branch:** `epic/e3-query` → `feat/r2-c3-executor`  
**Epic:** E3 stories S3.2, S3.3, S3.4

**Deliver:**
- `services/query/cusplunk/planner/` — logical plan
  - `LogicalPlan` from SPL AST (built on C3's R1 parser)
  - Push-down filter optimizer
  - Bloom filter skip hints attached to scan nodes
  - `explain()` method: human-readable plan
- `services/query/cusplunk/executor/` — cuDF GPU executor
  - `GPUExecutor.execute(plan: LogicalPlan, store_client) -> cudf.DataFrame`
  - Each operator implemented:
    - `ScanOperator`: calls store gRPC Scan, returns cuDF DataFrame
    - `FilterOperator`: `df[boolean_mask]`
    - `StatsOperator`: `df.groupby().agg()`
    - `EvalOperator`: expression evaluator (`eval` command)
    - `RexOperator`: `df['field'].str.extract(pattern)`
    - `SortOperator`, `HeadOperator`, `TableOperator`
    - `TimechartOperator`: time-bucket groupby
    - `TstatsOperator`: direct columnar scan
- `libs/gpu-kernels/time_window_join.cu` — custom CUDA kernel for `transaction`
  - Sort by key, sweep time window
  - Python binding via ctypes or cupy
- `services/query/cusplunk/executor/tests/` — pytest with real GPU
  - All operators tested with fixture data from `tests/fixtures/`
  - 50 golden SPL queries produce correct output

**Benchmark:** `make bench-query` — `stats count by src_ip` over 1B synthetic events <2s

---

### C4 — Detection Engine Skeleton + Sigma Loader
**Branch:** `epic/e5-detect` → `feat/r2-c4-detect-skeleton`  
**Epic:** E5 stories S5.1, S5.5 (partial)

**Deliver:**
- `services/detect/cusplunk/sigma/` — Sigma rule engine
  - `SigmaParser`: parse Sigma YAML → internal rule representation
    - Handle all condition types: keywords, field match, aggregation, near
    - Parse detection, logsource, timeframe fields
  - `SigmaCompiler`: rule → GPU regex pattern (multi-pattern string)
  - `SigmaEvaluator`: batch evaluate rules against cuDF DataFrame
    - GPU multi-pattern matching (using cuDF string contains/regex)
    - Return: `[(rule_id, matched_event_idx)]` list
  - Bulk load: 1,000 rules from `tests/fixtures/sigma/test_rules/`
  - Hot-reload: watch rules directory, reload on file change
- `services/detect/cusplunk/normalize/` — cyBERT log normalizer
  - Fork of RAPIDS CLX cyBERT inference code
  - Input: raw log string
  - Output: dict of extracted fields
  - Supported: Windows Event Log, Syslog, CEF
  - Integration test: `test_cybert_windows_event_log.py` with fixture WinEvents
- `services/detect/cusplunk/pipeline.py` — Morpheus pipeline skeleton
  - Source: cuStreamz stream from ingest queue
  - Stage 1: cyBERT normalization
  - Stage 2: Sigma evaluation
  - Sink: alert queue (in-memory for now)
- Unit tests: Sigma parser on SigmaHQ test corpus (download in CI), cyBERT F1 > 0.99

---

## R3 — Integration (depends on R2)

### C1 — Bridge Service + Time-Range Router
**Branch:** `epic/e4-bridge` → `feat/r3-c1-bridge`  
**Epic:** E4 stories S4.1, S4.2, S4.3, S4.4, S4.6

**Deliver:**
- `services/bridge/` — complete Go bridge service
  - Splunk REST client (auth, search job lifecycle, result pagination)
  - Time-range router with cutover date logic
  - Fan-out executor (parallel goroutines for GPU + Splunk)
  - Result merger (sort by `_time`, dedup by hash)
  - Auto-sunset handler (day 90+, log + disable)
  - `config.yaml` schema with validation
  - All bridge metrics exposed to Prometheus
- Integration tests:
  - `TestBridgeFanOut` with mock Splunk REST server (httptest)
  - `TestBridgeAutoSunset` time-travel test
  - `TestBridgeResultMerge_Dedup` with overlapping events
- `scripts/splunk-export.sh` — bulk rawdata export helper
- `docs/migration-guide.md` — step-by-step enterprise migration playbook

---

### C2 — Store Replication + Cluster
**Branch:** `epic/e2-store` → `feat/r3-c2-replication`  
**Epic:** E2 stories S2.5 (bloom), S2.7 (replication)

**Deliver:**
- `services/store/src/replication/` — Raft-based replication
  - openraft integration
  - Leader election, log replication
  - `replication_factor=2` default
  - Reads from replica on leader unavailability
- `services/store/src/bloom/` — bloom filter integrated into bucket scan
  - Build bloom filter during bucket write
  - Skip bucket if bloom says no match (key optimization for sparse queries)
  - `bloom.bin` persisted per bucket
- Cluster config: multiple store nodes, peer discovery via config
- Integration test: `TestReplication_LeaderFailover` — kill leader, verify reads still work
- Benchmark: replication lag < 500ms under 1M events/sec ingest

---

### C3 — Distributed Query + Scheduler + Cache
**Branch:** `epic/e3-query` → `feat/r3-c3-distributed`  
**Epic:** E3 stories S3.5, S3.6, S3.7, S3.8, S3.9, S3.10

**Deliver:**
- `services/query/cusplunk/distributed/` — fan-out executor
  - Consistent hash ring: index → indexer node
  - gRPC fan-out to all indexer nodes
  - Partial aggregation on each node, merge on coordinator
  - Streaming partial results
- `services/query/cusplunk/router/` — time-range router
  - Integrates with bridge service for pre-cutover queries
  - Handles `earliest`, `latest`, relative times
- `services/query/cusplunk/scheduler/` — priority queues
  - Interactive / Scheduled / Background lanes
  - GPU time-slice allocation
  - Queue depth monitoring
  - `GET /api/v1/search/jobs/{id}/status`
- `services/query/cusplunk/cache/` — Redis-backed result cache
  - LRU keyed on (SPL_hash, time_range, schema_version)
  - 60-second TTL for dashboard refresh
- `services/query/cusplunk/autocomplete.py` — field name + command autocomplete
- Integration test: fan-out across 3 mock store nodes, verify merged results

---

### C4 — ML Models + Alert Pipeline
**Branch:** `epic/e5-detect` → `feat/r3-c4-ml-alerts`  
**Epic:** E5 stories S5.3, S5.4, S5.6, S5.7, S5.8, S5.9

**Deliver:**
- `services/detect/cusplunk/triton/` — Triton model client
  - gRPC inference client
  - Model: DGA detector (DNS logs) — download pretrained from Morpheus NGC
  - Model: cyBERT v2 — download from Morpheus NGC
  - Async inference with batching
- `services/detect/cusplunk/pipeline.py` — complete Morpheus pipeline
  - Source: Kafka or ingest queue
  - Stage 1: cyBERT normalization
  - Stage 2: Sigma + YARA evaluation
  - Stage 3: Triton ML inference (DGA, anomaly)
  - Stage 4: Threat intel join (cuDF left join on IOC table)
  - Sink: Alert API gRPC
- `services/detect/cusplunk/mitre/` — MITRE ATT&CK enrichment
  - Load ATT&CK STIX bundle (from MITRE GitHub)
  - Sigma rule → technique mapping
  - Alert enrichment: add `mitre.tactic`, `mitre.technique_id`
- `services/detect/cusplunk/threatintel/` — STIX/TAXII feed ingestion
  - AlienVault OTX, Abuse.ch
  - Refresh scheduler
  - IOC table in GPU memory (cuDF) for join
- `services/api/internal/alerts/` — alert management gRPC handler
  - Create, dedup, group, suppress, lifecycle state machine
  - PostgreSQL persistence
- Alert output integrations: webhook (generic), Slack, PagerDuty
- Integration test: inject WinEvent 4625 ×10 → verify alert + MITRE T1110 tag

---

## R4 — Platform (depends on R3)

### C1 — REST API + Auth (Splunk-compatible)
**Branch:** `epic/e6-platform` → `feat/r4-c1-api`  
**Epic:** E6 story S6.7, S6.6 (auth part)

**Deliver:**
- `services/api/` — complete Go REST API
  - Splunk-compatible endpoints (same URL structure, same JSON schema):
    - `POST /services/search/jobs`
    - `GET  /services/search/jobs/{sid}`
    - `GET  /services/search/jobs/{sid}/results`
    - `DELETE /services/search/jobs/{sid}`
    - `GET  /services/data/indexes`
    - `POST /services/data/indexes`
    - `GET  /services/saved/searches`
    - `POST /services/saved/searches`
    - `GET  /services/search/timeparser`
  - cuSplunk-native endpoints:
    - `GET  /api/v1/health`
    - `GET  /api/v1/nodes`
    - `GET  /api/v1/metrics`
    - `GET  /api/v1/spl/autocomplete`
  - Auth middleware: JWT tokens, API token (Bearer)
  - Rate limiting: 100 req/min per user (Redis token bucket)
  - OpenAPI 3.0 spec auto-generated
- `services/api/internal/auth/` — auth service
  - Local user table (PostgreSQL, bcrypt passwords)
  - API token generation + validation
  - RBAC enforcement per endpoint
- Acceptance test: Splunk Python SDK `client.jobs.create()` works unchanged

---

### C2 — SPL Search UI + Results Table
**Branch:** `epic/e6-platform` → `feat/r4-c2-search-ui`  
**Epic:** E6 stories S6.1, S6.2

**Deliver:**
- `ui/src/app/search/page.tsx` — main search page
- `ui/src/components/SPLSearchBar/` — Monaco editor component
  - SPL syntax highlighting (TextMate grammar)
  - Autocomplete: fetches field names + commands from API
  - Time range picker component (relative + absolute)
  - Search history (localStorage, last 50)
  - Keyboard shortcut: Cmd+Enter to run
- `ui/src/components/ResultsTable/` — event viewer
  - `@tanstack/react-table` with virtual scroll (10K rows, no lag)
  - Field extraction sidebar (click field → show values, click value → filter)
  - JSON expand/collapse for `_raw`
  - Column picker
  - Download CSV/JSON button
- `ui/src/lib/api.ts` — typed API client (wraps fetch, handles job polling)
- `ui/src/types/splunk.ts` — TypeScript types for Splunk API responses
- Vitest tests: search bar renders, results table virtualization, time picker

---

### C3 — Dashboard Builder + Saved Searches
**Branch:** `epic/e6-platform` → `feat/r4-c3-dashboards`  
**Epic:** E6 stories S6.3, S6.4

**Deliver:**
- `ui/src/app/dashboards/` — dashboard builder page
  - Drag-drop panel layout (react-grid-layout)
  - Panel types: timechart, bar, pie, single value, table, heatmap
  - Each panel: SPL input + visualization config
  - Auto-refresh: 30s / 1m / 5m / off
  - Save dashboard (POST to API, stored in PostgreSQL)
  - Share: URL-based sharing
  - PDF export (puppeteer server-side)
- `ui/src/app/saved-searches/` — saved search management
  - List, create, edit saved searches
  - Schedule picker (cron)
  - Alert condition builder (results > 0, count threshold)
  - Throttle config
- `services/api/internal/schedules/` — cron scheduler (Go)
  - Execute saved searches on schedule
  - Evaluate alert conditions
  - Route to alert service if triggered

---

### C4 — Case Management + System Health UI
**Branch:** `epic/e6-platform` → `feat/r4-c4-cases`  
**Epic:** E6 stories S6.5, S6.8, S6.9

**Deliver:**
- `ui/src/app/alerts/` — alert list + detail view
  - Severity badges, MITRE technique chips
  - Alert timeline chart
  - Assign to analyst
  - Create case from alert
- `ui/src/app/cases/` — case management
  - Case list with filters (status, severity, assignee)
  - Case detail: timeline, comments, evidence attachments
  - Status state machine: new → assigned → investigating → resolved/fp
  - Close case form with resolution notes
- `ui/src/app/admin/` — system administration
  - Index management (list, create, set retention)
  - User management (create, assign role, revoke)
  - System health dashboard (GPU util, ingest rate, storage, active searches)
  - Bridge migration progress (when active)
- PostgreSQL schema: `cases`, `case_comments`, `case_evidence` tables
- API endpoints: full CRUD for cases, comments, evidence upload

---

## R5 — Enterprise + Scale (depends on R4)

### C1 — SSO + Multi-Tenancy
**Branch:** `epic/e7-enterprise` → `feat/r5-c1-sso`  
**Epic:** E7 stories S7.1, S7.2

**Deliver:**
- `services/api/internal/sso/` — SAML 2.0 + OIDC
  - SAML SP: metadata, ACS endpoint, assertion validation
  - OIDC client: authorization code flow
  - JIT user provisioning on first SSO login
  - Group → role mapping config
- `services/api/internal/multitenancy/` — tenant isolation
  - Tenant ID scoping on all index operations
  - Tenant-scoped API tokens
  - Per-tenant resource quotas (enforced at ingest + query)
- PostgreSQL schema: `tenants`, `tenant_quotas`, `tenant_users`
- Tests: SAML flow with mock IdP (samlidp library), OIDC flow with mock provider

---

### C2 — Kubernetes Operator + Helm Chart
**Branch:** `epic/e7-enterprise` → `feat/r5-c2-k8s`  
**Epic:** E7 story S7.6

**Deliver:**
- `infra/k8s/operator/` — Kubernetes operator
  - CRD: `CuSplunkCluster` spec (replicas, GPU resources, storage, TLS)
  - Controller: reconcile desired → actual state
  - GPU node affinity rules (only schedule on GPU nodes)
  - NVMe PVC provisioning via StorageClass
  - TLS cert rotation via cert-manager
  - Rolling upgrades with zero-downtime
- `infra/k8s/helm/cusplunk/` — Helm chart
  - Values: `values.yaml` with all configurable params
  - Templates: Deployment/StatefulSet for each service
  - ServiceMonitor for Prometheus scraping
  - HPA for query service (scale on GPU utilization)
- `docs/k8s-deploy.md` — production K8s deployment guide
- Test: `helm lint`, `helm template | kubectl apply --dry-run`

---

### C3 — Benchmark Suite + Load Tests
**Branch:** `epic/e8-scale` → `feat/r5-c3-benchmarks`  
**Epic:** E8 stories S8.1, S8.6

**Deliver:**
- `benchmarks/datasets/generate.py` — synthetic dataset generator
  - Generate N billion events: firewall, auth, DNS, web proxy log formats
  - Deterministic seed (reproducible)
  - Output: JSON files importable via HEC
- `benchmarks/compare/run.sh` — competitor comparison runner
  - Provisions Splunk + ClickHouse + Elastic (Docker)
  - Loads identical dataset into each
  - Runs 8 canonical queries against each
  - Outputs Markdown table to `benchmarks/results/YYYY-MM-DD.md`
- `benchmarks/load/k6-script.js` — 1,000-user load test
  - 3 scenarios (dashboard, adhoc, export) as defined in TESTING.md
  - SLO threshold validation
- `benchmarks/results/HARDWARE.md` — exact hardware spec for reproducibility
- GitHub Actions cron job for weekly benchmark run

---

### C4 — Compliance Reports + Audit Log + Encryption
**Branch:** `epic/e7-enterprise` → `feat/r5-c4-compliance`  
**Epic:** E7 stories S7.3, S7.4, S7.9

**Deliver:**
- `services/api/internal/audit/` — immutable audit log
  - Log every: login, search, config change, user action
  - HMAC chain (tamper-evident: each entry includes hash of previous)
  - PostgreSQL `audit_log` table with append-only policy (revoke DELETE)
  - SPL query: `index=_audit` routes to audit log table
- `services/api/internal/compliance/` — report generator
  - PCI-DSS report: saved SPL queries for cardholder data access, failed logins
  - HIPAA report: PHI access, unauthorized access
  - SOC2 report: availability, change management
  - PDF generation (headless Chrome via puppeteer)
  - Schedule: daily/weekly/monthly delivery
- `services/store/src/encryption/` — at-rest encryption
  - AES-256-GCM for warm tier bucket files
  - Key management: env var (dev), HashiCorp Vault (prod), AWS KMS (cloud)
  - Transparent: encryption/decryption in bucket reader/writer
- Tests: audit log HMAC verification, compliance report PDF renders correctly

---

## R6 — Beta Prep (depends on R5)

### C1 — Splunk API Compatibility + Migration Docs
**Branch:** `feat/r6-c1-compat`  
**Epic:** E7 story S7.7

**Deliver:**
- Run Splunk Python SDK test suite against cuSplunk API (target: 100% pass)
- Fix all API compatibility gaps found
- `docs/migration-guide.md` — complete enterprise migration playbook
  - Pre-flight checklist
  - Deploy cuSplunk alongside Splunk (step-by-step)
  - Configure Universal Forwarders (screenshots)
  - Set bridge cutover date
  - Monitor migration progress (dashboard walkthrough)
  - Day 90: bridge sunset checklist
  - Rollback procedure (< 30 min)
- `docs/spl-reference.md` — cuSplunk SPL reference, differences from Splunk SPL noted

---

### C2 — Performance Hardening
**Branch:** `feat/r6-c2-perf`  
**Epic:** E8 stories S8.4, S8.5

**Deliver:**
- `services/store/src/gpu_memory/` — RMM memory pool tuning
  - Pre-allocate 80% of GPU memory at startup
  - Pool size metrics: `cusplunk_gpu_memory_pool_used_bytes`
  - OOM guard: search killed gracefully, error returned to user
- `services/query/cusplunk/plan_cache.py` — physical plan cache
  - Cache by (SPL_normalized_hash, index, schema_version)
  - Redis TTL: 5 minutes
  - Invalidation on schema change
- Profile top 10 SPL queries from beta fixtures, optimize hot paths
- GPU profiling: use Nsight Systems to identify kernel bottlenecks
- Target: p95 interactive query <2s, p99 <10s

---

### C3 — Chaos Tests + SRE Runbooks
**Branch:** `feat/r6-c3-chaos`  
**Epic:** E8 story S8.7

**Deliver:**
- `tests/chaos/` — all 7 chaos scenarios implemented (chaostoolkit)
- All 7 scenarios pass their steady-state hypothesis
- `docs/runbooks/` — SRE runbooks
  - `runbooks/indexer-node-failure.md`
  - `runbooks/gpu-oom.md`
  - `runbooks/disk-full.md`
  - `runbooks/high-query-latency.md`
  - `runbooks/ingest-backlog.md`
  - `runbooks/bridge-timeout.md`
- Grafana dashboards committed to `infra/grafana/dashboards/`
  - `cusplunk-overview.json` — top-level health
  - `cusplunk-query-perf.json` — query latency breakdown
  - `cusplunk-gpu.json` — GPU utilization, memory, kernel time
  - `cusplunk-ingest.json` — events/sec, parse errors, queue depth

---

### C4 — Beta Infrastructure + Onboarding Automation
**Branch:** `feat/r6-c4-beta-infra`  
**Epic:** BETA.md implementation

**Deliver:**
- `scripts/beta-onboard.sh` — automated beta customer setup
  - Creates isolated namespace in K8s cluster
  - Generates customer-specific API tokens
  - Creates Slack channel (via Slack API)
  - Sends welcome email with credentials
- `scripts/beta-telemetry.py` — opt-in telemetry collector
  - Anonymized metrics to our endpoint
  - Customer consent flag in config
- `docs/beta-quickstart.md` — 4-hour onboarding guide (from zero to first search)
- `docs/faq.md` — top 20 expected beta questions answered
- Status page setup (Statuspage.io or self-hosted Gatus)
- `scripts/beta-report.sh` — weekly beta digest generator (pulls metrics, generates email)

---

## Summary: Who Does What

| Round | C1 | C2 | C3 | C4 |
|---|---|---|---|---|
| R1 | Ingest protocols (Go) | Store bucket format (Rust) | SPL grammar (ANTLR4) | CI/CD + dev env |
| R2 | GPU parse queue (cuDF) | Hot/warm/cold tiers | GPU executor (cuDF) | Sigma + cyBERT |
| R3 | Bridge service | Replication + bloom | Distributed query + cache | ML + alert pipeline |
| R4 | REST API + auth | Search UI + results | Dashboards + saved searches | Cases + admin UI |
| R5 | SSO + multi-tenancy | K8s operator | Benchmarks + load tests | Compliance + audit |
| R6 | Splunk compat + docs | Perf hardening | Chaos tests + runbooks | Beta infra |

## Rules for Claudes

1. **Read ARCHITECTURE.md and TECH_STACK.md before starting any round**
2. **Read your epic doc** (`docs/epics/eN-name.md`) for full story details
3. **Create a branch** from `main` (R1) or from the previous round's merged state
4. **Write tests first** — no PR without unit tests for new logic
5. **Update the epic doc** — check off completed stories (`- [x]`)
6. **Open PR** to the epic branch (not main) with story reference in title
7. **Do not implement** stories from other rounds — trust the plan
8. **Do not refactor** work from previous rounds unless it blocks your stories
9. **Benchmark target** — if your round has a benchmark, run it and paste results in the PR
10. **If blocked** — comment in the GitHub Issue, do not skip ahead
