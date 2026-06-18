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

## Requirements

- Python 3.10+
- [llama.cpp](https://github.com/ggml-org/llama.cpp) with Vulkan backend (for GPU inference)
- [ripgrep](https://github.com/BurntSushi/ripgrep) (`rg` command)
- [FastMCP](https://github.com/jlowin/fastmcp) (`pip install fastmcp`)
- ~6GB VRAM (or shared RAM for integrated GPUs)

## Installation

### 1. Install dependencies

```bash
pip install fastmcp mcp
```

### 2. Download the model

```bash
# Q4_K_M quantization (2.4GB, recommended)
huggingface-cli download sdougbrown/FastContext-1.0-4B-RL-GGUF \
  FastContext-1.0-4B-RL-Q4_K_M.gguf \
  --local-dir ./models

# Or Q8_0 for higher quality (4.5GB)
huggingface-cli download mitkox/FastContext-1.0-4B-RL-Q8_0-GGUF \
  FastContext-1.0-4B-RL-Q8_0.gguf \
  --local-dir ./models
```

### 3. Build llama.cpp with Vulkan

```bash
git clone https://github.com/ggml-org/llama.cpp.git
cd llama.cpp
cmake -B build -DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j$(nproc)
```

### 4. Install ripgrep

```bash
# Fedora
sudo dnf install ripgrep

# Ubuntu/Debian
sudo apt install ripgrep

# macOS
brew install ripgrep
```

## Usage

### Start the inference server

```bash
# 32K context, 1 parallel slot, Vulkan GPU offload
./llama.cpp/build/bin/llama-server \
  -m models/FastContext-1.0-4B-RL-Q4_K_M.gguf \
  --ctx-size 32768 \
  --parallel 1 \
  -ngl 99 \
  --host 127.0.0.1 \
  --port 8080 \
  --reasoning off
```

### Start the MCP server

```bash
# Set your project directory
export FASTCONTEXT_WORK_DIR=/path/to/your/project

# Run the MCP server
python3 mcp_server.py
```

### Configure in Hermes Agent

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

Restart Hermes Agent. The tools will appear as `mcp_fastcontext_*`.

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

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `FASTCONTEXT_WORK_DIR` | `/home/llmbox/fastcontext-eval` | Project directory to search |
| `FASTCONTEXT_SERVER` | `http://127.0.0.1:8080` | llama-server URL |
| `FASTCONTEXT_MODEL` | `models/FastContext-1.0-4B-RL-Q4_K_M.gguf` | Model path |
| `FASTCONTEXT_LLAMA_CPP` | auto-detected | llama-server binary path |

## Performance

| Metric | Value |
|--------|-------|
| Model size (Q4_K_M) | 2.4 GB |
| VRAM usage | ~6 GB (model + KV cache) |
| Prompt eval | ~420 tokens/sec |
| Generation | ~67 tokens/sec |
| Context per question | ~5K tokens |
| Time per question | ~20-40 seconds |

## Example

```python
from mcp_server import search_context
import json

result = search_context(
    question="what is the difference between survey and engagement?",
    work_dir="/path/to/your/project"
)

data = json.loads(result)
print(data["snippets"])  # ~5K tokens of relevant code
```

## License

MIT
