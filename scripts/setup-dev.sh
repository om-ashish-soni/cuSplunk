#!/usr/bin/env bash
# setup-dev.sh — Install all cuSplunk dev dependencies and verify the environment.
#
# Usage: bash scripts/setup-dev.sh [--gpu]
#
# Flags:
#   --gpu   Also verify GPU / CUDA / nvidia-container-toolkit setup
#
# Supports: Ubuntu 22.04+, Debian 12+, macOS 13+ (CPU path only on macOS)

set -euo pipefail

GPU=false
for arg in "$@"; do
  [[ "$arg" == "--gpu" ]] && GPU=true
done

OS="$(uname -s)"
ARCH="$(uname -m)"

# ── Colors ────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "  ${GREEN}✓${RESET} $*"; }
warn() { echo -e "  ${YELLOW}!${RESET} $*"; }
fail() { echo -e "  ${RED}✗${RESET} $*"; ERRORS=$((ERRORS+1)); }
info() { echo -e "  ${BLUE}→${RESET} $*"; }
ERRORS=0

echo -e "\n${BOLD}cuSplunk Dev Environment Setup${RESET}"
echo    "  OS: $OS  Arch: $ARCH  GPU mode: $GPU"
echo    "  ───────────────────────────────────────────────────────"

# ── 1. Go 1.22+ ──────────────────────────────────────────────────
echo -e "\n${BOLD}[1/7] Go${RESET}"
if command -v go &>/dev/null; then
  GO_VER="$(go version | awk '{print $3}')"
  GO_MINOR="$(echo "$GO_VER" | grep -oP '(?<=go1\.)\d+')"
  if [[ "${GO_MINOR:-0}" -ge 22 ]]; then
    ok "Go $GO_VER"
  else
    warn "Go $GO_VER found but 1.22+ required"
    info "Install: https://go.dev/dl/"
  fi
else
  fail "Go not found"
  if [[ "$OS" == "Linux" ]]; then
    info "Install: wget https://go.dev/dl/go1.22.4.linux-amd64.tar.gz && sudo tar -C /usr/local -xzf go*.tar.gz"
    info "Then add /usr/local/go/bin to PATH"
  elif [[ "$OS" == "Darwin" ]]; then
    info "Install: brew install go"
  fi
fi

# ── 2. Rust 1.80+ ─────────────────────────────────────────────────
echo -e "\n${BOLD}[2/7] Rust + Cargo${RESET}"
if command -v cargo &>/dev/null; then
  RUST_VER="$(rustc --version | awk '{print $2}')"
  RUST_MINOR="$(echo "$RUST_VER" | cut -d. -f2)"
  if [[ "${RUST_MINOR:-0}" -ge 80 ]]; then
    ok "Rust $RUST_VER"
  else
    warn "Rust $RUST_VER found but 1.80+ required"
    info "Update: rustup update stable"
  fi
else
  fail "Rust not found"
  info "Install: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
fi

# ── 3. Python 3.11+ ───────────────────────────────────────────────
echo -e "\n${BOLD}[3/7] Python 3.11+${RESET}"
PY_BIN=""
for bin in python3.11 python3.12 python3; do
  if command -v "$bin" &>/dev/null; then
    VER="$($bin --version 2>&1 | grep -oP '\d+\.\d+')"
    MINOR="${VER#*.}"
    if [[ "${MINOR:-0}" -ge 11 ]]; then
      PY_BIN="$bin"
      ok "Python $($bin --version)"
      break
    fi
  fi
done
if [[ -z "$PY_BIN" ]]; then
  fail "Python 3.11+ not found"
  if [[ "$OS" == "Linux" ]]; then
    info "Install: sudo apt install python3.11 python3.11-venv python3-pip"
  elif [[ "$OS" == "Darwin" ]]; then
    info "Install: brew install python@3.11"
  fi
else
  echo -e "\n  Installing Python test dependencies..."
  "$PY_BIN" -m pip install --quiet \
    pytest pytest-cov hypothesis \
    pyyaml stix2 \
    antlr4-python3-runtime==4.13 \
    ruff \
    2>/dev/null && ok "pytest, hypothesis, pyyaml, stix2, antlr4, ruff installed" \
    || warn "Some Python packages failed to install"

  # Generate fixtures if not present
  if [[ ! -f "tests/fixtures/events/windows_event_log_1000.json" ]]; then
    echo -e "\n  Generating test fixtures..."
    "$PY_BIN" tests/fixtures/generate_fixtures.py && ok "Fixtures generated"
  else
    ok "Fixtures already present"
  fi
