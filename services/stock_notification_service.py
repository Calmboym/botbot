"""
Gold Bot v2 – Back-In-Stock Notification Service
====================================================
Persists "notify me when this exact product is available again" requests
to the 'back_in_stock' worksheet, and sends the automatic notification
once that exact product becomes available.

This is intentionally separate from CustomerService's existing
notify_interested_customers() system:

    - CustomerService / notify_interested_customers  → FUZZY matching.
      Admin manually picks a product and broadcasts to every customer
      whose long-term stated PREFERENCES (budget, color, category, ...)
      are a good fit. Unrelated to any specific product a customer
      previously asked about.

    - StockNotificationService (this file)           → EXACT matching.
      A customer asked about ONE specific product while it happened to
      be unavailable. We remember that exact product_id and, fully
      automatically (no admin action needed), message ONLY that
      customer the moment that exact product is back — then never again.

Sheet columns:
    user_id | user_name | chat_id | product_id | product_name |
    requested_at | status | notified_at

status is one of: "waiting" | "notified". A row moves waiting -> notified
exactly once, which is what makes "never send duplicates" a structural
guarantee rather than something callers have to remember to check.
"""

import datetime
import logging

import gspread

from config.config import (
    BACK_IN_STOCK_SHEET, GOOGLE_SCOPES, SERVICE_ACCOUNT_FILE, SPREADSHEET_NAME,
)

logger = logging.getLogger(__name__)

_HEADERS = [
    "user_id", "user_name", "chat_id", "product_id", "product_name",
    "requested_at", "status", "notified_at",
]

_STATUS_WAITING  = "waiting"
_STATUS_NOTIFIED = "notified"


