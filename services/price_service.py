"""
Gold Bot v2 – Price Service
=============================
Pure price-calculation functions with no external dependencies.

Currency handling
------------------
Two separate, deliberately distinct concerns live here:

1. DISPLAY — currency_label(settings) resolves the store's configured
   currency into its Persian display text ("تومان"/"ریال"). This module
   never multiplies/divides a stored product price by 10; the gold price
   entered by the admin already IS in the store's configured currency.

2. CUSTOMER-INPUT NORMALIZATION (Part 1 of the currency fix) — customers
   often speak in Toman even when the store's internal currency is Rial
   (1 Toman = 10 Rial — a fixed denomination relationship, not a market
   exchange rate). resolve_currency_code()/convert_currency()/
   normalize_amount() convert a customer-stated budget from whatever
   currency THEY used into the store's currency, so every number that
   ever reaches SearchQuery/CustomerProfile/product-price comparisons is
   guaranteed to already be apples-to-apples with `calculate_price()`'s
   output. Search/notification matching code never needs to think about
   currency at all — normalization happens once, at the boundary.
"""

from __future__ import annotations
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from models.ai_models import IntentExtraction
    from models.product import Product

logger = logging.getLogger(__name__)

# ── Currency label resolution (DISPLAY) ────────────────────────────────────────

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


# ── Currency code resolution (INTERNAL LOGIC / NORMALIZATION) ─────────────────
# Canonical codes: "IRT" = Toman, "IRR" = Rial (ISO 4217 code for Rial;
# "IRT" is the commonly used informal code for Toman, which has none).

CURRENCY_CODE_TOMAN = "IRT"
CURRENCY_CODE_RIAL  = "IRR"

_CURRENCY_CODE_ALIASES: dict[str, str] = {
    "toman": CURRENCY_CODE_TOMAN, "تومان": CURRENCY_CODE_TOMAN,
    "تومن":  CURRENCY_CODE_TOMAN, "irt":   CURRENCY_CODE_TOMAN,
    "rial":  CURRENCY_CODE_RIAL,  "ریال":  CURRENCY_CODE_RIAL,
    "irr":   CURRENCY_CODE_RIAL,
}


def resolve_currency_code(raw: Optional[str]) -> Optional[str]:
    """
    Normalize any spelling/case of a currency reference (Persian word,
    English word, or already-canonical code) into a canonical code
    ("IRT" or "IRR"). Returns None if `raw` is empty or unrecognized —
    callers must then fall back to the store's own currency, never guess.
    """
    if not raw:
        return None
    return _CURRENCY_CODE_ALIASES.get(str(raw).strip().lower())


def store_currency_code(settings: dict) -> str:
    """Return the store's configured currency as a canonical code (IRT/IRR)."""
    raw = str(settings.get("currency", "") or "").strip().lower()
    return _CURRENCY_CODE_ALIASES.get(raw, CURRENCY_CODE_TOMAN)


def convert_currency(amount: Optional[float], from_code: str, to_code: str) -> Optional[float]:
    """
    Pure Toman<->Rial denomination conversion — 1 Toman = 10 Rial, exactly,
    always (this is a fixed unit relationship, not a market exchange rate
    that could ever change). No-op if the codes match or either is
    missing/unrecognized.
    """
    if amount is None or not from_code or not to_code or from_code == to_code:
        return amount
    if from_code == CURRENCY_CODE_TOMAN and to_code == CURRENCY_CODE_RIAL:
        return amount * 10
    if from_code == CURRENCY_CODE_RIAL and to_code == CURRENCY_CODE_TOMAN:
        return amount / 10
    return amount  # unrecognized code pair — safe no-op rather than a bad guess


def normalize_amount(
    amount: Optional[float],
    source_currency: Optional[str],
    settings: dict,
    *,
    context: str = "",
) -> Optional[float]:
    """
    Convert `amount` from `source_currency` (any spelling, or None/unknown
    → assumed to already be in store currency) into the store's configured
    currency. This is THE single normalization choke point — used by both
    the local regex extractor (services.search_service.local_extract) and
    the AI's IntentExtraction path (normalize_intent_budget below) — so
    every budget number that ever reaches SearchQuery, CustomerProfile, or
    a price comparison is guaranteed to already be in store currency.

    Args:
        context: Short label used only for logging (e.g. "max_budget"),
                 so a conversion decision can be traced back to where it
                 happened without needing to log the customer's raw text.
    """
    if amount is None:
        return None

    store_code  = store_currency_code(settings)
    source_code = resolve_currency_code(source_currency) or store_code

    normalized = convert_currency(amount, source_code, store_code)

    if source_code != store_code:
        logger.info(
            "Currency normalization%s: %.0f %s -> %.0f %s",
            f" ({context})" if context else "", amount, source_code, normalized, store_code,
        )
    else:
        logger.debug(
            "Currency normalization%s: %.0f already in store currency (%s) — no conversion.",
            f" ({context})" if context else "", amount, store_code,
        )

    return normalized


def normalize_intent_budget(intent: "IntentExtraction", settings: dict) -> "IntentExtraction":
    """
    Return a COPY of `intent` with max_budget/min_budget converted into the
    store's currency, based on intent.budget_currency (falls back to store
    currency if the customer didn't name one explicitly).

    Call this exactly once, right before CustomerProfile.merge_intent(), so
    every budget value that ever enters the persisted profile is guaranteed
    pre-normalized — score_product() and notification_similarity() never
    need to reason about currency at all.
    """
    if intent.max_budget is None and intent.min_budget is None:
        return intent

    store_code = store_currency_code(settings)

    data = intent.model_dump()
    data["max_budget"] = normalize_amount(
        intent.max_budget, intent.budget_currency, settings, context="max_budget"
    )
    data["min_budget"] = normalize_amount(
        intent.min_budget, intent.budget_currency, settings, context="min_budget"
    )
    # The values are now in store currency — reflect that in the returned copy.
    data["budget_currency"] = store_code

    from models.ai_models import IntentExtraction
    return IntentExtraction.model_validate(data)


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
