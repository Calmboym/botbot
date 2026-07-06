"""
Gold Bot v2 – AI Provider Interface
======================================
Abstract base class every AI provider must implement.

Business logic (ai_service.py, summary_service.py, etc.) NEVER imports a
concrete provider (GroqProvider, GeminiProvider, OpenAIProvider, ...)
directly. It only depends on this interface, obtained via
providers.get_provider().

Switching providers = change AI_PROVIDER in .env to "groq" | "gemini" | "openai".
No other file in the project needs to change.
"""

from abc import ABC, abstractmethod


# ── Provider-level exceptions ──────────────────────────────────────────────────
# Every concrete provider must translate its SDK's native exceptions into
# these, so callers can handle errors uniformly regardless of provider.

class ProviderError(Exception):
    """Base class for all provider-level errors."""


class ProviderAuthError(ProviderError):
    """Raised when the API key / credentials are invalid."""


class ProviderRateLimitError(ProviderError):
    """Raised when the provider is throttling requests."""


class ProviderTimeoutError(ProviderError):
    """Raised when a request exceeds the configured timeout."""


# ── Interface ─────────────────────────────────────────────────────────────────

class BaseAIProvider(ABC):
    """
    Minimal, provider-agnostic chat interface.

    Every concrete provider accepts OpenAI-style message lists:
        [{"role": "system"|"user"|"assistant", "content": str | list}]

    Vision input uses the OpenAI-compatible content-block format:
        {"role": "user", "content": [
            {"type": "text", "text": "..."},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}},
        ]}
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for logging, e.g. 'groq', 'gemini', 'openai'."""
        raise NotImplementedError

    @abstractmethod
    async def generate(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.7,
        max_tokens: int = 1500,
        json_mode: bool = False,
        vision: bool = False,
    ) -> str:
        """
        Send messages to the model and return the raw text response.

        Args:
            messages:    OpenAI-style message list.
            temperature: Sampling temperature.
            max_tokens:  Maximum tokens to generate.
            json_mode:   If True, constrain output to a single JSON object
                         (used for structured extraction / AIResponse).
            vision:      If True, route to the provider's vision-capable model.

        Returns:
            Raw text content of the model's response.

        Raises:
            ProviderAuthError:      Invalid credentials.
            ProviderRateLimitError: Provider is throttling requests.
            ProviderTimeoutError:   Request exceeded the timeout.
            ProviderError:          Any other provider-level failure.
        """
        raise NotImplementedError
