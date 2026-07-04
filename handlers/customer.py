"""
Gold Bot v2 – Customer Handler
================================
Handles all customer-facing interactions:
    cmd_start              – /start welcome
    handle_customer_text   – text → SearchService → AIService → reply (+ photos)
    handle_customer_photo  – image → AIService (vision) → reply

Product photo delivery
-----------------------
Two complementary paths send a product photo to the customer:

1. FAST PATH (no AI call): the customer is in "ask about this product" mode
   (conv_state.current_product_id is set, via the 🤖 channel button) and their
   message contains an explicit photo-request keyword (عکس / تصویر / نشون بده …).
   The photo is sent immediately — cheaper and faster than waiting on the AI.

2. AI PATH: during normal chat, the AI is instructed (see ai_service.py) to
   embed [IMAGE:<product_id>] markers in its reply whenever the customer asks
   to see a specific product's photo. Those markers are parsed out by
   AIService and the corresponding photos are sent right after the AI's text
   reply. As a safety net, if the customer's message clearly asked for a photo
   but the AI forgot the marker, the bot falls back to sending the photo of
   the single best-matching product.
"""

import asyncio
import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from config.config import IMAGE_REQUEST_KEYWORDS
from keyboards.customer_keyboard import build_support_keyboard, build_notify_keyboard
from services.ai_service import AIService
from services.customer_service import CustomerService
from services.gold_service import GoldService
from services.publish_service import send_product_photo
from services.search_service import extract_filters, filter_products
from services.sheet_service import SheetService
from services.telegram_service import notify_admin_support
from utils.cache import Cache

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _services(context: ContextTypes.DEFAULT_TYPE) -> tuple[SheetService, GoldService, AIService, Cache, CustomerService]:
    return (
        context.bot_data["sheet_service"],
        context.bot_data["gold_service"],
        context.bot_data["ai_service"],
        context.bot_data["cache"],
        context.bot_data.get("customer_service"),
    )


def _wants_photo(text: str) -> bool:
    """True if the customer's message explicitly asks to see a photo."""
    t = text.strip().lower()
    return any(kw in t for kw in IMAGE_REQUEST_KEYWORDS)


def _has_specific_preference(conv_state) -> bool:
    """True if the customer has expressed at least one specific product preference."""
    p = conv_state.preferences
    return any([p.budget, p.category, p.gold_color, p.stone, p.max_weight, p.gender])


async def _send_images(
    context: ContextTypes.DEFAULT_TYPE,
    sheet: SheetService,
    chat_id: int,
    product_ids: list[int],
) -> None:
    """Send one or more product photos to the customer's chat, best-effort."""
    for pid in product_ids:
        product = await asyncio.to_thread(sheet.get_product_by_id, pid)
        if product is None:
            logger.warning("AI requested image for unknown product id=%d.", pid)
            continue
        await send_product_photo(context.bot, chat_id, product)


# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, _, cache = _services(context)
    user = update.effective_user
    cache.stats.record_message(user.id)

    sheet, _, _, _ = _services(context)
    settings = await asyncio.to_thread(sheet.get_settings)
    store_name = settings.get("store_name", "فروشگاه جواهرات")

    await update.message.reply_text(
        f"💍 *به {store_name} خوش آمدید!*\n\n"
        "من مونا هستم، مشاور فروش جواهرات شما. 🤖✨\n\n"
        "می‌توانید:\n"
        "• درباره هر نوع جواهری بپرسید\n"
        "• بودجه و سلیقه‌تان را بگویید\n"
        "• تصویر جواهر دلخواهتان را بفرستید\n"
        "• درخواست عکس هر محصول را بدهید\n"
        "• قیمت‌ها را بررسی کنید\n\n"
        "چطور می‌توانم کمکتان کنم؟",
        parse_mode="Markdown",
    )


# ── Fast path: direct photo request while focused on one product ──────────────

