"""LLM provider factory.

Returns a LangChain chat model based on configuration. Defaults to a local
Ollama model (e.g. Qwen3 8B). An OpenAI-compatible endpoint is also supported.
"""

from __future__ import annotations

from functools import lru_cache

from langchain_core.language_models import BaseChatModel

from ..shared.config import get_settings
from ..shared.errors import LLMConfigError
from ..shared.logging import get_logger

logger = get_logger(__name__)


@lru_cache
def get_llm() -> BaseChatModel:
    settings = get_settings()
    provider = settings.llm_provider.lower()

    if provider in ("none", "off", "disabled"):
        # Explicitly disabled: callers fall back to the rule-based agent path.
        raise LLMConfigError("LLM disabled (LLM_PROVIDER=none)")

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        logger.info("Using Ollama LLM: %s", settings.llm_model)
        return ChatOllama(
            model=settings.llm_model,
            base_url=settings.ollama_base_url,
            temperature=settings.llm_temperature,
        )

    if provider == "openai":
        if not settings.openai_api_key:
            raise LLMConfigError("LLM_PROVIDER=openai but OPENAI_API_KEY is not set")
        from langchain_openai import ChatOpenAI

        logger.info("Using OpenAI-compatible LLM: %s", settings.llm_model)
        return ChatOpenAI(
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )

    raise LLMConfigError(f"Unknown LLM_PROVIDER: {settings.llm_provider}")
