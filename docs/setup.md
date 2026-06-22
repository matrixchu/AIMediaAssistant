# Setup & Configuration

## 1. Requirements

- Python 3.10+
- (Optional) [Ollama](https://ollama.com) for a local LLM (e.g. `ollama pull qwen3:8b`)
- (Optional) MySQL — otherwise SQLite is used automatically
- (Optional) qBittorrent with the Web UI enabled

## 2. Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # optional; defaults run fully offline
```

## 3. Run

| What | Command | URL |
|---|---|---|
| CLI chat | `python -m ai_media_assistant.cli` | — |
| One-shot CLI | `python -m ai_media_assistant.cli "下载《沙丘2》"` | — |
| Web API + dashboard | `uvicorn ai_media_assistant.api.app:app --reload` | http://localhost:8000 |
| MCP server (stdio) | `python -m ai_media_assistant.mcp.server` | — |
| RSS worker (once) | `python -m ai_media_assistant.workers.rss_worker` | — |
| Scheduler (loop) | `python -m ai_media_assistant.workers.scheduler` | — |
| Tests | `pytest` | — |

## 4. Configuration reference

All settings live in `.env` (see `.env.example`). Highlights:

### LLM
```dotenv
LLM_PROVIDER=ollama          # or "openai"
LLM_MODEL=qwen3:8b           # qwen3:14b, deepseek-r1, gpt-4o-mini, …
OLLAMA_BASE_URL=http://localhost:11434
# OPENAI_API_KEY=...         # required if LLM_PROVIDER=openai
```
Without a reachable LLM, the agent uses its deterministic rule-based path — the
product still works end-to-end.

### Embeddings (RAG)
```dotenv
EMBED_PROVIDER=fallback      # "ollama" | "openai" | "fallback" (offline)
EMBED_MODEL=nomic-embed-text
```

### Database
```dotenv
# Leave DB_HOST empty to use a local SQLite file (data/app.db).
DB_HOST=
DB_NAME=ai_media_assistant
DB_USER=
DB_PASSWORD=
```

### Going live (disable mocks)
```dotenv
# Real PT search via a Torznab indexer (Jackett/Prowlarr):
PT_BACKEND=torznab
PT_MOCK=false
PT_BASE_URL=http://127.0.0.1:9117/api/v2.0/indexers/all/results/torznab/api
PT_API_KEY=...

# Real downloads via qBittorrent Web UI:
QB_MOCK=false
QB_HOST=http://localhost:8080
QB_USERNAME=admin
QB_PASSWORD=...
QB_CATEGORY=ai-media
DOWNLOAD_SAVE_PATH=/path/to/media
```
Full walkthrough: [going-live.md](going-live.md). Drive it from OpenClaw with a
local Ollama model: [openclaw-integration.md](openclaw-integration.md).

### Safety
```dotenv
AGENT_REQUIRE_DOWNLOAD_CONFIRM=true   # require explicit approval before downloads
AGENT_MAX_ITERATIONS=12
```

## 5. Connecting an MCP client

### OpenClaw (recommended — local, zero API cost)

```bash
./scripts/register_openclaw.sh ai-media     # registers + probes (expects "7 tools")
openclaw chat
```

Full guide: [openclaw-integration.md](openclaw-integration.md).

### Generic MCP host (Claude Desktop, etc.)

Add a server entry pointing at the stdio command:

```json
{
  "mcpServers": {
    "ai-media-assistant": {
      "command": "/path/to/AIMediaAssistant/scripts/mcp_stdio.sh",
      "cwd": "/path/to/AIMediaAssistant"
    }
  }
}
```

The client will discover the seven tools (`search_media`, `download_media`,
`follow_show`, `list_subscriptions`, `get_download_status`, `get_recommendations`,
`get_system_status`).

## 6. Docker

```bash
docker compose -f docker/docker-compose.yml up --build
```

This starts the API (and a MySQL service if you enable it in the compose file).

## 7. Troubleshooting

- **`LLMConfigError`** — your provider isn't reachable. Either start Ollama / set
  `OPENAI_API_KEY`, or just rely on the rule-based fallback.
- **MySQL connection errors** — clear `DB_HOST` to use SQLite, or verify credentials.
- **Slow first recommendation** — building the vector index embeds documents; with
  the `fallback` embedder this is instant and offline.
