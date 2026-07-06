"""
Gold Bot v2 – Gemini Provider (SKELETON — NOT YET IMPLEMENTED)
==================================================================
This is an empty skeleton. To activate Gemini as the AI provider:

    1. pip install google-generativeai
    2. Implement generate() below using google.generativeai
    3. Set in .env:
           AI_PROVIDER=gemini
           GEMINI_API_KEY=your-key
           GEMINI_MODEL=gemini-1.5-flash
           GEMINI_VISION_MODEL=gemini-1.5-flash

No other file in the project needs to change — ai_service.py and every
other business-logic module talk only to BaseAIProvider, never to a
concrete provider class.

Implementation notes for whoever picks this up:
    - Gemini's SDK is synchronous by default; wrap calls in
      asyncio.to_thread() to keep this method async-compatible, exactly
      like SheetService does for gspread elsewhere in this project.
    - Gemini's JSON mode is requested via
      generation_config={"response_mime_type": "application/json"}.
    - Gemini's vision input takes PIL Images or raw bytes directly,
      not base64 data URLs — you will need to convert the incoming
      "image_url" content blocks accordingly.
    - Translate google.api_core.exceptions into ProviderAuthError /
      ProviderRateLimitError / ProviderTimeoutError / ProviderError,
      the same way providers/groq_provider.py does.
"""

import logging

from providers.base_provider import BaseAIProvider, ProviderError

logger = logging.getLogger(__name__)


class GeminiProvider(BaseAIProvider):
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
        # TODO: import google.generativeai as genai; genai.configure(api_key=api_key)

    @property
    def name(self) -> str:
        return "gemini"

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
            "Gemini provider is not implemented yet. "
            "Implement providers/gemini_provider.py, or set AI_PROVIDER=groq in .env."
        )
