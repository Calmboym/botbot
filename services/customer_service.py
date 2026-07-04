"""
Gold Bot v2 – Customer Tracking Service
=========================================
Manages the 'customers' worksheet which records:
  • Every customer's Telegram ID and name
  • Their extracted preferences / wishlist (budget, category, weight, etc.)
  • A summary of their expressed needs (filled by AI)
  • Whether they have opted in for restock notifications

Columns in the 'customers' sheet:
    user_id | name | category | gold_color | stone | max_weight |
    max_budget | gender | style | notes | notify | last_seen | updated_at

The 'notify' column is either "yes" or "" (empty = no).

Notification flow:
    When the admin publishes a product (or manually triggers a check),
    check_and_notify() is called. It loads all customers with notify="yes",
    applies SearchService filters against the new product, and sends a
    Telegram message to every matched customer.
"""

import asyncio
import datetime
import logging
from typing import Optional, TYPE_CHECKING

import gspread

from config.config import (
    CUSTOMERS_SHEET, GOOGLE_SCOPES, SERVICE_ACCOUNT_FILE, SPREADSHEET_NAME,
)

if TYPE_CHECKING:
    from models.product import Product
    from utils.cache import ConversationState

logger = logging.getLogger(__name__)

# ── Column header list (order must match sheet) ───────────────────────────────
_HEADERS = [
    "user_id", "name", "category", "gold_color", "stone",
    "max_weight", "max_budget", "gender", "style", "notes",
    "notify", "last_seen", "updated_at",
]


class CustomerService:
    def __init__(self) -> None:
        pass

    # ── Private helpers ───────────────────────────────────────────────────────

    def _ws(self) -> gspread.Worksheet:
        from google.oauth2.service_account import Credentials
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=GOOGLE_SCOPES)
        client = gspread.Client(auth=creds)
        ss = client.open(SPREADSHEET_NAME)
        try:
            ws = ss.worksheet(CUSTOMERS_SHEET)
        except gspread.exceptions.WorksheetNotFound:
            # Auto-create the sheet with headers on first use
            ws = ss.add_worksheet(title=CUSTOMERS_SHEET, rows=1000, cols=len(_HEADERS))
            ws.append_row(_HEADERS)
            logger.info("Created '%s' worksheet.", CUSTOMERS_SHEET)
        return ws

    def _find_row(self, ws: gspread.Worksheet, user_id: int) -> tuple[int, Optional[dict]]:
        """Return (row_idx, record) for a user, or (0, None) if not found."""
        records = ws.get_all_records(numericise_ignore=["all"])
        for offset, rec in enumerate(records):
            try:
                if int(str(rec.get("user_id", "") or "0").strip()) == user_id:
                    return offset + 2, rec
            except (ValueError, TypeError):
                continue
        return 0, None

    # ── Public API ────────────────────────────────────────────────────────────

    def upsert_customer(
        self,
        user_id: int,
        name: str,
        conv_state: "ConversationState",
        notes: str = "",
        notify: bool = False,
    ) -> None:
        """
        Insert or update a customer row with the latest preferences extracted
        from their conversation state.

        Called at the end of every AI conversation turn so the sheet always
        reflects the customer's most up-to-date interests.
        """
        try:
            ws  = self._ws()
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            p   = conv_state.preferences

            row_data = {
                "user_id":    str(user_id),
                "name":       name,
                "category":   p.category or "",
                "gold_color": p.gold_color or "",
                "stone":      p.stone or "",
                "max_weight": str(p.max_weight) if p.max_weight else "",
                "max_budget": str(int(p.budget)) if p.budget else "",
                "gender":     p.gender or "",
                "style":      ", ".join(p.style_keywords) if p.style_keywords else "",
                "notes":      notes,
                "notify":     "yes" if notify else "",
                "last_seen":  now,
                "updated_at": now,
            }

            row_idx, existing = self._find_row(ws, user_id)

            if existing:
                # Preserve notify flag unless we're explicitly changing it
                if not notify and existing.get("notify") == "yes":
                    row_data["notify"] = "yes"
                # Preserve existing notes unless new ones provided
                if not notes:
                    row_data["notes"] = existing.get("notes", "")
                # Update row in-place
                ws.update(
                    range_name=f"A{row_idx}",
                    values=[[row_data[h] for h in _HEADERS]],
                )
                logger.debug("Updated customer row for user %d at row %d.", user_id, row_idx)
            else:
                ws.append_row([row_data[h] for h in _HEADERS])
                logger.info("Inserted new customer row for user %d.", user_id)

        except Exception as exc:
            # Never let CRM write failures crash the bot
            logger.error("Failed to upsert customer %d: %s", user_id, exc)

    def set_notify(self, user_id: int, notify: bool) -> None:
        """Toggle the restock notification flag for a customer."""
        try:
            ws = self._ws()
            row_idx, rec = self._find_row(ws, user_id)
            if not rec:
                logger.warning("Cannot set notify for unknown user %d.", user_id)
                return
            notify_col = _HEADERS.index("notify") + 1
            ws.update_cell(row_idx, notify_col, "yes" if notify else "")
            logger.info("Set notify=%s for user %d.", notify, user_id)
        except Exception as exc:
            logger.error("Failed to set notify for user %d: %s", user_id, exc)

    def get_notify_customers(self) -> list[dict]:
        """Return all customers who have opted in for restock notifications."""
        try:
            ws = self._ws()
            records = ws.get_all_records(numericise_ignore=["all"])
            return [
                r for r in records
                if str(r.get("notify", "") or "").strip().lower() == "yes"
            ]
        except Exception as exc:
            logger.error("Failed to load notify customers: %s", exc)
            return []

    # ── Notification matching ─────────────────────────────────────────────────

    def customers_matching_product(
        self, product: "Product", gold_price: float
    ) -> list[dict]:
        """
        Return customers whose saved wishlist matches the given product.
        Used after a product's stock changes from 0 → positive.
        """
        from services.price_service import calculate_price
        interested = []
        price = calculate_price(product, gold_price)

        for cust in self.get_notify_customers():
            if not self._matches(cust, product, price):
                continue
            interested.append(cust)

        logger.info(
            "Product %d ('%s') matched %d notify-customers.",
            product.id, product.name, len(interested),
        )
        return interested

    def _matches(self, cust: dict, product: "Product", price: float) -> bool:
        """Return True if the product satisfies the customer's saved preferences."""
        def _str(k: str) -> str:
            return str(cust.get(k, "") or "").strip().lower()
        def _float(k: str) -> Optional[float]:
            raw = str(cust.get(k, "") or "").strip().replace(",", "")
            try:
                return float(raw) if raw else None
            except ValueError:
                return None

        # Category
        cat = _str("category")
        if cat and product.category and cat not in product.category.lower():
            return False

        # Gold color
        color = _str("gold_color")
        if color and product.gold_color and color not in product.gold_color.lower():
            return False

        # Stone
        stone = _str("stone")
        if stone and stone not in ("", "any", "هر"):
            if stone == "بدون سنگ" and product.stone and product.stone not in ("", "بدون سنگ", "ندارد"):
                return False
            elif stone != "بدون سنگ" and product.stone and stone not in product.stone.lower():
                return False

        # Gender
        gender = _str("gender")
        if gender and product.gender and gender not in product.gender.lower() and product.gender.lower() != "یونیسکس":
            return False

        # Budget
        max_budget = _float("max_budget")
        if max_budget and price > max_budget:
            return False

        # Weight
        max_weight = _float("max_weight")
        if max_weight and product.weight > max_weight:
            return False

        # Product must be available
        if not product.is_available:
            return False

        return True


