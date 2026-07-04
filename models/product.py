"""
Gold Bot v2 – Product Model
============================
Dataclass representing a single jewelry product row from Google Sheets.

Image storage: products use telegram_file_id (the file_id returned by
Telegram when the admin sends a photo to the bot). This is stored directly
in the sheet. There is no external image hosting — Telegram stores the file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Product:
    # ── Identity ───────────────────────────────────────────────────────────────
    id:                    int   = 0
    name:                  str   = ""

    # ── Classification ─────────────────────────────────────────────────────────
    category:              str   = ""
    subcategory:           str   = ""
    gender:                str   = ""
    collection:            str   = ""

    # ── Pricing inputs ─────────────────────────────────────────────────────────
    weight:                float = 0.0
    wage_percent:          float = 0.0
    profit_percent:        float = 0.0

    # ── Appearance ─────────────────────────────────────────────────────────────
    stone:                 str   = ""
    stone_color:           str   = ""
    gold_color:            str   = ""
    purity:                str   = "18 عیار"

    # ── Inventory / pricing override ───────────────────────────────────────────
    stock:                 int   = 0
    price_override:        Optional[float] = None

    # ── Content ────────────────────────────────────────────────────────────────
    description:           str   = ""
    tags:                  str   = ""
    # Telegram file_id of the product photo — set when admin sends a photo.
    # Telegram stores the actual image; we only keep this identifier.
    telegram_file_id:      str   = ""

    # ── Lifecycle ──────────────────────────────────────────────────────────────
    status:                str   = "active"
    published_message_id:  str   = ""
    created_at:            str   = ""
    updated_at:            str   = ""

    # ── Factories ──────────────────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, data: dict) -> "Product":
        """
        Build a Product from a Google Sheets record dictionary.
        Handles both old sheets (column 'image') and new sheets
        (column 'telegram_file_id') transparently.
        """
        def _str(key: str) -> str:
            return str(data.get(key, "") or "").strip()

        def _int(key: str, default: int = 0) -> int:
            try:
                return int(str(data.get(key, default) or default).replace(",", "").strip())
            except (ValueError, TypeError):
                return default

        def _float(key: str, default: float = 0.0) -> float:
            try:
                return float(str(data.get(key, default) or default).replace(",", "").strip())
            except (ValueError, TypeError):
                return default

        def _opt_float(key: str) -> Optional[float]:
            raw = str(data.get(key, "") or "").replace(",", "").strip()
            if not raw:
                return None
            try:
                return float(raw)
            except ValueError:
                return None

        # Backward-compat: if old sheet still has "image" column, use it
        file_id = _str("telegram_file_id") or _str("image")

        return cls(
            id=_int("id"),
            name=_str("name"),
            category=_str("category"),
            subcategory=_str("subcategory"),
            gender=_str("gender"),
            collection=_str("collection"),
            weight=_float("weight"),
            wage_percent=_float("wage_percent"),
            profit_percent=_float("profit_percent"),
            stone=_str("stone"),
            stone_color=_str("stone_color"),
            gold_color=_str("gold_color"),
            purity=_str("purity") or "18 عیار",
            stock=_int("stock", default=1),
            price_override=_opt_float("price_override"),
            description=_str("description"),
            tags=_str("tags"),
            telegram_file_id=file_id,
            status=_str("status") or "active",
            published_message_id=_str("published_message_id"),
            created_at=_str("created_at"),
            updated_at=_str("updated_at"),
        )

    def to_dict(self) -> dict:
        """Serialise to a flat dict (all values as strings for Sheets)."""
        d = asdict(self)
        return {k: ("" if v is None else v) for k, v in d.items()}

    # ── Derived properties ────────────────────────────────────────────────────

    @property
    def has_photo(self) -> bool:
        """True if a Telegram file_id has been stored for this product."""
        return bool(self.telegram_file_id)

    @property
    def is_available(self) -> bool:
        status_norm = (self.status or "").strip().lower()
        return status_norm == "active" and self.stock > 0

    @property
    def is_published(self) -> bool:
        return bool(self.published_message_id and self.published_message_id != "0")

    @property
    def tag_list(self) -> list[str]:
        if not self.tags:
            return []
        return [t.strip() for t in re.split(r"[,،]", self.tags) if t.strip()]

    @property
    def status_emoji(self) -> str:
        return {"active": "✅", "sold": "❌", "draft": "⏸"}.get(self.status, "❓")

    def short_summary(self) -> str:
        photo_icon = "📷" if self.has_photo else "🚫"
        return (
            f"{self.status_emoji} [{self.id}] {self.name} "
            f"| {self.weight}گ | موجودی: {self.stock} | عکس: {photo_icon}"
        )

    def admin_detail(self) -> str:
        po = f"\n💵 قیمت ثابت: `{self.price_override:,.0f} تومان`" if self.price_override else ""
        photo_line = "✅ دارد" if self.has_photo else "❌ ندارد (عکس ارسال نشده)"
        return (
            f"*💍 {self.name}*\n\n"
            f"🆔 شناسه: `{self.id}`\n"
            f"📂 دسته: `{self.category}` / `{self.subcategory or '—'}`\n"
            f"👤 جنسیت: `{self.gender or 'نامشخص'}`\n"
            f"🎨 رنگ طلا: `{self.gold_color or '—'}` | عیار: `{self.purity}`\n"
            f"💎 سنگ: `{self.stone or 'بدون سنگ'}` ({self.stone_color or '—'})\n"
            f"⚖️ وزن: `{self.weight} گرم`\n"
            f"🛠 اجرت: `{self.wage_percent}٪` | سود: `{self.profit_percent}٪`\n"
            f"📦 موجودی: `{self.stock}`\n"
            f"📌 کالکشن: `{self.collection or '—'}`\n"
            f"🏷 برچسب‌ها: `{self.tags or '—'}`\n"
            f"📝 توضیحات: {self.description or '—'}\n"
            f"🖼 تصویر: {photo_line}\n"
            f"🌐 وضعیت: `{self.status_emoji} {self.status}`\n"
            f"📢 منتشر شده: `{'بله – ' + self.published_message_id if self.is_published else 'خیر'}`"
            f"{po}"
        )

    def channel_caption(self) -> str:
        """Caption for the Telegram channel post."""
        return (
            f"💍 *{self.name}*\n\n"
            f"🎨 رنگ طلا: `{self.gold_color or '—'}` | عیار: `{self.purity}`\n"
            f"💎 سنگ: `{self.stone or 'بدون سنگ'}`\n"
            f"⚖️ وزن: `{self.weight} گرم`\n"
            f"🛠 اجرت: `{self.wage_percent}٪` | سود: `{self.profit_percent}٪`\n"
            f"📦 موجودی: `{self.stock} عدد`"
        )

    def ai_summary(self, price: float) -> str:
        """Compact representation passed to the AI model."""
        return (
            f"ID:{self.id} | {self.name} | دسته:{self.category} | "
            f"جنسیت:{self.gender} | رنگ:{self.gold_color} | "
            f"سنگ:{self.stone or 'ندارد'} | وزن:{self.weight}گ | "
            f"قیمت:{price:,.0f}ت | موجودی:{self.stock}"
        )
