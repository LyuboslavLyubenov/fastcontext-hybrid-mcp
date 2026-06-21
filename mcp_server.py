#!/usr/bin/env python3
"""FastContext Hybrid MCP Server
Exposes context-gathering tools for coding projects.
Uses FastContext-1.0-4B-RL (Q4_K_M) for smart search + fuzzy gap-fill.
"""
import json, os, re, subprocess, sys, urllib.request
from typing import Optional
from fastmcp import FastMCP

# ─── Config ────────────────────────────────────────────────────────────────────

WORK_DIR = os.environ.get("FASTCONTEXT_WORK_DIR", "/home/llmbox/fastcontext-eval")
MODEL_PATH = os.environ.get("FASTCONTEXT_MODEL", os.path.join(WORK_DIR, "models/FastContext-1.0-4B-RL-Q4_K_M.gguf"))
SERVER_URL = os.environ.get("FASTCONTEXT_SERVER", "http://127.0.0.1:8080")
LLAMA_CPP = os.environ.get("FASTCONTEXT_LLAMA_CPP", os.path.join(WORK_DIR, "llama.cpp/build/bin/llama-server"))

mcp = FastMCP("fastcontext-hybrid")

# ─── Fuzzy Matching ────────────────────────────────────────────────────────────

def levenshtein(s1, s2):
    if len(s1) < len(s2): return levenshtein(s2, s1)
    if len(s2) == 0: return len(s1)
    prev = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j+1]+1, curr[j]+1, prev[j]+(c1!=c2)))
        prev = curr
    return prev[-1]

def normalize(s):
    s = re.sub(r'([a-z])([A-Z])', r'\1 \2', s)
    return s.lower().replace('_', ' ').replace('-', ' ').replace('/', ' ').replace('.', ' ')

def fuzzy_match(concept, text, max_distance=2):
    concept_words = normalize(concept).split()
    text_words = normalize(text).split()
    for cw in concept_words:
        for tw in text_words:
            if cw in tw or tw in cw:
                return True
            if abs(len(cw) - len(tw)) <= max_distance:
                if levenshtein(cw, tw) <= max_distance:
                    return True
    return False

def fuzzy_snippet(filepath, concepts, context=2):
    try:
        with open(filepath) as f:
            all_lines = f.readlines()
    except:
        return ""
    match_indices = set()
    for i, line in enumerate(all_lines):
        if any(fuzzy_match(c, line) for c in concepts):
            for j in range(max(0, i - context), min(len(all_lines), i + context + 1)):
                match_indices.add(j)
    if not match_indices:
        return ""
    sorted_indices = sorted(match_indices)
    out = []
    prev = -2
    for idx in sorted_indices:
        if prev >= 0 and idx > prev + 1:
            out.append("...")
        out.append(str(idx + 1) + "|" + all_lines[idx].rstrip()[:200])
        prev = idx
    return "\n".join(out)

# ─── Path Resolution ───────────────────────────────────────────────────────────

def resolve_path(p, work_dir):
    if not p: return p
    if os.path.exists(p): return p
    
    # Model training uses /basename as alias for work_dir
    ws_name = os.path.basename(work_dir)
    if p.startswith("/" + ws_name):
        # Replace leading /ws_name with the real work_dir
        p = work_dir + p[len(ws_name) + 1:]
        if os.path.exists(p): return p
    
    # Try prepending work_dir for relative paths
    candidate = os.path.join(work_dir, p.lstrip("/"))
    if os.path.exists(candidate): return candidate
    
    return p

# ─── Tool Execution ────────────────────────────────────────────────────────────

