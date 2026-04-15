# cuSplunk — Checkpoint

## Last updated
2026-04-15 by C3 (R2 survey + R1-C3 SPL parser complete)

## Handoff notes
- **C1 (2026-04-15, doc survey):** Read all docs, bootstrapped CHECKPOINT + memory. Zero code written.
- **C5 (2026-04-15):** Researched GPU simulation. Key finding: `NUMBA_ENABLE_CUDASIM=1` + `CUDF_PANDAS_FALLBACK_MODE=1` covers ~80% of codebase for CPU testing. Updated TESTING.md.
- **C4 (2026-04-15, R1):** Implemented R1-C4 in full. CI/CD, dev stack, fixtures, Makefile, setup script, docs.
- **C1 (2026-04-15, R1):** Implemented R1-C1 in full. S2S, HEC, Syslog servers. 58 tests passing.
- **C3 (2026-04-15, R1):** Implemented R1-C3 in full. SPL.g4 ANTLR4 grammar, Python AST/parser/visitor, 500-query corpus. **594 tests passing** (corpus + edge cases + hypothesis). Branch: `feat/r1-c3-spl-parser` (separate repo under libs/spl-parser/).
- **C4 (2026-04-15, R2):** Implemented R2-C4 in full. Sigma parser/compiler/evaluator, cyBERT CPU normalizer (Windows/Syslog/CEF), Morpheus pipeline skeleton, 81 tests all passing.
- **C1 (2026-04-15, R2):** Implemented R2-C1 in full. GPUQueue (Unix socket IPC, backpressure semaphore, 8 tests), Python cuDF processor with LZ4+CPU fallback (18 tests), gRPC store client (protoc-generated from store.proto), integration tests TestIngestS2S_EventsArrivedInStore + TestIngestHEC_EventsForwardedToQueue both passing. Benchmarks: 1.6M enqueue/s, 474K IPC/s, 231K S2S/s on CPU. main.go wires GPU queue via CUSPLUNK_GPU_QUEUE=1.
- **C3 (2026-04-15, survey):** Full R2 survey. R2-C1, R2-C2, R2-C4 code on disk but NOT committed to branches. R2-C3 (query executor/planner/gpu-kernels) NOT STARTED — this is the critical R2 gap blocking R3.

---

## Current Phase
**R2 in progress — C1/C4 complete (code on disk, uncommitted). C2 tiers on disk (uncommitted). C3 (query executor) NOT STARTED. R1-C2 (store skeleton) also on disk but uncommitted.**

## What's Complete
- [x] All specification documents (README, ARCHITECTURE, TECH_STACK, WORKPLAN, ROADMAP, TESTING, BETA, CONTRIBUTING)
- [x] 8 epic docs (`docs/epics/e1` through `e8`)
- [x] 5 ADRs (`docs/decisions/adr-001` through `adr-005`)
- [x] Checkpoint + memory bootstrapped (C1)
- [x] TESTING.md updated with no-GPU strategy (C5)

