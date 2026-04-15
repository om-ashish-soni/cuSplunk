.PHONY: dev dev-gpu stop test test-int test-e2e bench bench-ingest bench-query \
        lint lint-go lint-rust lint-py lint-ui fixtures clean help

# ──────────────────────────────────────────────────────────────────
# Dev stacks
# ──────────────────────────────────────────────────────────────────

## Start CPU-only dev stack (no GPU required)
dev:
	docker compose -f infra/docker/docker-compose.dev.yml up -d
	@echo ""
	@echo "  cuSplunk dev stack running:"
	@echo "    HEC ingest  → http://localhost:8088/services/collector/health"
	@echo "    Mock store  → http://localhost:8081/health"
	@echo "    PostgreSQL  → localhost:5432  (user: cusplunk / pass: cusplunk_dev)"
	@echo "    Redis       → localhost:6379"
	@echo "    Prometheus  → http://localhost:9091"
	@echo "    Grafana     → http://localhost:3001  (admin / cusplunk)"
	@echo ""

## Start full GPU stack (requires NVIDIA GPU + nvidia-container-toolkit)
dev-gpu:
	@command -v nvidia-smi >/dev/null 2>&1 || { echo "ERROR: nvidia-smi not found — GPU required for dev-gpu target"; exit 1; }
	docker compose -f infra/docker/docker-compose.gpu.yml up -d
	@echo ""
	@echo "  cuSplunk GPU stack running (GPU: $$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1))"
	@echo "    S2S ingest  → localhost:9997"
	@echo "    HEC ingest  → http://localhost:8088"
	@echo "    REST API    → http://localhost:8089"
	@echo "    Grafana     → http://localhost:3001  (admin / cusplunk)"
	@echo ""

## Stop all stacks
stop:
	docker compose -f infra/docker/docker-compose.dev.yml down -v 2>/dev/null || true
	docker compose -f infra/docker/docker-compose.gpu.yml down -v 2>/dev/null || true

# ──────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────

## Run all unit tests (no GPU required)
## Missing toolchains are skipped with a warning — does not fail.
test:
	@echo "==> Go unit tests"
	@if command -v go >/dev/null 2>&1; then \
		for svc in ingest bridge api; do \
			dir="services/$$svc"; \
			if [ -f "$$dir/go.mod" ]; then \
				echo "--- $$dir"; \
				(cd "$$dir" && go test ./... -v -race -count=1 -timeout 120s); \
			else \
				echo "--- $$dir: skipped (no go.mod yet)"; \
			fi; \
		done; \
	else \
		echo "--- Go: skipped (go not installed)"; \
	fi

	@echo ""
	@echo "==> Rust unit tests"
	@if command -v cargo >/dev/null 2>&1; then \
		if [ -f "services/store/Cargo.toml" ]; then \
			(cd services/store && cargo test --all-features -- --test-threads=4); \
		else \
			echo "--- services/store: skipped (no Cargo.toml yet)"; \
		fi; \
	else \
		echo "--- Rust: skipped (cargo not installed)"; \
	fi

	@echo ""
	@echo "==> Python unit tests (CPU-only, skip gpu marker)"
	@if command -v python3 >/dev/null 2>&1 && command -v pytest >/dev/null 2>&1; then \
		for dir in libs/spl-parser services/query services/detect; do \
			if [ -d "$$dir/tests" ]; then \
				echo "--- $$dir"; \
				pytest "$$dir/tests" -v --tb=short -m "not gpu" -q; \
			else \
				echo "--- $$dir: skipped (no tests/ yet)"; \
			fi; \
		done; \
	else \
		echo "--- Python: skipped (python3/pytest not installed)"; \
	fi

	@echo ""
	@echo "==> UI unit tests (vitest)"
	@if command -v node >/dev/null 2>&1 && [ -f "ui/package.json" ]; then \
		(cd ui && npx vitest run --reporter=verbose); \
	else \
		echo "--- ui/: skipped (node not installed or no package.json yet)"; \
	fi
	@echo ""
	@echo "All unit tests done."

## Run integration tests (requires dev stack running: make dev)
test-int:
	@echo "==> Integration tests (expects dev stack on localhost)"
	@if [ -d "tests/integration" ]; then \
		pytest tests/integration/ -v --tb=short -m "integration" --timeout=300; \
	else \
		echo "--- tests/integration not yet present"; \
	fi

## Run E2E tests (requires GPU stack running: make dev-gpu)
test-e2e:
	@echo "==> E2E tests (expects GPU stack on localhost)"
	@if [ -d "tests/e2e" ] && [ -f "ui/package.json" ]; then \
		(cd ui && npx playwright test tests/e2e/ --reporter=list); \
	else \
		echo "--- tests/e2e not yet present"; \
	fi

# ──────────────────────────────────────────────────────────────────
# Benchmarks
# ──────────────────────────────────────────────────────────────────

## Run all benchmarks (GPU required)
bench: bench-ingest bench-query bench-store

## Ingest throughput benchmark (events/sec target: 1M on A10G)
bench-ingest:
	@echo "==> Ingest benchmark"
	@if [ -f "benchmarks/bench_ingest.py" ]; then \
		python benchmarks/bench_ingest.py; \
	else \
		echo "--- benchmarks/bench_ingest.py not yet present (R2-C1)"; \
	fi