def execute_tool(name, args_str, work_dir):
    args = json.loads(args_str) if isinstance(args_str, str) else args_str
    try:
        if name == "Read":
            p = resolve_path(args["path"], work_dir)
            if os.path.isdir(p):
                files = [f for f in os.listdir(p) if os.path.isfile(os.path.join(p, f))][:10]
                return "Error: path is a directory. Use Read with a file path. Files here: " + ", ".join(files)
            if not os.path.isfile(p): return "File " + p + " does not exist."
            with open(p) as f: lines = f.readlines()
            off = max(args.get("offset", 1) or 1, 1)
            end = min(off + 99, len(lines))
            out = [str(i+1) + "|" + lines[i][:300].rstrip() for i in range(off-1, end)]
            return "```" + p + ":" + str(off) + "-" + str(end) + "\n" + "\n".join(out) + "\n```"
        elif name == "Glob":
            d = resolve_path(args.get("directory", work_dir), work_dir)
            r = subprocess.run(["rg", "--files", d, "--glob", args["pattern"]], capture_output=True, text=True, timeout=10, cwd=work_dir)
            return r.stdout.strip()[:2000] if r.returncode == 0 else r.stderr.strip()[:500]
        elif name == "Grep":
            cmd = ["rg", args["pattern"], resolve_path(args.get("path", work_dir), work_dir)]
            if args.get("glob"): cmd += ["--glob", args["glob"]]
            cmd += ["--files-with-matches", "--heading", "--color", "never"]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, cwd=work_dir)
            return r.stdout.strip()[:2000] if r.returncode == 0 else r.stderr.strip()[:500]
        return "Unknown tool"
    except Exception as e:
        return "Tool error: " + str(e)

# ─── FastContext Caller ────────────────────────────────────────────────────────

def call_fc(messages, tools, seed=42):
    payload = {
        "model": "FastContext", "messages": messages, "tools": tools,
        "temperature": 1.0, "top_p": 0.95, "max_tokens": 8192, "stream": False,
        "chat_template_kwargs": {"enable_thinking": False}, "top_k": 20, "seed": seed,
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(SERVER_URL + "/v1/chat/completions", data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read())
    choice = result["choices"][0]["message"]
    content = choice.get("content", "") or ""
    tool_calls = []
    for tc in choice.get("tool_calls", []) or []:
        fn = tc.get("function", {})
        tool_calls.append({"id": tc.get("id", ""), "name": fn.get("name", ""), "arguments": fn.get("arguments", "{}")})
    return {"content": content, "tool_calls": tool_calls}

# ─── Tools Schema ──────────────────────────────────────────────────────────────

FC_TOOLS = [
    {"type":"function","function":{"name":"Read","description":"Reads a file. Lines numbered starting at 1.","parameters":{"type":"object","properties":{"path":{"type":"string","description":"Absolute path"},"offset":{"type":"integer"},"limit":{"type":"integer"}},"required":["path"]}}},
    {"type":"function","function":{"name":"Glob","description":"File pattern matching.","parameters":{"type":"object","properties":{"directory":{"type":"string"},"pattern":{"type":"string"}},"required":["pattern"]}}},
    {"type":"function","function":{"name":"Grep","description":"Find files matching a regex pattern (use Read to see file contents).","parameters":{"type":"object","properties":{"pattern":{"type":"string"},"path":{"type":"string"},"glob":{"type":"string"},"output_mode":{"type":"string","enum":["files_with_matches"]},"-C":{"type":"number"},"-i":{"type":"boolean"}},"required":["pattern"]}}},
]

SYSTEM_PROMPT = """You are a codebase exploration specialist focused exclusively on searching and analyzing existing code.
Your main goal is to explore the codebase based on a query, which are denoted by the <query> tag.

Your strengths:
- Rapidly finding files using glob patterns
- Searching code and text with powerful regex patterns
- Reading and analyzing file contents

Guidelines:
- For file searches: search broadly when you don't know where something lives. Use Read when you know the specific file path.
- For analysis: Start broad and narrow down. Use multiple search strategies if the first didn't yield results.
- Be thorough: Check multiple locations, consider different naming conventions, look for related files.
- Wherever possible spawn multiple parallel tool calls for grepping and reading files.

## Required Output
End your response with an optional brief explanation (no more than 50 words), followed by a <final_answer> tag containing relevant file paths and line ranges.

<example>
The core routing logic lives in two files.

<final_answer>
/absolute/path/to/file_1.py:10-15 (Core logic to modify)
/absolute/path/to/file_2.js:102-123
</final_answer></example>

## Working Environment

OS: Linux
Workspace: {work_dir}

Now, complete the user's search request efficiently and report your findings clearly."""

# ─── Core Pipeline ─────────────────────────────────────────────────────────────

def fc_explore(question, work_dir, seed=42, max_turns=6):
    """Run FastContext, return files accessed via Read tool calls."""
    sys_prompt = SYSTEM_PROMPT.format(work_dir=work_dir)
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": "<query>\n" + question + "\n</query>"},
    ]
    read_files = {}
    for turn in range(max_turns):
        resp = call_fc(messages, FC_TOOLS, seed=seed)
        content, tool_calls = resp["content"], resp["tool_calls"]
        if not tool_calls:
            break
        amsg = {"role": "assistant", "content": content or "", "tool_calls": [
            {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}}
            for tc in tool_calls
        ]}
        messages.append(amsg)
        for tc in tool_calls:
            result = execute_tool(tc["name"], tc["arguments"], work_dir)
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
            if tc["name"] == "Read":
                args = json.loads(tc["arguments"])
                fpath = resolve_path(args.get("path", ""), work_dir)
                if fpath and os.path.isfile(fpath):
                    off = args.get("offset", 1) or 1
                    lim = args.get("limit", 100) or 100
                    read_files[fpath] = {"start": off, "end": off + lim - 1}
    return read_files

