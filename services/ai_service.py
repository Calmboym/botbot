"""
Gold Bot v2 – AI Service
==========================
Provider-independent orchestrator for the Persian jewelry sales assistant.

This module NEVER imports Groq/Gemini/OpenAI directly — it only talks to
the injected BaseAIProvider (see providers/base_provider.py). Switching
the underlying model is a one-line .env change (AI_PROVIDER=...), zero
changes here.

Cost / architecture design:
- ONE provider call per customer turn returns a single JSON object
  (validated as models.ai_models.AIResponse) containing BOTH the natural-
  language reply AND the extracted IntentExtraction. This halves API
  usage compared to running a separate intent-extraction call before
  every response.
- Output is always validated with Pydantic. On invalid/unparsable JSON,
  the call is retried once (AI_RETRY_COUNT) with a stricter reminder; if
  that also fails, a safe fallback AIResponse is returned. The bot never
  crashes on a bad model response.
"""

from __future__ import annotations

import base64
import logging
from typing import Optional, TYPE_CHECKING

from pydantic import ValidationError

from config.config import AI_MAX_TOKENS, AI_RETRY_COUNT, AI_TEMPERATURE, MAX_IMAGES_PER_REPLY
from models.ai_models import AIResponse, IntentExtraction
from providers.base_provider import BaseAIProvider, ProviderError
from utils.json_utils import extract_json_block

if TYPE_CHECKING:
    from models.ai_models import ConversationSummary, CustomerProfile
    from models.product import Product

logger = logging.getLogger(__name__)


_JSON_SCHEMA_INSTRUCTIONS = f"""
خروجی را **فقط** به‌صورت یک آبجکت JSON معتبر برگردان — بدون هیچ متن اضافه، بدون Markdown،
دقیقاً با این ساختار:

{{
  "reply": "متن پاسخ فارسی طبیعی که مستقیماً به مشتری نمایش داده می‌شود",
  "needs_support": false,
  "image_product_ids": [],
  "intent": {{
    "category": null,
    "gender": null,
    "gold_color": null,
    "stone": null,
    "max_budget": null,
    "min_budget": null,
    "max_weight": null,
    "min_weight": null,
    "style_keywords": [],
    "occasion": null,
    "shopping_stage": null,
    "urgency": null,
    "emotion": null,
    "purchase_readiness": 0,
    "interest_level": 0,
    "wants_notification": false
  }}
}}

مقادیر مجاز intent.shopping_stage: browsing, comparing, ready_to_buy, need_advice, gift_shopping, just_asking
مقادیر مجاز intent.urgency: low, medium, high
مقادیر مجاز intent.emotion: happy, neutral, excited, frustrated, uncertain

قوانین پر کردن intent:
- فقط فیلدهایی را پر کن که از همین پیام واقعاً قابل استنتاج هستند.
- اگر از shopping_stage / urgency / emotion مطمئن نیستی، آن‌ها را null بگذار
  (نه یک مقدار پیش‌فرض حدسی) — این مقادیر مستقیماً در پروفایل دائمی مشتری
  ذخیره می‌شوند و حدس اشتباه باعث گمراهی در آینده می‌شود.
- image_product_ids فقط باید شامل شناسه محصولاتی باشد که واقعاً در [PRODUCTS] هستند
  و مشتری صراحتاً خواسته عکسشان را ببیند (حداکثر {MAX_IMAGES_PER_REPLY} مورد).
- needs_support را فقط وقتی true بگذار که مشتری صراحتاً خواست با انسان صحبت کند
  یا مشکل جدی/پیچیده‌ای داشت که از عهده تو خارج است.
- هرگز چیزی خارج از این JSON ننویس.
"""


