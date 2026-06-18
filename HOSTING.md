# Hosting Guide

This guide covers how to deploy FastContext Hybrid MCP as a hosted service.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│  MCP Client │────▶│  MCP Server  │────▶│ llama-server │
│  (Hermes,   │     │ (Python,     │     │ (GGUF model, │
│   Claude,   │     │  stdio/HTTP) │     │  Vulkan/Metal│
│   etc.)     │     └──────────────┘     │  /CPU)       │
└─────────────┘            │              └──────────────┘
                           │
                    ┌──────▼──────┐
                    │  Your Code  │
                    │  Repository │
                    └─────────────┘
```

Both servers run on the same machine. The MCP server communicates with llama-server via localhost HTTP.

---

## Option 1: Local (single machine)

Already covered in the main README. Run both servers on your development machine.

```bash
./start.sh /path/to/project
```

Best for: personal use, development, single user.

---

## Option 2: VPS with GPU

Deploy on a cloud VM with a GPU for shared team access.

### Recommended providers

| Provider | GPU | Cost | Notes |
|----------|-----|------|-------|
| Lambda Labs | A10, A100, H100 | $0.60-$2.50/hr | Best for ML workloads |
| Vast.ai | Various | $0.10-$1.00/hr | Cheapest, marketplace |
| RunPod | RTX 4090, A100 | $0.20-$1.50/hr | Good templates |
| Paperspace | A6000, A100 | $0.50-$2.00/hr | Easy setup |
| Hetzner | RTX 4090 | ~€100/mo | Best value dedicated |

### Setup on Ubuntu/Debian VPS

```bash
# 1. SSH into your VPS
ssh user@your-server-ip

# 2. Install system deps
sudo apt update
sudo apt install -y cmake build-essential git curl glslc \
    spirv-headers spirv-tools libvulkan-dev ripgrep python3-pip

# 3. Clone and setup
git clone https://github.com/LyuboslavLyubenov/fastcontext-hybrid-mcp
cd fastcontext-hybrid-mcp
pip install fastmcp mcp huggingface_hub

# 4. Build llama.cpp with Vulkan
git clone --depth 1 https://github.com/ggml-org/llama.cpp
cd llama.cpp
cmake -B build -DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j$(nproc)
sudo cp build/bin/llama-server /usr/local/bin/
cd ..

# 5. Download model
huggingface-cli download sdougbrown/FastContext-1.0-4B-RL-GGUF \
    FastContext-1.0-4B-RL-Q4_K_M.gguf --local-dir ./models

# 6. Start (see systemd section below for auto-start)
./start.sh /path/to/project
```

---

## Option 3: Dedicated Server (bare metal)

For maximum performance and always-on availability.

### Requirements

- Linux (Fedora, Ubuntu, Arch)
- Vulkan-capable GPU (AMD/Intel/NVIDIA with Mesa or proprietary drivers)
- 8GB+ RAM
- 10GB+ disk

### Setup

```bash
# Same as VPS setup above, but use setup.sh for automated install
git clone https://github.com/LyuboslavLyubenov/fastcontext-hybrid-mcp
cd fastcontext-hybrid-mcp
./setup.sh
./start.sh /path/to/project
```

---

## Auto-start with systemd

Run as a system service that starts on boot.

### llama-server service

```bash
sudo tee /etc/systemd/system/fastcontext-llama.service > /dev/null << 'EOF'
[Unit]
Description=FastContext llama-server
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/home/your-user/fastcontext-hybrid-mcp
Environment=LD_LIBRARY_PATH=/usr/lib64
ExecStart=/usr/local/bin/llama-server \
    -m /home/your-user/fastcontext-hybrid-mcp/models/FastContext-1.0-4B-RL-Q4_K_M.gguf \
    --ctx-size 32768 \
    --parallel 1 \
    -ngl 99 \
    --host 127.0.0.1 \
    --port 8080 \
    --reasoning off
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable fastcontext-llama
sudo systemctl start fastcontext-llama
```

### MCP server service

```bash
sudo tee /etc/systemd/system/fastcontext-mcp.service > /dev/null << 'EOF'
[Unit]
Description=FastContext MCP Server
After=fastcontext-llama.service
Requires=fastcontext-llama.service

