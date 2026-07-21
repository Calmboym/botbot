"""
Gold Bot v2 – Customer Handler
================================
AI-driven, provider-independent customer chat flow.

Flow per message:
    1. Cheap local checks first (fast photo path, zero AI calls).
    2. local_extract() seeds a same-turn SearchQuery from the raw message
       (regex, no AI call) merged with the customer's cumulative profile.
    3. search_service.search() ranks real products by relevance — the AI
       only ever sees this short, scored candidate list.
    4. ONE AI call (AIService) returns a structured AIResponse: reply text,
       support flag, image IDs, and this turn's IntentExtraction — all in
       a single JSON response (see services/ai_service.py for why).
    5. The extracted intent is merged (never overwritten) into the
       customer's cumulative CustomerProfile and persisted to Sheets.
    6. The rolling ConversationSummary is regenerated periodically instead
       of ever sending full history to the AI.
"""

import asyncio
import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from config.config import IMAGE_REQUEST_KEYWORDS, RECENT_MESSAGES_COUNT
from keyboards.customer_keyboard import build_notify_keyboard, build_support_keyboard
from services.ai_service import AIService
from services.customer_service import CustomerService
from services.gold_service import GoldService
from services.price_service import calculate_price, currency_label, normalize_intent_budget
from services.publish_service import send_product_photo
from services.search_service import build_query, find_unavailable_match, search
from services.sheet_service import SheetService
from services.summary_service import SummaryService
from services.telegram_service import notify_admin_order, notify_admin_support
from utils.cache import Cache, ConversationState

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _services(context: ContextTypes.DEFAULT_TYPE):
    return (
        context.bot_data["sheet_service"],
        context.bot_data["gold_service"],
        context.bot_data["ai_service"],
        context.bot_data["cache"],
        context.bot_data.get("customer_service"),
        context.bot_data.get("summary_service"),
        context.bot_data.get("stock_notification_service"),
    )


def _wants_photo(text: str) -> bool:
    """Cheap, local, NO-AI-CALL check for an explicit photo request."""
    t = text.strip().lower()
    return any(kw in t for kw in IMAGE_REQUEST_KEYWORDS)


async def _send_images(context, sheet: SheetService, chat_id: int, product_ids: list[int]) -> None:
    for pid in product_ids:
        product = await asyncio.to_thread(sheet.get_product_by_id, pid)
        if product is None:
            logger.warning("AI requested image for unknown product id=%d.", pid)
            continue
        await send_product_photo(context.bot, chat_id, product)


async def _ensure_profile_loaded(
    conv_state: ConversationState,
    cust_svc: "CustomerService",
    user_id: int,
    user_name: str,
) -> None:
    """
    On a FRESH in-memory session (new process, or conversation TTL expired)
    the profile starts empty. Try to reload it from Google Sheets so
    returning customers keep their preferences across sessions, not just
    within one in-memory window — this is what makes the profile truly
    cumulative rather than merely per-session.
    """
    conv_state.profile.name = user_name
    if conv_state.profile.has_any_preference() or conv_state.profile.updated_at:
        return  # already populated this session
    if not cust_svc:
        return
    try:
        loaded = await asyncio.to_thread(cust_svc.load_profile, user_id)
        if loaded:
            loaded.name = user_name
            conv_state.profile = loaded
            logger.info("Reloaded persisted profile for returning user %d.", user_id)
    except Exception as exc:
        logger.warning("Could not reload profile for user %d: %s", user_id, exc)


async def _persist_profile(cust_svc: "CustomerService", conv_state: ConversationState) -> None:
    if cust_svc and conv_state.profile.has_any_preference():
        asyncio.create_task(asyncio.to_thread(cust_svc.save_profile, conv_state.profile))


# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sheet, _, _, cache, _, _, _ = _services(context)
    user = update.effective_user
    cache.stats.record_message(user.id)

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

async def _try_fast_photo_path(update: Update, context: ContextTypes.DEFAULT_TYPE, user_message: str) -> bool:
    """Zero-AI-call path: explicit photo keyword while focused on one product."""
    sheet, _, _, cache, _, _, _ = _services(context)
    user_id = update.effective_user.id
    conv_state = cache.get_conversation(user_id)

    if not conv_state.current_product_id or not _wants_photo(user_message):
        return False

    product = await asyncio.to_thread(sheet.get_product_by_id, conv_state.current_product_id)
    conv_state.current_product_id = None

    if product is None:
        cache.save_conversation(conv_state)
        return False

    sent = await send_product_photo(context.bot, update.effective_chat.id, product)
    reply_text = (
        f"📸 عکس «{product.name}» ارسال شد. سوال دیگری دارید؟"
        if sent else "⚠️ متأسفم، نتوانستم تصویر این محصول را دریافت کنم."
    )

    conv_state.recent_messages.append({"role": "user", "content": user_message})
    conv_state.recent_messages.append({"role": "assistant", "content": reply_text})
    conv_state.recent_messages = conv_state.recent_messages[-RECENT_MESSAGES_COUNT:]
    conv_state.summary.messages_since_update += 2
    cache.save_conversation(conv_state)

    await update.message.reply_text(reply_text)
    return True