class AIService:
    def __init__(self, provider: BaseAIProvider) -> None:
        self._provider = provider

    # ── Public API ────────────────────────────────────────────────────────────

    async def handle_message(
        self,
        *,
        profile: "CustomerProfile",
        summary: "ConversationSummary",
        recent_messages: list[dict],
        user_message: str,
        product_lines: list[str],
        faqs: list[dict],
        settings: dict,
        image_bytes: Optional[bytes] = None,
    ) -> AIResponse:
        """
        Generate one structured turn for the customer.

        Returns a validated AIResponse — reply text, support flag, image
        product IDs, and this turn's extracted IntentExtraction. Never
        raises; returns a safe fallback AIResponse on any failure.
        """
        system_prompt = self._build_system_prompt(settings, profile, summary)
        context_block = self._build_context(product_lines, faqs)
        user_text = f"{context_block}\n\n---\nپیام مشتری: {user_message}"

        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        messages.extend(recent_messages)

        if image_bytes:
            b64 = base64.b64encode(image_bytes).decode("utf-8")
            content: object = [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ]
        else:
            content = user_text
        messages.append({"role": "user", "content": content})

        return await self._generate_structured(messages, vision=bool(image_bytes))

    async def handle_product_question(
        self,
        *,
        profile: "CustomerProfile",
        summary: "ConversationSummary",
        recent_messages: list[dict],
        product: "Product",
        price: float,
        user_question: str,
        settings: dict,
    ) -> AIResponse:
        """Focused single-product Q&A (triggered by the 🤖 channel button)."""
        system_prompt = self._build_system_prompt(settings, profile, summary)
        context = (
            f"[محصول مورد نظر مشتری]\n{product.admin_detail()}\n"
            f"قیمت تقریبی: {price:,.0f} تومان\n"
            f"شناسه این محصول برای image_product_ids: {product.id}\n\n"
            f"---\nپیام مشتری: {user_question}"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            *recent_messages,
            {"role": "user", "content": context},
        ]
        return await self._generate_structured(messages, vision=False)

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _generate_structured(self, messages: list[dict], *, vision: bool) -> AIResponse:
        last_error: Optional[Exception] = None

        for attempt in range(AI_RETRY_COUNT + 1):
            try:
                raw = await self._provider.generate(
                    messages,
                    temperature=AI_TEMPERATURE,
                    max_tokens=AI_MAX_TOKENS,
                    json_mode=True,
                    vision=vision,
                )
                data = extract_json_block(raw)
                response = AIResponse.model_validate(data)
                response.image_product_ids = response.image_product_ids[:MAX_IMAGES_PER_REPLY]

                logger.info(
                    "AI turn ok | provider=%s | attempt=%d | stage=%s | support=%s | images=%s",
                    self._provider.name, attempt + 1,
                    response.intent.shopping_stage.value if response.intent.shopping_stage else "?",
                    response.needs_support, response.image_product_ids,
                )
                return response

            except (ValueError, ValidationError) as exc:
                last_error = exc
                logger.warning(
                    "AI JSON parse/validation failed (attempt %d/%d): %s",
                    attempt + 1, AI_RETRY_COUNT + 1, exc,
                )
                if attempt < AI_RETRY_COUNT:
                    messages = [
                        *messages,
                        {
                            "role": "user",
                            "content": (
                                "خروجی قبلی معتبر نبود. لطفاً دقیقاً و فقط یک JSON معتبر "
                                "با ساختار درخواست‌شده برگردان، بدون هیچ متن اضافه."
                            ),
                        },
                    ]
                    continue

            except ProviderError as exc:
                last_error = exc
                logger.error("AI provider error (%s): %s", self._provider.name, exc)
                break

        logger.error("AI turn failed after retries; returning safe fallback. Last error: %s", last_error)
        return AIResponse(
            reply="⚠️ در حال حاضر مشکل فنی داریم. لطفاً چند لحظه دیگر دوباره تلاش کنید.",
            needs_support=False,
            image_product_ids=[],
            intent=IntentExtraction(),
        )

    def _build_system_prompt(
        self,
        settings: dict,
        profile: "CustomerProfile",
        summary: "ConversationSummary",
    ) -> str:
        store_name  = settings.get("store_name", "فروشگاه جواهرات")
        store_phone = settings.get("store_phone", "")
        currency    = settings.get("currency", "تومان")
        phone_line  = f"\nتلفن: {store_phone}" if store_phone else ""
        summary_block = summary.summary_text or "هنوز خلاصه‌ای ثبت نشده."

        return f"""شما مونا هستید، مشاور فروش متخصص جواهرات در {store_name}.

**شخصیت:** گرم، حرفه‌ای، صادق و با دانش گسترده در حوزه طلا و جواهر.

**اطلاعات فروشگاه:**
نام: {store_name}{phone_line}
واحد پول: {currency}

**پروفایل انباشته مشتری (از کل تاریخچه مکالمات):**
{profile.summary_text()}

**خلاصه مکالمه تا این لحظه:**
{summary_block}

══════════════════════════════════════════════
قوانین محتوایی:
══════════════════════════════════════════════
✅ سوالات عمومی (تفاوت عیار، نگهداری طلا، انواع سنگ، مد، ارزش سرمایه‌گذاری طلا، ...)
   → با دانش کامل خودت پاسخ بده.

✅ معرفی/توصیه محصول → فقط از لیست [PRODUCTS] استفاده کن:
   هرگز محصول یا قیمتی خارج از این لیست اختراع نکن؛ فقط موجودی > 0 پیشنهاد بده.

✅ اگر سوال کلی بود (مثل «چه محصولاتی دارید؟»)، همه [PRODUCTS] را معرفی کن،
   حتی اگر پروفایل مشتری محدودتر به نظر می‌رسد.

✅ اگر محصولی در لیست موجود نبود، صادقانه بگو و بپرس چه مشخصات دیگری مدنظر دارد.

{_JSON_SCHEMA_INSTRUCTIONS}
"""

    def _build_context(self, product_lines: list[str], faqs: list[dict]) -> str:
        parts: list[str] = []

        if product_lines:
            parts.append("[PRODUCTS]\n" + "\n".join(f"  • {line}" for line in product_lines))
        else:
            parts.append("[PRODUCTS]\nهیچ محصولی با این مشخصات در لیست فعلی نیست.")

        if faqs:
            faq_lines = "\n".join(
                f"  س: {f.get('question','')} | ج: {f.get('answer','')}" for f in faqs[:10]
            )
            parts.append(f"[FAQ]\n{faq_lines}")

        return "\n\n".join(parts)