[Service]
Type=simple
User=your-user
WorkingDirectory=/home/your-user/fastcontext-hybrid-mcp
Environment=FASTCONTEXT_WORK_DIR=/path/to/your/project
Environment=FASTCONTEXT_SERVER=http://127.0.0.1:8080
ExecStart=/usr/bin/python3 /home/your-user/fastcontext-hybrid-mcp/mcp_server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable fastcontext-mcp
sudo systemctl start fastcontext-mcp
```

### Check status

```bash
sudo systemctl status fastcontext-llama
sudo systemctl status fastcontext-mcp
sudo journalctl -u fastcontext-llama -f  # live logs
```

---

## Reverse Proxy (expose to network)

To access the MCP server from other machines, expose it via HTTP.

### Option A: Convert MCP stdio to HTTP

The current MCP server uses stdio transport. To expose it over HTTP, use a bridge:

```bash
# Install mcporter (stdio-to-HTTP bridge)
pip install mcporter

# Run MCP server as HTTP
mcporter serve python3 /path/to/mcp_server.py --port 9000
```

### Option B: nginx reverse proxy

```nginx
# /etc/nginx/sites-available/fastcontext
server {
    listen 443 ssl;
    server_name fastcontext.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/fastcontext.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/fastcontext.yourdomain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:9000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE support for MCP
        proxy_buffering off;
        proxy_cache off;
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        chunked_transfer_encoding off;
    }
}
```

### Option C: Caddy (simpler)

```bash
# Install Caddy
sudo apt install caddy

# /etc/caddy/Caddyfile
fastcontext.yourdomain.com {
    reverse_proxy localhost:9000
}
```

---

## Docker with persistent models

```bash
# Create a volume for the model (download once, reuse)
docker volume create fastcontext-models

# First run: download model into volume
docker run --rm \
    -v fastcontext-models:/models \
    fastcontext-mcp \
    "huggingface-cli download sdougbrown/FastContext-1.0-4B-RL-GGUF FastContext-1.0-4B-RL-Q4_K_M.gguf --local-dir /models"

# Run with persistent model volume
docker run -d \
    --name fastcontext \
    -v /path/to/project:/workspace \
    -v fastcontext-models:/models \
    -p 8080:8080 \
    --device /dev/dri:/dev/dri \
    --restart unless-stopped \
    fastcontext-mcp
```

---

## Multi-project setup

To serve multiple projects, run one MCP server per project with different ports:

```bash
# Project A on port 8080
FASTCONTEXT_WORK_DIR=/projects/a ./start.sh /projects/a models/FastContext-1.0-4B-RL-Q4_K_M.gguf 8080

# Project B on port 8081
FASTCONTEXT_WORK_DIR=/projects/b ./start.sh /projects/b models/FastContext-1.0-4B-RL-Q4_K_M.gguf 8081
```

Or use a single llama-server with multiple MCP servers pointing to it:

```bash
# Single llama-server
llama-server -m models/FastContext-1.0-4B-RL-Q4_K_M.gguf \
    --ctx-size 32768 --parallel 4 -ngl 99 --port 8080

# Multiple MCP servers (different projects)
FASTCONTEXT_WORK_DIR=/projects/a FASTCONTEXT_SERVER=http://localhost:8080 python3 mcp_server.py &
FASTCONTEXT_WORK_DIR=/projects/b FASTCONTEXT_SERVER=http://localhost:8080 python3 mcp_server.py &
```

---

## Cost estimates

| Setup | GPU | Monthly cost | Users |
|-------|-----|-------------|-------|
| Local machine | Integrated GPU | $0 (electricity only) | 1 |
| VPS (Vast.ai) | RTX 3090 | ~$70/mo | 1-5 |
| VPS (Lambda) | A10 | ~$450/mo | 5-20 |
| Dedicated (Hetzner) | RTX 4090 | ~€100/mo | 1-10 |
| Dedicated (Lambda) | A100 | ~$1,100/mo | 20-100 |

For a team of 1-5 people, a VPS with an RTX 3090 or 4090 is sufficient. The 4B model is small and fast — it doesn't need enterprise GPUs.