## Query benchmark (stats count by src_ip over 1B events, target: <2s)
bench-query:
	@echo "==> Query benchmark"
	@if [ -f "benchmarks/bench_query.py" ]; then \
		python benchmarks/bench_query.py; \
	else \
		echo "--- benchmarks/bench_query.py not yet present (R2-C3)"; \
	fi

## Rust criterion store benchmarks
bench-store:
	@echo "==> Store benchmark (criterion)"
	@if [ -f "services/store/Cargo.toml" ]; then \
		mkdir -p benchmarks/results; \
		(cd services/store && cargo bench 2>&1 | tee ../../benchmarks/results/$$(date +%Y-%m-%d)-store.txt); \
	else \
		echo "--- services/store/Cargo.toml not yet present"; \
	fi

# ──────────────────────────────────────────────────────────────────
# Lint
# ──────────────────────────────────────────────────────────────────

## Run all linters
lint: lint-go lint-rust lint-py lint-ui

## Go lint (golangci-lint)
lint-go: _check-go
	@echo "==> golangci-lint"
	@if command -v golangci-lint >/dev/null 2>&1; then \
		golangci-lint run --timeout=5m; \
	else \
		echo "golangci-lint not installed — run: go install github.com/golangci/golangci-lint/cmd/golangci-lint@v1.59.0"; \
	fi

## Rust lint (clippy + fmt check)
lint-rust: _check-rust
	@echo "==> cargo clippy"
	@if [ -f "services/store/Cargo.toml" ]; then \
		(cd services/store && cargo clippy --all-targets --all-features -- -D warnings); \
		(cd services/store && cargo fmt --check); \
	else \
		echo "--- services/store: skipped"; \
	fi

## Python lint (ruff)
lint-py: _check-python
	@echo "==> ruff"
	@command -v ruff >/dev/null 2>&1 || pip install ruff -q
	@for dir in services/query services/detect libs/spl-parser; do \
		[ -d "$$dir" ] && ruff check "$$dir" --ignore E501 || true; \
	done

## UI lint (eslint)
lint-ui: _check-node
	@echo "==> eslint"
	@if [ -f "ui/package.json" ]; then \
		(cd ui && npm ci --silent && npx eslint src --max-warnings=0); \
	else \
		echo "--- ui/: skipped"; \
	fi

# ──────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────

## Regenerate test fixture files
fixtures: _check-python
	@echo "==> Generating test fixtures"
	python tests/fixtures/generate_fixtures.py

# ──────────────────────────────────────────────────────────────────
# Clean
# ──────────────────────────────────────────────────────────────────

## Remove generated build artifacts (not fixtures)
clean:
	@echo "==> Clean"
	@for svc in ingest bridge api; do \
		[ -f "services/$$svc/go.mod" ] && (cd "services/$$svc" && go clean ./...) || true; \
	done
	@[ -f "services/store/Cargo.toml" ] && (cd services/store && cargo clean) || true
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -name "*.pyc" -delete 2>/dev/null || true
	@[ -d "ui/.next" ] && rm -rf ui/.next || true
	@[ -d "ui/node_modules" ] && rm -rf ui/node_modules || true
	@echo "Clean done."

# ──────────────────────────────────────────────────────────────────
# Internal: prerequisite checks
# ──────────────────────────────────────────────────────────────────

_check-go:
	@command -v go >/dev/null 2>&1 || { echo "ERROR: go not found — install Go 1.22+"; exit 1; }
	@go version | grep -qE "go1\.(2[2-9]|[3-9][0-9])" || { echo "ERROR: Go 1.22+ required (got $$(go version))"; exit 1; }

_check-rust:
	@command -v cargo >/dev/null 2>&1 || { echo "ERROR: cargo not found — install Rust 1.80+"; exit 1; }

_check-python:
	@command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found — install Python 3.11+"; exit 1; }
	@command -v pytest >/dev/null 2>&1 || pip install pytest -q

_check-node:
	@command -v node >/dev/null 2>&1 || { echo "ERROR: node not found — install Node.js 20+"; exit 1; }

# ──────────────────────────────────────────────────────────────────
# Help
# ──────────────────────────────────────────────────────────────────

## Show this help
help:
	@echo "cuSplunk — Makefile targets"
	@echo ""
	@echo "  Dev:"
	@echo "    make dev          Start CPU dev stack (no GPU)"
	@echo "    make dev-gpu      Start GPU dev stack"
	@echo "    make stop         Stop all stacks"
	@echo ""
	@echo "  Test:"
	@echo "    make test         Run all unit tests (no GPU)"
	@echo "    make test-int     Run integration tests (dev stack required)"
	@echo "    make test-e2e     Run E2E browser tests (GPU stack required)"
	@echo ""
	@echo "  Bench:"
	@echo "    make bench        Run all benchmarks (GPU required)"
	@echo "    make bench-ingest Ingest throughput benchmark"
	@echo "    make bench-query  Query latency benchmark"
	@echo "    make bench-store  Rust store criterion benchmarks"
	@echo ""
	@echo "  Lint:"
	@echo "    make lint         Run all linters"
	@echo "    make lint-go      golangci-lint"
	@echo "    make lint-rust    cargo clippy + fmt"
	@echo "    make lint-py      ruff"
	@echo "    make lint-ui      eslint"
	@echo ""
	@echo "  Other:"
	@echo "    make fixtures     Regenerate test fixture data"
	@echo "    make clean        Remove build artifacts"
