# AI Media Assistant 🎬🤖

> An AI-Agent media assistant for learning **modern agent development**:
> LangChain + LangGraph multi-agent workflows, RAG, Agent Memory, MCP tools,
> and built-in **safety guardrails (HHH / "harmless")**.

It implements every scenario in [`Design.md`](./Design.md) — PT search, qBittorrent
download, follow-show subscriptions, RSS auto-completion and AI recommendations —
re-architected on the Python AI-Agent stack.

---

## ✨ What it demonstrates

| Learning goal | Where it lives |
|---|---|
| AI Agent development | [`agent/`](src/ai_media_assistant/agent) (LangChain + LangGraph) |
| Tool Calling | [`agent/tools.py`](src/ai_media_assistant/agent/tools.py) |
| MCP Tool development | [`mcp/server.py`](src/ai_media_assistant/mcp/server.py) |
| Agent Memory (long-term) | [`agent/memory.py`](src/ai_media_assistant/agent/memory.py) + `agent_memory` table |
| RAG (recommendations) | [`agent/rag.py`](src/ai_media_assistant/agent/rag.py) + [`recommendation_service.py`](src/ai_media_assistant/services/recommendation_service.py) |
| Multi-Agent workflow | [`agent/graph.py`](src/ai_media_assistant/agent/graph.py) (Planner/Search/Download/Follow) |
| Agent safety / harmlessness | [`agent/guardrails.py`](src/ai_media_assistant/agent/guardrails.py) + [`docs/ai-safety.md`](docs/ai-safety.md) |
| Execution trace / observability | `agent_execution_log` table + `/api/tasks/{id}/trace` |

## 🧱 Tech stack

- **Language:** Python 3.10+
- **Agent framework:** LangChain + LangGraph (supervisor / orchestrator-workers)
- **RAG:** vector retrieval over a media knowledge base (offline hashing embeddings by default; Ollama/OpenAI/Chroma optional)
- **LLM:** Ollama (Qwen3 8B by default) or any OpenAI-compatible endpoint
- **API:** FastAPI + a static web dashboard
- **Database:** MySQL via SQLAlchemy (auto-falls back to SQLite for zero-setup)
- **Integrations:** qBittorrent (`qbittorrent-api`), RSS (`feedparser`), PT search (pluggable)
- **Protocol:** MCP (Model Context Protocol) server for OpenClaw / Claude-Desktop style clients

> **Runs fully offline.** Mock PT + mock qBittorrent + deterministic embeddings mean
> you can run the whole thing with **no external services and no model download**.
> Flip the `*_MOCK` flags and configure credentials to go live.

> **Runs for real, too.** Point it at a **Torznab indexer (Jackett/Prowlarr)** and a
> real **qBittorrent** Web UI and the full *search → select → download* chain works
> end-to-end. Drive it from **OpenClaw** using a **local Ollama** model — zero API cost.
> See [docs/going-live.md](docs/going-live.md) and [docs/openclaw-integration.md](docs/openclaw-integration.md).

---

## 🔌 Use it from OpenClaw + local Ollama (no API cost)

This project is a real MCP server. Register it into your local **OpenClaw**
gateway and drive it with a **local Ollama** model:

```bash
./scripts/register_openclaw.sh ai-media     # registers + probes (expects "7 tools")
openclaw chat                               # then: 追《最后生还者》第二季
```

OpenClaw plans with `ollama/qwen3:8b` and calls the `ai-media` tools. Full guide:
[docs/openclaw-integration.md](docs/openclaw-integration.md).

---

## � Documentation

| Document | Purpose |
|---|---|
| [`Design.md`](./Design.md) | Original requirements and system design |
| [`docs/USAGE.md`](docs/USAGE.md) | Complete usage guide (commands, API, OpenClaw) |
| [`docs/DIAGNOSIS.md`](docs/DIAGNOSIS.md) | **Troubleshooting: Why searches return 0 results** (RSS limits, backends, etc.) |
| [`docs/ai-safety.md`](docs/ai-safety.md) | Safety guardrails and harmlessness principles |
| [`docs/implementation-notes.md`](docs/implementation-notes.md) | Architecture decisions and patterns |

---

## �🚀 Quick start

```bash
# 1. Create a virtual environment and install
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure (optional — defaults work offline)
cp .env.example .env

# 3a. Chat from the terminal
python -m ai_media_assistant.cli "下载《沙丘2》"

# 3b. Or run the web API + dashboard
uvicorn ai_media_assistant.api.app:app --reload
#    open http://localhost:8000

# 3c. Or expose tools over MCP (stdio)
python -m ai_media_assistant.mcp.server

# 4. Run the test suite
pytest
```

### The four design scenarios

```bash
python -m ai_media_assistant.cli "下载《沙丘2》"                    # movie download
python -m ai_media_assistant.cli "追《最后生还者》第二季"            # follow a show
python -m ai_media_assistant.cli "推荐最近值得下载的科幻电影"       # AI recommendation
python -m ai_media_assistant.workers.rss_worker                    # RSS auto-completion
```

---

## 🗺️ Architecture

```text
            ┌──────────────────────────────┐
   Chat /   │   AgentRunner  (guardrails)   │
   API /    │  ┌────────────────────────┐  │
   MCP  ───▶ │  │ LangGraph multi-agent  │  │  ← Planner routes to workers
            │  │ Planner→Search/DL/Follow│  │     (falls back to rule-based)
            │  └────────────────────────┘  │
            └───────────────┬──────────────┘
                            ▼
        ┌─────────── Service Layer ───────────┐
        │ Search · Download · Follow · Recommend│
        └───┬────────┬─────────┬──────────┬────┘
            ▼        ▼         ▼          ▼
        PT client  qB client  RSS     RAG / Memory
            │        │         │          │
            └────────┴────┬────┴──────────┘
                          ▼
                     MySQL / SQLite
```

See [`docs/architecture.md`](docs/architecture.md) for the full design and
[`docs/agent-design.md`](docs/agent-design.md) for the agent internals.

---

## 🛡️ Safety & "harmless" (requirement 3)

This project intentionally implements the safety patterns recommended in
Anthropic's [*Building effective agents*](https://www.anthropic.com/research/building-effective-agents):
input/output **sectioning guardrails**, **prompt-injection** sanitisation of
untrusted content, **human-in-the-loop confirmation** for sensitive actions, and
a full **execution trace**. The reasoning, citations and verification are in
[`docs/ai-safety.md`](docs/ai-safety.md).

---

## 📚 Documentation

- [`docs/USAGE.md`](docs/USAGE.md) — **完整使用说明（中文）**: RSS PT 站 + NAS qBittorrent + MySQL 全流程
- [`docs/setup.md`](docs/setup.md) — install, configuration, going live
- [`docs/architecture.md`](docs/architecture.md) — layers, data model, scenarios
- [`docs/agent-design.md`](docs/agent-design.md) — tools, memory, RAG, multi-agent
- [`docs/ai-safety.md`](docs/ai-safety.md) — HHH / harmlessness, guardrails, verification
- [`docs/openclaw-integration.md`](docs/openclaw-integration.md) — OpenClaw + local Ollama (zero-cost)
- [`docs/going-live.md`](docs/going-live.md) — real Torznab indexer + real qBittorrent

> 一键体检三大集成（MySQL / NAS qBittorrent / PT 源）：`python -m ai_media_assistant.doctor`

## ⚖️ Legal note

The default PT client is a **mock** with placeholder magnet links. This project
is for learning agent engineering. If you connect real trackers/clients, you are
responsible for complying with each service's terms and your local laws.
