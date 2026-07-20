"""
Gold Bot v2 – Admin Handlers
==============================
All admin-side logic lives here.

Entry points registered in main.py:
    cmd_admin(update, context)            ← /admin command
    handle_admin_message(update, context) ← text input during a flow
    handle_admin_photo(update, context)   ← photo → Telegram file_id saved to sheet

Everything else is invoked by callbacks.py.
"""

import asyncio
import io
import logging
from typing import Optional

from telegram import Update, Message
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from config.config import ADMIN_ID
from keyboards.admin_keyboard import (
    dashboard_kb, products_list_kb, product_actions_kb,
    publish_confirm_kb, publish_attrs_kb, edit_groups_kb, edit_fields_kb,
    edit_field_options_kb, delete_confirm_kb,
    add_category_kb, add_gender_kb, add_gold_color_kb,
    add_stone_kb, add_confirm_kb, gold_price_kb,
    settings_kb, support_list_kb, support_chat_kb, back_to_dashboard_kb,
)
from models.product import Product, _md_escape
from services.caption_service import build_caption
from services.customer_service import CustomerService
from services.gold_service import GoldService
from services.price_service import calculate_price, currency_label
from services.publish_service import publish_product
from services.sheet_service import SheetService
from services.telegram_service import format_statistics, send_admin_reply_to_customer
from utils.cache import AdminState, Cache
from utils.validators import (
    is_admin, validate_numeric_field, validate_gold_price
)

logger = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _services(context: ContextTypes.DEFAULT_TYPE) -> tuple[SheetService, GoldService, Cache]:
    return (
        context.bot_data["sheet_service"],
        context.bot_data["gold_service"],
        context.bot_data["cache"],
    )


async def _safe_edit(msg: Message, text: str, **kwargs) -> None:
    """Edit a message, fall back to send on failure."""
    try:
        await msg.edit_text(text, **kwargs)
    except TelegramError:
        await msg.reply_text(text, **kwargs)


def _target_message(update: Update) -> Message:
    """
    Feature 5 — return the Message to render output into, regardless of
    whether this call came from an inline button (callback_query.message,
    which _safe_edit will try to edit) or a direct slash command like
    /publish 15 (update.message, which _safe_edit's fallback will reply to).

    This lets every existing cb_xxx handler below serve BOTH entry points
    with zero duplicated logic — the only difference is which Message
    object gets passed in.
    """
    if update.callback_query:
        return update.callback_query.message
    return update.message


async def _report_not_found(update: Update, msg: Message, product_id: int) -> None:
    """
    Feature 5 — report a missing product ID gracefully, never crashing.
    Shows a popup alert when triggered by a button, or a plain reply when
    triggered by a direct /publish|/preview|/edit|/delete <id> command.
    """
    text = f"❌ محصولی با شناسه {product_id} یافت نشد."
    if update.callback_query:
        await update.callback_query.answer(text, show_alert=True)
    else:
        await msg.reply_text(text)


# ── /admin command ─────────────────────────────────────────────────────────────

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ دسترسی مجاز نیست.")
        return
    sheet, gold, cache = _services(context)
    cache.clear_admin_state()
    await update.message.reply_text(
        "🎛 *پنل مدیریت Gold Bot*\n\n"
        "یکی از گزینه‌ها را انتخاب کنید:\n\n"
        "💡 _میان‌بر برای کاتالوگ بزرگ:_\n"
        "`/publish <شناسه>` `/preview <شناسه>` `/edit <شناسه>` `/delete <شناسه>`",
        parse_mode="Markdown",
        reply_markup=dashboard_kb(),
    )


# ══════════════════════════════════════════════════════════════════════════════
# Feature 5 — Direct product commands by ID
# ══════════════════════════════════════════════════════════════════════════════
# /publish <id>, /preview <id>, /edit <id>, /delete <id> let the admin skip
# the product list entirely for large catalogs. Each command, when given an
# ID, delegates straight to the SAME cb_xxx handler a button click on that
# product would trigger (see _target_message() above) — there is no second
# implementation of publishing/previewing/editing/deleting anywhere.
#
# Product lookup always goes through SheetService.get_product_by_id() — the
# single existing lookup function already used everywhere else in this file.
#
# With no ID argument, every command falls back to the original, unchanged
# list-based workflow (cb_publish_list / cb_edit_list / cb_delete_list).

def _parse_product_id_arg(context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    """
    Parse a single numeric product ID from context.args (Feature 5).

    Returns:
        None if no argument was given at all (caller should fall back to
        the existing list-based workflow).

    Raises:
        ValueError: An argument WAS given but isn't a valid non-negative
                    integer — caller shows a friendly message instead of
                    letting int() raise an uncaught exception.
    """
    if not context.args:
        return None
    raw = context.args[0].strip()
    if not raw.isdigit():
        raise ValueError(raw)
    return int(raw)


async def publish_product_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int) -> None:
    """
    Feature 5 reusable entry point — opens product `product_id` directly at
    the same first step a button click on it (from the publish list) would:
    the per-product attribute checklist (cb_publish_preview). No separate
    publishing implementation.
    """
    sheet, _, _ = _services(context)
    product = await asyncio.to_thread(sheet.get_product_by_id, product_id)
    if not product:
        await _report_not_found(update, _target_message(update), product_id)
        return
    await cb_publish_preview(update, context, product_id)


async def preview_product_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int) -> None:
    """
    Feature 5 reusable entry point — renders the exact channel-post caption
    for `product_id` (currency, footer, and any in-progress attribute
    selection already applied) WITHOUT publishing it, by reusing
    cb_publish_go() — the identical function the button-driven "step 2"
    preview uses. Guarantees /preview <id> always matches what /publish <id>
    would eventually send; no separate rendering logic.
    """
    sheet, _, _ = _services(context)
    product = await asyncio.to_thread(sheet.get_product_by_id, product_id)
    if not product:
        await _report_not_found(update, _target_message(update), product_id)
        return
    await cb_publish_go(update, context, product_id)


async def edit_product_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int) -> None:
    """Feature 5 reusable entry point — opens the field-group editor directly."""
    sheet, _, cache = _services(context)
    product = await asyncio.to_thread(sheet.get_product_by_id, product_id)
    if not product:
        await _report_not_found(update, _target_message(update), product_id)
        return
    state = cache.get_admin_state()
    state.action = "edit"
    cache.save_admin_state(state)
    await cb_edit_groups(update, context, product_id)


async def delete_product_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int) -> None:
    """Feature 5 reusable entry point — jumps straight to the delete confirmation."""
    sheet, _, cache = _services(context)
    product = await asyncio.to_thread(sheet.get_product_by_id, product_id)
    if not product:
        await _report_not_found(update, _target_message(update), product_id)
        return
    state = cache.get_admin_state()
    state.action = "delete"
    cache.save_admin_state(state)
    await cb_delete_confirm_prompt(update, context, product_id)


