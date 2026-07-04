"""
Gold Bot v2 – Configuration
============================
Single source of truth for every environment variable and constant.
All other modules import from here. No module ever reads os.environ directly.
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()


def _req(key: str) -> str:
    """Return required env var or exit with a clear error."""
    val = os.environ.get(key, "").strip()
    if not val:
        print(f"[FATAL] Missing required environment variable: {key}", file=sys.stderr)
        sys.exit(1)
    return val


# ── Telegram ──────────────────────────────────────────────────────────────────
TOKEN: str            = _req("TOKEN")
ADMIN_ID: int         = int(_req("ADMIN_ID"))
CHANNEL_USERNAME: str = _req("CHANNEL_USERNAME")
if not CHANNEL_USERNAME.startswith("@"):
    CHANNEL_USERNAME = f"@{CHANNEL_USERNAME}"

# ── Groq AI ───────────────────────────────────────────────────────────────────
GROQ_API_KEY: str      = _req("GROQ_API_KEY")
GROQ_MODEL: str        = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
GROQ_VISION_MODEL: str = os.environ.get(
    "GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"
).strip()

# ── Google Sheets ─────────────────────────────────────────────────────────────
SPREADSHEET_NAME: str     = _req("SPREADSHEET_NAME")
SERVICE_ACCOUNT_FILE: str = os.environ.get("SERVICE_ACCOUNT_FILE", "service_account.json").strip()
GOOGLE_SCOPES: list[str]  = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ── Sheet / Tab Names ─────────────────────────────────────────────────────────
PRODUCTS_SHEET: str  = "products"
SETTINGS_SHEET: str  = "settings"
FAQ_SHEET: str       = "faq"
CUSTOMERS_SHEET: str = "customers"   # NEW: per-user wishlist / interest tracking

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL: str        = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_DIR: str          = "logs"
LOG_MAX_BYTES: int    = 5 * 1024 * 1024
LOG_BACKUP_COUNT: int = 5

# ── Caching ───────────────────────────────────────────────────────────────────
CACHE_TTL: int        = int(os.environ.get("CACHE_TIME", "300"))
CONVERSATION_TTL: int = int(os.environ.get("CONV_TTL", "3600"))
ADMIN_STATE_TTL: int  = int(os.environ.get("ADMIN_TTL", "1800"))

# ── Behaviour ─────────────────────────────────────────────────────────────────
MAX_SEARCH_RESULTS: int = int(os.environ.get("MAX_SEARCH_RESULTS", "10"))
PRODUCTS_PER_PAGE: int  = 5

# Automatic gold price update interval in seconds.
# 3600 = every 1 hour | 7200 = every 2 hours | 0 = disabled
PRICE_UPDATE_INTERVAL: int = int(os.environ.get("PRICE_UPDATE_INTERVAL", "3600"))

# ── AI / Conversation ─────────────────────────────────────────────────────────
SUPPORT_SIGNAL: str     = "[SUPPORT]"
MAX_CONV_RESPONSES: int = 50
# How many past user+assistant message PAIRS to keep in Groq context window.
# 10 pairs = 20 messages. Increase if you want longer memory; decrease to
# save Groq tokens. Each pair is ~100–400 tokens on average.
CONV_HISTORY_PAIRS: int = int(os.environ.get("CONV_HISTORY_PAIRS", "10"))
MAX_HISTORY_MSGS: int   = CONV_HISTORY_PAIRS * 2   # used by ai_service

IMAGE_SIGNAL_PATTERN: str = r"\[IMAGE:(\d+)\]"
MAX_IMAGES_PER_REPLY: int = 3

IMAGE_REQUEST_KEYWORDS: list[str] = [
    "عکس", "عکسش", "عکسشو", "عکسو", "تصویر", "تصویرش",
    "نشونم بده", "نشون بده", "نشونم بدید", "نشونمون بده",
    "ببینمش", "ببینم", "فوتو", "عکس بفرست", "عکس بده", "می‌خوام ببینم",
]

# ── Product Status Values ─────────────────────────────────────────────────────
STATUS_ACTIVE: str = "active"
STATUS_SOLD: str   = "sold"
STATUS_DRAFT: str  = "draft"

# ── Field Metadata ────────────────────────────────────────────────────────────
FIELD_LABELS: dict[str, str] = {
    "name":           "نام محصول",
    "category":       "دسته‌بندی",
    "subcategory":    "زیردسته",
    "gender":         "جنسیت",
    "collection":     "کالکشن",
    "weight":         "وزن (گرم)",
    "wage_percent":   "درصد اجرت",
    "profit_percent": "درصد سود",
    "stone":          "سنگ",
    "stone_color":    "رنگ سنگ",
    "gold_color":     "رنگ طلا",
    "purity":         "عیار",
    "stock":          "موجودی",
    "price_override": "قیمت ثابت",
    "description":    "توضیحات",
    "tags":           "برچسب‌ها",
    "telegram_file_id": "تصویر محصول",
    "status":         "وضعیت",
}

FIELD_GROUPS: dict[str, list[str]] = {
    "📝 اطلاعات پایه":  ["name", "category", "subcategory", "gender", "collection"],
    "💰 قیمت‌گذاری":   ["weight", "wage_percent", "profit_percent", "price_override"],
    "🎨 ظاهر محصول":   ["gold_color", "purity", "stone", "stone_color"],
    "📦 موارد دیگر":   ["stock", "description", "tags", "telegram_file_id", "status"],
}

NUMERIC_FIELDS: set[str] = {
    "weight", "wage_percent", "profit_percent", "price_override", "stock"
}

OPTION_FIELDS: dict[str, list[str]] = {
    "category":   ["انگشتر", "گردنبند", "دستبند", "گوشواره", "النگو", "آویز", "ست", "سایر"],
    "gender":     ["زنانه", "مردانه", "بچگانه", "یونیسکس"],
    "gold_color": ["زرد", "سفید", "رزگلد"],
    "purity":     ["18 عیار", "21 عیار", "24 عیار"],
    "status":     [STATUS_ACTIVE, STATUS_SOLD, STATUS_DRAFT],
    "stone": [
        "بدون سنگ", "الماس", "زمرد", "یاقوت",
        "فیروزه", "سنگ طبیعی", "سنگ مصنوعی", "سایر"
    ],
}
