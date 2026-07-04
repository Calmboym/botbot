"""
Gold Bot v2 – Entry Point
==========================
Wires all services together, registers handlers, and starts polling.
Includes a JobQueue-based automatic gold price updater.

Run:
    python main.py
"""

import logging
import sys

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config.config import (
    TOKEN, ADMIN_ID,
    CACHE_TTL, CONVERSATION_TTL, ADMIN_STATE_TTL,
    PRICE_UPDATE_INTERVAL,
)
from handlers.admin import cmd_admin, handle_admin_message, handle_admin_photo
from handlers.callbacks import callback_router
from handlers.customer import cmd_start, handle_customer_text, handle_customer_photo
from services.ai_service import AIService
from services.customer_service import CustomerService
from services.gold_service import GoldService
from services.sheet_service import SheetService
from utils.cache import Cache
from utils.logger import setup_logger

logger = logging.getLogger(__name__)


# ── Scheduled job: automatic gold price update ────────────────────────────────

async def job_update_gold_price(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Runs on the configured PRICE_UPDATE_INTERVAL.
    Scrapes tgju.org and writes the new price to the settings sheet.
    Notifies the admin on Telegram whether it succeeded or failed.
    """
    gold_service: GoldService = context.bot_data["gold_service"]
    logger.info("JobQueue: starting automatic gold price update …")

    try:
        old_price = gold_service.get_gold_price()
    except Exception:
        old_price = 0.0

    try:
        new_price = await __import__("asyncio").to_thread(
            GoldService.scrape_with_retry, 3, 5
        )
        gold_service.update_gold_price(new_price)

        if old_price and old_price > 0:
            diff    = new_price - old_price
            pct     = (diff / old_price) * 100
            arrow   = "▲" if diff >= 0 else "▼"
            change  = f"\n{arrow} تغییر: {abs(diff):,.0f} تومان ({pct:+.2f}٪)"
        else:
            change  = ""

        msg = (
            f"🪙 *بروزرسانی خودکار قیمت طلا*\n\n"
            f"💰 قیمت جدید: `{new_price:,.0f} تومان/گرم`"
            f"{change}"
        )
        logger.info("Auto price update: %.0f → %.0f Toman/gram", old_price, new_price)

    except Exception as exc:
        msg = (
            f"⚠️ *بروزرسانی خودکار قیمت طلا ناموفق بود*\n\n"
            f"خطا: `{exc}`\n"
            f"قیمت فعلی دست‌نخورده باقی ماند."
        )
        logger.error("Auto price update failed: %s", exc, exc_info=True)

    # Notify admin
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=msg,
            parse_mode="Markdown",
        )
    except Exception as notify_err:
        logger.warning("Could not notify admin after price update: %s", notify_err)


# ── Combined message router ───────────────────────────────────────────────────

async def route_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Route text messages:
      - Admin in active flow  → admin state machine
      - Everyone else         → customer AI chat
    """
    if update.effective_user and update.effective_user.id == ADMIN_ID:
        cache: Cache = context.bot_data["cache"]
        state = cache.get_admin_state()
        if state.action:
            await handle_admin_message(update, context)
            return
    await handle_customer_text(update, context)


async def route_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Route photo messages:
      - Admin in an active image-upload step → Drive upload
      - Everyone else → customer AI photo handler
    """
    if update.effective_user and update.effective_user.id == ADMIN_ID:
        handled = await handle_admin_photo(update, context)
        if handled:
            return
    await handle_customer_photo(update, context)


# ── Application factory ───────────────────────────────────────────────────────

def build_application() -> Application:
    setup_logger()
    logger.info("Initialising Gold Bot v2 …")

    # ── Services ──────────────────────────────────────────────────────────────
    cache            = Cache(
        sheet_ttl=CACHE_TTL,
        conv_ttl=CONVERSATION_TTL,
        admin_ttl=ADMIN_STATE_TTL,
    )
    sheet_service    = SheetService(cache.sheet_cache)
    gold_service     = GoldService(sheet_service)
    ai_service       = AIService()
    customer_service = CustomerService()

    # ── Build application ─────────────────────────────────────────────────────
    application = Application.builder().token(TOKEN).build()

    application.bot_data["sheet_service"]    = sheet_service
    application.bot_data["gold_service"]     = gold_service
    application.bot_data["ai_service"]       = ai_service
    application.bot_data["customer_service"] = customer_service
    application.bot_data["cache"]            = cache

    # ── Commands ──────────────────────────────────────────────────────────────
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("admin", cmd_admin))

    # ── Text messages ─────────────────────────────────────────────────────────
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, route_text)
    )

    # ── Photo messages ────────────────────────────────────────────────────────
    application.add_handler(
        MessageHandler(filters.PHOTO, route_photo)
    )

    # ── Inline button callbacks ───────────────────────────────────────────────
    application.add_handler(CallbackQueryHandler(callback_router))

    # ── Automatic gold price update job ──────────────────────────────────────
    if PRICE_UPDATE_INTERVAL > 0:
        application.job_queue.run_repeating(
            callback=job_update_gold_price,
            interval=PRICE_UPDATE_INTERVAL,
            first=60,          # first run 60 seconds after bot starts
            name="auto_gold_price_update",
        )
        hours = PRICE_UPDATE_INTERVAL / 3600
        logger.info(
            "Auto gold price update scheduled every %.1f hour(s) "
            "(first run in 60 seconds).",
            hours,
        )
    else:
        logger.info(
            "Auto gold price update is DISABLED "
            "(PRICE_UPDATE_INTERVAL=0 in .env)."
        )

    logger.info("All handlers registered.")
    return application


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    app = build_application()
    logger.info("Bot is running — press Ctrl+C to stop.")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
