"""
Gold Bot v2 – Gemini Provider
================================
Concrete BaseAIProvider implementation backed by Google's official
`google-genai` SDK — the modern, actively-maintained package (NOT the
deprecated `google-generativeai`).

Fully implements the same contract as GroqProvider: normal text
generation, JSON-constrained generation, vision (image) requests, system
prompts, multi-turn conversations, configurable temperature/max_tokens,
timeout, retry, and structured logging.

Zero changes are required anywhere else in the project to use this
provider — setting AI_PROVIDER=gemini in .env is enough. The constructor
signature intentionally matches GroqProvider's exactly, since
providers/__init__.py's factory instantiates both the same way:

    GeminiProvider(GEMINI_API_KEY, GEMINI_MODEL, GEMINI_VISION_MODEL, timeout=AI_TIMEOUT)
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import time
from typing import Optional

from google import genai
from google.genai import types

from providers.base_provider import (
    BaseAIProvider,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)

logger = logging.getLogger(__name__)

# Best-effort import of the SDK's structured error hierarchy.
# google-genai raises google.genai.errors.APIError, with ClientError /
# ServerError subclasses that carry an HTTP-style `.code`. This import is
# guarded so a future SDK refactor can never break module load — if these
# names ever change, _classify_error() transparently falls back to
# inspecting `.code` / the message text instead (see below).
try:
    from google.genai import errors as _genai_errors
except ImportError:  # pragma: no cover - defensive against SDK changes
    _genai_errors = None


# Keyword fallback used only when the SDK's exception hierarchy doesn't
# expose a usable `.code` (e.g. network-layer failures raised before any
# HTTP response comes back at all).
_AUTH_HINTS       = ("api key", "api_key", "unauthenticated", "permission", "credential")
_RATE_LIMIT_HINTS = ("rate limit", "quota", "resource_exhausted", "too many requests")


class GeminiProvider(BaseAIProvider):
    """Google Gemini provider using the official `google-genai` SDK."""

    def __init__(
        self,
        api_key: str,
        text_model: str,
        vision_model: str,
        timeout: int = 30,
    ) -> None:
        if not api_key:
            raise ProviderAuthError(
                "GEMINI_API_KEY is required when AI_PROVIDER=gemini."
            )

        self._client       = genai.Client(api_key=api_key)
        self._text_model   = text_model
        self._vision_model = vision_model
        self._timeout      = timeout

        # Reuses the project's existing AI_RETRY_COUNT setting (number of
        # extra attempts after the first) rather than introducing a second,
        # differently-named config knob for the identical concept.
        from config.config import AI_RETRY_COUNT
        self._max_retries = AI_RETRY_COUNT

    @property
    def name(self) -> str:
        return "gemini"

    # ── Public interface (BaseAIProvider contract) ────────────────────────────

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
        Send messages to Gemini and return the raw text response.

        See providers.base_provider.BaseAIProvider.generate for the full
        contract this must satisfy — this implementation adds Gemini-specific
        JSON-validity retry logic on top of the shared transient-error retry
        loop (see _generate_with_retries).
        """
        model = self._vision_model if vision else self._text_model
        system_instruction, contents = _convert_messages(messages)

        if not contents:
            raise ProviderError(
                "Gemini request has no user/assistant content to send "
                "(only a system message was provided)."
            )

        config_kwargs: dict = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        if json_mode:
            config_kwargs["response_mime_type"] = "application/json"

        config = types.GenerateContentConfig(**config_kwargs)

        text = await self._generate_with_retries(model, contents, config)

        if not json_mode:
            return text

        if _is_valid_json(text):
            return text

        logger.warning(
            "Gemini JSON mode returned invalid JSON on first attempt | model=%s — retrying once.",
            model,
        )
        text = await self._generate_with_retries(model, contents, config)

        if _is_valid_json(text):
            return text

        logger.error("Gemini JSON mode still invalid after retry | model=%s", model)
        raise ProviderError(
            "Gemini returned invalid JSON after one retry in json_mode."
        )

    # ── Internal: transient-error-resilient single generation ────────────────

    async def _generate_with_retries(
        self,
        model: str,
        contents: list,
        config: "types.GenerateContentConfig",
    ) -> str:
        """
        Run one generation call, retrying up to self._max_retries extra
        times on transient failures (rate limit, timeout, server error,
        network). Authentication errors are never retried — bad
        credentials cannot succeed on a second attempt.
        """
        last_exc: Optional[Exception] = None
        attempts = self._max_retries + 1

        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            try:
                text = await asyncio.wait_for(
                    asyncio.to_thread(self._call_sync, model, contents, config),
                    timeout=self._timeout,
                )
                latency_ms = (time.monotonic() - started) * 1000
                logger.info(
                    "Gemini generate ok | model=%s | attempt=%d/%d | latency=%.0fms",
                    model, attempt, attempts, latency_ms,
                )
                return text

            except asyncio.TimeoutError:
                latency_ms = (time.monotonic() - started) * 1000
                logger.warning(
                    "Gemini timeout | model=%s | attempt=%d/%d | after=%.0fms | limit=%ds",
                    model, attempt, attempts, latency_ms, self._timeout,
                )
                last_exc = ProviderTimeoutError(
                    f"Gemini request exceeded {self._timeout}s timeout."
                )

            except ProviderAuthError:
                # Retrying with the same bad credentials can never succeed.
                logger.error("Gemini authentication error | model=%s — not retrying.", model)
                raise

            except ProviderError as exc:
                latency_ms = (time.monotonic() - started) * 1000
                logger.warning(
                    "Gemini failure | model=%s | attempt=%d/%d | after=%.0fms | %s: %s",
                    model, attempt, attempts, latency_ms, type(exc).__name__, exc,
                )
                last_exc = exc

            if attempt < attempts:
                await asyncio.sleep(min(2 ** (attempt - 1), 8))  # simple capped backoff

        logger.error(
            "Gemini exhausted all %d attempt(s) | model=%s | last_error=%s",
            attempts, model, last_exc,
        )
        raise last_exc or ProviderError("Gemini request failed for an unknown reason.")

    # ── Internal: the actual blocking SDK call, run via asyncio.to_thread ────

    def _call_sync(self, model: str, contents: list, config: "types.GenerateContentConfig") -> str:
        """
        Blocking google-genai call. Always run through asyncio.to_thread()
        by the caller — this method itself must stay synchronous since the
        SDK's primary client is sync.
        """
        try:
            response = self._client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
        except Exception as exc:
            raise _classify_error(exc) from exc

        text = getattr(response, "text", None)
        if text is None:
            # Defensive fallback in case a future SDK response shape ever
            # stops populating `.text` directly.
            text = _extract_text_from_response(response)

        return text or ""


