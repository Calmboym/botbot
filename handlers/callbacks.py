"""
Gold Bot v2 – Callback Router
================================
Single entry-point for every InlineKeyboardButton press.

CRITICAL FIX: query.answer() must be called EXACTLY ONCE per callback.
- Admin callbacks: answered in router (handlers use edit_message, not answer)
- Customer callbacks: NOT answered in router — each handler calls it once
  with show_alert=True so the popup is guaranteed to appear.

Routing scheme:
    a:<action>[:<p1>[:<p2>[:<p3>]]]   →  admin handler
    c:<action>[:<p1>]                 →  customer handler (popup)
"""

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from services.gold_service import GoldService
from services.price_service import format_price_alert, format_gold_price_alert
from services.sheet_service import SheetService
from utils.cache import Cache
from utils.validators import is_admin

import handlers.admin as adm

logger = logging.getLogger(__name__)


# ── Entry point ───────────────────────────────────────────────────────────────

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    data    = query.data
    user_id = query.from_user.id

    if data == "a:noop":
        await query.answer()
        return

    if data.startswith("a:"):
        # ── Admin ──────────────────────────────────────────────────────────────
        if not is_admin(user_id):
            await query.answer("⛔ دسترسی مجاز نیست.", show_alert=True)
            return
        await query.answer()   # Admin handlers use edit_message, so answer first
        await _route_admin(update, context, data)

    elif data.startswith("c:"):
        # ── Customer ───────────────────────────────────────────────────────────
        # ⚠️ DO NOT call query.answer() here.
        # Each customer handler calls it once with show_alert=True.
        # Calling it here first would "consume" the callback and prevent the popup.
        await _route_customer(update, context, data)

    else:
        logger.warning("Unknown callback: %r from user %d", data, user_id)
        await query.answer("⚠️ عملیات ناشناخته.", show_alert=True)


# ══════════════════════════════════════════════════════════════════════════════
# Admin routing
# ══════════════════════════════════════════════════════════════════════════════

async def _route_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:  # noqa: C901
    parts  = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    params = parts[2:] if len(parts) > 2 else []

    if action == "d":
        await adm.cb_dashboard(update, context)
    elif action == "pl":
        await adm.cb_products_list(update, context, int(params[0]) if params else 0)
    elif action == "ps":
        await adm.cb_product_select(update, context, int(params[0]) if params else 0)
    elif action == "pub_list":
        await adm.cb_publish_list(update, context)
    elif action == "pub":
        await adm.cb_publish_preview(update, context, int(params[0]) if params else 0)
    elif action == "pubc":
        await adm.cb_publish_confirm(update, context, int(params[0]) if params else 0)
    elif action == "e_list":
        await adm.cb_edit_list(update, context)
    elif action == "e":
        await adm.cb_edit_groups(update, context, int(params[0]) if params else 0)
    elif action == "eg":
        gi  = int(params[0]) if len(params) > 0 else 0
        pid = int(params[1]) if len(params) > 1 else 0
        await adm.cb_edit_field_group(update, context, gi, pid)
    elif action == "ef":
        field = params[0] if len(params) > 0 else ""
        pid   = int(params[1]) if len(params) > 1 else 0
        await adm.cb_edit_field(update, context, field, pid)
    elif action == "efo":
        field = params[0] if len(params) > 0 else ""
        pid   = int(params[1]) if len(params) > 1 else 0
        value = ":".join(params[2:]) if len(params) > 2 else ""
        await adm.cb_edit_field_option(update, context, field, pid, value)
    elif action == "del_list":
        await adm.cb_delete_list(update, context)
    elif action == "del":
        await adm.cb_delete_confirm_prompt(update, context, int(params[0]) if params else 0)
    elif action == "delc":
        await adm.cb_delete_execute(update, context, int(params[0]) if params else 0)
    elif action == "add":
        await adm.cb_add_start(update, context)
    elif action == "add_o":
        step  = params[0] if len(params) > 0 else ""
        value = ":".join(params[1:]) if len(params) > 1 else ""
        await adm.cb_add_option(update, context, step, value)
    elif action == "add_skip":
        await adm.cb_add_skip(update, context, params[0] if params else "")
    elif action == "add_conf":
        await adm.cb_add_confirm(update, context)
    elif action == "add_cancel":
        await adm.cb_add_cancel(update, context)
    elif action == "gp":
        await adm.cb_gold_price_menu(update, context)
    elif action == "gp_scr":
        await adm.cb_gold_price_scrape(update, context)
    elif action == "gp_man":
        await adm.cb_gold_price_manual(update, context)
    elif action == "st":
        await adm.cb_statistics(update, context)
    elif action == "se":
        await adm.cb_settings(update, context)
    elif action == "se_f":
        await adm.cb_settings_field(update, context, params[0] if params else "")
    elif action == "bk":
        await adm.cb_backup(update, context)
    elif action == "rf":
        await adm.cb_refresh(update, context)
    elif action == "sync":
        await adm.cb_sync(update, context)
    elif action == "cust":
        await adm.cb_customers(update, context)
    elif action == "cust_list":
        page = int(params[0]) if params else 0
        await adm.cb_customers_list(update, context, page)
    elif action == "cust_notify":
        await adm.cb_customers_notify(update, context)
    elif action == "cust_nsel":
        pid = int(params[0]) if params else 0
        await adm.cb_customers_notify_preview(update, context, pid)
    elif action == "cust_nconf":
        pid = int(params[0]) if params else 0
        await adm.cb_customers_notify_confirm(update, context, pid)
    elif action == "sup":
        await adm.cb_support_list(update, context)
    elif action == "sup_c":
        await adm.cb_support_chat(update, context, int(params[0]) if params else 0)
    elif action == "sup_r":
        await adm.cb_support_reply(update, context, int(params[0]) if params else 0)
    elif action == "sup_x":
        await adm.cb_support_close(update, context, int(params[0]) if params else 0)
    else:
        logger.warning("Unhandled admin callback: %r", action)
        await update.callback_query.answer("⚠️ عملیات پیاده‌سازی نشده.", show_alert=True)


