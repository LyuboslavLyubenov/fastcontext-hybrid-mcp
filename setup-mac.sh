#!/bin/bash
# macOS setup with Metal GPU acceleration
# Usage: ./setup-mac.sh

set -e

echo "FastContext Hybrid MCP — macOS Metal Setup"
echo "==========================================="
echo ""

# Check macOS
if [ "$(uname -s)" != "Darwin" ]; then
    echo "Error: This script is for macOS only."
    echo "For Linux, use: ./setup.sh"
    exit 1
fi

# Check Apple Silicon
if [ "$(uname -m)" != "arm64" ]; then
    echo "Warning: Not running on Apple Silicon."
    echo "Metal GPU acceleration works best on M1/M2/M3/M4 chips."
    echo "Continuing with CPU fallback..."
    METAL_FLAG="-DGGML_METAL=OFF"
else
    echo "Apple Silicon detected — Metal GPU will be enabled"
    METAL_FLAG="-DGGML_METAL=ON"
fi

# Install dependencies via Homebrew
echo ""
echo "Checking dependencies..."

command -v brew >/dev/null 2>&1 || { echo "Error: Homebrew not found. Install from https://brew.sh"; exit 1; }
command -v python3 >/dev/null 2>&1 || brew install python3
command -v cmake >/dev/null 2>&1 || brew install cmake
command -v git >/dev/null 2>&1 || brew install git
command -v rg >/dev/null 2>&1 || brew install ripgrep

echo "All system dependencies found"

# Install Python deps
echo ""
echo "Installing Python dependencies..."
pip install fastmcp mcp huggingface_hub

# Build llama.cpp with Metal
echo ""
if command -v llama-server >/dev/null 2>&1; then
    echo "llama-server already installed"
else
    echo "Building llama.cpp with Metal support..."
    TMPDIR=$(mktemp -d)
    git clone --depth 1 https://github.com/ggml-org/llama.cpp "$TMPDIR/llama.cpp"
    cd "$TMPDIR/llama.cpp"
    
    cmake -B build $METAL_FLAG -DCMAKE_BUILD_TYPE=Release
    cmake --build build --config Release -j$(sysctl -n hw.ncpu)
    
    echo "Installing llama-server..."
    sudo cp build/bin/llama-server /usr/local/bin/
    sudo cp build/bin/llama-cli /usr/local/bin/
    
    cd - > /dev/null
    rm -rf "$TMPDIR"
    echo "llama-server installed with Metal support"
fi

# Download model
echo ""
MODEL_DIR="./models"
MODEL_FILE="$MODEL_DIR/FastContext-1.0-4B-RL-Q4_K_M.gguf"
if [ -f "$MODEL_FILE" ]; then
    echo "Model already downloaded: $MODEL_FILE"
else
    echo "Downloading Q4_K_M model (2.4GB)..."
    mkdir -p "$MODEL_DIR"
    huggingface-cli download sdougbrown/FastContext-1.0-4B-RL-GGUF \
        FastContext-1.0-4B-RL-Q4_K_M.gguf --local-dir "$MODEL_DIR"
fi

echo ""
echo "==========================================="
echo "Setup complete!"
echo ""
echo "Start the server:"
echo "  ./start.sh /path/to/your/project"
echo ""
echo "The server will use Metal GPU on Apple Silicon."
echo "For Docker (CPU only): WORK_DIR=/path docker compose up fastcontext-cpu"
