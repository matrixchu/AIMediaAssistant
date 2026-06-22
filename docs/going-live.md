# Going Live — making the full chain real

By default the project runs with a mock PT catalog and a simulated qBittorrent
so it works offline. This guide turns on the **real** search → select → download
pipeline. Nothing in the code changes — only `.env`.

## 1. Real downloads via qBittorrent

1. Install/launch **qBittorrent** and enable the Web UI:
   *Tools → Preferences → Web UI* → set a username/password and port (default 8080).
2. Configure `.env`:
   ```dotenv
   QB_MOCK=false
   QB_HOST=http://localhost:8080
   QB_USERNAME=admin
   QB_PASSWORD=your-password
   QB_CATEGORY=ai-media
   DOWNLOAD_SAVE_PATH=/path/to/your/media
   ```
3. Downloads added by the agent appear in qBittorrent under the `ai-media`
   category, and `get_download_status` reflects real progress.

The integration uses the official `qbittorrent-api`. Magnet info-hashes are
resolved up front; `.torrent` HTTP links are also supported.

## 2. Real search via a Torznab indexer (Jackett / Prowlarr)

Private trackers differ wildly, so the realistic and maintainable path is an
**indexer aggregator** that exposes the standard **Torznab** API:

- **Jackett** — add your trackers in its UI, then use the "all indexers" Torznab
  feed:
  ```dotenv
  PT_BACKEND=torznab
  PT_MOCK=false
  PT_BASE_URL=http://127.0.0.1:9117/api/v2.0/indexers/all/results/torznab/api
  PT_API_KEY=<your-jackett-api-key>
  PT_MIN_SEEDERS=1
  ```
- **Prowlarr** — use a per-indexer Torznab endpoint:
  ```dotenv
  PT_BACKEND=torznab
  PT_MOCK=false
  PT_BASE_URL=http://127.0.0.1:9696/<indexerId>/api
  PT_API_KEY=<your-prowlarr-api-key>
  ```

`search_media` now returns real torrents (title, size, seeders, magnet/.torrent),
ranked by your stored preferences, and `download_media` hands the link to
qBittorrent.

### Custom JSON indexer

If you have a bespoke JSON search API instead of Torznab, set `PT_BACKEND=json`
and point `PT_BASE_URL` at it; adapt the parser in
[clients/pt/http.py](../src/ai_media_assistant/clients/pt/http.py).

## 3. Verify the chain is real

Ask the agent (or call the tool) for `get_system_status`:

```bash
# via OpenClaw
openclaw agent --agent main --session-key media \
  --message "/no_think Call ai-media get_system_status and show the JSON."

# or directly
python -c "from ai_media_assistant.mcp.server import get_system_status as f; print(f())"
```

Expected when live:

```json
{
  "pt_backend": "torznab",
  "pt_base_url": "http://127.0.0.1:9117/api/...",
  "qb_mock": false,
  "qb_connected": true,
  "qb_active_torrents": 0,
  "llm_provider": "ollama",
  "llm_model": "qwen3:8b"
}
```

After editing `.env`, refresh OpenClaw's cached runtime:

```bash
openclaw mcp reload
```

## 4. End-to-end example (real)

```text
You (OpenClaw chat):  下载《沙丘2》
Agent:
  1. search_media("沙丘2")        → Torznab → real results ranked by preference
  2. download_media(<best id>)    → qBittorrent adds the magnet (category ai-media)
  3. get_download_status()        → real % progress from qBittorrent
```

## 5. Safety reminder

Real downloading is gated by the same guardrails described in
[ai-safety.md](ai-safety.md). For autonomous/unattended operation, set
`AGENT_REQUIRE_DOWNLOAD_CONFIRM=true` to require explicit approval before any
download is started. Respect each tracker's terms of service and your local law.
