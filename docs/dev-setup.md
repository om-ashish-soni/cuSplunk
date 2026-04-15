# cuSplunk — Local Dev Setup

Two paths: **CPU path** (unit tests, mock services, no GPU) and **GPU path** (integration + benchmarks, requires NVIDIA A10G+).

---

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| Go | 1.22+ | https://go.dev/dl/ |
| Rust | 1.80+ | `curl https://sh.rustup.rs -sSf \| sh` |
| Python | 3.11+ | https://python.org/downloads/ |
| Node.js | 20+ | https://nodejs.org/en/download |
| Docker + Compose | 26+ | https://docs.docker.com/engine/install/ |
| NVIDIA GPU | A10G+ (GPU path only) | CUDA 12.4+, driver 535.104+ |

Run the automated installer to check everything at once:

```bash
bash scripts/setup-dev.sh          # CPU path check
bash scripts/setup-dev.sh --gpu    # CPU + GPU check
```

---

## CPU Path (no GPU required)

This path runs unit tests and the mock dev stack. No GPU needed.

### 1. Install dependencies

```bash
# Python test deps
pip install pytest pytest-cov hypothesis pyyaml stix2 \
            antlr4-python3-runtime==4.13 ruff

# Generate fixture data (creates tests/fixtures/events/*.json)
make fixtures
```

### 2. Start the dev stack

```bash
make dev
```

Services started:

| Service | URL / Address | Notes |
|---|---|---|
| mock-ingest (HEC) | http://localhost:8088 | Accepts HEC events, writes to log file |
| mock-ingest (S2S) | localhost:9997 | Stub: accepts forwarder connections, ACKs |
| mock-store | http://localhost:8081 | In-memory store, pre-loaded with fixtures |
| PostgreSQL | localhost:5432 | DB: `cusplunk` / User: `cusplunk` / Pass: `cusplunk_dev` |
| Redis | localhost:6379 | No auth in dev |
| Prometheus | http://localhost:9091 | Metrics |
| Grafana | http://localhost:3001 | admin / cusplunk |

Verify the stack is healthy:

```bash
curl http://localhost:8088/services/collector/health     # HEC
curl http://localhost:8081/health                        # mock store
curl -X POST http://localhost:8081/scan \
  -H 'Content-Type: application/json' \
  -d '{"index":"firewall","limit":5}'                   # scan fixture data
```

### 3. Send a test event

```bash
# HEC — JSON event
curl -X POST http://localhost:8088/services/collector/event \
  -H 'Authorization: Splunk dev-token-anything-works' \
  -H 'Content-Type: application/json' \
  -d '{"event": {"src_ip": "1.2.3.4", "action": "deny", "dst_port": 22}, "index": "firewall"}'

# Check it arrived in mock-store
curl -X POST http://localhost:8081/scan \
  -H 'Content-Type: application/json' \
  -d '{"index":"firewall","limit":10}'
```

### 4. Run unit tests

```bash
make test
```

Individual service tests:

```bash
# Go (once services/ingest/go.mod exists)
cd services/ingest && go test ./... -v -race

# Rust (once services/store/Cargo.toml exists)
cd services/store && cargo test --all-features

# Python — SPL parser (once libs/spl-parser exists)
pytest libs/spl-parser/tests/ -v

# UI (once ui/package.json exists)
cd ui && npx vitest run
```

### 5. Lint

```bash
make lint          # all linters
make lint-go       # golangci-lint only
make lint-rust     # cargo clippy + fmt
make lint-py       # ruff
make lint-ui       # eslint
```

### 6. Stop the stack

```bash
make stop
```

---

## GPU Path (requires NVIDIA A10G+)

The GPU path runs the full production stack with real GPU acceleration.

### GPU requirements

- NVIDIA GPU: A10G (24 GB VRAM) minimum; A100 80GB recommended
- CUDA Compute Capability: 8.0+
- CUDA Toolkit: 12.4+
- NVIDIA Driver: 535.104+
- nvidia-container-toolkit: 1.14+

Verify:

```bash
nvidia-smi                    # driver + GPU info
nvidia-ctk --version          # container toolkit
bash scripts/setup-dev.sh --gpu
```

### Install GPU Python packages

```bash
pip install cudf-cu12==24.10.* cuml-cu12==24.10.*
# Full RAPIDS stack (optional):
# pip install rapids-morpheus tritonclient[grpc]==2.45.*
```

### Start the GPU stack

```bash
make dev-gpu
```

This starts all services with GPU passthrough (uses `docker-compose.gpu.yml`).

### Run integration tests

Integration tests require the dev stack running and (for GPU tests) the GPU stack:

```bash
make dev       # or make dev-gpu for GPU integration tests
make test-int
```

