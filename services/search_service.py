"""
Gold Bot v2 – Search Service
==============================
Two layers of intelligence, both LOCAL (no AI call) for speed and cost:

1. local_extract(text)   – cheap regex-based Persian keyword extraction,
                            used to seed a search query for the CURRENT
                            message before any AI call is made. This solves
                            the "first message" problem: even the very
                            first thing a customer says gets matched against
                            real products before the AI ever runs.

2. score_product(...)    – weighted relevance scoring (category, budget,
                            color, stone, style, weight, occasion, and the
                            customer's longer-term profile) used to RANK
                            products, not just filter them in/out.

The richer, LLM-based IntentExtraction (shopping stage, emotion, urgency,
purchase readiness, etc.) happens inside the AI's own structured response
(see services/ai_service.py) and is merged into the CustomerProfile for
FUTURE turns — it does not need to run again here.

A separate, stricter function — notification_similarity() — powers the
restock-notification follow-up system with a normalized 0..1 score.
"""

from __future__ import annotations

import re
import logging
from typing import TYPE_CHECKING, Optional

from config.config import MAX_SEARCH_RESULTS
from models.ai_models import CustomerProfile, ProductContext, SearchQuery, SearchResult

if TYPE_CHECKING:
    from models.product import Product

logger = logging.getLogger(__name__)


# ── Local (regex) keyword tables ───────────────────────────────────────────────

_CATEGORY_MAP: dict[str, list[str]] = {
    "انگشتر":   ["انگشتر", "انگشتری", "حلقه"],
    "گردنبند":  ["گردنبند", "زنجیر", "چوکر"],
    "دستبند":   ["دستبند"],
    "گوشواره":  ["گوشواره"],
    "النگو":    ["النگو"],
    "آویز":     ["آویز", "مدال"],
    "ست":       ["ست"],
}

_GENDER_MAP: dict[str, list[str]] = {
    "مردانه":  ["مردانه", "مرد", "آقا", "پسرانه", "پسر"],
    "زنانه":   ["زنانه", "زن", "خانم", "دخترانه", "دختر"],
    "بچگانه":  ["بچه", "کودک", "بچگانه", "نوزاد"],
    "یونیسکس": ["یونیسکس"],
}

_COLOR_MAP: dict[str, list[str]] = {
    "سفید":   ["سفید", "white", "وایت"],
    "زرد":    ["زرد", "طلایی", "yellow"],
    "رزگلد":  ["رزگلد", "rose", "صورتی", "رز"],
}

_STONE_MAP: dict[str, list[str]] = {
    "none":     ["بدون سنگ", "ساده", "بی سنگ"],
    "الماس":   ["الماس", "برلیان", "diamond"],
    "زمرد":    ["زمرد", "emerald"],
    "یاقوت":   ["یاقوت", "ruby"],
    "فیروزه":  ["فیروزه"],
}

_STYLE_KEYWORDS: list[str] = [
    "مدرن", "کلاسیک", "ظریف", "سنگین", "حجیم",
    "لوکس", "مینیمال", "اسپرت", "شیک", "سنتی",
]

_OCCASION_MAP: dict[str, list[str]] = {
    "نامزدی": ["نامزدی", "حلقه نامزدی", "عروسی", "ازدواج"],
    "هدیه":   ["هدیه", "کادو", "پیشکش", "gift"],
    "روزمره": ["روزانه", "روزمره", "هر روز", "کاری"],
}

# Explicit Toman/Rial mentions in the customer's own words (Part 1 of the
# currency fix). Only an EXPLICIT match sets a currency — if none of these
# appear, the caller must assume store currency, never guess.
_CURRENCY_WORD_MAP: dict[str, str] = {
    "تومان": "IRT", "تومن": "IRT", "toman": "IRT",
    "ریال":  "IRR", "rial":  "IRR",
}


def _detect_currency_word(t: str) -> Optional[str]:
    """Detect an explicit Toman/Rial mention anywhere in the message (local, no AI call)."""
    for word, code in _CURRENCY_WORD_MAP.items():
        if word in t:
            return code
    return None


