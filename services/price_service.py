"""
Gold Bot v2 – Price Service
=============================
Pure price-calculation functions with no external dependencies.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.product import Product


def calculate_price(product: "Product", gold_price: float) -> float:
    """
    Return the final product price in Toman.

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


def format_price_alert(product: "Product", gold_price: float) -> str:
    """
    Compact Persian breakdown for Telegram popup (≤ 200 chars).
    """
    bd = price_breakdown(product, gold_price)
    if bd["override"]:
        return (
            f"💎 {product.name}\n\n"
            f"✅ قیمت: {bd['total']:,.0f} تومان\n"
            f"(قیمت ثابت)"
        )[:200]

    return (
        f"💎 {product.name}\n\n"
        f"📦 پایه: {bd['base']:,.0f}\n"
        f"🛠 اجرت ({bd['wage_pct']}٪): +{bd['wage_amt']:,.0f}\n"
        f"📈 سود ({bd['profit_pct']}٪): +{bd['profit_amt']:,.0f}\n"
        f"──────────\n"
        f"✅ نهایی: {bd['total']:,.0f} تومان"
    )[:200]


def format_gold_price_alert(gold_price: float, last_update: str = "") -> str:
    """Compact gold price message for Telegram popup (≤ 200 chars)."""
    upd = f"\n🕐 آخرین بروزرسانی: {last_update}" if last_update else ""
    return (
        f"📈 قیمت طلا ۱۸ عیار\n\n"
        f"💰 هر گرم: {gold_price:,.0f} تومان"
        f"{upd}"
    )[:200]
