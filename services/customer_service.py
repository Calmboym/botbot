"""
Gold Bot v2 – Customer Tracking Service
=========================================
Persists each customer's cumulative CustomerProfile (a typed Pydantic
model — see models/ai_models.py) to the 'customers' worksheet, and
matches restocked/new products against every opted-in customer using a
normalized similarity score (see search_service.notification_similarity).

Sheet columns:
    user_id | name | category | gender | gold_color | stone |
    max_budget | min_budget | max_weight | min_weight | style_keywords |
    occasion | shopping_stage | interest_level | notify | last_seen | updated_at

Note: this schema replaces the earlier ad-hoc 'preferences' dict-based
sheet. If you have an existing 'customers' tab from a previous version,
delete it (or rename it) so the bot can recreate it with the new columns
on first use — see README "AI Architecture" section.
"""

import datetime
import logging
from typing import Optional, TYPE_CHECKING

import gspread

from config.config import (
    CUSTOMERS_SHEET, GOOGLE_SCOPES, NOTIFICATION_SIMILARITY_THRESHOLD,
    SERVICE_ACCOUNT_FILE, SPREADSHEET_NAME,
)
from models.ai_models import CustomerProfile, ShoppingStage

if TYPE_CHECKING:
    from models.product import Product

logger = logging.getLogger(__name__)

_HEADERS = [
    "user_id", "name", "category", "gender", "gold_color", "stone",
    "max_budget", "min_budget", "max_weight", "min_weight",
    "style_keywords", "occasion", "shopping_stage", "interest_level",
    "notify", "last_seen", "updated_at",
]