def _extract_budget(t: str) -> tuple[Optional[float], Optional[float], Optional[str]]:
    """
    Extract a raw budget figure (exactly as typed, in millions/units — NOT
    yet currency-normalized) plus the currency the customer explicitly
    named, if any. Currency normalization into store currency happens
    separately in local_extract() via price_service.normalize_amount().
    """
    max_b = min_b = None
    under = re.search(r"(?:زیر|تا|کمتر از)\s*([\d,]+(?:\.\d+)?)\s*میلیون", t)
    over  = re.search(r"(?:بالای|بیشتر از)\s*([\d,]+(?:\.\d+)?)\s*میلیون", t)
    plain = re.search(r"([\d,]+(?:\.\d+)?)\s*میلیون", t)

    if under:
        max_b = float(under.group(1).replace(",", "")) * 1_000_000
    if over:
        min_b = float(over.group(1).replace(",", "")) * 1_000_000
    elif plain and not under:
        max_b = float(plain.group(1).replace(",", "")) * 1_000_000

    toman = re.search(r"([\d,]+)\s*تومان", t)
    if toman and not max_b:
        try:
            max_b = float(toman.group(1).replace(",", ""))
        except ValueError:
            pass

    currency_code = _detect_currency_word(t)
    return max_b, min_b, currency_code


def _extract_weight(t: str) -> tuple[Optional[float], Optional[float]]:
    max_w = min_w = None
    under = re.search(r"(?:زیر|تا|کمتر از)\s*([\d.]+)\s*گرم", t)
    over  = re.search(r"(?:بالای|بیشتر از)\s*([\d.]+)\s*گرم", t)
    if under:
        max_w = float(under.group(1))
    if over:
        min_w = float(over.group(1))
    return max_w, min_w


def local_extract(text: str, settings: Optional[dict] = None) -> SearchQuery:
    """
    Cheap, deterministic, NO-AI-CALL extraction from a single message.
    Used only to seed the same-turn product search before the AI runs.

    Args:
        settings: Store settings dict (needs 'currency'). Any budget the
                  customer names in Toman or Rial is normalized into the
                  store's configured currency here — see
                  services.price_service.normalize_amount(). If omitted,
                  the store currency defaults to Toman (matching
                  price_service's own default fallback).
    """
    if not text:
        return SearchQuery()

    from services.price_service import normalize_amount

    settings = settings or {}
    t = text.lower()
    q = SearchQuery()

    raw_max, raw_min, detected_currency = _extract_budget(t)
    q.max_budget = normalize_amount(raw_max, detected_currency, settings, context="local:max_budget")
    q.min_budget = normalize_amount(raw_min, detected_currency, settings, context="local:min_budget")
    q.max_weight, q.min_weight = _extract_weight(t)

    for gender, kws in _GENDER_MAP.items():
        if any(kw in t for kw in kws):
            q.gender = gender
            break
    for cat, kws in _CATEGORY_MAP.items():
        if any(kw in t for kw in kws):
            q.category = cat
            break
    for color, kws in _COLOR_MAP.items():
        if any(kw in t for kw in kws):
            q.gold_color = color
            break
    for stone, kws in _STONE_MAP.items():
        if any(kw in t for kw in kws):
            q.stone = stone
            break
    for occ, kws in _OCCASION_MAP.items():
        if any(kw in t for kw in kws):
            q.occasion = occ
            break

    q.style_keywords = [kw for kw in _STYLE_KEYWORDS if kw in t]

    return q


def build_query(profile: CustomerProfile, current_text: str = "", settings: Optional[dict] = None) -> SearchQuery:
    """
    Combine (1) cheap local extraction from the CURRENT message (with any
    Toman/Rial budget normalized into store currency — see local_extract)
    with (2) the customer's cumulative profile as a fallback for anything
    the current message didn't mention. profile.max_budget/min_budget are
    always already store-currency-normalized (see
    CustomerProfile.merge_intent + price_service.normalize_intent_budget),
    so no further conversion is needed on that side. The current message
    always wins when it explicitly says something.
    """
    local = local_extract(current_text, settings)
    return SearchQuery(
        category       = local.category or profile.category,
        gender         = local.gender or profile.gender,
        gold_color     = local.gold_color or profile.gold_color,
        stone          = local.stone or profile.stone,
        max_budget     = local.max_budget if local.max_budget is not None else profile.max_budget,
        min_budget     = local.min_budget if local.min_budget is not None else profile.min_budget,
        max_weight     = local.max_weight if local.max_weight is not None else profile.max_weight,
        min_weight     = local.min_weight if local.min_weight is not None else profile.min_weight,
        style_keywords = local.style_keywords or profile.style_keywords,
        occasion       = local.occasion or profile.occasion,
    )