# ══════════════════════════════════════════════════════════════════════════════
# Customer routing  — every branch calls query.answer() exactly once
# ══════════════════════════════════════════════════════════════════════════════

async def _route_customer(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    parts  = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    params = parts[2:] if len(parts) > 2 else []
    query  = update.callback_query

    sheet: SheetService = context.bot_data["sheet_service"]
    gold:  GoldService  = context.bot_data["gold_service"]
    cache: Cache        = context.bot_data["cache"]

    # ── 📈 Live gold price ────────────────────────────────────────────────────
    if action == "gp":
        try:
            price    = await asyncio.to_thread(gold.get_gold_price)
            last_upd = await asyncio.to_thread(gold.get_last_update)
            if price == 0:
                await query.answer(
                    "⚠️ قیمت طلا هنوز تنظیم نشده است.\nلطفاً با فروشگاه تماس بگیرید.",
                    show_alert=True,
                )
            else:
                await query.answer(
                    format_gold_price_alert(price, last_upd),
                    show_alert=True,
                )
        except Exception as exc:
            logger.error("Customer gold price callback error: %s", exc)
            await query.answer("⚠️ خطا در دریافت قیمت طلا. دوباره تلاش کنید.", show_alert=True)

    # ── 💎 Product price calculation ──────────────────────────────────────────
    elif action == "pp":
        pid = int(params[0]) if params else 0
        try:
            product = await asyncio.to_thread(sheet.get_product_by_id, pid)
            if product is None:
                await query.answer(f"⚠️ محصول یافت نشد.", show_alert=True)
                return
            gold_price = await asyncio.to_thread(gold.get_gold_price)
            if gold_price == 0:
                await query.answer(
                    "⚠️ قیمت طلا هنوز تنظیم نشده است.\nلطفاً با فروشگاه تماس بگیرید.",
                    show_alert=True,
                )
                return
            alert_text = format_price_alert(product, gold_price)
            await query.answer(alert_text, show_alert=True)
        except Exception as exc:
            logger.error("Customer product price callback error (pid=%s): %s", params, exc)
            await query.answer("⚠️ خطا در محاسبه قیمت. دوباره تلاش کنید.", show_alert=True)

    # ── 🤖 Ask about this product ─────────────────────────────────────────────
    elif action == "ask":
        pid = int(params[0]) if params else 0
        try:
            product = await asyncio.to_thread(sheet.get_product_by_id, pid)
            if product is None:
                await query.answer("⚠️ محصول یافت نشد.", show_alert=True)
                return
            # Save product context for next message
            conv_state = cache.get_conversation(query.from_user.id)
            conv_state.current_product_id = pid
            cache.save_conversation(conv_state)
            # Show popup — works regardless of whether user has started the bot
            await query.answer(
                f"✅ به ربات پیام بفرستید و سوال خود درباره\n«{product.name[:40]}» را بپرسید.",
                show_alert=True,
            )
        except Exception as exc:
            logger.error("Ask about product callback error (pid=%s): %s", params, exc)
            await query.answer("⚠️ خطا. دوباره تلاش کنید.", show_alert=True)

    # ── 🧑‍💼 Request human support ────────────────────────────────────────────
    elif action == "sup":
        uid       = query.from_user.id
        user_name = query.from_user.full_name or str(uid)
        conv      = cache.get_conversation(uid)
        if conv.support_requested:
            await query.answer(
                "✅ درخواست شما قبلاً ثبت شده است.\nمنتظر پاسخ کارشناس باشید.",
                show_alert=True,
            )
            return
        conv.support_requested = True
        cache.save_conversation(conv)
        cache.add_support_message(uid, "user", "درخواست اتصال به پشتیبانی")
        from services.telegram_service import notify_admin_support
        await notify_admin_support(context.bot, uid, user_name, "درخواست پشتیبانی انسانی")
        await query.answer(
            "✅ درخواست شما ثبت شد.\nکارشناس ما به زودی پاسخ می‌دهد.",
            show_alert=True,
        )

    # ── 🔔 Restock notification opt-in / opt-out ──────────────────────────────
    elif action in ("notify_on", "notify_off"):
        uid      = query.from_user.id
        notify   = (action == "notify_on")
        cust_svc = context.bot_data.get("customer_service")
        if cust_svc is None:
            await query.answer("⚠️ سرویس در دسترس نیست.", show_alert=True)
            return
        try:
            conv = cache.get_conversation(uid)
            await asyncio.to_thread(
                cust_svc.upsert_customer,
                uid,
                query.from_user.full_name or str(uid),
                conv,
                notify=notify,
            )
            if notify:
                await query.answer(
                    "✅ ثبت شد! هر وقت محصول مناسبی موجود شد، خبرتان می‌دهیم.",
                    show_alert=True,
                )
            else:
                await query.answer("✅ اطلاع‌رسانی غیرفعال شد.", show_alert=False)
        except Exception as exc:
            logger.error("notify toggle error for user %d: %s", uid, exc)
            await query.answer("⚠️ خطا در ثبت. دوباره تلاش کنید.", show_alert=True)

    else:
        logger.warning("Unhandled customer callback: %r", action)
        await query.answer("⚠️ عملیات ناشناخته.", show_alert=True)