async def cmd_publish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /publish            → existing product-list workflow (unchanged)
    /publish <id>       → jump straight into publishing that product,
                           skipping the list entirely (Feature 5)
    """
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ دسترسی مجاز نیست.")
        return
    try:
        product_id = _parse_product_id_arg(context)
    except ValueError as bad_value:
        await update.message.reply_text(
            f"⚠️ شناسه محصول باید یک عدد باشد. دریافت شد: «{bad_value}»\n\n"
            "مثال: `/publish 15`",
            parse_mode="Markdown",
        )
        return

    if product_id is None:
        await cb_publish_list(update, context)
        return
    await publish_product_by_id(update, context, product_id)


async def cmd_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/preview <id> — show the exact post that would be published, without publishing it (Feature 5)."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ دسترسی مجاز نیست.")
        return
    try:
        product_id = _parse_product_id_arg(context)
    except ValueError as bad_value:
        await update.message.reply_text(
            f"⚠️ شناسه محصول باید یک عدد باشد. دریافت شد: «{bad_value}»\n\n"
            "مثال: `/preview 15`",
            parse_mode="Markdown",
        )
        return

    if product_id is None:
        await update.message.reply_text(
            "📌 لطفاً شناسه محصول را وارد کنید.\n\nمثال: `/preview 15`",
            parse_mode="Markdown",
        )
        return
    await preview_product_by_id(update, context, product_id)


async def cmd_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /edit            → existing product-list workflow (unchanged)
    /edit <id>       → open the field-group editor directly (Feature 5)
    """
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ دسترسی مجاز نیست.")
        return
    try:
        product_id = _parse_product_id_arg(context)
    except ValueError as bad_value:
        await update.message.reply_text(
            f"⚠️ شناسه محصول باید یک عدد باشد. دریافت شد: «{bad_value}»\n\n"
            "مثال: `/edit 15`",
            parse_mode="Markdown",
        )
        return

    if product_id is None:
        await cb_edit_list(update, context)
        return
    await edit_product_by_id(update, context, product_id)


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /delete            → existing product-list workflow (unchanged)
    /delete <id>       → jump straight to the delete confirmation (Feature 5)
    """
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ دسترسی مجاز نیست.")
        return
    try:
        product_id = _parse_product_id_arg(context)
    except ValueError as bad_value:
        await update.message.reply_text(
            f"⚠️ شناسه محصول باید یک عدد باشد. دریافت شد: «{bad_value}»\n\n"
            "مثال: `/delete 15`",
            parse_mode="Markdown",
        )
        return

    if product_id is None:
        await cb_delete_list(update, context)
        return
    await delete_product_by_id(update, context, product_id)


# ── Text message router (during active admin flow) ────────────────────────────

async def handle_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Called for every text message from the admin.
    Routes to the appropriate sub-handler based on AdminState.
    Returns True if the message was consumed by the admin flow.
    """
    if not is_admin(update.effective_user.id):
        return

    sheet, gold, cache = _services(context)
    state = cache.get_admin_state()

    if not state.action:
        return  # No active flow – let customer handler process it

    text = update.message.text.strip()

    if state.action == "add":
        await _add_product_text_step(update, context, state, text, sheet, cache)
    elif state.action == "edit" and state.step == "waiting_value":
        await _apply_edit_value(update, context, state, text, sheet, cache)
    elif state.action == "goldprice_manual":
        await _apply_gold_price_manual(update, context, state, text, gold, sheet, cache)
    elif state.action == "settings_edit" and state.step == "waiting_value":
        await _apply_settings_value(update, context, state, text, sheet, cache)
    elif state.action == "reply":
        await _forward_admin_reply(update, context, state, text, cache)


