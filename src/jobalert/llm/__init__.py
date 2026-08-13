"""LLM provider factory.

Swap providers with one environment variable — LLM_PROVIDER=groq|gemini. Free
tiers change terms; this keeps that a config change rather than a refactor.
"""

from __future__ import annotations

from ..settings import get_settings
from .base import LLMClient, LLMError, parse_facts
from .prompt import build_system_prompt, build_user_prompt


def get_client() -> LLMClient:
    provider = get_settings().llm_provider
    if provider == "groq":
        from .groq import GroqClient

        return GroqClient()
    if provider == "gemini":
        from .gemini import GeminiClient

        return GeminiClient()
    raise LLMError(f"unsupported LLM_PROVIDER: {provider}")


__all__ = [
    "LLMClient",
    "LLMError",
    "build_system_prompt",
    "build_user_prompt",
    "get_client",
    "parse_facts",
]
