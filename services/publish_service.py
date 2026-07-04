"""
Gold Bot v2 – Publish Service
================================
Handles sending a product post to the Telegram channel and sending
a product photo directly to a customer's private chat.

Image approach: Telegram file_id
    The bot uses product.telegram_file_id (a Telegram-native file identifier)
    for all photo sends. No external hosting, no URL downloads, no Drive.
    Telegram stores the file; we only store its identifier in Google Sheets.
"""

import logging
from typing import Optional

from telegram import Bot, Message
from telegram.error import TelegramError

from config.config import CHANNEL_USERNAME
from keyboards.customer_keyboard import build_product_keyboard
from models.product import Product
from services.price_service import calculate_price
from services.sheet_service import SheetService

logger = logging.getLogger(__name__)


async def publish_product(
    bot: Bot,
    product: Product,
    gold_price: float,
    sheet_service: SheetService,
) -> Message:
    """
    Publish a product photo post to the configured Telegram channel.

    Uses product.telegram_file_id — the file_id stored when the admin
    originally sent the photo to the bot. No download or re-upload needed.

    Returns the sent Message object.
    Raises ValueError for invalid product data.
    """
    if not product.name:
        raise ValueError("نام محصول خالی است.")
    if not product.telegram_file_id:
        raise ValueError(
            "این محصول تصویری ندارد.\n"
            "لطفاً ابتدا از منوی ویرایش، عکس محصول را ارسال کنید."
        )

    caption  = product.channel_caption()
    keyboard = build_product_keyboard(product.id)

    try:
        message = await bot.send_photo(
            chat_id=CHANNEL_USERNAME,
            photo=product.telegram_file_id,
            caption=caption,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
    except TelegramError as exc:
        logger.error(
            "Failed to send photo for product %d (file_id=%s): %s",
            product.id, product.telegram_file_id, exc,
        )
        raise

    # Write message_id back to Sheets (non-fatal)
    try:
        import asyncio
        await asyncio.to_thread(
            sheet_service.update_published_message_id,
            product.id,
            message.message_id,
        )
    except Exception as write_err:
        logger.error(
            "Could not save published_message_id for product %d: %s",
            product.id, write_err,
        )

    logger.info(
        "Product %d ('%s') published to %s (msg_id=%d).",
        product.id, product.name, CHANNEL_USERNAME, message.message_id,
    )
    return message


async def send_product_photo(
    bot: Bot,
    chat_id: int,
    product: Product,
    caption: Optional[str] = None,
) -> bool:
    """
    Send a product photo directly to a customer's private chat.

    Uses product.telegram_file_id — no download, no re-upload, no Drive.
    Returns True on success, False on failure (logged but never raised).
    """
    if not product.telegram_file_id:
        logger.warning(
            "Cannot send photo for product %d ('%s') — no telegram_file_id set.",
            product.id, product.name,
        )
        return False

    cap = caption if caption is not None else product.channel_caption()

    try:
        await bot.send_photo(
            chat_id=chat_id,
            photo=product.telegram_file_id,
            caption=cap,
            parse_mode="Markdown",
        )
        logger.info("Sent product %d photo to chat %d.", product.id, chat_id)
        return True

    except TelegramError as exc:
        logger.error(
            "Failed to send product %d photo to chat %d: %s",
            product.id, chat_id, exc,
        )
        return False