# ── Message conversion: OpenAI-style -> google-genai Content objects ──────────

def _convert_messages(messages: list[dict]) -> tuple[Optional[str], list]:
    """
    Convert the project's OpenAI-style message list into
    (system_instruction, contents) for GenerateContentConfig and
    client.models.generate_content(contents=...).

    Gemini has no "system" role inside `contents` — system messages are
    collected separately and passed via system_instruction. "assistant"
    maps to Gemini's "model" role; everything else maps to "user".
    """
    system_parts: list[str] = []
    contents: list = []

    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")

        if role == "system":
            text = _content_to_plain_text(content)
            if text:
                system_parts.append(text)
            continue

        gemini_role = "model" if role == "assistant" else "user"
        parts = _content_to_parts(content)
        if parts:
            contents.append(types.Content(role=gemini_role, parts=parts))

    system_instruction = "\n\n".join(system_parts) if system_parts else None
    return system_instruction, contents


def _content_to_parts(content) -> list:
    """Convert one message's `content` (str or content-block list) into Gemini Parts."""
    if isinstance(content, str):
        return [types.Part(text=content)] if content else []

    if isinstance(content, list):
        parts: list = []
        for block in content:
            block_type = block.get("type")
            if block_type == "text":
                text = block.get("text", "")
                if text:
                    parts.append(types.Part(text=text))
            elif block_type == "image_url":
                part = _image_block_to_part(block)
                if part is not None:
                    parts.append(part)
        return parts

    # Unknown content shape — coerce to text rather than silently dropping it.
    return [types.Part(text=str(content))] if content else []