class StockNotificationService:
    # ── Private helpers ───────────────────────────────────────────────────────

    def _ws(self) -> gspread.Worksheet:
        from google.oauth2.service_account import Credentials
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=GOOGLE_SCOPES)
        client = gspread.Client(auth=creds)
        ss = client.open(SPREADSHEET_NAME)
        try:
            ws = ss.worksheet(BACK_IN_STOCK_SHEET)
        except gspread.exceptions.WorksheetNotFound:
            ws = ss.add_worksheet(title=BACK_IN_STOCK_SHEET, rows=1000, cols=len(_HEADERS))
            ws.append_row(_HEADERS)
            logger.info("Created '%s' worksheet.", BACK_IN_STOCK_SHEET)
            return ws

        self._ensure_valid_headers(ws)
        return ws

    def _ensure_valid_headers(self, ws: gspread.Worksheet) -> None:
        """
        Same defensive header repair as CustomerService._ensure_valid_headers()
        — get_all_records() raises on any empty/duplicate header cell, which
        is exactly the class of bug already fixed once for the 'customers'
        sheet. Applying the identical guard here up front avoids repeating
        that bug for this new sheet. Data rows are never touched.
        """
        try:
            raw_headers = ws.row_values(1)
        except Exception as exc:
            logger.error("Could not read header row for '%s': %s", BACK_IN_STOCK_SHEET, exc)
            return

        if not raw_headers:
            ws.update(range_name="A1", values=[_HEADERS])
            logger.warning(
                "Header repair: '%s' had no header row — wrote the expected schema fresh.",
                BACK_IN_STOCK_SHEET,
            )
            return

        seen: dict[str, int] = {}
        repaired: list[str] = []
        changed = False

        for idx, name in enumerate(raw_headers):
            clean = str(name or "").strip()
            if not clean:
                clean = f"_empty_col_{idx + 1}"
                changed = True
            if clean in seen:
                seen[clean] += 1
                clean = f"{clean}_{seen[clean]}"
                changed = True
            else:
                seen[clean] = 0
            repaired.append(clean)

        missing = [h for h in _HEADERS if h not in repaired]
        if missing:
            repaired = repaired + missing
            changed = True

        if changed:
            ws.update(range_name="A1", values=[repaired])
            logger.warning(
                "Header repair: normalized headers in '%s' — raw=%r -> repaired=%r "
                "(data rows untouched, missing expected columns=%s).",
                BACK_IN_STOCK_SHEET, raw_headers, repaired, missing or "none",
            )

    # ── Public API ────────────────────────────────────────────────────────────

    def add_request(self, user_id: int, user_name: str, chat_id: int, product_id: int, product_name: str) -> None:
        """
        Save a "notify me" request for one exact product. Idempotent: if
        this user already has a WAITING request for this exact product,
        does nothing (no duplicate rows) — matches "do not ask the
        customer to repeat later" and "never send duplicates".

        Never raises — a failed write here must never break the customer
        chat flow it's silently piggy-backing on.
        """
        try:
            ws = self._ws()
            records = ws.get_all_records(numericise_ignore=["all"])
            for rec in records:
                try:
                    same_user = int(str(rec.get("user_id", "") or "0").strip()) == user_id
                    same_prod = int(str(rec.get("product_id", "") or "0").strip()) == product_id
                except (ValueError, TypeError):
                    continue
                status = str(rec.get("status", "") or "").strip().lower()
                if same_user and same_prod and status == _STATUS_WAITING:
                    logger.info(
                        "Back-in-stock request already waiting for user %d / product %d — skipped duplicate.",
                        user_id, product_id,
                    )
                    return

            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            ws.append_row([
                str(user_id), user_name or "", str(chat_id), str(product_id),
                product_name, now, _STATUS_WAITING, "",
            ])
            logger.info(
                "Saved back-in-stock request: user %d ('%s') waiting on product %d ('%s').",
                user_id, user_name, product_id, product_name,
            )
        except Exception as exc:
            logger.error(
                "Failed to save back-in-stock request (user %d, product %d): %s",
                user_id, product_id, exc,
            )

    def get_waiting_for_product(self, product_id: int) -> list[dict]:
        """Every WAITING row for this exact product, each tagged with its 1-based sheet row."""
        try:
            ws = self._ws()
            records = ws.get_all_records(numericise_ignore=["all"])
            out = []
            for offset, rec in enumerate(records):
                try:
                    pid_match = int(str(rec.get("product_id", "") or "0").strip()) == product_id
                except (ValueError, TypeError):
                    continue
                status = str(rec.get("status", "") or "").strip().lower()
                if pid_match and status == _STATUS_WAITING:
                    rec["_row"] = offset + 2
                    out.append(rec)
            return out
        except Exception as exc:
            logger.error("Failed to load waiting back-in-stock requests for product %d: %s", product_id, exc)
            return []

    def mark_notified(self, row: int) -> None:
        """Flip one row from waiting -> notified so it is never picked up again."""
        try:
            ws = self._ws()
            col_status   = _HEADERS.index("status") + 1
            col_notified = _HEADERS.index("notified_at") + 1
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            ws.update_cell(row, col_status, _STATUS_NOTIFIED)
            ws.update_cell(row, col_notified, now)
        except Exception as exc:
            logger.error("Failed to mark back-in-stock request (row %d) as notified: %s", row, exc)

    def get_all_requests(self) -> list[dict]:
        """Every request, newest first — used by the admin panel (Task 6)."""
        try:
            ws = self._ws()
            records = ws.get_all_records(numericise_ignore=["all"])
            return list(reversed(records))
        except Exception as exc:
            logger.error("Failed to load back-in-stock requests: %s", exc)
            return []

    def count_waiting(self) -> int:
        try:
            return sum(
                1 for r in self.get_all_requests()
                if str(r.get("status", "") or "").strip().lower() == _STATUS_WAITING
            )
        except Exception as exc:
            logger.error("Failed to count waiting back-in-stock requests: %s", exc)
            return 0


# ── Async notification sender ───────────────────────────────────────────────

async def notify_back_in_stock(bot, product, stock_service: StockNotificationService) -> int:
    """
    Send the "it's back!" message to every customer waiting on this EXACT
    product, then mark each as notified. Returns how many were notified.

    Safe to call on every stock/status change — if nobody is waiting (the
    common case), this is a single cheap sheet read and nothing else
    happens. Never raises.
    """
    import asyncio

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.error import TelegramError

    from models.product import _md_escape

    waiting = await asyncio.to_thread(stock_service.get_waiting_for_product, product.id)
    if not waiting:
        return 0

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🛍 مشاهده محصول", callback_data=f"c:viewstock:{product.id}"),
    ]])
    text = (
        f"✨ *خبر خوب!*\n\n"
        f"محصولی که منتظرش بودید دوباره موجود شد:\n\n"
        f"💍 *{_md_escape(product.name)}*\n\n"
        "برای مشاهده، دکمه زیر را بزنید 👇"
    )

    notified = 0
    for req in waiting:
        raw_chat_id = req.get("chat_id") or req.get("user_id")
        try:
            chat_id = int(str(raw_chat_id).strip())
        except (ValueError, TypeError):
            logger.warning("Skipping back-in-stock row with invalid chat_id: %r", req)
            continue

        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=keyboard)
            await asyncio.to_thread(stock_service.mark_notified, req["_row"])
            notified += 1
            logger.info("Back-in-stock notification sent to user %d for product %d.", chat_id, product.id)
        except TelegramError as exc:
            logger.warning("Could not send back-in-stock notification to %d: %s", chat_id, exc)

    return notified