# ── Relevance scoring (ranking, not just filtering) ────────────────────────────

def score_product(
    product: "Product",
    query: SearchQuery,
    price: float,
    profile: Optional[CustomerProfile] = None,
) -> float:
    """
    Weighted relevance score — higher is better. Combines the CURRENT
    query with a smaller bonus for matching the customer's longer-term
    profile, so consistently-relevant items rank higher over time.
    """
    score = 0.0

    if query.category and product.category:
        score += 25.0 if query.category.lower() in product.category.lower() else 0.0

    if query.gender and product.gender:
        if query.gender == product.gender:
            score += 10.0
        elif product.gender == "یونیسکس":
            score += 6.0

    if query.gold_color and product.gold_color:
        score += 15.0 if query.gold_color.lower() in product.gold_color.lower() else 0.0

    if query.stone:
        if query.stone == "none":
            if not product.stone or product.stone in ("", "بدون سنگ", "ندارد"):
                score += 10.0
        elif product.stone and query.stone.lower() in product.stone.lower():
            score += 15.0

    if query.occasion:
        blob = f"{product.tags} {product.description}".lower()
        if query.occasion.lower() in blob:
            score += 8.0

    if query.style_keywords:
        blob = f"{product.name} {product.tags} {product.description}".lower()
        hits = sum(1 for kw in query.style_keywords if kw.lower() in blob)
        score += min(hits, 3) * 5.0

    # Budget fit — reward affordability, penalize going over
    if query.max_budget:
        if price <= query.max_budget:
            closeness = (price / query.max_budget) if query.max_budget > 0 else 0
            score += 15.0 * closeness
        else:
            overshoot = (price - query.max_budget) / query.max_budget
            score -= min(overshoot, 1.0) * 20.0
    if query.min_budget and price < query.min_budget:
        score -= 10.0

    # Weight fit
    if query.max_weight:
        score += 8.0 if product.weight <= query.max_weight else -8.0
    if query.min_weight:
        score += 4.0 if product.weight >= query.min_weight else -4.0

    # Long-term profile bonus (consistency across the whole conversation)
    if profile:
        if profile.category and profile.category.lower() in (product.category or "").lower():
            score += 5.0
        if profile.gold_color and profile.gold_color.lower() in (product.gold_color or "").lower():
            score += 3.0
        if profile.stone and product.stone and profile.stone.lower() in product.stone.lower():
            score += 3.0

    if product.stock > 0:
        score += 2.0

    return round(score, 2)


def search(
    products: list["Product"],
    query: SearchQuery,
    gold_price: float,
    profile: Optional[CustomerProfile] = None,
    max_results: int = MAX_SEARCH_RESULTS,
) -> SearchResult:
    """
    Score every available product, sort by relevance, return the top
    `max_results` as a typed SearchResult. Falls back to best-available
    products (ignoring the query) if nothing scores positively, so the AI
    always has real products to work with.
    """
    from services.price_service import calculate_price

    available = [p for p in products if p.is_available]
    scored: list[tuple[float, "Product"]] = [
        (score_product(p, query, calculate_price(p, gold_price), profile), p)
        for p in available
    ]
    scored.sort(key=lambda pair: pair[0], reverse=True)

    positive = [pair for pair in scored if pair[0] > 0]
    chosen = positive[:max_results] if positive else scored[:max_results]

    contexts = [
        ProductContext(
            id=p.id, name=p.name, category=p.category, gender=p.gender,
            gold_color=p.gold_color, stone=p.stone, weight=p.weight,
            price=calculate_price(p, gold_price), stock=p.stock,
            relevance_score=s,
        )
        for s, p in chosen
    ]

    logger.info(
        "Search: %d available, %d positively scored, returning top %d.",
        len(available), len(positive), len(contexts),
    )
    return SearchResult(products=contexts, total_matched=len(positive), query=query)


