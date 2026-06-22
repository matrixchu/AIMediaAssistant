"""Multi-agent workflow built with LangGraph (Phase 6 of the design).

Architecture — *supervisor* (a.k.a. orchestrator-workers) pattern:

    Planner (supervisor)
        ├── Search Agent   (search_media, get_recommendations)
        ├── Download Agent (download_media, get_download_status)
        └── Follow Agent   (follow_show, list_subscriptions)

The Planner routes each turn to the most appropriate worker until the task is
complete, then finishes. This mirrors the "orchestrator-workers" workflow from
Anthropic's *Building effective agents*.

Building the graph requires a working LLM (Ollama/OpenAI). Callers should be
ready for an :class:`LLMConfigError` and fall back to the rule-based runner.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import create_react_agent
from langgraph.types import Command
from pydantic import BaseModel

from ..shared.logging import get_logger
from .llm import get_llm
from .tools import (
    download_media,
    follow_show,
    get_download_status,
    get_recommendations,
    list_subscriptions,
    search_media,
)

logger = get_logger(__name__)

_WORKERS = ["search_agent", "download_agent", "follow_agent"]

_SUPERVISOR_PROMPT = (
    "You are the Planner of an AI media assistant. Given the conversation, decide "
    "which worker should act next, or FINISH when the user's goal is met.\n"
    "Workers:\n"
    "- search_agent: search trackers and recommend titles.\n"
    "- download_agent: start downloads and report progress.\n"
    "- follow_agent: subscribe to shows and list subscriptions.\n"
    "Route to exactly one worker, or FINISH. Do not loop unnecessarily."
)


class Router(BaseModel):
    """Structured routing decision returned by the supervisor."""

    next: Literal["search_agent", "download_agent", "follow_agent", "FINISH"]


def _make_worker(name: str, tools: list, instructions: str):
    agent = create_react_agent(get_llm(), tools=tools, prompt=instructions)

    def node(state: MessagesState) -> Command[Literal["supervisor"]]:
        result = agent.invoke(state)
        last = result["messages"][-1]
        return Command(
            update={"messages": [HumanMessage(content=last.content, name=name)]},
            goto="supervisor",
        )

    return node


def _supervisor_node(state: MessagesState) -> Command:
    messages = [SystemMessage(content=_SUPERVISOR_PROMPT), *state["messages"]]
    decision = get_llm().with_structured_output(Router).invoke(messages)
    goto = END if decision.next == "FINISH" else decision.next
    logger.debug("Supervisor route -> %s", decision.next)
    return Command(goto=goto)


@lru_cache
def build_agent_graph():
    """Compile and cache the multi-agent graph."""
    graph = StateGraph(MessagesState)
    graph.add_node("supervisor", _supervisor_node)
    graph.add_node(
        "search_agent",
        _make_worker(
            "search_agent",
            [search_media, get_recommendations],
            "You find media. Use search_media to find resources and "
            "get_recommendations to suggest titles. Report concise results.",
        ),
    )
    graph.add_node(
        "download_agent",
        _make_worker(
            "download_agent",
            [download_media, get_download_status],
            "You manage downloads. Use download_media with a resource id from a "
            "prior search, and get_download_status to report progress.",
        ),
    )
    graph.add_node(
        "follow_agent",
        _make_worker(
            "follow_agent",
            [follow_show, list_subscriptions],
            "You manage subscriptions. Use follow_show to subscribe and "
            "list_subscriptions to report the current follow list.",
        ),
    )
    graph.add_edge(START, "supervisor")
    return graph.compile()
