"""
Gold Bot v2 – Provider Factory
=================================
Single place that decides which concrete AI provider to instantiate,
based on the AI_PROVIDER environment variable.

Business logic never imports GroqProvider/GeminiProvider/OpenAIProvider
directly — always call get_provider() and depend only on BaseAIProvider.
"""

import logging

from providers.base_provider import BaseAIProvider, ProviderError

logger = logging.getLogger(__name__)

_provider_instance: BaseAIProvider | None = None


def get_provider() -> BaseAIProvider:
    """
    Return a process-wide singleton instance of the configured AI provider.

    Reads AI_PROVIDER from config (default: "groq"). Raises ProviderError
    with a clear message if the selected provider is unimplemented or
    missing required credentials.
    """
    global _provider_instance
    if _provider_instance is not None:
        return _provider_instance

    from config.config import (
        AI_PROVIDER, AI_TIMEOUT,
        GROQ_API_KEY, GROQ_MODEL, GROQ_VISION_MODEL,
        GEMINI_API_KEY, GEMINI_MODEL, GEMINI_VISION_MODEL,
        OPENAI_API_KEY, OPENAI_MODEL, OPENAI_VISION_MODEL,
    )

    provider_name = (AI_PROVIDER or "groq").strip().lower()

    if provider_name == "groq":
        from providers.groq_provider import GroqProvider
        if not GROQ_API_KEY:
            raise ProviderError("GROQ_API_KEY is required when AI_PROVIDER=groq.")
        _provider_instance = GroqProvider(GROQ_API_KEY, GROQ_MODEL, GROQ_VISION_MODEL, timeout=AI_TIMEOUT)

    elif provider_name == "gemini":
        from providers.gemini_provider import GeminiProvider
        _provider_instance = GeminiProvider(GEMINI_API_KEY, GEMINI_MODEL, GEMINI_VISION_MODEL, timeout=AI_TIMEOUT)

    elif provider_name == "openai":
        from providers.openai_provider import OpenAIProvider
        _provider_instance = OpenAIProvider(OPENAI_API_KEY, OPENAI_MODEL, OPENAI_VISION_MODEL, timeout=AI_TIMEOUT)

    else:
        raise ProviderError(
            f"Unknown AI_PROVIDER '{AI_PROVIDER}'. Supported values: groq, gemini, openai."
        )

    logger.info("AI provider initialised: %s", _provider_instance.name)
    return _provider_instance


def reset_provider() -> None:
    """Clear the cached provider instance (mainly useful for tests)."""
    global _provider_instance
    _provider_instance = None
