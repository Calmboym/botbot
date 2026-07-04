"""
Gold Bot v2 – Customer Keyboards
==================================
Inline keyboards attached to published product posts in the channel.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def build_product_keyboard(product_id: int) -> InlineKeyboardMarkup:
    """
    Three-button keyboard for every product post — one button per row
    so the full label always fits, regardless of screen width:
        [📈 قیمت لحظه‌ای طلا]
        [💎 محاسبه قیمت]
        [🤖 سوال درباره این محصول]
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 قیمت لحظه‌ای طلا",      callback_data=f"c:gp:{product_id}")],
        [InlineKeyboardButton("💎 محاسبه قیمت",            callback_data=f"c:pp:{product_id}")],
        [InlineKeyboardButton("🤖 سوال درباره این محصول",  callback_data=f"c:ask:{product_id}")],
    ])


def build_support_keyboard() -> InlineKeyboardMarkup:
    """Shown when AI suggests escalating to human support."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🧑‍💼 اتصال به پشتیبانی", callback_data="c:sup"),
    ]])


def build_notify_keyboard() -> InlineKeyboardMarkup:
    """
    Keyboard shown to customer to opt in/out of restock notifications.
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔔 بله، اطلاعم بده", callback_data="c:notify_on")],
        [InlineKeyboardButton("❌ نه ممنون",         callback_data="c:notify_off")],
    ])
