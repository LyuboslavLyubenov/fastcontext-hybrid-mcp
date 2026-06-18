#!/bin/bash
# Start FastContext Hybrid MCP Server
# Auto-detects platform: Metal (macOS), Vulkan (Linux), or CPU
# Usage: ./start.sh [work_dir] [model_path] [port]

set -e

WORK_DIR="${1:-.}"
MODEL="${2:-models/FastContext-1.0-4B-RL-Q4_K_M.gguf}"
PORT="${3:-8080}"

echo "FastContext Hybrid MCP Server"
echo "============================="

# Detect platform
OS="$(uname -s)"
if [ "$OS" = "Darwin" ]; then
    PLATFORM="macos"
    THREADS=$(sysctl -n hw.ncpu)
    # Metal is built into the binary — no special flags needed
    GPU_ARGS="-ngl 99"
else
    PLATFORM="linux"
    THREADS=$(nproc)
    GPU_ARGS="-ngl 99"
fi

# Find llama-server
if command -v llama-server >/dev/null 2>&1; then
    LLAMA_SERVER="llama-server"
elif [ -f "./llama.cpp/build/bin/llama-server" ]; then
    LLAMA_SERVER="./llama.cpp/build/bin/llama-server"
else
    echo "Error: llama-server not found."
    echo "Run ./setup.sh (Linux) or ./setup-mac.sh (macOS) first."
    exit 1
fi

# Resolve paths
WORK_DIR="$(cd "$WORK_DIR" && pwd)"
MODEL="$(cd "$(dirname "$MODEL")" && pwd)/$(basename "$MODEL")"

echo "Platform:  $PLATFORM"
echo "Work dir:  $WORK_DIR"
echo "Model:     $MODEL"
echo "Port:      $PORT"
echo "GPU:       $GPU_ARGS"
echo ""

# Check deps
command -v rg >/dev/null 2>&1 || { echo "Error: ripgrep not found"; exit 1; }
[ -f "$MODEL" ] || { echo "Error: Model not found at $MODEL"; exit 1; }

# Start llama-server
echo "Starting llama-server ($PLATFORM, $THREADS threads)..."
$LLAMA_SERVER \
    -m "$MODEL" \
    --ctx-size 32768 \
    --parallel 1 \
    $GPU_ARGS \
    --host 127.0.0.1 \
    --port "$PORT" \
    --reasoning off &
LLAMA_PID=$!

# Wait for readiness
echo "Waiting for llama-server..."
for i in $(seq 1 30); do
    if curl -s "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
        echo "llama-server ready on port $PORT"
        break
    fi
    sleep 1
done

# Start MCP server
export FASTCONTEXT_WORK_DIR="$WORK_DIR"
export FASTCONTEXT_SERVER="http://127.0.0.1:$PORT"

echo "Starting MCP server..."
python3 mcp_server.py &
MCP_PID=$!

# Cleanup
trap "echo 'Shutting down...'; kill $LLAMA_PID $MCP_PID 2>/dev/null; exit 0" INT TERM

echo ""
echo "Both servers running!"
echo "  llama-server: PID $LLAMA_PID (port $PORT)"
echo "  MCP server:   PID $MCP_PID"
echo ""
echo "Press Ctrl+C to stop."

wait