### Run benchmarks

```bash
make bench-ingest   # target: >500K events/sec on A10G (R2)
make bench-query    # target: stats count by src_ip over 1B events <2s (R2)
make bench-store    # Rust criterion benchmarks
```

Results land in `benchmarks/results/`.

---

## Test Fixtures

Fixtures are pre-generated deterministic datasets for CI and unit tests.

| File | Contents | Size |
|---|---|---|
| `tests/fixtures/events/windows_event_log_1000.json` | 1,000 Windows Security events (4624/4625/4688…) | ~480 KB |
| `tests/fixtures/events/firewall_100k.json` | 100,000 firewall events (allow/deny/drop) | ~50 MB |
| `tests/fixtures/events/firewall_sample.json` | 100 firewall events (fast CI subset) | ~50 KB |
| `tests/fixtures/spl/golden_results.json` | 50 SPL queries + expected output shapes | — |
| `tests/fixtures/sigma/test_rules/` | 10 Sigma detection rules | — |

Regenerate:

```bash
make fixtures
# or directly:
python tests/fixtures/generate_fixtures.py
```

Fixture data uses `SEED=42` for reproducibility.

---

## Repository Structure (R1 layout)

```
cuSplunk/
├── .github/workflows/
│   ├── ci.yml          ← Unit tests, SPL compat, lint (every push)
│   │                      Integration tests (epic/* merges, GPU runner)
│   │                      E2E tests (nightly, GPU runner)
│   │                      Benchmarks (weekly, GPU runner)
│   └── release.yml     ← Tag → build + push Docker images to GHCR
├── services/
│   ├── ingest/         ← Go — S2S + HEC + Syslog (R1-C1)
│   ├── store/          ← Rust + CUDA — columnar storage (R1-C2)
│   ├── query/          ← Python + cuDF — GPU query engine (R2-C3)
│   ├── detect/         ← Python + Morpheus — detection (R2-C4)
│   ├── bridge/         ← Go — Splunk federation (R3-C1)
│   └── api/            ← Go — REST + gRPC gateway (R4-C1)
├── libs/
│   └── spl-parser/     ← ANTLR4 SPL grammar + Python AST (R1-C3)
├── ui/                 ← Next.js 14 + React 18 (R4-C2+)
├── tests/
│   ├── fixtures/       ← Shared test data (this round)
│   ├── integration/    ← Integration tests (R3+)
│   ├── e2e/            ← Playwright E2E (R4+)
│   └── spl-compat/     ← SPL compatibility corpus (R2-C3)
├── infra/
│   ├── docker/
│   │   ├── docker-compose.dev.yml   ← CPU dev stack (this round)
│   │   ├── docker-compose.gpu.yml   ← GPU production stack
│   │   └── mock-services/           ← Mock ingest + store Python servers
│   ├── postgres/
│   │   └── init.sql    ← DB schema (applied on first container start)
│   └── k8s/            ← Helm + operator (R5-C2)
├── benchmarks/
│   └── results/        ← Benchmark output (weekly CI run)
├── docs/
│   └── dev-setup.md    ← This file
├── scripts/
│   └── setup-dev.sh    ← Automated dependency installer + verifier
└── Makefile            ← dev / test / lint / bench targets
```

---

## CI Pipeline

Every push/PR triggers (no GPU required):

| Job | When | Runner |
|---|---|---|
| `unit-tests` | Every push/PR | ubuntu-22.04 |
| `spl-compat` | Every push/PR | ubuntu-22.04 |
| `lint` | Every push/PR | ubuntu-22.04 |
| `integration-tests` | Push to `epic/*` | self-hosted GPU |
| `e2e-tests` | Nightly (02:00 UTC) | self-hosted GPU |
| `benchmarks` | Weekly (Sun 04:00 UTC) | self-hosted GPU |

Coverage gates (enforced from R2 onward):

| Service | Min coverage |
|---|---|
| ingest | 80% |
| store | 85% |
| query | 75% |
| spl-parser | 90% |

---

## Commit + Branch Convention

```
feat/<scope>: short description
fix/<scope>: short description
test/<scope>: short description
docs/<scope>: short description
```

Branch naming per WORKPLAN:

```
feat/r1-c1-protocols      # R1, Claude 1
feat/r1-c2-store-skeleton # R1, Claude 2
feat/r1-c3-spl-parser     # R1, Claude 3
feat/r1-c4-devenv         # R1, Claude 4 (this branch)
```

PRs open to the epic branch (`epic/e1-ingest`, etc.), not `main`.
`main` only receives merge commits after a full round is reviewed and green.

See [CONTRIBUTING.md](../CONTRIBUTING.md) for full branching rules.
