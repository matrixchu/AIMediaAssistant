# Architecture

This document maps the original [`Design.md`](../Design.md) onto the implemented
Python AI-Agent stack.

## 1. Stack mapping (Node/TS design → Python implementation)

| Design (V2.0) | Implementation | Why |
|---|---|---|
| Node.js + Express | **Python + FastAPI** | Required AI-Agent stack (LangChain/RAG/Python) |
| `openclaw-tools` | **MCP server** (`mcp/server.py`) | Tools published over the Model Context Protocol |
| Agent Core | **LangChain + LangGraph** (`agent/`) | Mainstream agent framework, multi-agent ready |
| MySQL | **SQLAlchemy + MySQL** (SQLite fallback) | Same schema; zero-setup local dev |
| qBittorrent | `qbittorrent-api` client (mock + real) | Pluggable |
| RSS Worker | `workers/rss_worker.py` + APScheduler | Phase 3 auto-completion |
| Flutter Web | **FastAPI static dashboard** | Lightweight, same REST contract a Flutter app could use |

## 2. Layered design

```text
Interfaces      CLI            FastAPI/REST + Web        MCP server
                  \                 |                      /
                   \                v                     /
Agent layer     ┌───────────────────────────────────────────┐
                │ AgentRunner → guardrails → LangGraph graph  │
                │ (Planner supervisor + Search/DL/Follow)     │
                │ memory · RAG · tools · execution trace      │
                └───────────────────────────────────────────┘
                                   |
Service layer    SearchService · DownloadService · FollowService · RecommendationService
                                   |
Client layer        PTClient        QBClient        RSS parser
                                   |
Data layer                 SQLAlchemy models (MySQL / SQLite)
```

Each layer depends only on the layer beneath it. Services are framework-agnostic
(they have no LangChain imports), so they are reusable by the API, the MCP server
and the agent tools alike.

## 3. Data model

All nine tables from the design are implemented in
[`database/models.py`](../src/ai_media_assistant/database/models.py):

- `media_subscription`, `media_episode` — follow-show subscriptions & tracking
- `torrent_resource`, `download_task` — search cache & downloads
- `rss_feed`, `rss_item` — RSS monitoring
- `agent_memory` — long-term preferences (Phase 5)
- `agent_task`, `agent_execution_log` — task records & execution trace (observability)

## 4. The four user scenarios

| Scenario | Flow |
|---|---|
| **Download a movie** (`下载《沙丘2》`) | guardrail → search PT → rank by prefs → qB add → `download_task` |
| **Follow a show** (`追《最后生还者》第二季`) | create `media_subscription` → search episodes → download each → `media_episode` |
| **Auto-complete** (RSS `S02E05`) | RSS worker → parse → match subscription → download → mark episode |
| **Recommendation** (`推荐科幻电影`) | RAG: build corpus → embed → retrieve → LLM synthesises (or retrieval fallback) |

## 5. Phase roadmap coverage

| Phase | Design goal | Status |
|---|---|---|
| 1 | Download movies | ✅ Search + Download services + qB client |
| 2 | Follow shows | ✅ FollowService + subscription/episode tables |
| 3 | RSS auto-completion | ✅ RssWorker + scheduler |
| 4 | OpenClaw MCP / tool calling | ✅ MCP server + LangChain tools |
| 5 | Agent memory | ✅ AgentMemoryStore + `agent_memory` |
| 6 | Multi-agent | ✅ LangGraph supervisor (Planner/Search/Download/Follow) |

## 6. Extensibility

- **Real PT site:** implement `PTClient.search` in `clients/pt/http.py` (Torznab/JSON
  template provided) and set `PT_MOCK=false`.
- **Real qBittorrent:** set `QB_MOCK=false` + credentials; `RealQBClient` is used.
- **Persistent RAG:** swap `SimpleVectorIndex` for `build_chroma_index` (Chroma).
- **Stronger LLM:** set `LLM_MODEL=deepseek-r1` / `qwen3:14b` or point at OpenAI.
