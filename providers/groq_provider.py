"""
Gold Bot v2 – Groq Provider
==============================
Concrete BaseAIProvider implementation backed by Groq's OpenAI-compatible
Chat Completions API. This is the default, fully-working provider.
"""

import logging

from groq import AsyncGroq, AuthenticationError, RateLimitError

from providers.base_provider import (
    BaseAIProvider, ProviderAuthError, ProviderError, ProviderRateLimitError,
)

logger = logging.getLogger(__name__)


class GroqProvider(BaseAIProvider):
    def __init__(
        self,
        api_key: str,
        text_model: str,
        vision_model: str,
        timeout: int = 30,
    ) -> None:
        self._client       = AsyncGroq(api_key=api_key, timeout=timeout)
        self._text_model   = text_model
        self._vision_model = vision_model

    @property
    def name(self) -> str:
        return "groq"

    async def generate(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.7,
        max_tokens: int = 1500,
        json_mode: bool = False,
        vision: bool = False,
    ) -> str:
        model = self._vision_model if vision else self._text_model

        kwargs: dict = dict(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = await self._client.chat.completions.create(**kwargs)
        except AuthenticationError as exc:
            logger.error("Groq authentication failed — check GROQ_API_KEY.")
            raise ProviderAuthError(str(exc)) from exc
        except RateLimitError as exc:
            logger.warning("Groq rate limit hit.")
            raise ProviderRateLimitError(str(exc)) from exc
        except Exception as exc:
            logger.error("Groq API error: %s", exc, exc_info=True)
            raise ProviderError(str(exc)) from exc

        return response.choices[0].message.content or ""
