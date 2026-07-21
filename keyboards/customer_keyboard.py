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


def start_menu_kb() -> InlineKeyboardMarkup:
    """Shown under the /start welcome message."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📋 مشاهده لیست محصولات", callback_data="c:pl:0"),
    ]])


def customer_products_list_kb(products: list, page: int, per_page: int = 8) -> InlineKeyboardMarkup:
    """
    Paginated, tappable product list for customers — same layout as the
    admin product list (one product per row, ◀️ page ▶️ navigation), just
    with a customer-facing callback prefix and no edit/delete actions.
    Pagination alone doesn't carry a category filter in its callback_data
    (Persian text + Telegram's 64-byte limit); the current filter, if any,
    lives on conv_state.product_list_category instead — see
    handlers/customer.py._render_product_list.
    """
    import math
    total_pages = max(1, math.ceil(len(products) / per_page))
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    page_products = products[start: start + per_page]

    rows = []
    for p in page_products:
        label = f"💍 [{p.id}] {p.name[:26]} | {p.weight}گ"
        rows.append([InlineKeyboardButton(label, callback_data=f"c:pd:{p.id}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ قبل", callback_data=f"c:pl:{page - 1}"))
    nav.append(InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data="c:noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("بعد ▶️", callback_data=f"c:pl:{page + 1}"))
    rows.append(nav)
    return InlineKeyboardMarkup(rows)


def product_detail_kb(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 سوال درباره این محصول", callback_data=f"c:ask:{product_id}")],
        [InlineKeyboardButton("🔙 بازگشت به لیست",         callback_data="c:pl:0")],
    ])
