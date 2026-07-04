"""
Gold Bot v2 – Admin Keyboards
================================
All InlineKeyboardMarkup builders for the admin panel.
Callback data format: a:<action>[:<params>]
"""

import math
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config.config import PRODUCTS_PER_PAGE, FIELD_GROUPS, FIELD_LABELS, OPTION_FIELDS
from models.product import Product


# ── Dashboard ─────────────────────────────────────────────────────────────────

def dashboard_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📦 محصولات",          callback_data="a:pl:0"),
            InlineKeyboardButton("📢 انتشار محصول",     callback_data="a:pub_list"),
        ],
        [
            InlineKeyboardButton("✏️ ویرایش محصول",    callback_data="a:e_list"),
            InlineKeyboardButton("➕ افزودن محصول",     callback_data="a:add"),
        ],
        [
            InlineKeyboardButton("❌ حذف محصول",        callback_data="a:del_list"),
            InlineKeyboardButton("🪙 بروزرسانی قیمت",  callback_data="a:gp"),
        ],
        [
            InlineKeyboardButton("📊 آمار",             callback_data="a:st"),
            InlineKeyboardButton("💬 پشتیبانی",         callback_data="a:sup"),
        ],
        [
            InlineKeyboardButton("👥 مشتریان",          callback_data="a:cust"),
            InlineKeyboardButton("⚙️ تنظیمات",          callback_data="a:se"),
        ],
        [
            InlineKeyboardButton("📁 پشتیبان‌گیری",    callback_data="a:bk"),
            InlineKeyboardButton("🔄 همگام‌سازی شیت",  callback_data="a:sync"),
        ],
    ])


# ── Product list (paginated) ──────────────────────────────────────────────────

def products_list_kb(
    products: list[Product],
    page: int,
    action_prefix: str = "a:ps",   # callback prefix for each product button
    back_cb: str = "a:d",
) -> InlineKeyboardMarkup:
    """
    Paginated product list.
    action_prefix + ':' + str(product.id) is the callback for each row.
    """
    total_pages = max(1, math.ceil(len(products) / PRODUCTS_PER_PAGE))
    page = max(0, min(page, total_pages - 1))
    start = page * PRODUCTS_PER_PAGE
    page_products = products[start: start + PRODUCTS_PER_PAGE]

    rows = []
    for p in page_products:
        label = f"{p.status_emoji} [{p.id}] {p.name[:22]} | {p.weight}گ"
        rows.append([InlineKeyboardButton(label, callback_data=f"{action_prefix}:{p.id}")])

    # Pagination row
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ قبل", callback_data=f"a:pl:{page - 1}"))
    nav.append(InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data="a:noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("بعد ▶️", callback_data=f"a:pl:{page + 1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton("🔙 برگشت", callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)


# ── Product actions ───────────────────────────────────────────────────────────

def product_actions_kb(product_id: int) -> InlineKeyboardMarkup:
    pid = product_id
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📢 انتشار",    callback_data=f"a:pub:{pid}"),
            InlineKeyboardButton("✏️ ویرایش",   callback_data=f"a:e:{pid}"),
        ],
        [
            InlineKeyboardButton("❌ حذف",        callback_data=f"a:del:{pid}"),
        ],
        [InlineKeyboardButton("🔙 برگشت",         callback_data="a:pl:0")],
    ])


# ── Publish confirm ───────────────────────────────────────────────────────────

def publish_confirm_kb(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تأیید و انتشار", callback_data=f"a:pubc:{product_id}"),
            InlineKeyboardButton("❌ انصراف",          callback_data=f"a:ps:{product_id}"),
        ],
    ])


# ── Edit field groups ─────────────────────────────────────────────────────────

def edit_groups_kb(product_id: int) -> InlineKeyboardMarkup:
    rows = []
    for gi, group_name in enumerate(FIELD_GROUPS.keys()):
        rows.append([InlineKeyboardButton(group_name, callback_data=f"a:eg:{gi}:{product_id}")])
    rows.append([InlineKeyboardButton("🔙 برگشت", callback_data=f"a:ps:{product_id}")])
    return InlineKeyboardMarkup(rows)


def edit_fields_kb(group_index: int, product_id: int) -> InlineKeyboardMarkup:
    group_names = list(FIELD_GROUPS.keys())
    group_name  = group_names[group_index]
    field_list  = FIELD_GROUPS[group_name]
    rows = [
        [InlineKeyboardButton(
            FIELD_LABELS.get(f, f),
            callback_data=f"a:ef:{f}:{product_id}",
        )]
        for f in field_list
    ]
    rows.append([InlineKeyboardButton("🔙 برگشت", callback_data=f"a:e:{product_id}")])
    return InlineKeyboardMarkup(rows)


def edit_field_options_kb(field: str, product_id: int) -> InlineKeyboardMarkup:
    """For fields with predefined options, show option buttons."""
    options = OPTION_FIELDS.get(field, [])
    rows = [
        [InlineKeyboardButton(opt, callback_data=f"a:efo:{field}:{product_id}:{opt}")]
        for opt in options
    ]
    group_index = _field_group_index(field)
    back_cb = f"a:eg:{group_index}:{product_id}" if group_index >= 0 else f"a:e:{product_id}"
    rows.append([InlineKeyboardButton("🔙 برگشت", callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)


def _field_group_index(field: str) -> int:
    for gi, fields in enumerate(FIELD_GROUPS.values()):
        if field in fields:
            return gi
    return -1


# ── Delete confirm ────────────────────────────────────────────────────────────

def delete_confirm_kb(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚠️ بله، حذف شود", callback_data=f"a:delc:{product_id}"),
            InlineKeyboardButton("❌ انصراف",          callback_data=f"a:ps:{product_id}"),
        ],
    ])


