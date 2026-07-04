"""
Gold Bot v2 – AI Service (Groq)
==================================
Powers the Persian jewelry sales assistant using the Groq Chat Completions API.

Key design decisions:
- Uses AsyncGroq for non-blocking calls.
- Maintains client-side conversation history (list of messages per user).
- Fresh product search results injected into every turn's context.
- System prompt allows AI to use its own knowledge for GENERAL questions
  (gold properties, jewelry care, stone types, etc.) while only
  recommending products that actually exist in the sheet.
- [SUPPORT] signal in AI response triggers escalation to admin.
- [IMAGE:<product_id>] signal(s) in AI response tell the caller which
  product photo(s) to send to the customer.
"""

from __future__ import annotations

import base64
import logging
import re
from typing import Optional, TYPE_CHECKING

from groq import AsyncGroq, RateLimitError, AuthenticationError

from config.config import (
    GROQ_API_KEY, GROQ_MODEL, GROQ_VISION_MODEL,
    SUPPORT_SIGNAL, MAX_CONV_RESPONSES, MAX_HISTORY_MSGS,
    IMAGE_SIGNAL_PATTERN, MAX_IMAGES_PER_REPLY,
)

if TYPE_CHECKING:
    from models.product import Product
    from utils.cache import ConversationState

from services.price_service import calculate_price

logger = logging.getLogger(__name__)

# AIResult = (response_text, needs_human_support, image_product_ids)
AIResult = tuple[str, bool, list[int]]


