#!/bin/bash
# Setup script for macOS (Metal GPU) and Linux (Vulkan)
# Usage: ./setup.sh

set -e

echo "FastContext Hybrid MCP Server — Setup"
echo "====================================="
echo ""

# Detect OS
OS="$(uname -s)"
case "$OS" in
    Darwin*) PLATFORM="macos" ;;
    Linux*)  PLATFORM="linux" ;;
    *)       echo "Unsupported OS: $OS"; exit 1 ;;
esac
echo "Platform: $PLATFORM"

# Check Python
command -v python3 >/dev/null 2>&1 || { echo "Error: python3 not found"; exit 1; }
echo "Python: $(python3 --version)"

# Install Python deps
echo ""
echo "Installing Python dependencies..."
pip install fastmcp mcp huggingface_hub

# Check/build llama.cpp
echo ""
if command -v llama-server >/dev/null 2>&1; then
    echo "llama-server found in PATH"
else
    echo "Building llama.cpp..."
    
    # Install build deps
    if [ "$PLATFORM" = "macos" ]; then
        command -v cmake >/dev/null 2>&1 || brew install cmake
        command -v git >/dev/null 2>&1 || brew install git
    else
        command -v cmake >/dev/null 2>&1 || { echo "Install cmake: sudo dnf install cmake or sudo apt install cmake"; exit 1; }
        command -v g++ >/dev/null 2>&1 || { echo "Install g++: sudo dnf install gcc-c++ or sudo apt install build-essential"; exit 1; }
    fi
    
    TMPDIR=$(mktemp -d)
    git clone --depth 1 https://github.com/ggml-org/llama.cpp "$TMPDIR/llama.cpp"
    cd "$TMPDIR/llama.cpp"
    
    if [ "$PLATFORM" = "macos" ]; then
        # macOS: Metal backend
        cmake -B build -DGGML_METAL=ON -DCMAKE_BUILD_TYPE=Release
    else
        # Linux: Vulkan backend
        command -v glslc >/dev/null 2>&1 || { echo "Install glslc: sudo dnf install glslc or sudo apt install glslc"; exit 1; }
        cmake -B build -DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release
    fi
    
    cmake --build build --config Release -j$(nproc 2>/dev/null || sysctl -n hw.ncpu)
    
    echo "Installing llama-server to /usr/local/bin..."
    sudo cp build/bin/llama-server /usr/local/bin/
    sudo cp build/bin/llama-cli /usr/local/bin/
    
    cd - > /dev/null
    rm -rf "$TMPDIR"
    echo "llama-server installed"
fi

# Check ripgrep
echo ""
if command -v rg >/dev/null 2>&1; then
    echo "ripgrep found"
else
    echo "Installing ripgrep..."
    if [ "$PLATFORM" = "macos" ]; then
        brew install ripgrep
    else
        echo "Install ripgrep: sudo dnf install ripgrep or sudo apt install ripgrep"
        exit 1
    fi
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
echo "====================================="
echo "Setup complete!"
echo ""
echo "To start the server:"
echo "  ./start.sh /path/to/your/project"
echo ""
echo "Or with Docker:"
echo "  WORK_DIR=/path/to/project docker compose up fastcontext-vulkan"
echo "  WORK_DIR=/path/to/project docker compose up fastcontext-cpu"
echo ""
echo "Add to ~/.hermes/config.yaml:"
echo "  mcp_servers:"
echo "    fastcontext:"
echo "      command: python3"
echo "      args: [$(pwd)/mcp_server.py]"
echo "      env:"
echo "        FASTCONTEXT_WORK_DIR: /path/to/project"
echo "        FASTCONTEXT_SERVER: http://127.0.0.1:8080"