# ── Async notification sender ─────────────────────────────────────────────────

async def notify_interested_customers(
    bot,
    product: "Product",
    gold_price: float,
    customer_service: CustomerService,
) -> int:
    """
    Send a restock notification to every customer whose wishlist matches
    the given product.

    Returns the number of customers successfully notified.
    """
    from services.price_service import calculate_price
    from telegram.error import TelegramError

    matched = await asyncio.to_thread(
        customer_service.customers_matching_product, product, gold_price
    )
    if not matched:
        return 0

    price = calculate_price(product, gold_price)
    notified = 0

    for cust in matched:
        try:
            uid_raw = str(cust.get("user_id", "") or "").strip()
            if not uid_raw:
                continue
            uid = int(uid_raw)
        except ValueError:
            continue

        try:
            msg = (
                f"🔔 *محصول مورد نظر شما موجود شد!*\n\n"
                f"💍 {product.name}\n"
                f"🎨 {product.gold_color or '—'} | {product.purity}\n"
                f"💎 {product.stone or 'بدون سنگ'}\n"
                f"⚖️ {product.weight} گرم\n"
                f"💰 قیمت تقریبی: `{price:,.0f} تومان`\n\n"
                f"برای اطلاعات بیشتر و خرید با فروشگاه تماس بگیرید."
            )
            await bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown")
            notified += 1
            logger.info("Restock notification sent to user %d for product %d.", uid, product.id)
        except TelegramError as exc:
            logger.warning("Could not notify user %d: %s", uid, exc)

    return notified