### R1-C4 — CI/CD + Dev Environment ✓ COMPLETE
- [x] `.github/workflows/ci.yml` — 5 jobs: unit-tests (Go+Rust+Python+Node, CPU), spl-compat, lint, integration-tests (GPU runner, epic/* only), e2e-tests (nightly GPU), benchmarks (weekly GPU)
- [x] `.github/workflows/release.yml` — tag → 7 Docker images built in parallel → GHCR → GitHub Release
- [x] `infra/docker/docker-compose.dev.yml` — CPU dev stack: mock-ingest (HEC+S2S stub), mock-store (in-memory+fixtures), PostgreSQL 16, Redis 7.2, Prometheus, Grafana. Sets `NUMBA_ENABLE_CUDASIM=1` + `CUDF_PANDAS_FALLBACK_MODE=1`
- [x] `infra/docker/mock-services/mock_ingest.py` — HEC HTTP + S2S stub (stdlib only, no GPU)
- [x] `infra/docker/mock-services/mock_store.py` — in-memory store, HTTP scan/write/reset API, preloads fixtures
- [x] `infra/postgres/init.sql` — full DB schema (users, tokens, indexes, saved_searches, alerts, cases, audit_log HMAC chain, detection_rules, dashboards, tenants)
- [x] `tests/fixtures/generate_fixtures.py` — deterministic generator (seed=42)
- [x] `tests/fixtures/events/windows_event_log_1000.json` — 1,000 Windows Security events
- [x] `tests/fixtures/events/firewall_100k.json` — 100,000 firewall events (~50 MB)
- [x] `tests/fixtures/events/firewall_sample.json` — 100-event fast CI subset
- [x] `tests/fixtures/spl/golden_results.json` — 50 SPL queries + expected output shapes
- [x] `tests/fixtures/sigma/test_rules/` — 10 Sigma rules (brute force, RDP scan, privilege escalation, data exfil, Pass-the-Hash, etc.)
- [x] `Makefile` — dev, dev-gpu, stop, test, test-int, test-e2e, bench, bench-ingest, bench-query, bench-store, lint (go/rust/py/ui), fixtures, clean, help
- [x] `scripts/setup-dev.sh` — automated dep check + installer (Go, Rust, Python, Node, Docker, optional GPU)
- [x] `docs/dev-setup.md` — full CPU path + GPU path dev guide

## What's In Progress

## What's Not Started (full backlog)

### R1 — Foundation (all 4 parallel, start NOW)
- [x] **C1 → R1**: Ingest protocol servers (Go) ✓ COMPLETE
  - `services/ingest/cmd/ingest/main.go` — entry point with graceful shutdown
  - `services/ingest/internal/s2s/` — S2S TCP server + frame decoder + handshake + ack
  - `services/ingest/internal/hec/` — HEC HTTP server (event/raw/ack/health endpoints)
  - `services/ingest/internal/syslog/` — RFC3164 + RFC5424 parsers, UDP+TCP+TLS listeners
  - `services/ingest/internal/queue/` — channel queue stub (100ms flush interval)
  - `services/ingest/internal/metrics/` — Prometheus metrics
  - `services/ingest/internal/config/` — YAML config loader with defaults
  - `services/ingest/go.mod` — all deps pinned
  - 58 tests passing, `go build/test/vet` all clean

- [~] **C2 → R1**: Store bucket format + gRPC skeleton (Rust) — CODE ON DISK, NOT COMMITTED
  - `services/store/src/bucket/` — BucketWriter, BucketReader, dict-encoding ✓
  - `services/store/src/bloom/` — bloom filter (xxhash) ✓
  - `services/store/src/proto/` — WriteRequest/ScanRequest proto defs ✓
  - `services/store/src/server/mod.rs` — tonic gRPC skeleton (541 lines) ✓
  - `libs/proto/store.proto` ✓
  - **Missing:** `cargo test` unverified (cargo not installed on dev machine), no branch committed

- [x] **C3 → R1**: SPL grammar (ANTLR4 + Python) ✓ COMPLETE
  - `libs/spl-parser/SPL.g4` — complete ANTLR4 grammar (1,162 lines, all SPL commands)
  - `libs/spl-parser/cusplunk/spl/parser.py` (1,053 lines), `ast.py` (536 lines), `visitor.py` (172 lines)
  - `libs/spl-parser/corpus/basic.txt` — 500 representative queries
  - **594 tests passing** (test_corpus.py + test_edge_cases.py + test_hypothesis.py)
  - Branch: `feat/r1-c3-spl-parser` (committed in libs/spl-parser/.git)

- [x] **C4 → R1**: CI/CD + dev environment ✓ COMPLETE — Branch: `feat/r1-c4-devenv`

### R2 — Core Engine (after R1 merged)
- [x] C1: GPU parse queue + cuDF ingest pipeline ✓ COMPLETE
  - `services/ingest/internal/gpuqueue/` — GPUQueue: Unix socket IPC, 10K/100ms batching, MaxInFlight=10 backpressure, 8 tests
  - `services/query/cusplunk/ingest/processor.py` — Python cuDF/pandas processor: parse_batch(), LZ4 compress_raw(), store gRPC Write(), 18 tests
  - `services/query/cusplunk/ingest/store_grpc.py` — gRPC Write client (lazy singleton channel)
  - `services/ingest/internal/store_client/` — Go gRPC StoreClient + NoOpStoreClient
  - `libs/proto/go/storepb/` — protoc-generated store.pb.go + store_grpc.pb.go
  - `services/ingest/integration_test.go` — 2 integration tests passing (build tag: integration)
  - `services/ingest/bench_test.go` — 3 benchmarks: GPUQueue, IPC, S2S
  - `cmd/ingest/main.go` — updated to wire GPUQueue when CUSPLUNK_GPU_QUEUE=1
- [~] C2: Hot/warm/cold tiers + retention engine — CODE ON DISK, NOT COMMITTED
  - `services/store/src/hot/` (346 lines), `warm/` (336), `cold/` (67 — skeletal), `retention/` (272)
  - **Missing:** full ScanRequest handler, `cargo test`, branch `feat/r2-c2-tiers`
- [ ] C3: GPU query executor (cuDF) + logical planner — NOT STARTED ⚠️ CRITICAL GAP
  - `services/query/cusplunk/planner/` — MISSING
  - `services/query/cusplunk/executor/` — MISSING
  - `libs/gpu-kernels/time_window_join.cu` — MISSING
  - **This is the only R2 component that has zero code on disk**
- [x] C4: Detection engine skeleton + Sigma loader ✓ COMPLETE (code on disk, uncommitted)
  - `services/detect/cusplunk/sigma/` — parser/compiler/evaluator/loader (1,095 lines, 7 tests)
  - `services/detect/cusplunk/normalize/` — Windows/Syslog/CEF normalizers (718 lines)
  - `services/detect/cusplunk/pipeline.py` — Morpheus skeleton (210 lines)
  - **Missing:** branch `feat/r2-c4-detect-skeleton`

### R3 — Integration (after R2 merged)
- [ ] C1: Bridge service + time-range router
- [ ] C2: Store replication (Raft/openraft) + bloom integration
- [ ] C3: Distributed query + scheduler + Redis cache
- [ ] C4: ML models (Triton) + alert pipeline + MITRE enrichment

### R4 — Platform (after R3 merged)
- [ ] C1: REST API + auth (Splunk-compatible endpoints)
- [ ] C2: SPL search UI + results table (Monaco + TanStack)
- [ ] C3: Dashboard builder + saved searches (ECharts)
- [ ] C4: Case management + admin UI + system health

### R5 — Enterprise + Scale (after R4 merged)
- [ ] C1: SSO (SAML 2.0 + OIDC) + multi-tenancy
- [ ] C2: Kubernetes operator + Helm chart
- [ ] C3: Benchmark suite + load tests (k6, vs Splunk/ClickHouse/Elastic)
- [ ] C4: Compliance reports + audit log + at-rest encryption

### R6 — Beta Prep (after R5 merged)
- [ ] C1: Splunk API compatibility + migration docs
- [ ] C2: Performance hardening (RMM tuning, plan cache)
- [ ] C3: Chaos tests (7 scenarios) + SRE runbooks + Grafana dashboards
- [ ] C4: Beta infrastructure + onboarding automation

---

## Key Decisions (locked, no changes without ADR)

| Decision | Choice | Rationale |
|---|---|---|
| Storage format | Columnar Arrow (ADR-001) | GPU-compatible, memory bandwidth maximized |
| SPL parser | ANTLR4 (ADR-002) | Maintainable grammar, visitor pattern |
| GPU executor | cuDF (ADR-003) | Native RAPIDS, Python API |
| Ingest language | Go (ADR-004) | 10K concurrent TCP, fast binary parsing |
| Store language | Rust (ADR-005) | Zero GC on write path, memory safety |

## Architecture Quick Reference

- Ingest port 9997 (S2S), 8088 (HEC), 514 (syslog), 8089 (REST API), 50051 (gRPC internal)
- Storage tiers: Hot = GPU memory (last 5 min), Warm = NVMe/GDS (last 30 days), Cold = S3 (30-90 days)
- Bridge: federates queries to Splunk REST for pre-cutover data, auto-sunsets at day 90
- GPU minimum: NVIDIA A10G (24 GB VRAM), CUDA CC 8.0+
- All service communication: gRPC (protobuf)
- Metadata: PostgreSQL 16. Cache: Redis 7.2+. Metrics: Prometheus. Traces: OpenTelemetry.

## File Map

```
cuSplunk/
├── ARCHITECTURE.md     ← READ FIRST — full system diagram, data flows, SPL mapping
├── TECH_STACK.md       ← READ SECOND — locked versions + rationale
├── WORKPLAN.md         ← Exact deliverables per Claude per round
├── ROADMAP.md          ← Milestones M1–M6
├── TESTING.md          ← Full testing pyramid, CI pipeline, coverage gates
├── BETA.md             ← Beta phases, customer profile, success metrics
├── CONTRIBUTING.md     ← Branching, PR rules, commit convention, dev setup
├── docs/
│   ├── epics/          ← e1-ingest.md through e8-scale.md (story details)
│   └── decisions/      ← ADR-001 through ADR-005 (locked tech choices)
├── services/           ← All service directories (empty, ready to implement)
└── infra/docker/       ← docker-compose.dev.yml, docker-compose.gpu.yml
```

## CI/CD Rules (enforce from R1 onward)
- `make test` must pass before any PR
- Coverage gates hard-fail CI (ingest 80%, store 85%, query 75%, spl-parser 90%)
- Integration tests run on GPU self-hosted runner on PR merge to epic branches
- SPL compat test (10K query corpus) blocks any PR to query service

## For Next Claude (C2+)
1. Read `ARCHITECTURE.md` and `TECH_STACK.md` fully
2. Read `WORKPLAN.md` to find your round assignment
3. Read the relevant epic doc(s) in `docs/epics/`
4. Create your feature branch
5. Write tests first, implement, open PR to epic branch
6. Update this CHECKPOINT.md: check off completed items, add your handoff note
