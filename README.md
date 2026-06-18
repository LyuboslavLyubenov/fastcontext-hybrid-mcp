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

## Quick Start (macOS — Recommended)

For Metal GPU acceleration on Apple Silicon (M1–M4). No Docker needed.

```bash
git clone https://github.com/LyuboslavLyubenov/fastcontext-hybrid-mcp
cd fastcontext-hybrid-mcp
chmod +x setup-mac.sh start.sh

# One-command setup (installs dependencies, builds llama.cpp with Metal, downloads model)
./setup-mac.sh

# Start with your project
./start.sh /path/to/your/project
```

This uses Metal GPU for ~67 tok/s generation. No Docker required.

> **Prerequisites**: macOS on Apple Silicon, Homebrew.
> The setup script auto-detects everything and installs what's missing.

---

## Quick Start (Linux)

### Linux with Vulkan GPU

```bash
git clone https://github.com/LyuboslavLyubenov/fastcontext-hybrid-mcp
cd fastcontext-hybrid-mcp
chmod +x setup.sh start.sh

./setup.sh

# Start with your project
./start.sh /path/to/your/project
```

### Linux CPU-only (or Docker)

```bash
WORK_DIR=/path/to/your/project docker compose up fastcontext-cpu
```

---

## Quick Start (Docker)

Docker handles all dependencies but runs CPU-only on macOS (no GPU passthrough).

### macOS / Linux CPU

```bash
git clone https://github.com/LyuboslavLyubenov/fastcontext-hybrid-mcp
cd fastcontext-hybrid-mcp

WORK_DIR=/path/to/your/project docker compose up fastcontext-cpu
```

The MCP server exposes SSE on port 8090 for MCP clients to connect.

### Linux with Vulkan GPU

```bash
WORK_DIR=/path/to/your/project docker compose up fastcontext-vulkan
```

---

## Using with MCP Clients

### Stdio (native macOS/Linux)

Add to `~/.config/opencode/opencode.json` or `~/.hermes/config.yaml`:

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

Make sure `llama-server` is running first (via `./start.sh` or manually).

### SSE (Docker)

When running in Docker, the MCP server listens on port 8090 with SSE transport.
Configure your MCP client to connect via SSE:

```yaml
mcp_servers:
  fastcontext:
    transport: "sse"
    url: "http://localhost:8090/mcp"
```

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
| `FASTCONTEXT_TRANSPORT` | `stdio` | MCP transport: `stdio`, `sse`, `http`, `streamable-http` |
| `FASTCONTEXT_MCP_HOST` | `0.0.0.0` | MCP server bind host (for SSE/HTTP) |
| `FASTCONTEXT_MCP_PORT` | `8090` | MCP server port (for SSE/HTTP) |

## Hardware Requirements

| Backend | Min RAM | GPU | Platform | Notes |
|---------|---------|-----|----------|-------|
| **Metal** | 8 GB unified | Apple Silicon M1+ | macOS native | **Best for macOS** — requires native install, not Docker |
| **Vulkan** | 6 GB | AMD/Intel/NVIDIA | Linux | Mesa or proprietary drivers |
| **CPU** | 8 GB RAM | None | Any | Works in Docker on any platform, ~10x slower |

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
