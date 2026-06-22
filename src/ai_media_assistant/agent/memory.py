"""Agent long-term memory backed by the ``agent_memory`` table.

Stores user preferences and other durable facts so the agent personalises its
behaviour across sessions (e.g. "prefer 2160P REMUX").
"""

from __future__ import annotations

import re

from ..database import session_scope
from ..database import repositories as repo
from ..shared.logging import get_logger

logger = get_logger(__name__)

# Lightweight rules that turn natural language into preference memories.
_RES_RE = re.compile(r"\b(2160p|4k|1080p|720p|480p)\b", re.IGNORECASE)
_QUAL_RE = re.compile(r"\b(remux|blu-?ray|web-?dl|webrip|hdtv)\b", re.IGNORECASE)
_GENRE_RE = re.compile(r"\b(sci-?fi|科幻|action|动作|drama|剧情|comedy|喜剧|horror|恐怖)\b", re.IGNORECASE)


class AgentMemoryStore:
    """High-level API over the agent_memory table."""

    def remember(self, memory_type: str, key: str, value: str, importance: int = 1) -> None:
        with session_scope() as session:
            repo.set_memory(
                session, memory_type=memory_type, key=key, value=value, importance=importance
            )
        logger.info("Memory set: [%s] %s=%s", memory_type, key, value)

    def get_preferences(self) -> dict[str, str]:
        with session_scope() as session:
            return {
                m.memory_key: (m.memory_value or "")
                for m in repo.list_memories(session, memory_type="preference")
            }

    def all(self) -> list[dict]:
        with session_scope() as session:
            return [
                {
                    "type": m.memory_type,
                    "key": m.memory_key,
                    "value": m.memory_value,
                    "importance": m.importance,
                }
                for m in repo.list_memories(session)
            ]

    def learn_from_text(self, text: str) -> dict[str, str]:
        """Extract and persist simple preferences from a user utterance."""
        learned: dict[str, str] = {}
        if m := _RES_RE.search(text):
            value = m.group(1).upper().replace("4K", "2160P")
            self.remember("preference", "preferred_resolution", value, importance=3)
            learned["preferred_resolution"] = value
        if m := _QUAL_RE.search(text):
            value = m.group(1).upper().replace("BLURAY", "BluRay").replace("WEBDL", "WEB-DL")
            self.remember("preference", "preferred_quality", value.upper(), importance=3)
            learned["preferred_quality"] = value.upper()
        if m := _GENRE_RE.search(text):
            self.remember("preference", "favorite_genre", m.group(1), importance=2)
            learned["favorite_genre"] = m.group(1)
        return learned

    def summary_for_prompt(self) -> str:
        prefs = self.get_preferences()
        if not prefs:
            return "No stored user preferences yet."
        return "; ".join(f"{k}={v}" for k, v in prefs.items())
