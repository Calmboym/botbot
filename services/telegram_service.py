"""
Gold Bot v2 – Telegram Service
================================
Utility functions for bot-to-bot and bot-to-user interactions
that don't belong to publishing or AI.
"""

import logging
from telegram import Bot
from telegram.error import Forbidden, TelegramError

from config.config import ADMIN_ID
from utils.cache import BotStats

logger = logging.getLogger(__name__)


async def notify_admin_support(
    bot: Bot,
    user_id: int,
    user_name: str,
    user_message: str,
) -> None:
    """
    Forward a support escalation request to the admin.
    Sends a notification message to ADMIN_ID.
    """
    text = (
        f"🆘 *درخواست پشتیبانی*\n\n"
        f"👤 کاربر: [{user_name}](tg://user?id={user_id}) (`{user_id}`)\n\n"
        f"💬 پیام:\n_{user_message}_"
    )
    try:
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=text,
            parse_mode="Markdown",
        )
        logger.info("Support notification sent to admin for user %d.", user_id)
    except TelegramError as exc:
        logger.error("Could not notify admin about support request: %s", exc)


async def send_admin_reply_to_customer(
    bot: Bot,
    user_id: int,
    reply_text: str,
) -> bool:
    """
    Forward admin's reply back to the customer.
    Returns True on success, False if the customer has blocked the bot.
    """
    text = f"👨‍💼 *پشتیبانی فروشگاه:*\n\n{reply_text}"
    try:
        await bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
        logger.info("Admin reply forwarded to user %d.", user_id)
        return True
    except Forbidden:
        logger.warning("User %d has blocked the bot; cannot send reply.", user_id)
        return False
    except TelegramError as exc:
        logger.error("Failed to forward reply to user %d: %s", user_id, exc)
        return False


def format_statistics(sheet_stats: dict, bot_stats: BotStats) -> str:
    """Build the statistics message for the admin panel."""
    cats = sheet_stats.get("categories", {})
    cat_lines = "\n".join(
        f"  • {cat}: {cnt} محصول"
        for cat, cnt in list(cats.items())[:8]
    )
    cat_block = cat_lines if cat_lines else "  (داده‌ای موجود نیست)"

    return (
        f"📊 *آمار فروشگاه*\n\n"
        f"📦 کل محصولات: `{sheet_stats['total']}`\n"
        f"✅ فعال: `{sheet_stats['active']}`\n"
        f"📢 منتشر شده در کانال: `{sheet_stats['published']}`\n"
        f"⏸ پیش‌نویس: `{sheet_stats['draft']}`\n"
        f"❌ فروخته شده: `{sheet_stats['sold']}`\n"
        f"⚠️ ناموجود (موجودی ۰): `{sheet_stats['no_stock']}`\n\n"
        f"👥 کاربران منحصربه‌فرد: `{len(bot_stats.unique_users)}`\n"
        f"💬 پیام‌های امروز: `{bot_stats.today_count()}`\n\n"
        f"🏷️ *دسته‌بندی‌ها:*\n{cat_block}"
    )