async def handle_admin_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Called for every photo message sent by the admin.

    If the admin is currently at the 'telegram_file_id' step of the
    add-product flow, or editing a product's image field, the Telegram
    file_id of the highest-resolution photo is extracted and stored
    directly — no downloading, no uploading, no external hosting.

    Telegram stores the file; we only keep the file_id in Google Sheets.

    Returns:
        True  – photo was handled (caller should stop processing).
        False – not in an image step; route to customer photo handler.
    """
    if not is_admin(update.effective_user.id):
        return False

    sheet, _, cache = _services(context)
    state = cache.get_admin_state()

    is_add_image_step  = state.action == "add"  and state.step == "telegram_file_id"
    is_edit_image_step = (
        state.action == "edit"
        and state.step == "waiting_value"
        and state.field_name == "telegram_file_id"
    )

    if not (is_add_image_step or is_edit_image_step):
        return False  # Not in an image step → let it fall through to customer handler

    # Extract file_id from the highest-resolution version of the photo
    file_id = update.message.photo[-1].file_id

    if is_add_image_step:
        state.add_data["telegram_file_id"] = file_id
        cache.save_admin_state(state)
        await update.message.reply_text("✅ تصویر دریافت شد.")
        await _advance_add_step(update.message, state, cache)
    else:
        try:
            await asyncio.to_thread(
                sheet.update_product_field,
                state.product_id,
                "telegram_file_id",
                file_id,
            )
            cache.clear_admin_state()
            await update.message.reply_text(
                f"✅ تصویر محصول {state.product_id} ذخیره شد.",
                reply_markup=back_to_dashboard_kb(),
            )
            logger.info(
                "Product %d telegram_file_id updated (file_id=%s).",
                state.product_id, file_id,
            )
        except Exception as exc:
            logger.error(
                "Failed to save telegram_file_id for product %d: %s",
                state.product_id, exc,
            )
            await update.message.reply_text(f"❌ خطا در ذخیره تصویر: {exc}")

    return True


# ══════════════════════════════════════════════════════════════════════════════
# Dashboard callback handlers (called from callbacks.py)
# ══════════════════════════════════════════════════════════════════════════════

async def cb_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sheet, gold, cache = _services(context)
    cache.clear_admin_state()
    q = update.callback_query
    await _safe_edit(
        q.message,
        "🎛 *پنل مدیریت Gold Bot*\n\nیکی از گزینه‌ها را انتخاب کنید:",
        parse_mode="Markdown",
        reply_markup=dashboard_kb(),
    )


# ── Products list ─────────────────────────────────────────────────────────────

async def cb_products_list(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> None:
    sheet, _, cache = _services(context)
    cache.clear_admin_state()
    q = update.callback_query
    products = await asyncio.to_thread(sheet.get_products)
    if not products:
        await _safe_edit(q.message, "📦 هیچ محصولی در جدول یافت نشد.", reply_markup=back_to_dashboard_kb())
        return
    await _safe_edit(
        q.message,
        f"📦 *لیست محصولات* ({len(products)} محصول)\n\nمحصول مورد نظر را انتخاب کنید:",
        parse_mode="Markdown",
        reply_markup=products_list_kb(products, page),
    )


async def cb_product_select(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int) -> None:
    """Generic product selection – shows product details + action buttons."""
    sheet, gold, cache = _services(context)
    q = update.callback_query
    product = await asyncio.to_thread(sheet.get_product_by_id, product_id)
    if not product:
        await q.answer("⚠️ محصول یافت نشد.", show_alert=True)
        return
    gp, settings = await asyncio.gather(
        asyncio.to_thread(gold.get_gold_price),
        asyncio.to_thread(sheet.get_settings),
    )
    price    = calculate_price(product, gp)
    currency = currency_label(settings)
    text = (
        product.admin_detail(currency=currency)
        + f"\n\n💵 *قیمت تقریبی: `{price:,.0f} {currency}`*"
    )
    await _safe_edit(q.message, text, parse_mode="Markdown", reply_markup=product_actions_kb(product_id))


# ── Publish ───────────────────────────────────────────────────────────────────

async def cb_publish_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sheet, _, cache = _services(context)
    state = cache.get_admin_state()
    state.action = "publish"
    cache.save_admin_state(state)
    msg = _target_message(update)
    products = await asyncio.to_thread(sheet.get_products)
    available = [p for p in products if p.status == "active"]
    if not available:
        await _safe_edit(msg, "⚠️ هیچ محصول فعالی برای انتشار وجود ندارد.", reply_markup=back_to_dashboard_kb())
        return
    await _safe_edit(
        msg,
        "📢 *انتشار محصول*\n\nمحصولی که می‌خواهید منتشر کنید را انتخاب کنید:",
        parse_mode="Markdown",
        reply_markup=products_list_kb(available, 0, action_prefix="a:pub", back_cb="a:d"),
    )


async def cb_publish_preview(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int) -> None:
    """
    Step 1 of publishing — Feature 1: let the admin choose which attributes
    appear under THIS product's post (per-product, never global).

    Note: this function is triggered by the `a:pub:<id>` callback (product
    selected from the publish list) AND by /publish <id> (Feature 5) — the
    old single-step flow became a two-step flow: checklist → preview → confirm.
    """
    sheet, _, cache = _services(context)
    msg = _target_message(update)
    product = await asyncio.to_thread(sheet.get_product_by_id, product_id)
    if not product:
        await _report_not_found(update, msg, product_id)
        return

    from config.config import DEFAULT_PUBLISH_ATTRS
    state = cache.get_admin_state()
    if state.product_id != product_id or not state.publish_attrs:
        state.publish_attrs = set(DEFAULT_PUBLISH_ATTRS)
    state.action     = "publish_attrs"
    state.product_id = product_id
    cache.save_admin_state(state)

    await _safe_edit(
        msg,
        f"📢 *انتخاب اطلاعات نمایشی برای «{_md_escape(product.name)}»*\n\n"
        "کدام مشخصات زیر پست این محصول نشان داده شود؟\n"
        "_(این انتخاب فقط برای همین محصول است)_",
        parse_mode="Markdown",
        reply_markup=publish_attrs_kb(product_id, state.publish_attrs),
    )


async def cb_publish_attr_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int, attr_key: str) -> None:
    """Toggle one attribute on/off for the product currently being published (Feature 1)."""
    from config.config import PUBLISH_ATTRIBUTES

    sheet, _, cache = _services(context)
    q = update.callback_query

    if attr_key not in PUBLISH_ATTRIBUTES:
        await q.answer("⚠️ فیلد نامعتبر.", show_alert=True)
        return

    state = cache.get_admin_state()
    if state.product_id != product_id:
        await q.answer("⚠️ لطفاً دوباره از لیست محصولات شروع کنید.", show_alert=True)
        return

    if attr_key in state.publish_attrs:
        state.publish_attrs.discard(attr_key)
    else:
        state.publish_attrs.add(attr_key)
    cache.save_admin_state(state)

    product = await asyncio.to_thread(sheet.get_product_by_id, product_id)
    name = _md_escape(product.name) if product else str(product_id)

    await _safe_edit(
        q.message,
        f"📢 *انتخاب اطلاعات نمایشی برای «{name}»*\n\n"
        "کدام مشخصات زیر پست این محصول نشان داده شود؟\n"
        "_(این انتخاب فقط برای همین محصول است)_",
        parse_mode="Markdown",
        reply_markup=publish_attrs_kb(product_id, state.publish_attrs),
    )


async def cb_publish_go(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int) -> None:
    """
    Step 2 of publishing — show the EXACT caption that will be posted
    (selected attributes + resolved currency + global footer already
    applied), then ask for final confirmation.

    Also reused directly by /preview <id> (Feature 5) via
    preview_product_by_id(), so the command and the button flow are
    guaranteed to render an identical preview — single implementation.
    """
    sheet, gold, cache = _services(context)
    msg = _target_message(update)
    product = await asyncio.to_thread(sheet.get_product_by_id, product_id)
    if not product:
        await _report_not_found(update, msg, product_id)
        return

    state = cache.get_admin_state()
    selected_attrs = set(state.publish_attrs) if state.product_id == product_id and state.publish_attrs else None

    gp, settings = await asyncio.gather(
        asyncio.to_thread(gold.get_gold_price),
        asyncio.to_thread(sheet.get_settings),
    )
    price    = calculate_price(product, gp)
    currency = currency_label(settings)
    footer   = settings.get("post_footer", "")

    caption = build_caption(product, price, selected_attrs, currency, footer)

    text = (
        f"*👁 پیش‌نمایش دقیق پست کانال*\n\n"
        f"{caption}\n\n"
        f"──────────\n"
        f"⚠️ آیا این محصول را در کانال منتشر می‌کنید؟"
    )
    await _safe_edit(msg, text, parse_mode="Markdown", reply_markup=publish_confirm_kb(product_id))


async def cb_publish_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int) -> None:
    sheet, gold, cache = _services(context)
    q = update.callback_query
    await _safe_edit(q.message, f"⏳ در حال انتشار محصول {product_id} …")
    product = await asyncio.to_thread(sheet.get_product_by_id, product_id)
    if not product:
        await _safe_edit(q.message, "⚠️ محصول یافت نشد.", reply_markup=back_to_dashboard_kb())
        return

    state = cache.get_admin_state()
    selected_attrs = set(state.publish_attrs) if state.product_id == product_id and state.publish_attrs else None

    gp = await asyncio.to_thread(gold.get_gold_price)
    try:
        msg = await publish_product(context.bot, product, gp, sheet, selected_attrs=selected_attrs)
        cache.clear_admin_state()
        await _safe_edit(
            q.message,
            f"✅ محصول «{product.name}» منتشر شد.\n🔖 شناسه پیام: `{msg.message_id}`",
            parse_mode="Markdown",
            reply_markup=back_to_dashboard_kb(),
        )
    except Exception as exc:
        logger.error("Publish failed for product %d: %s", product_id, exc)
        await _safe_edit(q.message, f"❌ انتشار ناموفق: {exc}", reply_markup=back_to_dashboard_kb())


# ── Edit ──────────────────────────────────────────────────────────────────────

async def cb_edit_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sheet, _, cache = _services(context)
    state = cache.get_admin_state()
    state.action = "edit"
    cache.save_admin_state(state)
    msg = _target_message(update)
    products = await asyncio.to_thread(sheet.get_products)
    if not products:
        await _safe_edit(msg, "📦 محصولی یافت نشد.", reply_markup=back_to_dashboard_kb())
        return
    await _safe_edit(
        msg,
        "✏️ *ویرایش محصول*\n\nمحصول مورد نظر را انتخاب کنید:",
        parse_mode="Markdown",
        reply_markup=products_list_kb(products, 0, action_prefix="a:e", back_cb="a:d"),
    )


async def cb_edit_groups(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int) -> None:
    """Also reused directly by /edit <id> (Feature 5) via edit_product_by_id()."""
    sheet, _, cache = _services(context)
    msg = _target_message(update)
    product = await asyncio.to_thread(sheet.get_product_by_id, product_id)
    if not product:
        await _report_not_found(update, msg, product_id)
        return
    state = cache.get_admin_state()
    state.product_id = product_id
    cache.save_admin_state(state)
    await _safe_edit(
        msg,
        f"✏️ *ویرایش: {_md_escape(product.name)}*\n\nگروه فیلد مورد نظر را انتخاب کنید:",
        parse_mode="Markdown",
        reply_markup=edit_groups_kb(product_id),
    )


async def cb_edit_field_group(update: Update, context: ContextTypes.DEFAULT_TYPE, group_index: int, product_id: int) -> None:
    q = update.callback_query
    await _safe_edit(
        q.message,
        "✏️ فیلد مورد نظر را انتخاب کنید:",
        reply_markup=edit_fields_kb(group_index, product_id),
    )


async def cb_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE, field: str, product_id: int) -> None:
    from config.config import OPTION_FIELDS, FIELD_LABELS, NUMERIC_FIELDS
    q = update.callback_query
    sheet, _, cache = _services(context)

    if field in OPTION_FIELDS:
        await _safe_edit(
            q.message,
            f"✏️ مقدار جدید برای «{FIELD_LABELS.get(field, field)}» را انتخاب کنید:",
            reply_markup=edit_field_options_kb(field, product_id),
        )
        return

    # Free-text or numeric input
    state = cache.get_admin_state()
    state.action     = "edit"
    state.step       = "waiting_value"
    state.product_id = product_id
    state.field_name = field
    cache.save_admin_state(state)

    if field == "telegram_file_id":
        prompt = "🖼 یک عکس از محصول بفرستید، یا لینک مستقیم تصویر جدید را تایپ کنید:"
    else:
        hint = "عدد" if field in NUMERIC_FIELDS else "متن"
        prompt = f"✏️ مقدار جدید برای «{FIELD_LABELS.get(field, field)}» را وارد کنید ({hint}):"

    await _safe_edit(
        q.message,
        prompt,
        reply_markup=back_to_dashboard_kb(),
    )


async def _maybe_notify_back_in_stock(context: ContextTypes.DEFAULT_TYPE, product_id: int, field: str) -> None:
    """
    Task 4 — after a stock/status edit, if the product is now available,
    automatically notify everyone on its back-in-stock waitlist and mark
    them as notified. No-op for any other field, or if nobody is waiting.

    update_product_field() already invalidated the products cache before
    this runs, so the re-fetch below reflects this exact edit. Never
    raises — a failure here must never break the admin's own
    edit-confirmation message.
    """
    if field not in ("stock", "status"):
        return
    stock_svc = context.bot_data.get("stock_notification_service")
    if stock_svc is None:
        return
    try:
        sheet, _, _ = _services(context)
        product = await asyncio.to_thread(sheet.get_product_by_id, product_id)
        if not product or not product.is_available:
            return
        from services.stock_notification_service import notify_back_in_stock
        count = await notify_back_in_stock(context.bot, product, stock_svc)
        if count:
            logger.info("Back-in-stock: notified %d waiting customer(s) for product %d.", count, product_id)
    except Exception as exc:
        logger.error("Back-in-stock notify check failed for product %d: %s", product_id, exc)


async def cb_edit_field_option(update: Update, context: ContextTypes.DEFAULT_TYPE, field: str, product_id: int, value: str) -> None:
    """Handle option selection for an edit field (e.g. status, gold_color)."""
    q = update.callback_query
    sheet, _, cache = _services(context)
    try:
        await asyncio.to_thread(sheet.update_product_field, product_id, field, value)
        await _maybe_notify_back_in_stock(context, product_id, field)
        await q.answer("✅ بروزرسانی شد.", show_alert=False)
        await _safe_edit(q.message, f"✅ فیلد «{field}» به «{value}» تغییر یافت.", reply_markup=back_to_dashboard_kb())
    except Exception as exc:
        logger.error("Edit option failed: %s", exc)
        await q.answer("❌ خطا در بروزرسانی.", show_alert=True)


async def _apply_edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE, state: AdminState, text: str, sheet: SheetService, cache: Cache) -> None:
    from config.config import NUMERIC_FIELDS, FIELD_LABELS
    field = state.field_name
    pid   = state.product_id

    # telegram_file_id must come from a photo, not text
    if field == "telegram_file_id":
        await update.message.reply_text(
            "📸 لطفاً یک عکس ارسال کنید.\n"
            "برای تغییر تصویر محصول، باید عکس بفرستید (نه متن)."
        )
        return

    if field in NUMERIC_FIELDS:
        ok, value, err = validate_numeric_field(field, text)
        if not ok:
            await update.message.reply_text(f"⚠️ {err}")
            return
    else:
        value = text

    try:
        await asyncio.to_thread(sheet.update_product_field, pid, field, value)
        await _maybe_notify_back_in_stock(context, pid, field)
        cache.clear_admin_state()
        await update.message.reply_text(
            f"✅ فیلد «{FIELD_LABELS.get(field, field)}» محصول {pid} به «{value}» تغییر یافت.",
            reply_markup=back_to_dashboard_kb(),
        )
    except Exception as exc:
        logger.error("Update field failed: %s", exc)
        await update.message.reply_text(f"❌ خطا: {exc}")


# ── Delete ────────────────────────────────────────────────────────────────────

async def cb_delete_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sheet, _, cache = _services(context)
    state = cache.get_admin_state()
    state.action = "delete"
    cache.save_admin_state(state)
    msg = _target_message(update)
    products = await asyncio.to_thread(sheet.get_products)
    if not products:
        await _safe_edit(msg, "📦 محصولی یافت نشد.", reply_markup=back_to_dashboard_kb())
        return
    await _safe_edit(
        msg,
        "❌ *حذف محصول*\n\nمحصول مورد نظر را انتخاب کنید:",
        parse_mode="Markdown",
        reply_markup=products_list_kb(products, 0, action_prefix="a:del", back_cb="a:d"),
    )


async def cb_delete_confirm_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int) -> None:
    """Also reused directly by /delete <id> (Feature 5) via delete_product_by_id()."""
    sheet, _, _ = _services(context)
    msg = _target_message(update)
    product = await asyncio.to_thread(sheet.get_product_by_id, product_id)
    if not product:
        await _report_not_found(update, msg, product_id)
        return
    name = _md_escape(product.name)
    await _safe_edit(
        msg,
        f"⚠️ آیا مطمئنید می‌خواهید محصول «{name}» را حذف کنید؟\nاین عملیات قابل بازگشت نیست.",
        reply_markup=delete_confirm_kb(product_id),
    )


async def cb_delete_execute(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int) -> None:
    sheet, _, cache = _services(context)
    q = update.callback_query
    try:
        await asyncio.to_thread(sheet.delete_product, product_id)
        cache.clear_admin_state()
        await _safe_edit(q.message, f"✅ محصول {product_id} حذف شد.", reply_markup=back_to_dashboard_kb())
        logger.info("Product %d deleted by admin.", product_id)
    except Exception as exc:
        logger.error("Delete product failed: %s", exc)
        await _safe_edit(q.message, f"❌ خطا در حذف: {exc}", reply_markup=back_to_dashboard_kb())


# ── Add product ───────────────────────────────────────────────────────────────

_ADD_STEPS = [
    "name", "category", "gender", "weight",
    "wage_percent", "profit_percent", "gold_color",
    "stone", "stock", "telegram_file_id",
]
# telegram_file_id is a PHOTO step handled by handle_admin_photo, not text
_TEXT_STEPS  = {"name", "weight", "wage_percent", "profit_percent", "stock"}
_KBD_STEPS   = {"category": add_category_kb, "gender": add_gender_kb,
                 "gold_color": add_gold_color_kb, "stone": add_stone_kb}
_STEP_PROMPTS = {
    "name":             "📝 نام محصول را وارد کنید:",
    "weight":           "⚖️ وزن (گرم) را وارد کنید (مثال: 3.5):",
    "wage_percent":     "🛠 درصد اجرت را وارد کنید (مثال: 15):",
    "profit_percent":   "💰 درصد سود را وارد کنید (مثال: 10):",
    "stock":            "📦 موجودی اولیه را وارد کنید (مثال: 1):",
    "telegram_file_id": "📸 عکس محصول را بفرستید:",
}


async def cb_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, cache = _services(context)
    q = update.callback_query
    state = cache.get_admin_state()
    state.action   = "add"
    state.step     = "name"
    state.add_data = {}
    cache.save_admin_state(state)
    await _safe_edit(q.message, "➕ *افزودن محصول جدید*\n\n" + _STEP_PROMPTS["name"], parse_mode="Markdown")


async def cb_add_option(update: Update, context: ContextTypes.DEFAULT_TYPE, step: str, value: str) -> None:
    """Handle option selection (category, gender, gold_color, stone)."""
    _, _, cache = _services(context)
    q = update.callback_query
    state = cache.get_admin_state()
    state.add_data[step] = value
    await _advance_add_step(q.message, state, cache)


async def cb_add_skip(update: Update, context: ContextTypes.DEFAULT_TYPE, step: str) -> None:
    _, _, cache = _services(context)
    q = update.callback_query
    state = cache.get_admin_state()
    state.add_data.setdefault(step, "")
    await _advance_add_step(q.message, state, cache)


async def _add_product_text_step(update, context, state: AdminState, text: str, sheet: SheetService, cache: Cache) -> None:
    from config.config import NUMERIC_FIELDS
    step = state.step

    # telegram_file_id is a photo step — user must send a photo, not type text
    if step == "telegram_file_id":
        await update.message.reply_text(
            "📸 لطفاً یک عکس از محصول ارسال کنید.\n"
            "(متن قابل قبول نیست — عکس بفرستید)"
        )
        return

    if step not in _TEXT_STEPS:
        return

    if step in NUMERIC_FIELDS:
        ok, value, err = validate_numeric_field(step, text)
        if not ok:
            await update.message.reply_text(f"⚠️ {err}")
            return
        state.add_data[step] = value
    else:
        state.add_data[step] = text

    await _advance_add_step(update.message, state, cache)


async def _advance_add_step(msg: Message, state: AdminState, cache: Cache) -> None:
    """Move to the next step or show confirmation."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    idx      = _ADD_STEPS.index(state.step) if state.step in _ADD_STEPS else -1
    next_idx = idx + 1 if idx >= 0 else len(_ADD_STEPS)

    if next_idx >= len(_ADD_STEPS):
        # All steps done → show confirmation
        state.step = "confirm"
        cache.save_admin_state(state)
        has_photo = bool(state.add_data.get("telegram_file_id"))
        summary   = "\n".join(
            f"  • {k}: {'✅ دارد' if k == 'telegram_file_id' and v else v}"
            for k, v in state.add_data.items() if v
        )
        # NOTE: summary contains raw admin-typed text (name, description, tags...)
        # which may include unescaped Markdown characters (_, *, `, [ ]).
        # No parse_mode is used here to avoid "Can't parse entities" crashes.
        await msg.reply_text(
            f"✅ خلاصه محصول جدید:\n\n{summary}\n\nآیا تأیید می‌کنید؟",
            reply_markup=add_confirm_kb(),
        )
        return

    next_step = _ADD_STEPS[next_idx]
    state.step = next_step
    cache.save_admin_state(state)

    if next_step in _KBD_STEPS:
        prompt = {"category": "📂 دسته‌بندی", "gender": "👤 جنسیت",
                  "gold_color": "🎨 رنگ طلا", "stone": "💎 سنگ"}
        await msg.reply_text(
            f"{prompt.get(next_step, next_step)} را انتخاب کنید:",
            reply_markup=_KBD_STEPS[next_step](),
        )
    elif next_step == "telegram_file_id":
        # Photo step: show skip option in case admin doesn't have a photo ready
        skip_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("⏭ رد کردن (بدون عکس)", callback_data="a:add_skip:telegram_file_id")
        ]])
        await msg.reply_text(
            "📸 عکس محصول را ارسال کنید:\n"
            "(می‌توانید این مرحله را رد کنید و بعداً از منوی ویرایش اضافه کنید)",
            reply_markup=skip_kb,
        )
    else:
        await msg.reply_text(_STEP_PROMPTS.get(next_step, f"مقدار {next_step} را وارد کنید:"))