async def _try_fast_photo_path(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_message: str,
) -> bool:
    """
    If the customer is in "ask about this product" mode and explicitly asks
    for a photo, send it immediately without calling the AI.

    Returns True if this path handled the message (caller should stop).
    """
    sheet, _, _, cache, _ = _services(context)
    user_id = update.effective_user.id
    conv_state = cache.get_conversation(user_id)

    if not conv_state.current_product_id:
        return False
    if not _wants_photo(user_message):
        return False

    product = await asyncio.to_thread(sheet.get_product_by_id, conv_state.current_product_id)
    conv_state.current_product_id = None  # one-shot, same as the AI path

    if product is None:
        cache.save_conversation(conv_state)
        return False

    sent = await send_product_photo(context.bot, update.effective_chat.id, product)

    if sent:
        reply_text = f"📸 عکس «{product.name}» ارسال شد. سوال دیگری دارید؟"
    else:
        reply_text = "⚠️ متأسفم، نتوانستم تصویر این محصول را دریافت کنم."

    # Keep conversation history consistent even though the AI wasn't called
    conv_state.messages.append({"role": "user", "content": user_message})
    conv_state.messages.append({"role": "assistant", "content": reply_text})
    conv_state.response_count += 1
    cache.save_conversation(conv_state)

    await update.message.reply_text(reply_text)
    return True


# ── Main message processor ────────────────────────────────────────────────────

async def _process_ai_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_message: str,
    image_bytes: bytes | None = None,
) -> None:
    sheet, gold, ai, cache, cust_svc = _services(context)
    user      = update.effective_user
    user_id   = user.id
    chat_id   = update.effective_chat.id

    cache.stats.record_message(user_id)

    # ── Fast path: explicit photo request for the currently focused product ──
    if image_bytes is None and await _try_fast_photo_path(update, context, user_message):
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    products_task = asyncio.to_thread(sheet.get_products)
    faqs_task     = asyncio.to_thread(sheet.get_faqs)
    settings_task = asyncio.to_thread(sheet.get_settings)
    gold_task     = asyncio.to_thread(gold.get_gold_price)
    products, faqs, settings, gold_price = await asyncio.gather(
        products_task, faqs_task, settings_task, gold_task
    )

    conv_state = cache.get_conversation(user_id)

    # Update accumulated preferences from this message
    filters = extract_filters(user_message)
    prefs   = conv_state.preferences
    if filters.max_budget:     prefs.budget     = filters.max_budget
    if filters.gender:         prefs.gender     = filters.gender
    if filters.gold_color:     prefs.gold_color = filters.gold_color
    if filters.stone:          prefs.stone      = filters.stone
    if filters.category:       prefs.category   = filters.category
    if filters.max_weight:     prefs.max_weight = filters.max_weight
    if filters.occasion:       prefs.occasion   = filters.occasion
    if filters.style_keywords: prefs.style_keywords = filters.style_keywords

    # ── Focused "ask about this product" mode (non-photo question) ───────────
    if conv_state.current_product_id:
        product = await asyncio.to_thread(sheet.get_product_by_id, conv_state.current_product_id)
        if product:
            try:
                text, needs_support, image_ids = await ai.get_product_response(
                    conv_state, product, gold_price, user_message, settings
                )
            except Exception as exc:
                logger.error("AI product response error for user %d: %s", user_id, exc)
                text, needs_support, image_ids = (
                    "متأسفم، در حال حاضر مشکل فنی داریم. لطفاً دوباره تلاش کنید.", False, []
                )
            conv_state.current_product_id = None
            cache.save_conversation(conv_state)

            await update.message.reply_text(text, parse_mode="Markdown")

            # AI marker path
            if image_ids:
                await _send_images(context, sheet, chat_id, image_ids)
            # Defensive fallback: customer asked for a photo but AI forgot the marker
            elif _wants_photo(user_message):
                await send_product_photo(context.bot, chat_id, product)

            if needs_support:
                await _escalate_to_support(update, context, user, user_message, cache)
            return

    # ── Normal AI chat flow ────────────────────────────────────────────────────
    combined_filters = extract_filters(user_message)
    if prefs.budget and not combined_filters.max_budget:
        combined_filters.max_budget = prefs.budget
    if prefs.gender and not combined_filters.gender:
        combined_filters.gender = prefs.gender
    if prefs.gold_color and not combined_filters.gold_color:
        combined_filters.gold_color = prefs.gold_color
    if prefs.category and not combined_filters.category:
        combined_filters.category = prefs.category

    matching = filter_products(products, combined_filters, gold_price)
    logger.info("User %d | '%s' | %d matching products", user_id, user_message[:50], len(matching))

    try:
        text, needs_support, image_ids = await ai.get_response(
            conv_state, user_message, matching, gold_price, faqs, settings, image_bytes
        )
    except Exception as exc:
        logger.error("AI error for user %d: %s", user_id, exc)
        text, needs_support, image_ids = (
            "⚠️ در حال حاضر مشکل فنی داریم. لطفاً چند لحظه دیگر تلاش کنید.", False, []
        )

    cache.save_conversation(conv_state)

    await update.message.reply_text(text, parse_mode="Markdown")

    # ── Send product photo(s) ──────────────────────────────────────────────────
    if image_ids:
        await _send_images(context, sheet, chat_id, image_ids)
    elif image_bytes is None and _wants_photo(user_message) and len(matching) >= 1:
        await _send_images(context, sheet, chat_id, [matching[0].id])

    # ── Save customer interests to Google Sheets (background, non-blocking) ───
    if cust_svc and conv_state.preferences.to_text() != "بدون ترجیح خاص":
        asyncio.create_task(asyncio.to_thread(
            cust_svc.upsert_customer,
            user_id,
            user.full_name or str(user_id),
            conv_state,
        ))

    # ── Offer restock notification if customer showed clear product interest ──
    if (
        not needs_support
        and not conv_state.support_requested
        and _has_specific_preference(conv_state)
        and conv_state.response_count % 5 == 0   # show offer every 5 turns
    ):
        await update.message.reply_text(
            "🔔 می‌خواهید وقتی محصول مورد نظرتان موجود شد، به شما اطلاع دهیم؟",
            reply_markup=build_notify_keyboard(),
        )

    if needs_support:
        await _escalate_to_support(update, context, user, user_message, cache)


