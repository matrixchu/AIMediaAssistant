"""Agent runner — the single entry point used by the API, MCP and CLI.

It provides two execution paths:

1. **LLM multi-agent** (LangGraph supervisor) when an LLM is configured.
2. **Deterministic fallback** that parses intent and calls services directly,
   so the assistant is fully demonstrable offline (no model required).

Every run is wrapped in safety guardrails, records preferences to memory, and
writes an execution trace to ``agent_execution_log`` for observability.
"""

from __future__ import annotations

import re

from ..database import session_scope
from ..database import repositories as repo
from ..shared.config import get_settings
from ..shared.logging import get_logger
from ..shared.schemas import AgentRequest, AgentResponse, AgentStep
from . import guardrails
from .memory import AgentMemoryStore
from .tools import (
    download_media,
    follow_show,
    get_download_status,
    get_recommendations,
    list_subscriptions,
    search_media,
)

logger = get_logger(__name__)

_TITLE_CLEAN = re.compile(r"[《》\"'“”]")


class AgentRunner:
    def __init__(self) -> None:
        self._memory = AgentMemoryStore()

    def run(self, request: AgentRequest) -> AgentResponse:
        message = request.message.strip()

        # 1. Safety guardrail (sectioning pattern).
        verdict = guardrails.screen_input(message)
        if not verdict.allowed:
            return AgentResponse(reply=verdict.reason, steps=[])

        # 2. Learn durable preferences from the utterance.
        learned = self._memory.learn_from_text(message)

        # 3. Open a task + execution trace.
        with session_scope() as session:
            task = repo.create_agent_task(session, task_type="chat", content=message)
            task_id = task.id
            if learned:
                repo.log_execution(
                    session,
                    task_id=task_id,
                    step_name="learn_preferences",
                    tool_name=None,
                    response_data=learned,
                )

        # 4. Try the LLM multi-agent graph, else fall back.
        try:
            response = self._run_graph(message, task_id)
        except Exception as exc:  # noqa: BLE001 - LLM may be unavailable
            logger.info("Multi-agent graph unavailable (%s); using rule-based runner.", exc)
            response = self._run_rules(message, task_id)

        with session_scope() as session:
            repo.finish_agent_task(session, task_id)
        response.task_id = task_id
        response.reply = guardrails.screen_output(response.reply)
        return response

    # ------------------------------------------------------------------ #
    # LLM path
    # ------------------------------------------------------------------ #
    def _run_graph(self, message: str, task_id: int) -> AgentResponse:
        from langchain_core.messages import HumanMessage

        from .graph import build_agent_graph

        prefs = self._memory.summary_for_prompt()
        graph = build_agent_graph()
        primer = f"[User preferences: {prefs}]\n{message}"
        # Bound autonomy: cap supervisor<->worker iterations (safety guardrail).
        config = {"recursion_limit": get_settings().agent_max_iterations}
        result = graph.invoke({"messages": [HumanMessage(content=primer)]}, config=config)

        steps: list[AgentStep] = []
        for msg in result["messages"]:
            name = getattr(msg, "name", None)
            if name:
                steps.append(AgentStep(step_name=name, detail=_truncate(str(msg.content))))
        with session_scope() as session:
            for s in steps:
                repo.log_execution(
                    session,
                    task_id=task_id,
                    step_name=s.step_name,
                    tool_name=s.step_name,
                    response_data=s.detail,
                )
        reply = result["messages"][-1].content if result["messages"] else ""
        return AgentResponse(reply=reply, steps=steps)

    # ------------------------------------------------------------------ #
    # Deterministic fallback path
    # ------------------------------------------------------------------ #
    def _run_rules(self, message: str, task_id: int) -> AgentResponse:
        intent = _classify(message)
        confirm = True  # CLI/rule path treats the request itself as the approval
        steps: list[AgentStep] = []

        if intent == "recommend":
            out = get_recommendations.invoke({"query": message})
            steps.append(self._log(task_id, "recommend", "get_recommendations", out))
            reply = f"Here are some recommendations:\n{out}"

        elif intent == "status":
            out = get_download_status.invoke({})
            steps.append(self._log(task_id, "status", "get_download_status", out))
            reply = f"Current download tasks:\n{out}"

        elif intent == "list_subscriptions":
            out = list_subscriptions.invoke({})
            steps.append(self._log(task_id, "list", "list_subscriptions", out))
            reply = f"Your subscriptions:\n{out}"

        elif intent == "follow":
            title, season = _extract_title_season(message)
            out = follow_show.invoke({"title": title, "season": season})
            steps.append(self._log(task_id, "follow", "follow_show", out))
            reply = f"Now following '{title}'.\n{out}"

        else:  # download (default actionable intent)
            title, _ = _extract_title_season(message)
            search_out = search_media.invoke({"keyword": title})
            steps.append(self._log(task_id, "search", "search_media", search_out))
            resource_id = _first_resource_id(search_out)
            if resource_id is None:
                reply = f"No resources found for '{title}'."
            else:
                dl = download_media.invoke({"resource_id": resource_id, "confirm": confirm})
                steps.append(self._log(task_id, "download", "download_media", dl))
                reply = f"Started downloading the best match for '{title}'.\n{dl}"

        return AgentResponse(reply=reply, steps=steps)

    def _log(self, task_id: int, step: str, tool: str, response: object) -> AgentStep:
        with session_scope() as session:
            repo.log_execution(
                session,
                task_id=task_id,
                step_name=step,
                tool_name=tool,
                response_data=response,
            )
        return AgentStep(step_name=step, tool_name=tool, detail=_truncate(str(response)))


# --------------------------------------------------------------------------- #
# Intent parsing helpers (rule-based path)
# --------------------------------------------------------------------------- #
def _classify(message: str) -> str:
    m = message.lower()
    if any(k in message for k in ("推荐",)) or "recommend" in m:
        return "recommend"
    if any(k in message for k in ("进度", "状态")) or "status" in m or "progress" in m:
        return "status"
    if any(k in message for k in ("订阅列表", "追剧列表")) or "subscriptions" in m:
        return "list_subscriptions"
    if message.startswith("追") or "追" in message or "follow" in m or "subscribe" in m:
        return "follow"
    return "download"


def _extract_title_season(message: str) -> tuple[str, int | None]:
    season = None
    sm = re.search(r"(?:第|s|season)\s*0*(\d+)\s*季?", message, re.IGNORECASE)
    if sm:
        season = int(sm.group(1))
    # Prefer text inside Chinese/typographic quotes if present.
    q = re.search(r"[《\"“]([^》\"”]+)[》\"”]", message)
    if q:
        title = q.group(1)
    else:
        title = message
        for kw in ("下载", "追剧", "追", "download", "follow", "subscribe", "请", "帮我"):
            title = title.replace(kw, "")
        title = re.sub(r"(?:第|s|season)\s*0*\d+\s*季?", "", title, flags=re.IGNORECASE)
    return _TITLE_CLEAN.sub("", title).strip(), season


def _first_resource_id(search_output: str) -> int | None:
    import json

    try:
        payload = json.loads(search_output)
        data = payload.get("data") or []
        return data[0]["id"] if data else None
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        return None


def _truncate(text: str, limit: int = 500) -> str:
    return text if len(text) <= limit else text[:limit] + "…"