async def cb_add_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sheet, _, cache = _services(context)
    q = update.callback_query
    state = cache.get_admin_state()
    if not state.add_data.get("name"):
        await q.answer("⚠️ داده‌های محصول ناقص است.", show_alert=True)
        return
    try:
        new_id = await asyncio.to_thread(sheet.add_product, state.add_data)
        cache.clear_admin_state()
        await _safe_edit(
            q.message,
            f"✅ محصول «{state.add_data.get('name')}» با شناسه {new_id} اضافه شد.",
            reply_markup=back_to_dashboard_kb(),
        )
        logger.info("New product id=%d added by admin.", new_id)
    except Exception as exc:
        logger.error("Add product failed: %s", exc)
        await _safe_edit(q.message, f"❌ خطا در افزودن محصول: {exc}", reply_markup=back_to_dashboard_kb())


async def cb_add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, cache = _services(context)
    cache.clear_admin_state()
    q = update.callback_query
    await _safe_edit(q.message, "❌ افزودن محصول لغو شد.", reply_markup=dashboard_kb())


# ── Gold price ────────────────────────────────────────────────────────────────

async def cb_gold_price_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sheet, gold, _ = _services(context)
    q = update.callback_query
    price, upd, settings = await asyncio.gather(
        asyncio.to_thread(gold.get_gold_price),
        asyncio.to_thread(gold.get_last_update),
        asyncio.to_thread(sheet.get_settings),
    )
    currency = currency_label(settings)
    await _safe_edit(
        q.message,
        f"🪙 *بروزرسانی قیمت طلا*\n\n"
        f"قیمت فعلی: `{price:,.0f} {currency}/گرم`\n"
        f"آخرین بروزرسانی: `{upd}`\n\n"
        "روش بروزرسانی را انتخاب کنید:",
        parse_mode="Markdown",
        reply_markup=gold_price_kb(),
    )


