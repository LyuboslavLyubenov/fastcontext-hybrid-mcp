# FastContext Hybrid MCP Server

An MCP (Model Context Protocol) server that gathers context from codebases using [FastContext-1.0-4B-RL](https://huggingface.co/microsoft/FastContext-1.0-4B-RL) — a 4B parameter model trained by Microsoft for repository exploration.

The server combines LLM-guided code exploration with fuzzy matching to find relevant code snippets for any question about a codebase.

## How It Works

```
User question
    ↓
1. DECOMPOSE — break into sub-questions (code-focused + doc-focused)
    ↓
2. EXPLORE — FastContext 4B model searches the codebase via Grep/Glob/Read
    ↓
3. EXTRACT — fuzzy matching extracts only relevant lines from found files
    ↓
4. GAP-FILL — ripgrep + Levenshtein distance catches what the model missed
    ↓
Snippets (~5K tokens) → fed to larger LLM for synthesis
```

### Performance Gains

Why use this pipeline instead of just asking the model directly?

```
APPROACH COMPARISON (tested on business-auditor, 1170 files)
═══════════════════════════════════════════════════════════════════════════

Method                          Concept     Answerable   Context/Question
                                Coverage
───────────────────────────────────────────────────────────────────────────
Raw FastContext (no pipeline)   50%         3/6          N/A (model output)
+ Path resolution fix           67%         4/6          N/A
+ Hybrid pipeline (unlimited)   97%         6/6          308K tokens
+ Hybrid pipeline (optimized)   92%         6/6           5K tokens  ← this
───────────────────────────────────────────────────────────────────────────
```

**What each layer adds:**

```
Layer                   What it does                            Gain
──────────────────────────────────────────────────────────────────────
FastContext 4B          Finds relevant files via tool calls     Baseline
Query decomposition     Breaks Q into doc + code sub-questions  +17%
Fuzzy snippet extract   camelCase split + Levenshtein matching  +15%
Gap-fill (ripgrep)      Catches what model missed               +25%
──────────────────────────────────────────────────────────────────────
Total: 50% → 92% concept coverage (+84% improvement)
```

**Context efficiency:**

```
Without optimization:  308K tokens/question  (loads full files)
With optimization:       5K tokens/question  (extracts relevant lines only)
Reduction:               62x smaller context
```

**What this means for the larger LLM:**
- Without pipeline: feed 308K tokens of raw files → exceeds most context windows, expensive
- With pipeline: feed 5K tokens of targeted snippets → fits easily, cheap, higher quality

The 4B model handles the expensive exploration work (searching, reading, filtering).
The larger LLM only sees the distilled evidence — no noise, no irrelevant code.

### Key Features

- **Smart search**: 4B model decides WHERE to look (not just keyword matching)
- **Fuzzy matching**: camelCase splitting, separator normalization, Levenshtein distance
- **Minimal context**: extracts only relevant lines, not full files (~5K tokens vs ~300K)
- **Gap-fill**: ripgrep safety net catches what the model misses
- **Q4 quantization**: runs on 6GB+ VRAM, ~67 tok/s generation

---

## Quick Start (Docker)

The fastest way to get started. Docker handles all dependencies.

### Linux with Vulkan GPU (AMD/Intel/NVIDIA)

```bash
git clone https://github.com/LyuboslavLyubenov/fastcontext-hybrid-mcp
cd fastcontext-hybrid-mcp

# Start with your project directory
WORK_DIR=/path/to/your/project docker compose up fastcontext-vulkan
```

The model downloads automatically on first run (~2.4GB).

### macOS or CPU-only Linux

```bash
git clone https://github.com/LyuboslavLyubenov/fastcontext-hybrid-mcp
cd fastcontext-hybrid-mcp

WORK_DIR=/path/to/your/project docker compose up fastcontext-cpu
```

### Docker run (manual)

```bash
# Build
docker build -f Dockerfile.vulkan -t fastcontext-mcp .

# Run
docker run -d \
  -v /path/to/project:/workspace \
  -v ./models:/models \
  -p 8080:8080 \
  --device /dev/dri:/dev/dri \
  fastcontext-mcp
```

---

## Quick Start (No Docker)

For native performance or if you prefer not to use containers.

### One-command setup

```bash
git clone https://github.com/LyuboslavLyubenov/fastcontext-hybrid-mcp
cd fastcontext-hybrid-mcp
chmod +x setup.sh start.sh
./setup.sh
```

This installs everything: Python deps, llama.cpp (Vulkan/Metal), ripgrep, and downloads the model.

Then start:
```bash
./start.sh /path/to/your/project
```

### Manual setup (Linux with Vulkan)

#### 1. Install system dependencies

```bash
# Fedora
sudo dnf install cmake gcc-c++ glslc spirv-headers-devel spirv-tools-devel \
    vulkan-headers vulkan-loader-devel ripgrep

# Ubuntu/Debian
sudo apt install cmake build-essential glslc spirv-headers spirv-tools \
    libvulkan-dev ripgrep
```

#### 2. Install Python dependencies

```bash
pip install fastmcp mcp huggingface_hub
```

#### 3. Build llama.cpp with Vulkan

```bash
git clone --depth 1 https://github.com/ggml-org/llama.cpp
cd llama.cpp
cmake -B build -DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j$(nproc)
sudo cp build/bin/llama-server /usr/local/bin/
cd ..
```

#### 4. Download the model

```bash
huggingface-cli download sdougbrown/FastContext-1.0-4B-RL-GGUF \
    FastContext-1.0-4B-RL-Q4_K_M.gguf --local-dir ./models
```

#### 5. Start

```bash
# Start inference server (32K context, 1 slot, Vulkan GPU)
llama-server \
    -m models/FastContext-1.0-4B-RL-Q4_K_M.gguf \
    --ctx-size 32768 \
    --parallel 1 \
    -ngl 99 \
    --host 127.0.0.1 \
    --port 8080 \
    --reasoning off &

# Start MCP server
FASTCONTEXT_WORK_DIR=/path/to/project python3 mcp_server.py
```

### Manual setup (macOS with Metal)

#### 1. Install dependencies

```bash
brew install cmake git ripgrep python3
pip install fastmcp mcp huggingface_hub
```

#### 2. Build llama.cpp with Metal

```bash
git clone --depth 1 https://github.com/ggml-org/llama.cpp
cd llama.cpp
cmake -B build -DGGML_METAL=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j$(sysctl -n hw.ncpu)
sudo cp build/bin/llama-server /usr/local/bin/
cd ..
```

#### 3. Download model and start

```bash
huggingface-cli download sdougbrown/FastContext-1.0-4B-RL-GGUF \
    FastContext-1.0-4B-RL-Q4_K_M.gguf --local-dir ./models

./start.sh /path/to/your/project
```

---

## Configure in Hermes Agent

Add to `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  fastcontext:
    command: "python3"
    args: ["/path/to/fastcontext-hybrid-mcp/mcp_server.py"]
    env:
      FASTCONTEXT_WORK_DIR: "/path/to/your/project"
      FASTCONTEXT_SERVER: "http://127.0.0.1:8080"
    timeout: 120
```

Restart Hermes Agent. Tools appear as `mcp_fastcontext_*`.

---

## Tools

### `search_context`

Main tool — searches a codebase for context relevant to a question.

```
Args:
  question: str          — The question (conceptual or code-specific)
  work_dir: str          — Path to codebase (optional, uses env var)
  seed: int              — Random seed (default: 42)
  max_turns: int         — Exploration turns per sub-question (default: 6)
  enable_gap_fill: bool  — Use fuzzy gap-fill (default: true)

Returns:
  JSON with:
    snippets: str        — Extracted code snippets (~5K tokens)
    files_read: int      — Number of files explored
    context_chars: int   — Total context size
    keywords: list       — Extracted keywords
```

### `read_snippet`

Extract relevant lines from a single file using fuzzy matching.

```
Args:
  filepath: str          — Absolute path to file
  concepts: list[str]    — Concepts to search for
  context_lines: int     — Surrounding lines (default: 2)
```

### `list_files`

List files matching a glob pattern.

### `health_check`

Check if the inference server is running.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `FASTCONTEXT_WORK_DIR` | `/home/llmbox/fastcontext-eval` | Project directory to search |
| `FASTCONTEXT_SERVER` | `http://127.0.0.1:8080` | llama-server URL |
| `FASTCONTEXT_MODEL` | `models/FastContext-1.0-4B-RL-Q4_K_M.gguf` | Model path |
| `FASTCONTEXT_LLAMA_CPP` | auto-detected | llama-server binary path |

## Hardware Requirements

| Backend | Min VRAM/RAM | GPU | Notes |
|---------|-------------|-----|-------|
| Vulkan | 6 GB | AMD/Intel/NVIDIA | Linux, Mesa or proprietary drivers |
| Metal | 8 GB unified | Apple Silicon | macOS only |
| CPU | 8 GB RAM | None | Slowest, works everywhere |

## Performance

| Metric | Value |
|--------|-------|
| Model size (Q4_K_M) | 2.4 GB |
| VRAM usage | ~6 GB (model + KV cache) |
| Prompt eval | ~420 tokens/sec |
| Generation | ~67 tokens/sec |
| Context per question | ~5K tokens |
| Time per question | ~20-40 seconds |

## License

MIT
