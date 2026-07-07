"""
Gold Bot v2 – Price Service
=============================
Pure price-calculation functions with no external dependencies.

Currency handling
------------------
The gold price stored in the sheet is a plain number with NO implicit
unit conversion applied anywhere in this module — whatever unit the admin
enters the gold price in (Toman or Rial) is the unit every calculated
price comes out in. This module never multiplies/divides by 10 to convert
between Rial and Toman; it only controls which LABEL ("تومان" / "ریال")
is shown next to a number, resolved from the admin's `currency` setting
via currency_label(). This is the single source of truth for that label —
every caller across the project should use it instead of hardcoding a
currency word.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.product import Product

# ── Currency label resolution ─────────────────────────────────────────────────

DEFAULT_CURRENCY_LABEL = "تومان"

# Accepts either English or Persian spelling in the settings sheet.
CURRENCY_ALIASES: dict[str, str] = {
    "toman":  "تومان",
    "تومان":  "تومان",
    "rial":   "ریال",
    "ریال":   "ریال",
}


def currency_label(settings: dict) -> str:
    """
    Resolve the admin-configured currency (settings['currency']) into its
    Persian display label.

    This is the ONLY place currency text is decided — every display
    function in this project (price popups, channel captions, admin
    previews, notifications) must call this instead of hardcoding
    "تومان", so setting currency=rial actually changes what's shown
    everywhere, consistently.

    Defaults to Toman if the setting is unset or unrecognized, so stores
    that never touch the currency setting keep their exact prior behaviour.
    """
    raw = str(settings.get("currency", "") or "").strip().lower()
    return CURRENCY_ALIASES.get(raw, DEFAULT_CURRENCY_LABEL)


# ── Price calculation (currency-agnostic — no conversion, ever) ───────────────

def calculate_price(product: "Product", gold_price: float) -> float:
    """
    Return the final product price, in whichever currency unit the admin's
    gold price is entered in (no conversion is applied here).

    If price_override is set, it takes precedence.
    Otherwise:   base = weight × gold_price
                 total = base × (1 + wage% / 100 + profit% / 100)
    """
    if product.price_override:
        return product.price_override
    base   = product.weight * gold_price
    total  = base * (1 + product.wage_percent / 100 + product.profit_percent / 100)
    return total


def price_breakdown(product: "Product", gold_price: float) -> dict:
    """Return the full numeric breakdown as a dictionary."""
    if product.price_override:
        return {
            "override":     True,
            "total":        product.price_override,
            "gold_price":   gold_price,
        }
    base         = product.weight * gold_price
    wage_amt     = base * product.wage_percent / 100
    profit_amt   = base * product.profit_percent / 100
    total        = base + wage_amt + profit_amt
    return {
        "override":     False,
        "weight":       product.weight,
        "gold_price":   gold_price,
        "base":         base,
        "wage_pct":     product.wage_percent,
        "wage_amt":     wage_amt,
        "profit_pct":   product.profit_percent,
        "profit_amt":   profit_amt,
        "total":        total,
    }


# ── Display formatting (always takes an explicit currency label) ─────────────

def format_price_alert(
    product: "Product",
    gold_price: float,
    currency: str = DEFAULT_CURRENCY_LABEL,
) -> str:
    """
    Compact Persian breakdown for Telegram popup (≤ 200 chars).

    Args:
        currency: Resolved label from currency_label(settings). Defaults to
                   Toman only for backward compatibility with any caller
                   that doesn't pass it — all current callers do.
    """
    bd = price_breakdown(product, gold_price)
    if bd["override"]:
        return (
            f"💎 {product.name}\n\n"
            f"✅ قیمت: {bd['total']:,.0f} {currency}\n"
            f"(قیمت ثابت)"
        )[:200]

    return (
        f"💎 {product.name}\n\n"
        f"📦 پایه: {bd['base']:,.0f}\n"
        f"🛠 اجرت ({bd['wage_pct']}٪): +{bd['wage_amt']:,.0f}\n"
        f"📈 سود ({bd['profit_pct']}٪): +{bd['profit_amt']:,.0f}\n"
        f"──────────\n"
        f"✅ نهایی: {bd['total']:,.0f} {currency}"
    )[:200]


def format_gold_price_alert(
    gold_price: float,
    last_update: str = "",
    currency: str = DEFAULT_CURRENCY_LABEL,
) -> str:
    """Compact gold price message for Telegram popup (≤ 200 chars)."""
    upd = f"\n🕐 آخرین بروزرسانی: {last_update}" if last_update else ""
    return (
        f"📈 قیمت طلا ۱۸ عیار\n\n"
        f"💰 هر گرم: {gold_price:,.0f} {currency}"
        f"{upd}"
    )[:200]
