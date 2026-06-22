"""Domain-specific exceptions."""

from __future__ import annotations


class AIMediaError(Exception):
    """Base exception for the application."""


class ResourceNotFoundError(AIMediaError):
    """A requested resource/record was not found."""


class DownloadError(AIMediaError):
    """A download could not be started or tracked."""


class GuardrailError(AIMediaError):
    """An action was blocked by a safety guardrail."""


class LLMConfigError(AIMediaError):
    """The configured LLM/embedding provider is unavailable or misconfigured."""