async def _escalate_to_support(update, context, user, last_message: str, cache: Cache) -> None:
    """Add to support queue, notify admin, tell the customer."""
    user_id   = user.id
    user_name = user.full_name or str(user_id)

    cache.add_support_message(user_id, "user", last_message)

    conv = cache.get_conversation(user_id)
    conv.support_requested = True
    cache.save_conversation(conv)

    await notify_admin_support(context.bot, user_id, user_name, last_message)

    await update.message.reply_text(
        "🧑‍💼 درخواست شما ثبت شد.\n"
        "یکی از کارشناسان ما به زودی پاسخ می‌دهد.",
        reply_markup=build_support_keyboard(),
    )


# ── Text messages ─────────────────────────────────────────────────────────────

async def handle_customer_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""
    await _process_ai_message(update, context, text)


# ── Photo / image messages ────────────────────────────────────────────────────

async def handle_customer_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Download the highest-resolution photo the customer sent and pass it to
    the AI with any accompanying caption text.
    """
    caption = update.message.caption or "تصویری ارسال کردم. محصول مشابه دارید؟"

    try:
        photo_file  = await update.message.photo[-1].get_file()
        image_bytes = bytes(await photo_file.download_as_bytearray())
    except Exception as exc:
        logger.error("Failed to download customer photo: %s", exc)
        await update.message.reply_text("⚠️ نتوانستم تصویر را دریافت کنم. لطفاً دوباره تلاش کنید.")
        return

    await _process_ai_message(update, context, caption, image_bytes=image_bytes)