class CustomerService:
    # ── Private helpers ───────────────────────────────────────────────────────

    def _ws(self) -> gspread.Worksheet:
        from google.oauth2.service_account import Credentials
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=GOOGLE_SCOPES)
        client = gspread.Client(auth=creds)
        ss = client.open(SPREADSHEET_NAME)
        try:
            return ss.worksheet(CUSTOMERS_SHEET)
        except gspread.exceptions.WorksheetNotFound:
            ws = ss.add_worksheet(title=CUSTOMERS_SHEET, rows=1000, cols=len(_HEADERS))
            ws.append_row(_HEADERS)
            logger.info("Created '%s' worksheet.", CUSTOMERS_SHEET)
            return ws

    def _find_row(self, ws: gspread.Worksheet, user_id: int) -> tuple[int, Optional[dict]]:
        records = ws.get_all_records(numericise_ignore=["all"])
        for offset, rec in enumerate(records):
            try:
                if int(str(rec.get("user_id", "") or "0").strip()) == user_id:
                    return offset + 2, rec
            except (ValueError, TypeError):
                continue
        return 0, None

    def _row_from_profile(self, profile: CustomerProfile, notify: bool) -> list[str]:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        return [
            str(profile.user_id),
            profile.name,
            profile.category or "",
            profile.gender or "",
            profile.gold_color or "",
            profile.stone or "",
            str(int(profile.max_budget)) if profile.max_budget else "",
            str(int(profile.min_budget)) if profile.min_budget else "",
            str(profile.max_weight) if profile.max_weight else "",
            str(profile.min_weight) if profile.min_weight else "",
            ", ".join(profile.style_keywords),
            profile.occasion or "",
            profile.shopping_stage.value,
            str(profile.interest_level),
            "yes" if notify else "",
            now,
            now,
        ]

    def _profile_from_row(self, row: dict) -> CustomerProfile:
        def _f(key: str) -> Optional[float]:
            raw = str(row.get(key, "") or "").strip().replace(",", "")
            try:
                return float(raw) if raw else None
            except ValueError:
                return None

        styles_raw = str(row.get("style_keywords", "") or "")
        styles = [s.strip() for s in styles_raw.split(",") if s.strip()]

        try:
            stage = ShoppingStage(str(row.get("shopping_stage", "") or "browsing"))
        except ValueError:
            stage = ShoppingStage.BROWSING

        try:
            interest = int(str(row.get("interest_level", 0) or 0))
        except ValueError:
            interest = 0

        return CustomerProfile(
            user_id=int(str(row.get("user_id", 0) or 0)),
            name=str(row.get("name", "") or ""),
            category=row.get("category") or None,
            gender=row.get("gender") or None,
            gold_color=row.get("gold_color") or None,
            stone=row.get("stone") or None,
            max_budget=_f("max_budget"),
            min_budget=_f("min_budget"),
            max_weight=_f("max_weight"),
            min_weight=_f("min_weight"),
            style_keywords=styles,
            occasion=row.get("occasion") or None,
            shopping_stage=stage,
            interest_level=interest,
            notify_enabled=str(row.get("notify", "") or "").strip().lower() == "yes",
            last_seen=str(row.get("last_seen", "") or ""),
            updated_at=str(row.get("updated_at", "") or ""),
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def save_profile(self, profile: CustomerProfile, notify: Optional[bool] = None) -> None:
        """
        Insert or update a customer's profile row.

        If `notify` is None, any existing notify flag is preserved (so a
        routine background profile-save never accidentally un-subscribes
        a customer from restock notifications).

        Never raises — CRM write failures are logged, not fatal to chat.
        """
        try:
            ws = self._ws()
            row_idx, existing = self._find_row(ws, profile.user_id)

            if notify is None:
                notify = (
                    str(existing.get("notify", "")).strip().lower() == "yes"
                    if existing else profile.notify_enabled
                )

            row = self._row_from_profile(profile, notify)

            if existing:
                ws.update(range_name=f"A{row_idx}", values=[row])
                logger.debug("Updated customer profile for user %d.", profile.user_id)
            else:
                ws.append_row(row)
                logger.info("Inserted new customer profile for user %d.", profile.user_id)

        except Exception as exc:
            logger.error("Failed to save profile for user %d: %s", profile.user_id, exc)

    def load_profile(self, user_id: int) -> Optional[CustomerProfile]:
        """Load a customer's persisted profile from Sheets, or None if never seen."""
        try:
            ws = self._ws()
            _, row = self._find_row(ws, user_id)
            return self._profile_from_row(row) if row else None
        except Exception as exc:
            logger.error("Failed to load profile for user %d: %s", user_id, exc)
            return None

    def set_notify(self, user_id: int, notify: bool) -> None:
        try:
            ws = self._ws()
            row_idx, rec = self._find_row(ws, user_id)
            if not rec:
                logger.warning("Cannot set notify for unknown user %d.", user_id)
                return
            col = _HEADERS.index("notify") + 1
            ws.update_cell(row_idx, col, "yes" if notify else "")
            logger.info("Set notify=%s for user %d.", notify, user_id)
        except Exception as exc:
            logger.error("Failed to set notify for user %d: %s", user_id, exc)

    def get_notify_profiles(self) -> list[CustomerProfile]:
        """Return CustomerProfile objects for every customer opted into notifications."""
        try:
            ws = self._ws()
            records = ws.get_all_records(numericise_ignore=["all"])
            profiles = []
            for r in records:
                if str(r.get("notify", "") or "").strip().lower() == "yes":
                    try:
                        profiles.append(self._profile_from_row(r))
                    except Exception as exc:
                        logger.warning("Skipping malformed customer row: %s", exc)
            return profiles
        except Exception as exc:
            logger.error("Failed to load notify profiles: %s", exc)
            return []

    # ── Notification matching ─────────────────────────────────────────────────

    def customers_matching_product(self, product: "Product", gold_price: float) -> list[CustomerProfile]:
        """
        Return profiles whose similarity score to this product is at or
        above NOTIFICATION_SIMILARITY_THRESHOLD.
        """
        from services.price_service import calculate_price
        from services.search_service import notification_similarity

        price = calculate_price(product, gold_price)
        matched: list[CustomerProfile] = []

        for profile in self.get_notify_profiles():
            score = notification_similarity(product, profile, price)
            if score >= NOTIFICATION_SIMILARITY_THRESHOLD:
                matched.append(profile)
                logger.debug(
                    "User %d matched product %d (similarity=%.2f).",
                    profile.user_id, product.id, score,
                )

        logger.info(
            "Product %d ('%s') matched %d notify-customers (threshold=%.2f).",
            product.id, product.name, len(matched), NOTIFICATION_SIMILARITY_THRESHOLD,
        )
        return matched


# ── Async notification sender ─────────────────────────────────────────────────

async def notify_interested_customers(
    bot,
    product: "Product",
    gold_price: float,
    customer_service: CustomerService,
    currency: str = "تومان",
) -> int:
    """
    Send a restock notification to every customer whose profile matches
    the given product. Returns the number of customers successfully notified.

    Args:
        currency: Resolved currency label (see services.price_service.currency_label).
                   Defaults to Toman only for backward compatibility with any
                   caller that doesn't pass it — the admin panel always does.
    """
    import asyncio
    from models.product import _md_escape
    from services.price_service import calculate_price
    from telegram.error import TelegramError

    matched = await asyncio.to_thread(
        customer_service.customers_matching_product, product, gold_price
    )
    if not matched:
        return 0

    price = calculate_price(product, gold_price)
    notified = 0

    for profile in matched:
        try:
            msg = (
                f"🔔 *محصول مورد نظر شما موجود شد!*\n\n"
                f"💍 {_md_escape(product.name)}\n"
                f"🎨 {_md_escape(product.gold_color) or '—'} | {_md_escape(product.purity)}\n"
                f"💎 {_md_escape(product.stone) if product.stone else 'بدون سنگ'}\n"
                f"⚖️ {product.weight} گرم\n"
                f"💰 قیمت تقریبی: `{price:,.0f} {currency}`\n\n"
                f"برای اطلاعات بیشتر و خرید با فروشگاه تماس بگیرید."
            )
            await bot.send_message(chat_id=profile.user_id, text=msg, parse_mode="Markdown")
            notified += 1
            logger.info("Restock notification sent to user %d for product %d.", profile.user_id, product.id)
        except TelegramError as exc:
            logger.warning("Could not notify user %d: %s", profile.user_id, exc)

    return notified
