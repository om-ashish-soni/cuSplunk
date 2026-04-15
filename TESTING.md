# cuSplunk — Testing Strategy

## Testing Pyramid

```
                    ┌─────────────────┐
                    │    E2E Tests     │  Playwright — 20 critical user flows
                    │   (slow, few)    │  Run: nightly + pre-release
                    ├─────────────────┤
                  ┌─┤  Integration     ├─┐
                  │ │     Tests        │ │  Real GPU + real services
                  │ │  (medium, some)  │ │  Run: every PR merge to epic branch
                  │ └─────────────────┘ │
                ┌─┴─────────────────────┴─┐
                │      Unit Tests          │  Per-service, mocked deps
                │    (fast, many)          │  Run: every commit, every PR
                └──────────────────────────┘
                ┌──────────────────────────┐
                │   Performance Tests       │  Benchmarks vs Splunk/ClickHouse
                │   (infra, scheduled)      │  Run: weekly + before milestone
                └──────────────────────────┘
                ┌──────────────────────────┐
                │   SPL Compatibility       │  10,000-query corpus
                │   (regression, critical)  │  Run: every PR to query service
                └──────────────────────────┘
```

---

## Layer 1: Unit Tests

### Go services (ingest, bridge, api)

**Framework:** `testing` (stdlib) + `testify`  
**Coverage target:** 80% per package  
**Run:** `go test ./...`

```go
// Example: S2S protocol frame parser
func TestS2SFrameParse_ValidFrame(t *testing.T) { ... }
func TestS2SFrameParse_TruncatedFrame(t *testing.T) { ... }
func TestS2SFrameParse_MalformedHeader(t *testing.T) { ... }
func TestHECTokenValidator_ValidToken(t *testing.T) { ... }
func TestTimeRangeRouter_BeforeCutover(t *testing.T) { ... }
func TestTimeRangeRouter_AfterCutover(t *testing.T) { ... }
func TestTimeRangeRouter_SpanningCutover(t *testing.T) { ... }
```

**Mocks:** `gomock` for gRPC clients (store, bridge)  
**Table-driven tests required** for all protocol parsers

### Rust (store)

**Framework:** `cargo test` + `criterion` for benchmarks  
**Coverage target:** 85% (storage correctness is critical)  
**Run:** `cargo test`, `cargo bench`

```rust
#[test] fn test_bucket_write_read_roundtrip() { ... }
#[test] fn test_bloom_filter_no_false_negatives() { ... }
#[test] fn test_retention_evicts_expired_buckets() { ... }
#[test] fn test_raft_leader_election_on_node_failure() { ... }
#[test] fn test_dict_encoding_roundtrip() { ... }
```

**Property tests:** `proptest` crate — bloom filter false positive rate, bucket time range invariants

### Python (query, detect)

**Framework:** `pytest` + `hypothesis`  
**Coverage target:** 75%  
**Run:** `pytest --cov`

```python
# SPL parser unit tests
def test_parse_stats_count_by(): ...
def test_parse_eval_expression(): ...
def test_parse_rex_named_group(): ...
def test_parse_subsearch(): ...
def test_parse_macro_expansion(): ...

# GPU executor unit tests (uses cuDF)
def test_filter_equals(): ...
def test_groupby_count(): ...
def test_time_window_join_basic(): ...
def test_timechart_span_1h(): ...

# Detection
def test_sigma_rule_loads(): ...
def test_sigma_rule_matches_event(): ...
def test_sigma_rule_no_match(): ...
```

**Hypothesis:** Property-based tests for SPL parser — generate random valid SPL, verify no parse crash

### UI (React / Next.js)

**Framework:** `vitest` + `@testing-library/react`  
**Coverage target:** 70% (UI components)  
**Run:** `npm test`

```typescript
test('SPL search bar submits on Enter', ...)
test('Time range picker defaults to last 24h', ...)
test('Results table renders 10k rows without lag', ...)
test('Dashboard panel saves SPL correctly', ...)
test('Alert severity badge renders correct color', ...)
```

---

## Layer 2: Integration Tests

**Location:** `tests/integration/`  
**Requirement:** Real GPU (CI uses GPU runner), real Docker Compose stack  
**Run:** `make integration-test` (on PR merge to epic branch)

### Integration test scenarios