fi

# ── 4. Node.js 20+ ───────────────────────────────────────────────
echo -e "\n${BOLD}[4/7] Node.js 20+${RESET}"
if command -v node &>/dev/null; then
  NODE_VER="$(node --version | tr -d 'v')"
  NODE_MAJOR="${NODE_VER%%.*}"
  if [[ "${NODE_MAJOR:-0}" -ge 20 ]]; then
    ok "Node.js v$NODE_VER"
  else
    warn "Node.js v$NODE_VER found but v20+ required"
    info "Install: https://nodejs.org or use nvm: nvm install 20"
  fi
else
  warn "Node.js not found (required only for UI development)"
  info "Install: https://nodejs.org/en/download or nvm install 20"
fi

# ── 5. Docker 26+ ────────────────────────────────────────────────
echo -e "\n${BOLD}[5/7] Docker + Compose${RESET}"
if command -v docker &>/dev/null; then
  DOCKER_VER="$(docker --version | grep -oP '\d+\.\d+' | head -1)"
  ok "Docker $DOCKER_VER"
  if docker compose version &>/dev/null; then
    ok "Docker Compose plugin $(docker compose version --short)"
  else
    fail "Docker Compose plugin not found — install: https://docs.docker.com/compose/install/"
  fi
else
  fail "Docker not found"
  info "Install: https://docs.docker.com/engine/install/"
fi

# ── 6. Git hooks ─────────────────────────────────────────────────
echo -e "\n${BOLD}[6/7] Git hooks${RESET}"
if [[ -d ".git" ]]; then
  HOOK_DIR=".git/hooks"
  # pre-push: run make test before pushing
  cat > "$HOOK_DIR/pre-push" <<'HOOK'
#!/usr/bin/env bash
echo "[pre-push] Running unit tests..."
make test || { echo "Tests failed — push aborted. Fix tests or use git push --no-verify"; exit 1; }
HOOK
  chmod +x "$HOOK_DIR/pre-push"
  ok "pre-push hook installed (runs make test)"
else
  warn "Not a git repo — skipping hook installation"
fi

# ── 7. GPU / CUDA (optional, only with --gpu) ─────────────────────
echo -e "\n${BOLD}[7/7] GPU / CUDA${RESET}"
if [[ "$GPU" == "true" ]]; then
  if command -v nvidia-smi &>/dev/null; then
    GPU_NAME="$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)"
    DRIVER_VER="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1)"
    CUDA_VER="$(nvidia-smi | grep -oP 'CUDA Version: \K[\d.]+')"
    ok "GPU: $GPU_NAME"
    ok "Driver: $DRIVER_VER  |  CUDA: $CUDA_VER"

    # Check CUDA version
    CUDA_MAJOR="${CUDA_VER%%.*}"
    if [[ "${CUDA_MAJOR:-0}" -lt 12 ]]; then
      fail "CUDA 12.4+ required (found $CUDA_VER) — update NVIDIA drivers"
    fi

    # Check nvidia-container-toolkit
    if command -v nvidia-ctk &>/dev/null; then
      ok "nvidia-container-toolkit $(nvidia-ctk --version 2>/dev/null | head -1)"
    else
      fail "nvidia-container-toolkit not found — required for Docker GPU passthrough"
      info "Install: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html"
    fi

    # Suggest GPU Python deps
    echo ""
    info "To install GPU Python packages (requires CUDA 12 runtime):"
    info "  pip install cudf-cu12==24.10.* cuml-cu12==24.10.* rapids-morpheus"
  else
    fail "nvidia-smi not found — GPU not available or drivers not installed"
    info "Minimum GPU: NVIDIA A10G (24 GB VRAM, CUDA CC 8.0+)"
  fi
else
  info "Skipping GPU check (pass --gpu to verify GPU setup)"
fi

# ── Summary ───────────────────────────────────────────────────────
echo ""
echo "  ───────────────────────────────────────────────────────"
if [[ "$ERRORS" -eq 0 ]]; then
  echo -e "  ${GREEN}${BOLD}Setup complete — no errors.${RESET}"
  echo ""
  echo "  Next steps:"
  echo "    make dev          # start CPU dev stack"
  echo "    make test         # run unit tests"
  echo "    make help         # show all targets"
else
  echo -e "  ${RED}${BOLD}Setup complete with $ERRORS error(s). Fix the issues above before running make test.${RESET}"
fi
echo ""