# ── Notification similarity (follow-up system) ─────────────────────────────────

def notification_similarity(product: "Product", profile: CustomerProfile, price: float) -> float:
    """
    Return a normalized 0..1 similarity score for restock-notification
    matching. Stricter and more interpretable than the chat relevance
    score above — used to decide whether to proactively message a customer.
    """
    if not profile.has_any_preference() or not product.is_available:
        return 0.0

    checks: list[tuple[float, bool]] = []

    if profile.category:
        checks.append((0.25, profile.category.lower() in (product.category or "").lower()))
    if profile.gender:
        checks.append((0.10, profile.gender == product.gender or product.gender == "یونیسکس"))
    if profile.gold_color:
        checks.append((0.20, profile.gold_color.lower() in (product.gold_color or "").lower()))
    if profile.stone:
        if profile.stone == "none":
            checks.append((0.15, not product.stone or product.stone in ("", "بدون سنگ", "ندارد")))
        else:
            checks.append((0.15, bool(product.stone) and profile.stone.lower() in product.stone.lower()))
    if profile.max_budget:
        checks.append((0.20, price <= profile.max_budget))
    if profile.max_weight:
        checks.append((0.10, product.weight <= profile.max_weight))

    if not checks:
        return 0.0

    total_weight   = sum(w for w, _ in checks)
    matched_weight = sum(w for w, ok in checks if ok)
    return round(matched_weight / total_weight, 3) if total_weight else 0.0


def find_unavailable_match(
    products: list["Product"],
    profile: CustomerProfile,
    gold_price: float,
    min_score: Optional[float] = None,
) -> Optional["Product"]:
    """
    Among products that are CURRENTLY UNAVAILABLE (sold out / draft), find
    the single best match for this customer's profile.

    This is notification_similarity()'s exact weighting philosophy run in
    reverse: that function only ever looks at AVAILABLE products (it
    exists to catch a newly-restocked item for the manual broadcast); this
    one only ever looks at UNAVAILABLE ones, so the general chat flow can
    attach a "let me know when it's back" request to one concrete
    product_id even when the customer never tapped a specific product's
    "ask about this" button — see handlers/customer.py._process_ai_message.

    Deliberately conservative: returns None (no attachment) unless a
    product clears min_score confidence, so a low-confidence guess never
    risks notifying a customer about the wrong item. When None, the
    customer's want is still captured by the existing, broader
    notify_enabled preference flag on their profile — nothing is lost,
    it's just not tied to one specific product.
    """
    from config.config import NOTIFICATION_SIMILARITY_THRESHOLD
    from services.price_service import calculate_price

    if min_score is None:
        min_score = NOTIFICATION_SIMILARITY_THRESHOLD

    if not profile.has_any_preference():
        return None

    best_product: Optional["Product"] = None
    best_score = 0.0

    for product in products:
        if product.is_available:
            continue

        price = calculate_price(product, gold_price)
        checks: list[tuple[float, bool]] = []

        if profile.category:
            checks.append((0.25, profile.category.lower() in (product.category or "").lower()))
        if profile.gender:
            checks.append((0.10, profile.gender == product.gender or product.gender == "یونیسکس"))
        if profile.gold_color:
            checks.append((0.20, profile.gold_color.lower() in (product.gold_color or "").lower()))
        if profile.stone:
            if profile.stone == "none":
                checks.append((0.15, not product.stone or product.stone in ("", "بدون سنگ", "ندارد")))
            else:
                checks.append((0.15, bool(product.stone) and profile.stone.lower() in product.stone.lower()))
        if profile.max_budget:
            checks.append((0.20, price <= profile.max_budget))
        if profile.max_weight:
            checks.append((0.10, product.weight <= profile.max_weight))

        if not checks:
            continue

        total_weight   = sum(w for w, _ in checks)
        matched_weight = sum(w for w, ok in checks if ok)
        score = (matched_weight / total_weight) if total_weight else 0.0

        if score > best_score:
            best_score, best_product = score, product

    return best_product if best_score >= min_score else None
