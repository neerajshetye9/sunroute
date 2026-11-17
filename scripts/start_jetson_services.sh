#!/usr/bin/env bash
# Start all SunRoute services on the Jetson Orin Nano
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

export LD_LIBRARY_PATH="$ROOT_DIR/bin/lib:$ROOT_DIR/bin/lib64:$ROOT_DIR/build/llama.cpp/build/bin:$ROOT_DIR/build/llama.cpp/build/src:/usr/local/cuda/lib64:${LD_LIBRARY_PATH:-}"

echo "=================================================="
echo " Starting SunRoute on Jetson Orin Nano Super"
echo "=================================================="

# 1. Clean up any existing instances on 8080, 8001, 8000
echo "[1/4] Freeing ports 8080, 8001, 8000..."
fuser -k 8080/tcp 2>/dev/null || true
fuser -k 8001/tcp 2>/dev/null || true
fuser -k 8000/tcp 2>/dev/null || true
sleep 1

# 2. Start llama-server on GPU
echo "[2/4] Starting llama-server (Qwen2.5-1.5B GPU) on port 8080..."
./bin/llama-server -m models/qwen2.5-1.5b-instruct-q4_k_m.gguf --port 8080 --host 0.0.0.0 -ngl 99 > /tmp/llama-server.log 2>&1 &

# 3. Start Edge Agent on port 8001
echo "[3/4] Starting Edge Agent on port 8001..."
source .venv/bin/activate
EDGE_PORT=8001 uvicorn edge.agent:app --host 0.0.0.0 --port 8001 > /tmp/edge-agent.log 2>&1 &

# 4. Start Gateway & Web UI on port 8000
echo "[4/4] Starting SunRoute Gateway & Web UI on port 8000..."
echo ""
echo "🚀 SunRoute is ready! Open in your browser:"
echo "   Tailscale: http://100.67.230.49:8000"
echo "   Local:     http://localhost:8000"
echo ""
SEED_NODES="jetson-01=http://127.0.0.1:8001;city-01;dev-edge-token" uvicorn gateway.app:app --host 0.0.0.0 --port 8000