#### Ingest ↔ Store
```
TestIngestS2S_EventsArrivedInStore
  → start S2S server + store service
  → connect mock Universal Forwarder
  → send 10,000 events
  → query store via gRPC ScanRequest
  → assert: all events present, _time correct, _raw intact
```

#### Query ↔ Store
```
TestQueryStatsCountBy
  → pre-load store with 1M synthetic events
  → submit SPL: index=test | stats count by host
  → assert: correct counts, GPU execution plan used
  
TestQueryTimeWindowJoin
  → load correlated process + network events
  → submit: | transaction pid maxspan=5m
  → assert: correct session boundaries
```

#### Bridge ↔ Splunk REST mock
```
TestBridgeFanOut_SpanningCutover
  → start mock Splunk REST server
  → submit query spanning cutover date
  → assert: both backends called, results merged, deduped
  
TestBridgeAutoSunset
  → set cutover_date = now - 91 days
  → verify bridge routes all queries to GPU only
```

#### Detect ↔ Ingest stream
```
TestSigmaDetection_FailedLogin
  → load sigma rule: multiple failed logins
  → inject 10 EventCode=4625 events for same user
  → assert: alert fired, MITRE T1110 tagged
```

---

## Layer 3: SPL Compatibility Test Suite

**Location:** `tests/spl-compat/`  
**Corpus:** 10,000 real SPL queries collected from:
- Splunk Community (public forum posts)
- SigmaHQ Splunk backends
- Splunk Security Essentials app
- cuSplunk team's own Splunk instances

**Test structure:**
```python
# tests/spl-compat/test_corpus.py
@pytest.mark.parametrize("spl", load_corpus("corpus/splunk_community.txt"))
def test_spl_parses_without_error(spl):
    ast = SPLParser().parse(spl)
    assert ast is not None

@pytest.mark.parametrize("spl,expected", load_golden("corpus/golden_results.json"))  
def test_spl_produces_correct_result(spl, expected, store_with_test_data):
    result = execute_spl(spl, store_with_test_data)
    assert result == expected
```

**Golden dataset:** 500 SPL queries with known correct results, run against real Splunk to generate expected output, stored in `tests/spl-compat/corpus/golden_results.json`

**CI gate:** 0 parse errors on full corpus, 100% match on golden dataset

---

## Layer 4: Performance Tests

**Location:** `benchmarks/`  
**Schedule:** Weekly (GitHub Actions cron) + before every milestone

### Micro-benchmarks (per service)

```bash
# Store write throughput
cargo bench --bench store_write_throughput

# GPU query: stats count by (1B events)
python -m pytest benchmarks/query/test_stats_benchmark.py -v

# Ingest: S2S events/sec
go test -bench=BenchmarkS2SIngest -benchtime=30s ./services/ingest/...
```

### Macro-benchmarks (vs competitors)

**Script:** `benchmarks/compare.sh`

Runs 8 canonical queries against:
- cuSplunk (this project, GPU)
- Splunk 9.x (same hardware, CPU)
- ClickHouse 24.x (same hardware, CPU)
- Elasticsearch 8.x (same hardware, CPU)

```
Dataset: 10B synthetic log events (firewall, auth, DNS, web proxy)
Hardware: identical (specified in benchmarks/HARDWARE.md)
Metric: wall time p50/p95, GPU time, memory used
Output: benchmarks/results/YYYY-MM-DD.md (committed to repo)
```

### Load test

**Tool:** k6  
**Script:** `benchmarks/load/k6-script.js`

```javascript
// 1,000 concurrent users
// 70% dashboard refresh (same SPL every 30s)
// 20% ad-hoc search
// 10% large export
export const options = {
  scenarios: {
    dashboard: { executor: 'constant-vus', vus: 700, duration: '10m' },
    adhoc: { executor: 'constant-vus', vus: 200, duration: '10m' },
    export: { executor: 'constant-vus', vus: 100, duration: '10m' },
  },
  thresholds: {
    'http_req_duration{scenario:dashboard}': ['p(95)<2000'],
    'http_req_duration{scenario:adhoc}': ['p(95)<10000'],
  },
};
```

---

## Layer 5: E2E Tests

**Framework:** Playwright  
**Location:** `tests/e2e/`  
**Run:** nightly + before release

### Critical user flows (20 flows)

