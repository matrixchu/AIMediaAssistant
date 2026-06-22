# OpenClaw + Ollama Integration (local, zero-API-cost)

This project ships a **real** Model Context Protocol (MCP) server. Your locally
installed **OpenClaw** gateway connects to it and drives it with a **local
Ollama** model (e.g. `qwen3:8b`), so natural-language commands run end-to-end
with **no paid API calls**.

```text
You ──▶ OpenClaw gateway ──▶ Ollama (qwen3:8b, local)   ← planning, zero cost
                │
                ▼  MCP (stdio)
        ai-media MCP server  ──▶ Search / Download / Follow / Recommend
                │
                ▼
        Torznab indexer (Jackett/Prowlarr)  +  qBittorrent  +  MySQL/SQLite
```

## 1. Prerequisites (already present on this machine)

- `ollama` with a tool-capable model — verified: `qwen3:8b`, `deepseek-r1:8b`
- `openclaw` CLI + gateway running (`openclaw status`)
- This project installed (`pip install -e .` inside `.venv`)

OpenClaw's default model is set in `~/.openclaw/openclaw.json`:

```json
"agents": { "defaults": { "model": { "primary": "ollama/qwen3:8b" } } }
```

## 2. Register the MCP server (one command)

```bash
./scripts/register_openclaw.sh ai-media
```

This runs `openclaw mcp add` pointing at [scripts/mcp_stdio.sh](../scripts/mcp_stdio.sh)
(which uses the project venv and loads your `.env`), then **probes** it. You
should see:

```text
- ai-media: 7 tools, resources, prompts
```

Verify any time with:

```bash
openclaw mcp list
openclaw mcp probe ai-media     # lists the 7 tools live
openclaw mcp show ai-media      # show the saved server definition
```

The saved definition in `~/.openclaw/openclaw.json` looks like:

```json
{
  "mcp": {
    "servers": {
      "ai-media": {
        "transport": "stdio",
        "command": "/Users/<you>/Workspaces/AIMediaAssistant/scripts/mcp_stdio.sh",
        "cwd": "/Users/<you>/Workspaces/AIMediaAssistant",
        "env": { "PYTHONUNBUFFERED": "1" }
      }
    }
  }
}
```

## 3. Use it from OpenClaw (driven by local Ollama)

```bash
# One-shot agent turn
openclaw agent --agent main --session-key media \
  --message "用 ai-media 搜索并下载《沙丘2》"

# Interactive
openclaw chat
#   追《最后生还者》第二季
#   最近有什么值得下载的科幻电影？
#   查看下载进度
```

The agent plans with `qwen3:8b` and calls our tools: `search_media`,
`download_media`, `follow_show`, `list_subscriptions`, `get_download_status`,
`get_recommendations`, `get_system_status`.

### Tip: small-model tool reliability

Small local models sometimes spend their output budget on reasoning. Two
practical mitigations:

- Prepend `/no_think` to disable qwen3's chain-of-thought for direct tool calls:
  ```bash
  openclaw agent --agent main --session-key media \
    --message "/no_think Call ai-media search_media with keyword 'Dune Part Two'."
  ```
- For complex multi-step jobs, prefer `deepseek-r1:8b` or a larger model
  (`qwen3:14b`) via `--model`:
  ```bash
  openclaw agent --agent main --model ollama/deepseek-r1:8b \
    --session-key media --message "追《最后生还者》第二季"
  ```

## 4. Why this keeps costs at zero

- **Planning/tool-calling** runs on Ollama locally (the model `cost` is `0` in
  OpenClaw's config).
- **Embeddings/RAG** default to an offline hashing embedder (`EMBED_PROVIDER=fallback`)
  or local Ollama embeddings — no cloud calls.
- No OpenAI/Anthropic keys are required anywhere in the default configuration.

## 5. Updating / removing

```bash
# After changing code or .env, refresh OpenClaw's cached MCP runtime:
openclaw mcp reload

# Re-register (idempotent):
./scripts/register_openclaw.sh ai-media

# Remove:
openclaw mcp unset ai-media
```

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| `probe` shows 0 tools | Ensure `.venv` exists and `pip install -e .` ran; run `scripts/mcp_stdio.sh` directly to see stderr. |
| `incomplete_result` from Ollama | Use `/no_think`, shorten the request, or pick a larger model with `--model`. |
| Tools run but in **mock** mode | Set `PT_BACKEND=torznab` + `PT_BASE_URL`/`PT_API_KEY` and `QB_MOCK=false` in `.env`, then `openclaw mcp reload`. See [going-live.md](going-live.md). |
| Garbled MCP output | Make sure nothing prints to **stdout**; this project logs to stderr only. |
