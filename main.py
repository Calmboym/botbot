"""
Gold Bot v2 – Entry Point
==========================
Supports two deployment modes, selected automatically by the presence of
the WEBHOOK_URL environment variable:

    WEBHOOK_URL set   →  Webhook mode  (production / Render)
    WEBHOOK_URL unset →  Polling mode  (local development)

Render deployment:
    1. Set WEBHOOK_URL = https://<your-service>.onrender.com  in Render env vars
    2. Render sets PORT automatically — no action needed
    3. Deploy → bot starts webhook automatically

Run locally (polling):
    python main.py          # WEBHOOK_URL not in .env → polling

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
    WEBHOOK_URL, PORT, WEBHOOK_SECRET,
)
from handlers.admin import cmd_admin, handle_admin_message, handle_admin_photo
from handlers.callbacks import callback_router
from handlers.customer import cmd_start, handle_customer_text, handle_customer_photo
from providers import get_provider
from services.ai_service import AIService
from services.customer_service import CustomerService
from services.gold_service import GoldService
from services.sheet_service import SheetService
from services.summary_service import SummaryService
from utils.cache import Cache
from utils.logger import setup_logger

logger = logging.getLogger(__name__)


# ── Scheduled job: automatic gold price update ────────────────────────────────

async def job_update_gold_price(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Runs on PRICE_UPDATE_INTERVAL schedule.
    Scrapes tgju.org and writes the new price to the settings sheet.
    Notifies the admin on Telegram on success or failure.
    """
    gold_service: GoldService = context.bot_data["gold_service"]
    logger.info("JobQueue: starting automatic gold price update …")

    try:
        old_price = gold_service.get_gold_price()
    except Exception:
        old_price = 0.0

    try:
        import asyncio as _asyncio
        new_price = await _asyncio.to_thread(GoldService.scrape_with_retry, 3, 5)
        gold_service.update_gold_price(new_price)

        if old_price and old_price > 0:
            diff   = new_price - old_price
            pct    = (diff / old_price) * 100
            arrow  = "▲" if diff >= 0 else "▼"
            change = f"\n{arrow} تغییر: {abs(diff):,.0f} تومان ({pct:+.2f}٪)"
        else:
            change = ""

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

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=msg,
            parse_mode="Markdown",
        )
    except Exception as notify_err:
        logger.warning("Could not notify admin after price update: %s", notify_err)


# ── Message routers ───────────────────────────────────────────────────────────

async def route_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin-in-flow → admin handler; everyone else → customer AI chat."""
    if update.effective_user and update.effective_user.id == ADMIN_ID:
        cache: Cache = context.bot_data["cache"]
        if cache.get_admin_state().action:
            await handle_admin_message(update, context)
            return
    await handle_customer_text(update, context)


async def route_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin in image step → save file_id; everyone else → customer AI."""
    if update.effective_user and update.effective_user.id == ADMIN_ID:
        if await handle_admin_photo(update, context):
            return
    await handle_customer_photo(update, context)


# ── Application factory ───────────────────────────────────────────────────────

def build_application() -> Application:
    setup_logger()
    logger.info("Initialising Gold Bot v2 …")

    # Services
    cache            = Cache(
        sheet_ttl=CACHE_TTL,
        conv_ttl=CONVERSATION_TTL,
        admin_ttl=ADMIN_STATE_TTL,
    )
    sheet_service    = SheetService(cache.sheet_cache)
    gold_service     = GoldService(sheet_service)

    # AI layer: provider-independent — switching AI_PROVIDER in .env is the
    # only change needed to use a different model/vendor (see providers/).
    ai_provider      = get_provider()
    ai_service       = AIService(ai_provider)
    summary_service  = SummaryService(ai_provider)
    customer_service = CustomerService()

    application = Application.builder().token(TOKEN).build()

    application.bot_data["sheet_service"]    = sheet_service
    application.bot_data["gold_service"]     = gold_service
    application.bot_data["ai_service"]       = ai_service
    application.bot_data["summary_service"]  = summary_service
    application.bot_data["customer_service"] = customer_service
    application.bot_data["cache"]            = cache

    # Handlers
    application.add_handler(CommandHandler("start",   cmd_start))
    application.add_handler(CommandHandler("admin",   cmd_admin))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, route_text))
    application.add_handler(MessageHandler(filters.PHOTO, route_photo))
    application.add_handler(CallbackQueryHandler(callback_router))

    # Scheduled gold price job
    if PRICE_UPDATE_INTERVAL > 0:
        application.job_queue.run_repeating(
            callback=job_update_gold_price,
            interval=PRICE_UPDATE_INTERVAL,
            first=60,
            name="auto_gold_price_update",
        )
        logger.info(
            "Auto gold price update: every %.1f hour(s), first run in 60 s.",
            PRICE_UPDATE_INTERVAL / 3600,
        )
    else:
        logger.info("Auto gold price update disabled (PRICE_UPDATE_INTERVAL=0).")

    logger.info("All handlers registered.")
    return application


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    app = build_application()

    if WEBHOOK_URL:
        # ── WEBHOOK MODE (Render / production) ────────────────────────────────
        # The url_path embeds the token as a secret so only Telegram can POST to it.
        webhook_path = f"webhook/{TOKEN}"
        full_url     = f"{WEBHOOK_URL}/{webhook_path}"

        logger.info("Starting in WEBHOOK mode.")
        logger.info("Port    : %d", PORT)
        logger.info("URL     : %s", full_url)
        logger.info("Secret  : %s", "set" if WEBHOOK_SECRET else "not set (optional)")

        app.run_webhook(
            listen          = "0.0.0.0",
            port            = PORT,
            url_path        = webhook_path,
            webhook_url     = full_url,
            secret_token    = WEBHOOK_SECRET or None,
            allowed_updates = Update.ALL_TYPES,
            drop_pending_updates = True,
        )

    else:
        # ── POLLING MODE (local development) ──────────────────────────────────
        logger.info(
            "WEBHOOK_URL not set → starting in POLLING mode "
            "(set WEBHOOK_URL in .env to switch to webhook)."
        )
        app.run_polling(
            allowed_updates      = Update.ALL_TYPES,
            drop_pending_updates = True,
        )


if __name__ == "__main__":
    main()
