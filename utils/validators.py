"""
Gold Bot v2 – Validators
=========================
Pure validation functions shared across handlers and services.
"""

import re
from typing import Optional

from config.config import ADMIN_ID, NUMERIC_FIELDS


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


def validate_numeric_field(field: str, raw: str) -> tuple[bool, Optional[float], str]:
    """
    Validate a value intended for a numeric product field.
    Returns (ok, value, error_message).
    """
    clean = raw.strip().replace(",", "")
    try:
        value = float(clean)
    except ValueError:
        return False, None, f"مقدار «{raw}» عدد معتبر نیست."
    if value < 0:
        return False, None, "مقدار نمی‌تواند منفی باشد."
    if field in ("wage_percent", "profit_percent") and value > 100:
        return False, None, "درصد نمی‌تواند بیشتر از ۱۰۰ باشد."
    if field == "weight" and value > 500:
        return False, None, "وزن بیش از ۵۰۰ گرم غیر معمول است. لطفاً دوباره بررسی کنید."
    return True, value, ""


def validate_image_url(url: str) -> tuple[bool, str]:
    """Check that the URL looks like an image link."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return False, "لینک باید با http:// یا https:// شروع شود."
    image_exts = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
    has_ext = any(url.lower().split("?")[0].endswith(ext) for ext in image_exts)
    if not has_ext and "drive.google.com" not in url and "images" not in url.lower():
        return False, "لینک باید مستقیماً به یک فایل تصویر اشاره کند (.jpg, .png …)."
    return True, ""


def validate_product_id(raw: str) -> tuple[bool, int, str]:
    """Parse and validate a product ID string."""
    try:
        pid = int(raw.strip())
        if pid <= 0:
            return False, 0, "شناسه محصول باید مثبت باشد."
        return True, pid, ""
    except ValueError:
        return False, 0, "شناسه محصول باید عدد صحیح باشد."


def validate_gold_price(raw: str) -> tuple[bool, float, str]:
    """Validate a manually entered gold price."""
    clean = raw.strip().replace(",", "").replace("٬", "")
    try:
        price = float(clean)
    except ValueError:
        return False, 0.0, "قیمت وارد شده معتبر نیست. یک عدد وارد کنید."
    if price <= 0:
        return False, 0.0, "قیمت باید بیشتر از صفر باشد."
    if price < 100_000:
        return False, 0.0, "قیمت خیلی پایین به نظر می‌رسد. واحد: تومان."
    if price > 100_000_000:
        return False, 0.0, "قیمت خیلی بالا به نظر می‌رسد. لطفاً بررسی کنید."
    return True, price, ""


def sanitise_text(text: str, max_len: int = 500) -> str:
    """Remove control characters and trim length."""
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text.strip()[:max_len]