# ── Apply one AI turn's output ─────────────────────────────────────────────────

async def _apply_ai_response(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    cache: Cache,
    conv_state: ConversationState,
    user_message: str,
    ai_response,
    sheet: SheetService,
    chat_id: int,
) -> None:
    """Send the reply, roll the message window, save state, send any images."""
    await update.message.reply_text(ai_response.reply, parse_mode="Markdown")

    conv_state.recent_messages.append({"role": "user", "content": user_message})
    conv_state.recent_messages.append({"role": "assistant", "content": ai_response.reply})
    conv_state.recent_messages = conv_state.recent_messages[-RECENT_MESSAGES_COUNT:]
    conv_state.summary.messages_since_update += 2
    conv_state.response_count += 1

    cache.save_conversation(conv_state)

    if ai_response.image_product_ids:
        await _send_images(context, sheet, chat_id, ai_response.image_product_ids)


# ── Main message processor ────────────────────────────────────────────────────

async def _process_ai_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_message: str,
    image_bytes: bytes | None = None,
) -> None:
    sheet, gold, ai, cache, cust_svc, summary_svc, stock_svc = _services(context)
    user    = update.effective_user
    user_id = user.id
    chat_id = update.effective_chat.id

    cache.stats.record_message(user_id)

    # ── Fast path: explicit photo request for the currently focused product ──
    if image_bytes is None and await _try_fast_photo_path(update, context, user_message):
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    products, faqs, settings, gold_price = await asyncio.gather(
        asyncio.to_thread(sheet.get_products),
        asyncio.to_thread(sheet.get_faqs),
        asyncio.to_thread(sheet.get_settings),
        asyncio.to_thread(gold.get_gold_price),
    )

    conv_state = cache.get_conversation(user_id)
    await _ensure_profile_loaded(conv_state, cust_svc, user_id, user.full_name or str(user_id))

    # ── Focused "ask about this product" mode (non-photo question) ───────────
    if conv_state.current_product_id:
        product = await asyncio.to_thread(sheet.get_product_by_id, conv_state.current_product_id)
        conv_state.current_product_id = None

        if product:
            price = calculate_price(product, gold_price)

            # ── Task 3: product unavailable → silently remember the request ──
            # Deterministic, same availability check search_service already
            # uses to decide what the AI gets to see — no AI/prompt involved,
            # nothing shown to the customer here (see stock_notification_service
            # module docstring for why this is a separate system from the
            # existing preference-based notify_interested_customers).
            if not product.is_available and stock_svc:
                asyncio.create_task(asyncio.to_thread(
                    stock_svc.add_request,
                    user_id, user.full_name or str(user_id), chat_id, product.id, product.name,
                ))

            try:
                ai_response = await ai.handle_product_question(
                    profile=conv_state.profile,
                    summary=conv_state.summary,
                    recent_messages=conv_state.recent_messages,
                    product=product,
                    price=price,
                    user_question=user_message,
                    settings=settings,
                )
            except Exception as exc:
                logger.error("AI product-question error for user %d: %s", user_id, exc, exc_info=True)
                await update.message.reply_text(
                    "متأسفم، در حال حاضر مشکل فنی داریم. لطفاً دوباره تلاش کنید."
                )
                return

            await _apply_ai_response(update, context, cache, conv_state, user_message, ai_response, sheet, chat_id)
            normalized_intent = normalize_intent_budget(ai_response.intent, settings)
            conv_state.profile = conv_state.profile.merge_intent(normalized_intent)
            cache.save_conversation(conv_state)
            await _persist_profile(cust_svc, conv_state)

            if ai_response.needs_support:
                if product.is_available:
                    await _escalate_to_support(
                        update, context, user, user_message, cache,
                        product=product, price=price, gold_price=gold_price,
                        currency=currency_label(settings),
                    )
                else:
                    await _escalate_to_support(update, context, user, user_message, cache)
            return

    # ── Normal AI chat flow ────────────────────────────────────────────────────
    query = build_query(conv_state.profile, user_message, settings)
    search_result = search(products, query, gold_price, conv_state.profile)
    product_lines = [p.as_ai_line(currency=currency_label(settings)) for p in search_result.products]

    logger.info(
        "User %d | '%s' | %d products in context",
        user_id, user_message[:50], len(product_lines),
    )

    try:
        ai_response = await ai.handle_message(
            profile=conv_state.profile,
            summary=conv_state.summary,
            recent_messages=conv_state.recent_messages,
            user_message=user_message,
            product_lines=product_lines,
            faqs=faqs,
            settings=settings,
            image_bytes=image_bytes,
        )
    except Exception as exc:
        logger.error("AI error for user %d: %s", user_id, exc, exc_info=True)
        await update.message.reply_text(
            "⚠️ در حال حاضر مشکل فنی داریم. لطفاً چند لحظه دیگر تلاش کنید."
        )
        return

    await _apply_ai_response(update, context, cache, conv_state, user_message, ai_response, sheet, chat_id)

    # ── Merge this turn's extracted intent into the cumulative profile ────────
    # Budget values are normalized into store currency HERE — the single
    # choke point — before ever touching CustomerProfile/search comparisons.
    normalized_intent = normalize_intent_budget(ai_response.intent, settings)
    conv_state.profile = conv_state.profile.merge_intent(normalized_intent)

    # ── Task 3 (general flow): customer wants a notification — try to pin ────
    # it to one SPECIFIC unavailable product via the same weighted matching
    # the existing preference system uses (see search_service.
    # find_unavailable_match). This is what the focused "ask about this
    # product" branch above already does with a known product_id; this
    # covers ordinary free-text conversation, which is how customers
    # actually talk. Falls through silently to the broader notify_enabled
    # preference flag (already set by merge_intent above) when nothing
    # matches confidently — nothing is lost either way.
    if ai_response.intent.wants_notification and stock_svc:
        matched_product = find_unavailable_match(products, conv_state.profile, gold_price)
        if matched_product:
            asyncio.create_task(asyncio.to_thread(
                stock_svc.add_request,
                user_id, user.full_name or str(user_id), chat_id, matched_product.id, matched_product.name,
            ))

    # ── Defensive local fallback: customer clearly asked for a photo but ─────
    # the AI didn't include an image_product_ids entry.
    if (
        not ai_response.image_product_ids
        and image_bytes is None
        and _wants_photo(user_message)
        and search_result.products
    ):
        fallback_product = await asyncio.to_thread(sheet.get_product_by_id, search_result.products[0].id)
        if fallback_product:
            await send_product_photo(context.bot, chat_id, fallback_product)

    # ── Update rolling summary if enough messages have accumulated ───────────
    if summary_svc:
        conv_state.summary = await summary_svc.maybe_update(conv_state.summary, conv_state.recent_messages)

    cache.save_conversation(conv_state)
    await _persist_profile(cust_svc, conv_state)

    # ── Offer restock notification (follow-up system) ─────────────────────────
    # Triggered immediately by explicit request or high purchase-readiness,
    # otherwise offered periodically once the customer has shown any
    # concrete preference.
    show_notify_offer = (
        not ai_response.needs_support
        and not conv_state.support_requested
        and not conv_state.profile.notify_enabled
        and (
            ai_response.intent.wants_notification
            or ai_response.intent.purchase_readiness >= 70
            or (conv_state.profile.has_any_preference() and conv_state.response_count % 5 == 0)
        )
    )
    if show_notify_offer:
        await update.message.reply_text(
            "🔔 می‌خواهید وقتی محصول مورد نظرتان موجود شد، به شما اطلاع دهیم؟",
            reply_markup=build_notify_keyboard(),
        )

    if ai_response.needs_support:
        await _escalate_to_support(update, context, user, user_message, cache)


async def _escalate_to_support(
    update, context, user, last_message: str, cache: Cache,
    product=None, price: float | None = None, gold_price: float | None = None, currency: str | None = None,
) -> None:
    """
    Add to support queue, notify admin, tell the customer.

    Task 2: when `product` is passed (customer was focused on one specific
    AVAILABLE product right before escalating — see _process_ai_message),
    the admin gets the richer order notification with full product/price
    details instead of the generic support ping. This project has no
    separate checkout step, so this escalation is the closest concrete
    "customer wants to buy X" event that exists — see the notify_admin_order
    docstring in services/telegram_service.py for the full rationale.
    The customer-facing message below is identical either way.
    """
    user_id   = user.id
    user_name = user.full_name or str(user_id)

    cache.add_support_message(user_id, "user", last_message)

    conv = cache.get_conversation(user_id)
    conv.support_requested = True
    cache.save_conversation(conv)

    if product is not None:
        await notify_admin_order(
            context.bot, user_id, user_name, user.username,
            product, price or 0.0, gold_price or 0.0, currency or "",
        )
    else:
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
    the AI (vision model) with any accompanying caption text.
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