async def cb_gold_price_scrape(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sheet, gold, _ = _services(context)
    q = update.callback_query
    await _safe_edit(q.message, "⏳ در حال دریافت قیمت از tgju.org …")
    try:
        from services.gold_service import GoldService
        new_price = await asyncio.to_thread(GoldService.scrape_with_retry)
        await asyncio.to_thread(gold.update_gold_price, new_price)
        settings = await asyncio.to_thread(sheet.get_settings)
        currency = currency_label(settings)
        await _safe_edit(
            q.message,
            f"✅ قیمت طلا به `{new_price:,.0f} {currency}/گرم` بروزرسانی شد.",
            parse_mode="Markdown",
            reply_markup=back_to_dashboard_kb(),
        )
    except Exception as exc:
        logger.error("Scrape gold price failed: %s", exc)
        await _safe_edit(q.message, f"❌ خطا در دریافت قیمت: {exc}", reply_markup=back_to_dashboard_kb())


async def cb_gold_price_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sheet, _, cache = _services(context)
    q = update.callback_query
    settings = await asyncio.to_thread(sheet.get_settings)
    currency = currency_label(settings)
    state = cache.get_admin_state()
    state.action = "goldprice_manual"
    cache.save_admin_state(state)
    await _safe_edit(q.message, f"✏️ قیمت جدید طلا را وارد کنید ({currency}/گرم):", reply_markup=back_to_dashboard_kb())


async def _apply_gold_price_manual(
    update, context, state: AdminState, text: str,
    gold: GoldService, sheet: SheetService, cache: Cache,
) -> None:
    settings = await asyncio.to_thread(sheet.get_settings)
    currency = currency_label(settings)
    ok, price, err = validate_gold_price(text, currency=currency)
    if not ok:
        await update.message.reply_text(f"⚠️ {err}")
        return
    await asyncio.to_thread(gold.update_gold_price, price)
    cache.clear_admin_state()
    await update.message.reply_text(
        f"✅ قیمت طلا به `{price:,.0f} {currency}/گرم` تنظیم شد.",
        parse_mode="Markdown",
        reply_markup=back_to_dashboard_kb(),
    )


# ── Statistics ────────────────────────────────────────────────────────────────

async def cb_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sheet, _, cache = _services(context)
    q = update.callback_query
    stats = await asyncio.to_thread(sheet.get_statistics)
    text  = format_statistics(stats, cache.stats)
    await _safe_edit(q.message, text, parse_mode="Markdown", reply_markup=back_to_dashboard_kb())


# ── Settings ──────────────────────────────────────────────────────────────────

async def cb_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sheet, _, _ = _services(context)
    q = update.callback_query
    settings = await asyncio.to_thread(sheet.get_settings)
    await _safe_edit(q.message, "⚙️ *تنظیمات فروشگاه*:", parse_mode="Markdown", reply_markup=settings_kb(settings))


async def cb_settings_field(update: Update, context: ContextTypes.DEFAULT_TYPE, field: str) -> None:
    _, _, cache = _services(context)
    q = update.callback_query
    state = cache.get_admin_state()
    state.action     = "settings_edit"
    state.step       = "waiting_value"
    state.field_name = field
    cache.save_admin_state(state)
    label = {
        "store_name":    "نام فروشگاه",
        "store_phone":   "تلفن",
        "store_address": "آدرس",
        "currency":      "واحد پول (مثلاً toman یا rial)",
        "post_footer":   "متن پایانی پست‌ها",
    }.get(field, field)
    hint = (
        "\n\nاین متن در انتهای هر پست محصول در کانال اضافه می‌شود.\n"
        "برای حذف کامل، یک فاصله خالی ارسال کنید."
        if field == "post_footer" else ""
    )
    await _safe_edit(
        q.message,
        f"⚙️ مقدار جدید برای «{label}» را وارد کنید:{hint}",
        reply_markup=back_to_dashboard_kb(),
    )


async def _apply_settings_value(update, context, state: AdminState, text: str, sheet: SheetService, cache: Cache) -> None:
    await asyncio.to_thread(sheet.update_setting, state.field_name, text)
    cache.clear_admin_state()
    await update.message.reply_text(
        f"✅ تنظیم «{state.field_name}» به «{text}» تغییر یافت.",
        reply_markup=back_to_dashboard_kb(),
    )


# ── Backup ────────────────────────────────────────────────────────────────────

async def cb_backup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sheet, _, _ = _services(context)
    q = update.callback_query
    await q.answer("⏳ در حال آماده‌سازی فایل …")
    try:
        json_data = await asyncio.to_thread(sheet.export_products_json)
        file_bytes = json_data.encode("utf-8")
        import datetime
        fname = f"gold_bot_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.json"
        await context.bot.send_document(
            chat_id=ADMIN_ID,
            document=io.BytesIO(file_bytes),
            filename=fname,
            caption=f"📁 پشتیبان محصولات – {fname}",
        )
        await _safe_edit(q.message, "✅ فایل پشتیبان ارسال شد.", reply_markup=back_to_dashboard_kb())
    except Exception as exc:
        logger.error("Backup failed: %s", exc)
        await _safe_edit(q.message, f"❌ خطا در پشتیبان‌گیری: {exc}", reply_markup=back_to_dashboard_kb())


# ── Refresh cache ─────────────────────────────────────────────────────────────

async def cb_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Legacy — kept for any old callback_data references. Delegates to cb_sync."""
    await cb_sync(update, context)


async def cb_sync(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    🔄 همگام‌سازی شیت

    Clears ALL in-memory sheet caches and immediately reloads products from
    Google Sheets so any changes made directly in the spreadsheet (new rows,
    edits, deletions) are instantly visible in the bot — no restart needed.
    """
    sheet, _, cache = _services(context)
    q = update.callback_query

    await _safe_edit(q.message, "⏳ در حال همگام‌سازی با Google Sheets …")

    try:
        await asyncio.to_thread(sheet.invalidate_cache)
        # Eagerly pre-load so we can report the count immediately
        products = await asyncio.to_thread(sheet.get_products)
        available = sum(1 for p in products if p.is_available)
        cache.clear_admin_state()
        await _safe_edit(
            q.message,
            f"✅ *همگام‌سازی کامل شد.*\n\n"
            f"📦 کل محصولات: `{len(products)}`\n"
            f"✅ موجود و فعال: `{available}`",
            parse_mode="Markdown",
            reply_markup=dashboard_kb(),
        )
        logger.info("Sheet synced: %d products loaded (%d available).", len(products), available)
    except Exception as exc:
        logger.error("Sync failed: %s", exc, exc_info=True)
        await _safe_edit(
            q.message,
            f"❌ خطا در همگام‌سازی:\n{exc}",
            reply_markup=back_to_dashboard_kb(),
        )


# ── Customers / Wishlist ──────────────────────────────────────────────────────

async def cb_customers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """👥 مشتریان — overview panel."""
    from keyboards.admin_keyboard import customers_kb
    q = update.callback_query
    cust_svc: "CustomerService" = context.bot_data.get("customer_service")
    if cust_svc is None:
        await _safe_edit(q.message, "⚠️ سرویس مشتریان در دسترس نیست.", reply_markup=back_to_dashboard_kb())
        return

    try:
        all_custs = await asyncio.to_thread(cust_svc.get_all_profiles)
        count = len(all_custs)
        notify_count = sum(1 for c in all_custs if c.notify_enabled)
    except Exception as exc:
        logger.error("Customers load error: %s", exc)
        count = "؟"
        notify_count = "؟"

    await _safe_edit(
        q.message,
        f"👥 *مدیریت مشتریان*\n\n"
        f"👤 کل مشتریان ثبت‌شده: `{count}`\n"
        f"🔔 با نوتیف فعال: `{notify_count}`\n\n"
        "از این بخش می‌توانید لیست کامل مشتریان را ببینید\n"
        "و وقتی محصول جدیدی موجود شد، نوتیف دستی بفرستید.",
        parse_mode="Markdown",
        reply_markup=customers_kb(),
    )


async def cb_customers_list(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> None:
    """📋 لیست همه مشتریان ثبت‌شده در شیت (نه فقط نوتیف‌فعال‌ها — رفع باگ Task 1)."""
    q = update.callback_query
    cust_svc: "CustomerService" = context.bot_data.get("customer_service")
    if cust_svc is None:
        await q.answer("⚠️ سرویس در دسترس نیست.", show_alert=True)
        return

    try:
        custs = await asyncio.to_thread(cust_svc.get_all_profiles)
    except Exception as exc:
        logger.error("Failed to load customer list: %s", exc)
        await _safe_edit(q.message, f"❌ خطا: {exc}", reply_markup=back_to_dashboard_kb())
        return

    if not custs:
        await _safe_edit(
            q.message,
            "👥 هنوز هیچ مشتری‌ای در شیت ثبت نشده.\n\n"
            "به محض اولین گفتگوی یک مشتری با ربات، اینجا نمایش داده می‌شود.",
            reply_markup=back_to_dashboard_kb(),
        )
        return

    per_page = 8
    total_pages = max(1, -(-len(custs) // per_page))
    page = max(0, min(page, total_pages - 1))
    page_custs = custs[page * per_page: (page + 1) * per_page]

    lines = []
    for c in page_custs:
        bud_str = f" | بودجه: {c.max_budget:,.0f}" if c.max_budget else ""
        cat_str = f" | {c.category}" if c.category else ""
        bell    = " 🔔" if c.notify_enabled else ""
        lines.append(f"• `{c.user_id}` — {c.name or 'ناشناس'}{cat_str}{bud_str}{bell}")

    text = (
        f"👥 *همه مشتریان* ({len(custs)} نفر)\n"
        f"صفحه {page + 1}/{total_pages}\n\n"
        + "\n".join(lines)
    )

    from keyboards.admin_keyboard import customers_kb
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ قبل", callback_data=f"a:cust_list:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("بعد ▶️", callback_data=f"a:cust_list:{page + 1}"))
    kb_rows = []
    if nav:
        kb_rows.append(nav)
    kb_rows.append([InlineKeyboardButton("🔙 برگشت", callback_data="a:cust")])

    await _safe_edit(q.message, text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb_rows))


async def cb_customers_notify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """📢 انتشار نوتیف دستی — ادمین یک محصول انتخاب می‌کند تا نوتیف بفرستد."""
    sheet, _, _ = _services(context)
    q = update.callback_query
    products = await asyncio.to_thread(sheet.get_products)
    available = [p for p in products if p.is_available]
    if not available:
        await _safe_edit(q.message, "⚠️ هیچ محصول موجودی یافت نشد.", reply_markup=back_to_dashboard_kb())
        return
    await _safe_edit(
        q.message,
        "📢 *ارسال نوتیف دستی*\n\nمحصولی که می‌خواهید برای مشتریان علاقه‌مند نوتیف بفرستید را انتخاب کنید:",
        parse_mode="Markdown",
        reply_markup=products_list_kb(available, 0, action_prefix="a:cust_nsel", back_cb="a:cust"),
    )


async def cb_customers_notify_preview(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int) -> None:
    """نمایش پیش‌نمایش نوتیف قبل از ارسال."""
    from keyboards.admin_keyboard import customer_notify_confirm_kb
    sheet, gold, _ = _services(context)
    q = update.callback_query

    product = await asyncio.to_thread(sheet.get_product_by_id, product_id)
    if not product:
        await q.answer("⚠️ محصول یافت نشد.", show_alert=True)
        return

    gp, settings = await asyncio.gather(
        asyncio.to_thread(gold.get_gold_price),
        asyncio.to_thread(sheet.get_settings),
    )
    price    = calculate_price(product, gp)
    currency = currency_label(settings)

    cust_svc: "CustomerService" = context.bot_data.get("customer_service")
    matched = 0
    if cust_svc:
        try:
            matched = len(await asyncio.to_thread(cust_svc.customers_matching_product, product, gp))
        except Exception:
            pass

    text = (
        f"📢 *پیش‌نمایش نوتیف*\n\n"
        f"محصول: *{_md_escape(product.name)}*\n"
        f"قیمت تقریبی: `{price:,.0f} {currency}`\n\n"
        f"👥 مشتریان مرتبط که نوتیف دریافت می‌کنند: `{matched}` نفر\n\n"
        "آیا نوتیف ارسال شود؟"
    )
    await _safe_edit(q.message, text, parse_mode="Markdown", reply_markup=customer_notify_confirm_kb(product_id))


async def cb_customers_notify_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int) -> None:
    """ارسال واقعی نوتیف به مشتریان مرتبط."""
    from services.customer_service import notify_interested_customers
    sheet, gold, _ = _services(context)
    q = update.callback_query

    product = await asyncio.to_thread(sheet.get_product_by_id, product_id)
    if not product:
        await _safe_edit(q.message, "⚠️ محصول یافت نشد.", reply_markup=back_to_dashboard_kb())
        return

    gp, settings = await asyncio.gather(
        asyncio.to_thread(gold.get_gold_price),
        asyncio.to_thread(sheet.get_settings),
    )
    cust_svc: "CustomerService" = context.bot_data.get("customer_service")
    if not cust_svc:
        await _safe_edit(q.message, "⚠️ سرویس مشتریان در دسترس نیست.", reply_markup=back_to_dashboard_kb())
        return

    await _safe_edit(q.message, "⏳ در حال ارسال نوتیف‌ها …")
    try:
        count = await notify_interested_customers(context.bot, product, gp, cust_svc, currency_label(settings))
        await _safe_edit(
            q.message,
            f"✅ نوتیف برای «{_md_escape(product.name)}» به *{count}* مشتری ارسال شد.",
            parse_mode="Markdown",
            reply_markup=back_to_dashboard_kb(),
        )
        logger.info("Manual notify: product %d → %d customers.", product_id, count)
    except Exception as exc:
        logger.error("Manual notify failed: %s", exc, exc_info=True)
        await _safe_edit(q.message, f"❌ خطا در ارسال نوتیف: {exc}", reply_markup=back_to_dashboard_kb())


# ── Back-in-stock requests (Task 6) ─────────────────────────────────────────

async def cb_back_in_stock(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> None:
    """📦 درخواست‌های موجودی — admin view of the back-in-stock waitlist."""
    q = update.callback_query
    stock_svc = context.bot_data.get("stock_notification_service")
    if stock_svc is None:
        await _safe_edit(q.message, "⚠️ سرویس موجودی در دسترس نیست.", reply_markup=back_to_dashboard_kb())
        return

    try:
        requests = await asyncio.to_thread(stock_svc.get_all_requests)
    except Exception as exc:
        logger.error("Failed to load back-in-stock requests: %s", exc)
        await _safe_edit(q.message, f"❌ خطا: {exc}", reply_markup=back_to_dashboard_kb())
        return

    waiting_count = sum(1 for r in requests if str(r.get("status", "") or "").strip().lower() == "waiting")

    if not requests:
        await _safe_edit(
            q.message,
            "📦 *درخواست‌های موجودی*\n\n"
            "هنوز هیچ درخواستی ثبت نشده.\n\n"
            "وقتی مشتری درباره محصولی ناموجود سوال کند، درخواستش خودکار اینجا ثبت می‌شود.",
            parse_mode="Markdown",
            reply_markup=back_to_dashboard_kb(),
        )
        return

    per_page = 8
    total_pages = max(1, -(-len(requests) // per_page))
    page = max(0, min(page, total_pages - 1))
    page_reqs = requests[page * per_page: (page + 1) * per_page]

    status_label = {"waiting": "⏳ در انتظار", "notified": "✅ اطلاع داده شد"}
    lines = []
    for r in page_reqs:
        status = str(r.get("status", "") or "").strip().lower()
        label  = status_label.get(status, status or "؟")
        pname  = _md_escape(r.get("product_name") or "؟")
        pid    = r.get("product_id") or "؟"
        uname  = _md_escape(str(r.get("user_name") or r.get("user_id") or "ناشناس"))
        date   = r.get("requested_at") or "—"
        lines.append(f"• [{pid}] {pname} — {uname} — {date} — {label}")

    text = (
        f"📦 *درخواست‌های موجودی*\n\n"
        f"⏳ در انتظار: `{waiting_count}`  |  📋 کل: `{len(requests)}`\n"
        f"صفحه {page + 1}/{total_pages}\n\n"
        + "\n".join(lines)
    )

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ قبل", callback_data=f"a:bis:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("بعد ▶️", callback_data=f"a:bis:{page + 1}"))
    kb_rows = []
    if nav:
        kb_rows.append(nav)
    kb_rows.append([InlineKeyboardButton("🔙 برگشت", callback_data="a:d")])

    await _safe_edit(q.message, text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb_rows))


# ── Support ───────────────────────────────────────────────────────────────────

async def cb_support_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, cache = _services(context)
    q = update.callback_query
    uids = list(cache.support_queue.keys())
    if not uids:
        await _safe_edit(q.message, "💬 هیچ درخواست پشتیبانی در صف نیست.", reply_markup=back_to_dashboard_kb())
        return
    # Fetch user names (best-effort from cache)
    user_names: dict[int, str] = {}
    for uid in uids:
        msgs = cache.support_queue.get(uid, [])
        user_names[uid] = str(uid)  # fallback; real name stored on first contact
    await _safe_edit(
        q.message,
        f"💬 *درخواست‌های پشتیبانی* ({len(uids)} کاربر):",
        parse_mode="Markdown",
        reply_markup=support_list_kb(uids, user_names),
    )


async def cb_support_chat(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    _, _, cache = _services(context)
    q = update.callback_query
    msgs = cache.support_queue.get(user_id, [])
    if not msgs:
        await q.answer("هیچ پیامی یافت نشد.", show_alert=True)
        return
    history = "\n".join(
        f"{'👤' if m['role'] == 'user' else '👨‍💼'} [{m['time']}] {m['text']}"
        for m in msgs[-10:]
    )
    await _safe_edit(
        q.message,
        f"💬 *گفتگو با کاربر {user_id}:*\n\n{history}",
        parse_mode="Markdown",
        reply_markup=support_chat_kb(user_id),
    )


async def cb_support_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    _, _, cache = _services(context)
    q = update.callback_query
    state = cache.get_admin_state()
    state.action        = "reply"
    state.reply_user_id = user_id
    cache.save_admin_state(state)
    await _safe_edit(
        q.message,
        f"✏️ پیام خود را برای کاربر `{user_id}` بنویسید:",
        parse_mode="Markdown",
        reply_markup=back_to_dashboard_kb(),
    )


async def cb_support_close(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    _, _, cache = _services(context)
    cache.clear_support(user_id)
    q = update.callback_query
    await _safe_edit(q.message, f"✅ تیکت کاربر {user_id} بسته شد.", reply_markup=back_to_dashboard_kb())


async def _forward_admin_reply(update, context, state: AdminState, text: str, cache: Cache) -> None:
    uid = state.reply_user_id
    success = await send_admin_reply_to_customer(context.bot, uid, text)
    cache.add_support_message(uid, "admin", text)
    cache.clear_admin_state()
    if success:
        await update.message.reply_text(f"✅ پاسخ به کاربر {uid} ارسال شد.", reply_markup=back_to_dashboard_kb())
    else:
        await update.message.reply_text(f"⚠️ کاربر {uid} ربات را مسدود کرده است.", reply_markup=back_to_dashboard_kb())
