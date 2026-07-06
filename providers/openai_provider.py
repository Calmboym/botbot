"""
Gold Bot v2 – OpenAI Provider (SKELETON — NOT YET IMPLEMENTED)
==================================================================
This is an empty skeleton. To activate OpenAI as the AI provider:

    1. pip install openai
    2. Implement generate() below using openai.AsyncOpenAI
    3. Set in .env:
           AI_PROVIDER=openai
           OPENAI_API_KEY=sk-...
           OPENAI_MODEL=gpt-4o-mini
           OPENAI_VISION_MODEL=gpt-4o-mini

No other file in the project needs to change — ai_service.py and every
other business-logic module talk only to BaseAIProvider, never to a
concrete provider class.

Implementation notes for whoever picks this up:
    - The OpenAI Python SDK's async client (AsyncOpenAI) is a near-drop-in
      replacement for AsyncGroq — see providers/groq_provider.py, the
      chat.completions.create(...) call signature is almost identical.
    - JSON mode: pass response_format={"type": "json_object"}, same as Groq.
    - Vision: OpenAI accepts the same {"type": "image_url", "image_url":
      {"url": "data:image/jpeg;base64,..."}} content-block format already
      used throughout this project — no conversion needed.
    - Translate openai.AuthenticationError / openai.RateLimitError /
      openai.APITimeoutError into ProviderAuthError / ProviderRateLimitError /
      ProviderTimeoutError, the same way providers/groq_provider.py does.
"""

import logging

from providers.base_provider import BaseAIProvider, ProviderError

logger = logging.getLogger(__name__)


class OpenAIProvider(BaseAIProvider):
    def __init__(
        self,
        api_key: str,
        text_model: str,
        vision_model: str,
        timeout: int = 30,
    ) -> None:
        self._api_key      = api_key
        self._text_model   = text_model
        self._vision_model = vision_model
        self._timeout      = timeout
        # TODO: from openai import AsyncOpenAI; self._client = AsyncOpenAI(api_key=api_key, timeout=timeout)

    @property
    def name(self) -> str:
        return "openai"

    async def generate(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.7,
        max_tokens: int = 1500,
        json_mode: bool = False,
        vision: bool = False,
    ) -> str:
        raise ProviderError(
            "OpenAI provider is not implemented yet. "
            "Implement providers/openai_provider.py, or set AI_PROVIDER=groq in .env."
        )
