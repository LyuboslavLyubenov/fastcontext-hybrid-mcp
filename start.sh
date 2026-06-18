#!/bin/bash
# Start FastContext Hybrid MCP Server
# Usage: ./start.sh [work_dir] [model_path] [port]

WORK_DIR="${1:-.}"
MODEL="${2:-models/FastContext-1.0-4B-RL-Q4_K_M.gguf}"
PORT="${3:-8080}"
LLAMA_CPP="${LLAMA_CPP:-llama-server}"

echo "FastContext Hybrid MCP Server"
echo "============================="
echo "Work dir: $WORK_DIR"
echo "Model:    $MODEL"
echo "Port:     $PORT"
echo ""

# Check dependencies
command -v rg >/dev/null 2>&1 || { echo "Error: ripgrep (rg) not found. Install it first."; exit 1; }
[ -f "$MODEL" ] || { echo "Error: Model not found at $MODEL"; exit 1; }

# Start llama-server in background
echo "Starting llama-server..."
$LLAMA_CPP \
  -m "$MODEL" \
  --ctx-size 32768 \
  --parallel 1 \
  -ngl 99 \
  --host 127.0.0.1 \
  --port "$PORT" \
  --reasoning off &
LLAMA_PID=$!

# Wait for server to be ready
echo "Waiting for llama-server to start..."
for i in $(seq 1 30); do
  if curl -s "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    echo "llama-server ready!"
    break
  fi
  sleep 1
done

# Start MCP server
export FASTCONTEXT_WORK_DIR="$(cd "$WORK_DIR" && pwd)"
export FASTCONTEXT_SERVER="http://127.0.0.1:$PORT"
echo "Starting MCP server (work_dir=$FASTCONTEXT_WORK_DIR)..."
python3 mcp_server.py &
MCP_PID=$!

# Cleanup on exit
trap "kill $LLAMA_PID $MCP_PID 2>/dev/null" EXIT

echo ""
echo "Both servers running!"
echo "  llama-server: PID $LLAMA_PID (port $PORT)"
echo "  MCP server:   PID $MCP_PID"
echo ""
echo "Press Ctrl+C to stop."

wait