def _content_to_plain_text(content) -> str:
    """Flatten a message's content into plain text (used for system messages)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "") for block in content if block.get("type") == "text"
        )
    return str(content) if content else ""


def _image_block_to_part(block: dict):
    """
    Convert an OpenAI-style {"type": "image_url", "image_url": {"url": "data:..."}}
    block into a google-genai Part carrying raw inline image bytes — the
    current, non-deprecated way to attach images with this SDK.
    """
    url = (block.get("image_url") or {}).get("url", "")
    if not url.startswith("data:"):
        logger.warning(
            "Gemini vision: only inline data: URLs are supported, got a remote URL — skipping."
        )
        return None

    try:
        header, b64data = url.split(",", 1)
        mime_type = header.split(";")[0].removeprefix("data:") or "image/jpeg"
        image_bytes = base64.b64decode(b64data)
    except (ValueError, binascii.Error) as exc:
        logger.warning("Gemini vision: could not decode inline image data: %s", exc)
        return None

    return types.Part(inline_data=types.Blob(data=image_bytes, mime_type=mime_type))


def _extract_text_from_response(response) -> str:
    """
    Defensive fallback for assembling text if response.text is unexpectedly
    empty/None — walks candidates/parts directly instead.
    """
    try:
        candidates = getattr(response, "candidates", None) or []
        chunks: list[str] = []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) or []
            for part in parts:
                part_text = getattr(part, "text", None)
                if part_text:
                    chunks.append(part_text)
        return "".join(chunks)
    except Exception:
        return ""


def _is_valid_json(text: str) -> bool:
    """Structural JSON validity check used to enforce json_mode's contract."""
    if not text or not text.strip():
        return False
    try:
        json.loads(text)
        return True
    except (json.JSONDecodeError, ValueError):
        return False


# ── Error classification ───────────────────────────────────────────────────────

def _classify_error(exc: Exception) -> ProviderError:
    """
    Map a raw google-genai (or lower-level network) exception onto this
    project's ProviderError hierarchy, so callers never see a raw SDK type.

    Uses the SDK's structured error classes when importable (see the
    best-effort `_genai_errors` import above), falls back to an HTTP-style
    `.code` attribute, and finally to keyword-matching the exception
    message — covering authentication, rate-limit/quota, timeout,
    invalid-request, and server errors without assuming one fixed SDK
    exception taxonomy.
    """
    message = str(exc)
    lowered = message.lower()
    code = getattr(exc, "code", None)

    # 1. Structured SDK exception classes, if importable.
    if _genai_errors is not None:
        server_error_cls = getattr(_genai_errors, "ServerError", None)
        client_error_cls = getattr(_genai_errors, "ClientError", None)

        if server_error_cls is not None and isinstance(exc, server_error_cls):
            return ProviderError(f"Gemini server error: {message}")

        if client_error_cls is not None and isinstance(exc, client_error_cls):
            if code in (401, 403) or any(hint in lowered for hint in _AUTH_HINTS):
                return ProviderAuthError(f"Gemini authentication error: {message}")
            if code == 429 or any(hint in lowered for hint in _RATE_LIMIT_HINTS):
                return ProviderRateLimitError(f"Gemini rate limit/quota exceeded: {message}")
            return ProviderError(f"Gemini invalid request: {message}")

    # 2. HTTP-style status code fallback (covers APIError or any bare
    #    exception that still carries `.code` without matching a subclass above).
    if isinstance(code, int):
        if code in (401, 403):
            return ProviderAuthError(f"Gemini authentication error: {message}")
        if code == 429:
            return ProviderRateLimitError(f"Gemini rate limit/quota exceeded: {message}")
        if code >= 500:
            return ProviderError(f"Gemini server error: {message}")
        if code >= 400:
            return ProviderError(f"Gemini invalid request: {message}")

    # 3. Keyword-based last resort (network errors, or exception types that
    #    carry neither a recognizable class nor a `.code`).
    if any(hint in lowered for hint in _AUTH_HINTS):
        return ProviderAuthError(f"Gemini authentication error: {message}")
    if any(hint in lowered for hint in _RATE_LIMIT_HINTS):
        return ProviderRateLimitError(f"Gemini rate limit/quota exceeded: {message}")
    if "timeout" in lowered or "timed out" in lowered:
        return ProviderTimeoutError(f"Gemini request timed out: {message}")
    if "network" in lowered or "connection" in lowered:
        return ProviderError(f"Gemini network error: {message}")

    return ProviderError(f"Gemini error: {message}")