# ── Add product step keyboards ────────────────────────────────────────────────

def _option_rows(step: str, options: list[str]) -> list[list[InlineKeyboardButton]]:
    rows = []
    for i in range(0, len(options), 2):
        pair = options[i: i + 2]
        rows.append([
            InlineKeyboardButton(opt, callback_data=f"a:add_o:{step}:{opt}")
            for opt in pair
        ])
    return rows


def add_category_kb() -> InlineKeyboardMarkup:
    from config.config import OPTION_FIELDS
    rows = _option_rows("category", OPTION_FIELDS["category"])
    rows.append([InlineKeyboardButton("🔙 انصراف", callback_data="a:add_cancel")])
    return InlineKeyboardMarkup(rows)


def add_gender_kb() -> InlineKeyboardMarkup:
    from config.config import OPTION_FIELDS
    rows = _option_rows("gender", OPTION_FIELDS["gender"])
    rows.append([InlineKeyboardButton("⏭ رد کردن", callback_data="a:add_skip:gender")])
    return InlineKeyboardMarkup(rows)


def add_gold_color_kb() -> InlineKeyboardMarkup:
    from config.config import OPTION_FIELDS
    rows = _option_rows("gold_color", OPTION_FIELDS["gold_color"])
    rows.append([InlineKeyboardButton("⏭ رد کردن", callback_data="a:add_skip:gold_color")])
    return InlineKeyboardMarkup(rows)


def add_stone_kb() -> InlineKeyboardMarkup:
    from config.config import OPTION_FIELDS
    rows = _option_rows("stone", OPTION_FIELDS["stone"])
    rows.append([InlineKeyboardButton("⏭ رد کردن", callback_data="a:add_skip:stone")])
    return InlineKeyboardMarkup(rows)


def add_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ افزودن محصول", callback_data="a:add_conf"),
            InlineKeyboardButton("❌ انصراف",        callback_data="a:add_cancel"),
        ],
    ])


# ── Gold price ────────────────────────────────────────────────────────────────

def gold_price_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 دریافت از tgju.org",  callback_data="a:gp_scr")],
        [InlineKeyboardButton("✏️ ورود دستی",           callback_data="a:gp_man")],
        [InlineKeyboardButton("🔙 برگشت",               callback_data="a:d")],
    ])


# ── Settings ──────────────────────────────────────────────────────────────────

def settings_kb(settings: dict) -> InlineKeyboardMarkup:
    editable = ["store_name", "store_phone", "store_address", "currency"]
    labels   = {
        "store_name":    "🏪 نام فروشگاه",
        "store_phone":   "📞 تلفن",
        "store_address": "📍 آدرس",
        "currency":      "💱 واحد پول",
    }
    rows = [
        [InlineKeyboardButton(
            f"{labels[k]}: {settings.get(k, '—')[:20]}",
            callback_data=f"a:se_f:{k}",
        )]
        for k in editable
    ]
    rows.append([InlineKeyboardButton("🔙 برگشت", callback_data="a:d")])
    return InlineKeyboardMarkup(rows)


# ── Support ───────────────────────────────────────────────────────────────────

def support_list_kb(user_ids: list[int], user_names: dict[int, str]) -> InlineKeyboardMarkup:
    if not user_ids:
        return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="a:d")]])
    rows = [
        [InlineKeyboardButton(
            f"👤 {user_names.get(uid, str(uid))}",
            callback_data=f"a:sup_c:{uid}",
        )]
        for uid in user_ids[:10]
    ]
    rows.append([InlineKeyboardButton("🔙 برگشت", callback_data="a:d")])
    return InlineKeyboardMarkup(rows)


def support_chat_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ پاسخ دادن",    callback_data=f"a:sup_r:{user_id}"),
            InlineKeyboardButton("✅ بستن تیکت",      callback_data=f"a:sup_x:{user_id}"),
        ],
        [InlineKeyboardButton("🔙 برگشت",            callback_data="a:sup")],
    ])


# ── Simple back / cancel ──────────────────────────────────────────────────────

def back_to_dashboard_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به داشبورد", callback_data="a:d")]])


def customers_kb(page: int = 0, customers: list | None = None) -> InlineKeyboardMarkup:
    """Customers overview panel keyboard."""
    rows = [
        [InlineKeyboardButton("📋 لیست علاقه‌مندی‌ها",   callback_data="a:cust_list:0")],
        [InlineKeyboardButton("📢 ارسال نوتیف دستی",       callback_data="a:cust_notify")],
        [InlineKeyboardButton("🔙 برگشت",                  callback_data="a:d")],
    ]
    return InlineKeyboardMarkup(rows)


def customer_notify_confirm_kb(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ ارسال نوتیف",   callback_data=f"a:cust_nconf:{product_id}"),
            InlineKeyboardButton("❌ انصراف",         callback_data="a:cust"),
        ],
    ])