def extract_snippets(read_files, concepts):
    """Extract concept-matching snippets from read files."""
    all_content = ""
    total_chars = 0
    for fpath, info in read_files.items():
        snippet = fuzzy_snippet(fpath, concepts, context=2)
        if not snippet:
            try:
                with open(fpath) as f:
                    lines = f.readlines()
                s = max(0, info["start"] - 1)
                e = min(len(lines), info["end"])
                snippet = "\n".join(str(s+i+1) + "|" + lines[s+i].rstrip()[:200] for i in range(min(e-s, 50)))
            except:
                snippet = ""
        total_chars += len(snippet)
        all_content += snippet + "\n"
    return all_content, total_chars

def gap_fill(missing_concepts, work_dir, existing_files):
    """Search for missing concepts using fuzzy matching."""
    gap_content = ""
    gap_chars = 0
    for concept in missing_concepts[:5]:
        try:
            r = subprocess.run(["rg", "--files-with-matches", concept, work_dir, "--heading", "--color", "never"],
                             capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                for f in r.stdout.strip().split("\n"):
                    f = f.strip()
                    if f and os.path.isfile(f) and f not in existing_files:
                        snippet = fuzzy_snippet(f, [concept], context=2)
                        if snippet:
                            gap_chars += len(snippet)
                            gap_content += snippet + "\n"
                            break
        except:
            pass
    return gap_content, gap_chars

def decompose(question):
    """Break question into sub-questions."""
    stopwords = {'the','what','where','when','how','does','this','that','with','from','have','been','will','would','could','should','after','before','between','difference','stored','find','file','mean','explain','describe','using','used','together','compared','happen','happens','finish','finishes','for','his','her'}
    keywords = [re.sub(r'[^a-z0-9]', '', w) for w in question.lower().split() if len(w) > 3 and w not in stopwords]
    keywords = [w for w in keywords if w]  # remove empty strings
    main_topic = " ".join(keywords[:3]) if keywords else question
    q_lower = question.lower()
    
    sub_qs = [{"query": "find documentation that explains: " + question, "type": "doc"},
              {"query": "find the source code that implements: " + main_topic, "type": "code"}]
    
    if "difference between" in q_lower:
        m = re.search(r'difference between (\w+) and (\w+)', q_lower)
        if m:
            sub_qs.append({"query": "find the {} type definition or data model".format(m.group(1)), "type": "code"})
            sub_qs.append({"query": "find the {} type definition or data model".format(m.group(2)), "type": "code"})
    if "component" in q_lower:
        sub_qs.append({"query": "find React component files for " + main_topic, "type": "code"})
    if "happen" in q_lower or "after" in q_lower:
        sub_qs.append({"query": "find the handler or workflow code for " + main_topic, "type": "code"})
    if "how" in q_lower and ("process" in q_lower or "implement" in q_lower):
        sub_qs.append({"query": "find the runtime or executor code for " + main_topic, "type": "code"})
        sub_qs.append({"query": "find runner, executor, or handler files for " + main_topic, "type": "code"})
    
    seen = set()
    unique = []
    for sq in sub_qs:
        if sq["query"] not in seen:
            seen.add(sq["query"])
            unique.append(sq)
    return unique, keywords

# ─── MCP Tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
def search_context(question: str, work_dir: Optional[str] = None, seed: int = 42, max_turns: int = 6, enable_gap_fill: bool = True) -> str:
    """Search a codebase for context relevant to a question.
    Use this to find code snippets, documentation, or implementation details
    in a project. Always pass the project's root directory as work_dir.
    Uses FastContext 4B model for smart exploration + fuzzy gap-fill.
    
    Args:
        question: The question about the codebase (can be conceptual or code-specific)
        work_dir: REQUIRED — the absolute path to the project root directory to search
        seed: Random seed for reproducibility (default: 42)
        max_turns: Max exploration turns per sub-question (default: 6)
        enable_gap_fill: Whether to use fuzzy gap-fill for missing concepts (default: true)
    
    Returns:
        JSON with collected snippets ready for a larger LLM to synthesize.
    """
    wd = work_dir or WORK_DIR
    
    if not os.path.isdir(wd):
        return json.dumps({"error": "Work directory does not exist: " + wd})
    
    # Step 1: Decompose
    sub_qs, keywords = decompose(question)
    
    # Step 2: Explore with FastContext
    all_read_files = {}
    for sq in sub_qs:
        files = fc_explore(sq["query"], wd, seed=seed, max_turns=max_turns)
        all_read_files.update(files)
    
    # Step 3: Extract snippets using fuzzy matching
    all_content, snippet_chars = extract_snippets(all_read_files, keywords)
    
    # Step 4: Gap-fill (optional)
    gap_content = ""
    gap_chars = 0
    if enable_gap_fill:
        # Check which keywords are missing
        missing = [kw for kw in keywords if kw.lower() not in all_content.lower()]
        if missing:
            gap_content, gap_chars = gap_fill(missing, wd, all_read_files)
            all_content += gap_content
    
    total_chars = snippet_chars + gap_chars
    
    return json.dumps({
        "question": question,
        "sub_questions": [sq["query"] for sq in sub_qs],
        "files_read": len(all_read_files),
        "snippets": all_content,
        "context_chars": total_chars,
        "context_tokens_est": total_chars // 4,
        "keywords": keywords,
    }, indent=2)

@mcp.tool()
def list_files(directory: str, pattern: str = "*") -> str:
    """List files in a directory matching a glob pattern.
    
    Args:
        directory: Absolute path to search in
        pattern: Glob pattern (default: * for all files)
    
    Returns:
        JSON list of matching file paths.
    """
    if not os.path.isdir(directory):
        return json.dumps({"error": "Directory does not exist: " + directory})
    try:
        r = subprocess.run(["rg", "--files", directory, "--glob", pattern], capture_output=True, text=True, timeout=10)
        files = r.stdout.strip().split("\n") if r.returncode == 0 else []
        return json.dumps({"directory": directory, "pattern": pattern, "files": files[:100], "total": len(files)})
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
def read_snippet(filepath: str, concepts: list[str], context_lines: int = 2) -> str:
    """Read only the relevant lines from a file using fuzzy concept matching.
    
    Args:
        filepath: Absolute path to the file
        concepts: List of concepts/keywords to search for
        context_lines: Number of surrounding lines to include (default: 2)
    
    Returns:
        Extracted snippet with line numbers.
    """
    if not os.path.isfile(filepath):
        return json.dumps({"error": "File does not exist: " + filepath})
    snippet = fuzzy_snippet(filepath, concepts, context=context_lines)
    if not snippet:
        return json.dumps({"file": filepath, "snippet": "", "note": "No matching lines found"})
    return json.dumps({"file": filepath, "concepts": concepts, "snippet": snippet, "chars": len(snippet)})

@mcp.tool()
def health_check() -> str:
    """Check if the FastContext server is running and reachable."""
    try:
        req = urllib.request.Request(SERVER_URL + "/health")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.dumps({"status": "ok", "server": SERVER_URL})
    except Exception as e:
        return json.dumps({"status": "error", "server": SERVER_URL, "error": str(e)})

# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    transport = os.environ.get("FASTCONTEXT_TRANSPORT", "stdio")
    if transport in ("sse", "http", "streamable-http"):
        host = os.environ.get("FASTCONTEXT_MCP_HOST", "0.0.0.0")
        port = int(os.environ.get("FASTCONTEXT_MCP_PORT", "8090"))
        mcp.run(transport=transport, host=host, port=port)
    else:
        mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