class AIService:
    def __init__(self) -> None:
        self._client = AsyncGroq(api_key=GROQ_API_KEY)

    # ── Public API ────────────────────────────────────────────────────────────

    async def get_response(
        self,
        conv_state: "ConversationState",
        user_message: str,
        products: list["Product"],
        gold_price: float,
        faqs: list[dict],
        settings: dict,
        image_bytes: Optional[bytes] = None,
    ) -> AIResult:
        """
        Generate a response for the customer's message.

        Returns (response_text, needs_human_support, image_product_ids).
        Updates conv_state.messages in-place with this turn.
        """
        if conv_state.response_count >= MAX_CONV_RESPONSES:
            logger.info("User %d: MAX_CONV_RESPONSES reached — resetting history.", conv_state.user_id)
            conv_state.messages = []
            conv_state.response_count = 0

        system_prompt = self._build_system_prompt(settings, conv_state)
        context_block = self._build_context(products, gold_price, faqs, conv_state)
        full_user_text = f"{context_block}\n\n---\nپیام مشتری: {user_message}"

        api_messages: list[dict] = [{"role": "system", "content": system_prompt}]
        api_messages.extend(conv_state.messages[-MAX_HISTORY_MSGS:])

        if image_bytes:
            b64 = base64.b64encode(image_bytes).decode("utf-8")
            user_content: object = [
                {"type": "text",      "text": full_user_text},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ]
            model = GROQ_VISION_MODEL
        else:
            user_content = full_user_text
            model = GROQ_MODEL

        api_messages.append({"role": "user", "content": user_content})

        return await self._call_and_store(conv_state, api_messages, user_message, model)

    async def get_product_response(
        self,
        conv_state: "ConversationState",
        product: "Product",
        gold_price: float,
        user_question: str,
        settings: dict,
    ) -> AIResult:
        """Focused single-product Q&A (triggered by 🤖 button on channel post)."""
        price = calculate_price(product, gold_price)
        context = (
            f"[محصول مورد نظر مشتری]\n"
            f"{product.admin_detail()}\n"
            f"قیمت تقریبی: {price:,.0f} تومان\n"
            f"(شناسه این محصول برای علامت [IMAGE:] برابر است با: {product.id})\n\n"
            f"---\n"
            f"پیام مشتری: {user_question}"
        )
        system = self._build_system_prompt(settings, conv_state)
        api_messages = [
            {"role": "system", "content": system},
            *conv_state.messages[-MAX_HISTORY_MSGS:],
            {"role": "user", "content": context},
        ]
        return await self._call_and_store(conv_state, api_messages, user_question, GROQ_MODEL)

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _call_and_store(
        self,
        conv_state: "ConversationState",
        api_messages: list[dict],
        original_user_text: str,
        model: str,
    ) -> AIResult:
        """Call Groq, handle errors, parse signals, store turn in history."""
        try:
            response = await self._client.chat.completions.create(
                model=model,
                messages=api_messages,
                temperature=0.7,
                max_tokens=1500,
            )
            ai_text = response.choices[0].message.content or ""

        except RateLimitError:
            logger.warning("Groq rate limit for user %d.", conv_state.user_id)
            return (
                "⚠️ سرور هوش مصنوعی در حال حاضر شلوغ است.\n"
                "لطفاً چند ثانیه صبر کنید و دوباره پیام بفرستید.",
                False, [],
            )
        except AuthenticationError:
            logger.error("Groq authentication failed — check GROQ_API_KEY in .env")
            return "⚠️ خطای پیکربندی سرور. لطفاً با مدیر فروشگاه تماس بگیرید.", False, []
        except Exception as exc:
            logger.error("Groq API error for user %d: %s", conv_state.user_id, exc, exc_info=True)
            return "⚠️ خطا در پردازش پیام. لطفاً دوباره تلاش کنید.", False, []

        # ── Extract [IMAGE:<id>] markers ─────────────────────────────────────
        image_ids: list[int] = []
        for match in re.findall(IMAGE_SIGNAL_PATTERN, ai_text):
            try:
                pid = int(match)
                if pid not in image_ids:
                    image_ids.append(pid)
            except ValueError:
                continue
        image_ids = image_ids[:MAX_IMAGES_PER_REPLY]

        text_no_images = re.sub(IMAGE_SIGNAL_PATTERN, "", ai_text)

        # ── Extract [SUPPORT] marker ──────────────────────────────────────────
        needs_support = SUPPORT_SIGNAL in text_no_images
        clean_text = text_no_images.replace(SUPPORT_SIGNAL, "")

        # Collapse extra blank lines/spaces left behind by removed markers
        clean_text = re.sub(r"[ \t]+\n", "\n", clean_text)
        clean_text = re.sub(r"\n{3,}", "\n\n", clean_text).strip()

        # Store this turn in history using clean text (no markers, no context block)
        conv_state.messages.append({"role": "user",      "content": original_user_text})
        conv_state.messages.append({"role": "assistant", "content": clean_text})
        conv_state.response_count += 1

        max_stored = MAX_HISTORY_MSGS * 2
        if len(conv_state.messages) > max_stored:
            conv_state.messages = conv_state.messages[-max_stored:]

        logger.info(
            "Groq response | user=%d | turn=%d | model=%s | escalate=%s | images=%s",
            conv_state.user_id, conv_state.response_count, model, needs_support, image_ids,
        )
        return clean_text, needs_support, image_ids

    def _build_system_prompt(
        self,
        settings: dict,
        conv_state: "ConversationState",
    ) -> str:
        store_name  = settings.get("store_name", "فروشگاه جواهرات")
        store_phone = settings.get("store_phone", "")
        currency    = settings.get("currency", "تومان")
        prefs_text  = conv_state.preferences.to_text()
        phone_line  = f"\nتلفن: {store_phone}" if store_phone else ""

        return f"""شما مونا هستید، مشاور فروش متخصص جواهرات در {store_name}.

**شخصیت:** گرم، حرفه‌ای، صادق و با دانش گسترده در حوزه طلا و جواهر.

**اطلاعات فروشگاه:**
نام: {store_name}{phone_line}
واحد پول: {currency}

**ترجیحات فعلی این مشتری:**
{prefs_text}

══════════════════════════════════════════════
قوانین پاسخ‌دهی:
══════════════════════════════════════════════

✅ سوالات عمومی → از دانش خودت استفاده کن:
   مثال‌ها: تفاوت عیارها، نگهداری طلا، انواع سنگ‌های قیمتی،
   روش تمیز کردن جواهرات، تفاوت طلا و نقره، خواص سنگ‌ها،
   مد و استایل، مناسب‌بودن برای مناسبت‌ها، ارزش سرمایه‌گذاری طلا،
   سوالات تاریخی یا فنی درباره جواهرات — اینها را با دانش کامل پاسخ بده.

✅ معرفی و توصیه محصول → فقط از لیست [PRODUCTS] استفاده کن:
   هرگز محصولی که در لیست نیست را اختراع نکن.
   هرگز قیمتی خارج از محاسبه لیست را اختراع نکن.
   فقط محصولات با موجودی > 0 را پیشنهاد بده.

✅ اگر سوال مشتری کلی و عمومی بود (مثلاً «چه محصولاتی دارید؟»، «موجودی چیه؟»)،
   تمام محصولات لیست [PRODUCTS] را معرفی کن — حتی اگر [KNOWN PREFERENCES]
   دسته یا ویژگی خاصی را نشان می‌دهد. ترجیحات قبلی را فقط زمانی اعمال کن
   که با سوال فعلی مرتبط باشد، نه برای محدود کردن یک سوال عمومی جدید.

✅ اگر محصولی در لیست موجود نبود، صادقانه بگو و بپرس چه مشخصات دیگری مدنظر دارند.

══════════════════════════════════════════════
📷 ارسال عکس محصول:
══════════════════════════════════════════════
هر محصول در [PRODUCTS] با یک شناسه (ID) مشخص شده است.

اگر مشتری صراحتاً خواست عکس/تصویر یک محصول مشخص را ببیند
(مثلاً: «عکسشو بفرست»، «تصویرشو نشون بده»، «می‌خوام ببینمش»)،
دقیقاً در همان نقطه از پاسخ (می‌تواند ابتدا، وسط یا انتهای متن باشد)
این علامت را برای هر محصول مدنظر اضافه کن:

[IMAGE:شناسه_محصول]

مثال: [IMAGE:5]

قوانین این علامت:
- فقط وقتی استفاده کن که مشتری واقعاً درخواست دیدن عکس داشته باشد.
- فقط شناسه محصولاتی که در لیست [PRODUCTS] واقعاً وجود دارند را استفاده کن.
- اگر مشتری چند محصول خواست، برای هرکدام یک علامت جداگانه بگذار (حداکثر 3 مورد).
- این علامت در پیام نهایی به مشتری نمایش داده نمی‌شود؛ فقط برای سیستم است،
  پس می‌توانی قبل یا بعد از آن جمله طبیعی مثل «الان عکسش رو براتون می‌فرستم»
  بنویسی.
══════════════════════════════════════════════

✅ اگر مشتری صراحتاً خواست با انسان صحبت کند، در انتهای پاسخ دقیقاً بنویس: {SUPPORT_SIGNAL}
══════════════════════════════════════════════"""

    def _build_context(
        self,
        products: list["Product"],
        gold_price: float,
        faqs: list[dict],
        conv_state: "ConversationState",
    ) -> str:
        parts: list[str] = []

        if products:
            lines = "\n".join(
                f"  • {p.ai_summary(calculate_price(p, gold_price))}"
                for p in products
            )
            parts.append(f"[PRODUCTS]\n{lines}")
        else:
            parts.append("[PRODUCTS]\nهیچ محصولی با این مشخصات در لیست فعلی نیست.")

        if faqs:
            faq_lines = "\n".join(
                f"  س: {f.get('question','')} | ج: {f.get('answer','')}"
                for f in faqs[:10]
            )
            parts.append(f"[FAQ]\n{faq_lines}")

        prefs = conv_state.preferences.to_text()
        if prefs and prefs != "بدون ترجیح خاص":
            parts.append(f"[KNOWN PREFERENCES]\n{prefs}")

        return "\n\n".join(parts)
