"""
Gold Bot v2 – Caption Builder Service
========================================
Builds the final Telegram channel post caption for a product.

Combines three independent, admin-controlled inputs:
    1. Per-product attribute selection (Feature 1) — which fields the admin
       chose to show under THIS specific post, toggled just before publishing.
       Never global — each publish action starts from config.DEFAULT_PUBLISH_ATTRS
       and the admin can change it per product.
    2. Resolved currency label (Feature 4) — see services/price_service.currency_label.
    3. Global footer text (Feature 2) — one setting, appended to every post,
       skipped entirely when empty.

This module is intentionally small and isolated: it has no Telegram,
Sheets, or AI dependencies — it just takes plain data in and returns a
Markdown string.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from models.product import Product


def _escape(value) -> str:
    """
    Escape Telegram legacy-Markdown special characters in free text.

    Mirrors models.product._md_escape exactly — duplicated here (a tiny,
    5-line pure function) so this module has zero cross-dependencies on
    the Product model's internals.
    """
    text = str(value)
    for ch in ("\\", "`", "*", "_", "["):
        text = text.replace(ch, f"\\{ch}")
    return text


# ── Attribute renderers ────────────────────────────────────────────────────────
# Each renderer takes (product, price, currency) and returns a line string,
# or None to skip the line (e.g. an empty field). Dict order = display order.

def _line_price(p: "Product", price: float, currency: str) -> Optional[str]:
    return f"💰 قیمت: `{price:,.0f} {currency}`"


def _line_weight(p: "Product", price: float, currency: str) -> Optional[str]:
    return f"⚖️ وزن: `{p.weight} گرم`"


def _line_gold_color(p: "Product", price: float, currency: str) -> Optional[str]:
    return f"🎨 رنگ طلا: `{_escape(p.gold_color)}`" if p.gold_color else None


def _line_purity(p: "Product", price: float, currency: str) -> Optional[str]:
    return f"عیار: `{_escape(p.purity)}`" if p.purity else None


def _line_stone(p: "Product", price: float, currency: str) -> Optional[str]:
    return f"💎 سنگ: `{_escape(p.stone) if p.stone else 'بدون سنگ'}`"


def _line_wage(p: "Product", price: float, currency: str) -> Optional[str]:
    return f"🛠 اجرت: `{p.wage_percent}٪`"


def _line_profit(p: "Product", price: float, currency: str) -> Optional[str]:
    return f"📈 سود: `{p.profit_percent}٪`"


def _line_stock(p: "Product", price: float, currency: str) -> Optional[str]:
    return f"📦 موجودی: `{p.stock} عدد`"


def _line_category(p: "Product", price: float, currency: str) -> Optional[str]:
    return f"📂 دسته: `{_escape(p.category)}`" if p.category else None


def _line_description(p: "Product", price: float, currency: str) -> Optional[str]:
    return f"📝 {_escape(p.description)}" if p.description else None


# Maps each PUBLISH_ATTRIBUTES key (config.py) to its renderer.
_ATTRIBUTE_RENDERERS = {
    "price":          _line_price,
    "weight":         _line_weight,
    "gold_color":     _line_gold_color,
    "purity":         _line_purity,
    "stone":          _line_stone,
    "wage_percent":   _line_wage,
    "profit_percent": _line_profit,
    "stock":          _line_stock,
    "category":       _line_category,
    "description":    _line_description,
}


def build_caption(
    product: "Product",
    price: float,
    selected_attrs: Optional[set] = None,
    currency: str = "تومان",
    footer: str = "",
) -> str:
    """
    Build the complete, Markdown-formatted channel post caption.

    Args:
        product:        The product being published.
        price:          Pre-calculated final price (services.price_service.calculate_price).
        selected_attrs: Attribute keys to include (see config.PUBLISH_ATTRIBUTES
                         for valid keys). None/empty falls back to
                         config.DEFAULT_PUBLISH_ATTRS — this keeps existing
                         publish flows working unchanged if the admin never
                         opens the new attribute checklist.
        currency:       Resolved currency label — see price_service.currency_label().
        footer:         Global footer text (admin setting `post_footer`).
                         Appended only if non-empty; nothing is added otherwise.

    Returns:
        The complete caption string, ready to pass as `caption=` to
        bot.send_photo(..., parse_mode="Markdown").
    """
    from config.config import DEFAULT_PUBLISH_ATTRS

    attrs = selected_attrs if selected_attrs else DEFAULT_PUBLISH_ATTRS

    lines: list[str] = [f"💍 *{_escape(product.name)}*", ""]

    for key, renderer in _ATTRIBUTE_RENDERERS.items():
        if key not in attrs:
            continue
        line = renderer(product, price, currency)
        if line:
            lines.append(line)

    caption = "\n".join(lines)

    if footer:
        caption += f"\n\n{footer}"

    return caption
