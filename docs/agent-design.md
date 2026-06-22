# Agent Design

How the agent is built, and how each "learning goal" from the design is realised.

## 1. The augmented LLM

Following Anthropic's *Building effective agents*, the base building block is an
**augmented LLM** = model + tools + memory + retrieval:

- **Tools** — [`agent/tools.py`](../src/ai_media_assistant/agent/tools.py)
- **Memory** — [`agent/memory.py`](../src/ai_media_assistant/agent/memory.py)
- **Retrieval (RAG)** — [`agent/rag.py`](../src/ai_media_assistant/agent/rag.py)

## 2. Tool calling

Six tools mirror the design's MCP tools and are exposed **twice**:

1. As **LangChain `@tool`s** for the in-process LangGraph agent.
2. As **MCP tools** (`mcp/server.py`) for OpenClaw / Claude-Desktop style clients.

Tool docstrings are treated as the **agent-computer interface (ACI)** — they state
arguments, return shapes and how tools chain (e.g. `search_media` → use `id` with
`download_media`). This is a deliberate application of Appendix 2 ("Prompt
engineering your tools") from *Building effective agents*.

| Tool | Purpose |
|---|---|
| `search_media(keyword)` | Search trackers; returns ranked resources with ids |
| `download_media(resource_id, confirm)` | Add a resource to qBittorrent |
| `follow_show(title, season, quality)` | Subscribe + download available episodes |
| `list_subscriptions()` | List follow list |
| `get_download_status(task_id?)` | Progress for one/all downloads |
| `get_recommendations(query)` | RAG-based recommendations |

## 3. Long-term memory (Phase 5)

`AgentMemoryStore` persists preferences to the `agent_memory` table and extracts
them from natural language (e.g. *"我喜欢 2160P REMUX"* → `preferred_resolution=2160P`,
`preferred_quality=REMUX`). The **SearchService ranks results** using these
preferences, so the agent's behaviour personalises over time. Memories are also
summarised into the supervisor's system prompt.

## 4. RAG recommendations

The recommendation pipeline is a textbook RAG flow:

1. **Index** — build documents from the cached `torrent_resource` rows + a curated
   media knowledge base.
2. **Embed** — using Ollama / OpenAI embeddings, or an **offline deterministic
   hashing embedding** so it always runs.
3. **Retrieve** — cosine similarity over the query enriched with learned preferences.
4. **Generate** — the LLM synthesises a grounded recommendation list *only from the
   retrieved context* (reducing hallucination). If no LLM is available, the ranked
   retrieval is returned directly.

## 5. Multi-agent workflow (Phase 6)

[`agent/graph.py`](../src/ai_media_assistant/agent/graph.py) implements the
**supervisor / orchestrator-workers** pattern with LangGraph:

```text
                 ┌─────────────┐
   user  ─────▶  │  Planner    │ ◀───────────────┐
                 │ (supervisor)│                 │ (returns to plan
                 └──────┬──────┘                 │  after each step)
        route to one of │                        │
        ┌───────────────┼────────────────┐       │
        ▼               ▼                ▼        │
  Search Agent    Download Agent    Follow Agent ─┘
 (search_media,  (download_media,  (follow_show,
  recommend)      status)           list_subs)
```

- The **Planner** uses structured output (`Router`) to pick the next worker or
  `FINISH`.
- Each **worker** is a `create_react_agent` bound to a *small, focused* toolset
  (separation of concerns → better tool selection).
- This path activates when an LLM is configured. Otherwise the `AgentRunner`
  transparently falls back to a **deterministic intent router** that calls the
  same services/tools — so the project is always demonstrable.

## 6. Observability: execution trace

Every run creates an `agent_task` and writes step-by-step rows to
`agent_execution_log` (tool name, request, response). Retrieve a trace via
`GET /api/tasks/{task_id}/trace`. This makes the agent's "thinking" inspectable —
directly supporting the design's *"观察Agent思考过程 / 分析Tool调用 / 学习Workflow"* goal.

## 7. Why a framework here (and where we keep it thin)

*Building effective agents* recommends starting simple and only adding complexity
when it pays off. Accordingly:

- Services contain plain Python business logic (no framework lock-in).
- LangGraph is used only for the genuinely agentic, multi-step routing.
- A non-LLM fallback guarantees the core product works without the framework.