```typescript
test('E2E-01: User logs in and runs a SPL search', ...)
test('E2E-02: Search returns correct results within 5s', ...)
test('E2E-03: Create dashboard with timechart panel', ...)
test('E2E-04: Saved search triggers alert on threshold breach', ...)
test('E2E-05: Alert creates case, analyst closes it', ...)
test('E2E-06: Admin creates user with Power User role', ...)
test('E2E-07: Universal Forwarder connection accepted (S2S)', ...)
test('E2E-08: HEC POST delivers event, appears in search', ...)
test('E2E-09: Query spanning bridge cutover returns merged results', ...)
test('E2E-10: Sigma rule fires alert on matching event', ...)
test('E2E-11: MITRE ATT&CK tag appears on alert', ...)
test('E2E-12: Dashboard export to PDF', ...)
test('E2E-13: Index retention purges events after 90 days', ...)
test('E2E-14: SSO login via SAML (mock IdP)', ...)
test('E2E-15: API token auth works for REST API', ...)
test('E2E-16: Splunk Python SDK job.create() works', ...)
test('E2E-17: 100 concurrent users load dashboard <3s', ...)
test('E2E-18: Node failure — queries degrade gracefully', ...)
test('E2E-19: GPU OOM — search returns error, ingest continues', ...)
test('E2E-20: Bridge auto-sunset fires, admin notified', ...)
```

---

## Layer 6: Chaos Tests

**Framework:** `chaostoolkit` + `chaosk8s`  
**Location:** `tests/chaos/`  
**Run:** pre-milestone, manually approved

```yaml
# tests/chaos/experiments/indexer-node-failure.yaml
title: Kill one indexer node
method:
  - type: action
    name: kill-indexer-2
    provider:
      type: python
      module: chaosk8s.node.actions
      func: delete_nodes
      arguments:
        label_selector: "cusplunk.io/role=indexer"
        count: 1
rollbacks:
  - restart killed node
steady-state-hypothesis:
  - query latency p95 < 10s (degraded but not down)
  - ingest rate drops < 30%
  - no data loss on re-ingestion check
```

Scenarios:
1. Kill 1 indexer node
2. Exhaust GPU memory (OOM)
3. Fill NVMe to 95%
4. Network partition between nodes
5. Splunk bridge timeout (500ms)
6. Redis cache down
7. Triton inference server crash

---

## CI/CD Pipeline (GitHub Actions)

```yaml
# .github/workflows/ci.yml

on: [push, pull_request]

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - go test ./...          # ingest, bridge, api
      - cargo test             # store
      - pytest --cov           # query, detect
      - npm test               # ui

  spl-compat:
    runs-on: ubuntu-latest
    steps:
      - pytest tests/spl-compat/  # 10K query corpus

  integration-tests:
    runs-on: [self-hosted, gpu]   # GPU runner required
    if: github.ref == 'refs/heads/epic/*' || github.ref == 'refs/heads/main'
    steps:
      - docker-compose up -d
      - pytest tests/integration/
      - docker-compose down

  e2e-tests:
    runs-on: [self-hosted, gpu]
    if: github.ref == 'refs/heads/main'
    steps:
      - docker-compose up -d
      - playwright test
      - docker-compose down

  benchmarks:
    runs-on: [self-hosted, gpu]
    if: github.event_name == 'schedule'   # weekly cron
    steps:
      - bash benchmarks/compare.sh
      - git commit benchmarks/results/
```

**Self-hosted GPU runner:** AWS `g5.xlarge` (A10G) registered as GitHub Actions runner  
Cost: ~$0.80/hr, runs ~2hr/week = ~$6/week for GPU CI

---

## Coverage Gates (CI enforced)

| Service | Minimum Coverage | Fails CI if below |
|---|---|---|
| `services/ingest` | 80% | Yes |
| `services/store` | 85% | Yes |
| `services/query` | 75% | Yes |
| `services/detect` | 70% | Yes |
| `services/bridge` | 80% | Yes |
| `libs/spl-parser` | 90% | Yes — parser correctness is critical |
| `ui` | 70% | Warning only |

## Golden Dataset Maintenance

When adding new SPL features:
1. Write the SPL query
2. Run it against real Splunk 9.x
3. Save expected output to `tests/spl-compat/corpus/golden_results.json`
4. cuSplunk must produce identical output

This is our Splunk compatibility contract. Never break the golden dataset.
