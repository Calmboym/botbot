"""
Gold Bot v2 – Search Service
==============================
Python-side product filtering that runs BEFORE any AI call.
GPT never receives the full product list – only the filtered subset.

Flow:
    1. extract_filters(user_text)  →  SearchFilters
    2. filter_products(products, filters, gold_price)  →  list[Product]
    3. Filtered list is passed to AIService
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from models.product import Product

from services.price_service import calculate_price
from config.config import MAX_SEARCH_RESULTS

logger = logging.getLogger(__name__)


# ── Filter Dataclass ──────────────────────────────────────────────────────────

@dataclass
class SearchFilters:
    max_budget:     Optional[float]  = None
    min_budget:     Optional[float]  = None
    gender:         Optional[str]    = None
    category:       Optional[str]    = None
    gold_color:     Optional[str]    = None
    stone:          Optional[str]    = None     # "none" = no stone
    max_weight:     Optional[float]  = None
    min_weight:     Optional[float]  = None
    keywords:       list[str]        = field(default_factory=list)
    style_keywords: list[str]        = field(default_factory=list)
    occasion:       Optional[str]    = None
    is_gift:        bool             = False
    sort_by:        str              = "relevance"   # relevance | price_asc | price_desc | newest
    available_only: bool             = True

    def has_any(self) -> bool:
        return any([
            self.max_budget, self.min_budget, self.gender, self.category,
            self.gold_color, self.stone, self.max_weight, self.min_weight,
            self.keywords, self.style_keywords, self.occasion, self.is_gift,
        ])


# ── Keyword tables ────────────────────────────────────────────────────────────

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

_SORT_MAP: dict[str, list[str]] = {
    "price_asc":  ["ارزان‌ترین", "کمترین قیمت", "ارزان تر"],
    "price_desc": ["گران‌ترین", "بیشترین قیمت"],
    "newest":     ["جدیدترین", "تازه‌ترین", "جدید"],
}

_STYLE_KEYWORDS: list[str] = [
    "مدرن", "کلاسیک", "ظریف", "سنگین", "حجیم",
    "لوکس", "مینیمال", "اسپرت", "شیک", "سنتی",
]

_OCCASION_MAP: dict[str, list[str]] = {
    "نامزدی":   ["نامزدی", "حلقه نامزدی", "عروسی", "ازدواج"],
    "هدیه":     ["هدیه", "کادو", "پیشکش", "gift"],
    "روزمره":   ["روزانه", "روزمره", "هر روز", "کاری"],
}


def _extract_budget(text: str) -> tuple[Optional[float], Optional[float]]:
    """Return (max_budget, min_budget) extracted from Persian text."""
    max_b = min_b = None

    # Patterns: "زیر ۴۰ میلیون", "تا ۴۰ میلیون", "۴۰ میلیون"
    under_pat = re.search(r"(?:زیر|تا|کمتر از)\s*([\d,]+(?:\.\d+)?)\s*میلیون", text)
    over_pat  = re.search(r"(?:بالای|بیشتر از)\s*([\d,]+(?:\.\d+)?)\s*میلیون", text)
    plain_pat = re.search(r"([\d,]+(?:\.\d+)?)\s*میلیون", text)

    if under_pat:
        max_b = float(under_pat.group(1).replace(",", "")) * 1_000_000
    if over_pat:
        min_b = float(over_pat.group(1).replace(",", "")) * 1_000_000
    elif plain_pat and not under_pat:
        max_b = float(plain_pat.group(1).replace(",", "")) * 1_000_000

    # Direct Toman patterns: "40,000,000 تومان"
    toman_pat = re.search(r"([\d,]+)\s*تومان", text)
    if toman_pat and not max_b:
        try:
            max_b = float(toman_pat.group(1).replace(",", ""))
        except ValueError:
            pass

    return max_b, min_b


def _extract_weight(text: str) -> tuple[Optional[float], Optional[float]]:
    """Return (max_weight, min_weight)."""
    max_w = min_w = None
    under = re.search(r"(?:زیر|تا|کمتر از)\s*([\d.]+)\s*گرم", text)
    over  = re.search(r"(?:بالای|بیشتر از)\s*([\d.]+)\s*گرم", text)
    if under:
        max_w = float(under.group(1))
    if over:
        min_w = float(over.group(1))
    return max_w, min_w


# ── Public API ────────────────────────────────────────────────────────────────

def extract_filters(text: str) -> SearchFilters:
    """
    Parse a natural Persian query and return a SearchFilters object.
    Handles budgets, categories, gender, colors, stones, weight, style, and sort.
    """
    f = SearchFilters()
    t = text.lower()

    # Budget
    f.max_budget, f.min_budget = _extract_budget(t)

    # Weight
    f.max_weight, f.min_weight = _extract_weight(t)

    # Gender
    for gender, kws in _GENDER_MAP.items():
        if any(kw in t for kw in kws):
            f.gender = gender
            break

    # Category
    for cat, kws in _CATEGORY_MAP.items():
        if any(kw in t for kw in kws):
            f.category = cat
            break

    # Gold color
    for color, kws in _COLOR_MAP.items():
        if any(kw in t for kw in kws):
            f.gold_color = color
            break

    # Stone
    for stone, kws in _STONE_MAP.items():
        if any(kw in t for kw in kws):
            f.stone = stone
            break

    # Sort preference
    for sort_key, kws in _SORT_MAP.items():
        if any(kw in t for kw in kws):
            f.sort_by = sort_key
            break

    # Style keywords
    f.style_keywords = [kw for kw in _STYLE_KEYWORDS if kw in t]

    # Occasion
    for occ, kws in _OCCASION_MAP.items():
        if any(kw in t for kw in kws):
            f.occasion = occ
            if occ == "هدیه":
                f.is_gift = True
            break

    if "هدیه" in t or "کادو" in t:
        f.is_gift = True

    logger.debug("Extracted filters: %s", f)
    return f


def filter_products(
    products: list["Product"],
    filters: SearchFilters,
    gold_price: float,
    max_results: int = MAX_SEARCH_RESULTS,
) -> list["Product"]:
    """
    Apply filters to the product list.
    Returns at most max_results products.
    If nothing matches, returns the top max_results available products as fallback.
    """
    results: list["Product"] = []

    for p in products:
        # Availability
        if filters.available_only and not p.is_available:
            continue

        # Gender (empty gender = unisex, matches all)
        if filters.gender and p.gender:
            if filters.gender not in (p.gender, "یونیسکس"):
                continue

        # Category
        if filters.category and p.category:
            if filters.category.lower() not in p.category.lower():
                continue

        # Gold color
        if filters.gold_color and p.gold_color:
            if filters.gold_color.lower() not in p.gold_color.lower():
                continue

        # Stone
        if filters.stone:
            if filters.stone == "none":
                if p.stone and p.stone not in ("", "بدون سنگ", "ندارد"):
                    continue
            else:
                if p.stone and filters.stone.lower() not in p.stone.lower():
                    continue

        # Weight
        if filters.max_weight and p.weight > filters.max_weight:
            continue
        if filters.min_weight and p.weight < filters.min_weight:
            continue

        # Budget
        if filters.max_budget or filters.min_budget:
            price = calculate_price(p, gold_price)
            if filters.max_budget and price > filters.max_budget:
                continue
            if filters.min_budget and price < filters.min_budget:
                continue

        # Style keywords (at least one must match)
        if filters.style_keywords:
            blob = f"{p.name} {p.tags} {p.description}".lower()
            if not any(kw.lower() in blob for kw in filters.style_keywords):
                continue

        results.append(p)

    # Sorting
    if filters.sort_by == "price_asc":
        results.sort(key=lambda p: calculate_price(p, gold_price))
    elif filters.sort_by == "price_desc":
        results.sort(key=lambda p: calculate_price(p, gold_price), reverse=True)
    elif filters.sort_by == "newest":
        results.sort(key=lambda p: p.updated_at or p.created_at or "", reverse=True)

    if results:
        return results[:max_results]

    # Fallback: return available products if nothing matched
    logger.info("No products matched filters; falling back to available products.")
    available = [p for p in products if p.is_available]
    return available[:max_results]
