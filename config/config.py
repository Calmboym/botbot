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

# ── Deployment / Webhook ──────────────────────────────────────────────────────
WEBHOOK_URL: str    = os.environ.get("WEBHOOK_URL", "").strip().rstrip("/")
PORT: int           = int(os.environ.get("PORT", 8443))
WEBHOOK_SECRET: str = os.environ.get("WEBHOOK_SECRET", "").strip()

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
CUSTOMERS_SHEET: str = "customers"

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL: str        = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_DIR: str          = "logs"
LOG_MAX_BYTES: int    = 5 * 1024 * 1024
LOG_BACKUP_COUNT: int = 5

# ── Caching (sheet data / conversation / admin flow TTLs) ─────────────────────
CACHE_TTL: int        = int(os.environ.get("CACHE_TIME", "300"))
CONVERSATION_TTL: int = int(os.environ.get("CONV_TTL", "3600"))
ADMIN_STATE_TTL: int  = int(os.environ.get("ADMIN_TTL", "1800"))

# ── Behaviour ─────────────────────────────────────────────────────────────────
MAX_SEARCH_RESULTS: int    = int(os.environ.get("MAX_SEARCH_RESULTS", "10"))
PRODUCTS_PER_PAGE: int     = 5
PRICE_UPDATE_INTERVAL: int = int(os.environ.get("PRICE_UPDATE_INTERVAL", "3600"))

# ══════════════════════════════════════════════════════════════════════════════
# AI Provider (provider-independent architecture — see providers/ package)
# ══════════════════════════════════════════════════════════════════════════════
# Switching providers requires changing ONLY this one value.
AI_PROVIDER: str = os.environ.get("AI_PROVIDER", "groq").strip().lower()

AI_TEMPERATURE: float = float(os.environ.get("AI_TEMPERATURE", "0.7"))
AI_MAX_TOKENS: int    = int(os.environ.get("AI_MAX_TOKENS", "1500"))
AI_RETRY_COUNT: int   = int(os.environ.get("AI_RETRY_COUNT", "1"))   # extra attempts after the first
AI_TIMEOUT: int       = int(os.environ.get("AI_TIMEOUT", "30"))      # seconds

# ── Groq (default / currently implemented provider) ───────────────────────────
GROQ_API_KEY: str      = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_MODEL: str        = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
GROQ_VISION_MODEL: str = os.environ.get(
    "GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"
).strip()

# ── Gemini (skeleton — see providers/gemini_provider.py) ──────────────────────
GEMINI_API_KEY: str      = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL: str        = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash").strip()
GEMINI_VISION_MODEL: str = os.environ.get("GEMINI_VISION_MODEL", "gemini-1.5-flash").strip()

# ── OpenAI (skeleton — see providers/openai_provider.py) ──────────────────────
OPENAI_API_KEY: str      = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL: str        = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()
OPENAI_VISION_MODEL: str = os.environ.get("OPENAI_VISION_MODEL", "gpt-4o-mini").strip()

if AI_PROVIDER == "groq" and not GROQ_API_KEY:
    print("[FATAL] AI_PROVIDER=groq but GROQ_API_KEY is missing in .env.", file=sys.stderr)
    sys.exit(1)

# ── Conversation Memory (Recent Messages + rolling Summary, not full history) ─
RECENT_MESSAGES_COUNT: int    = int(os.environ.get("RECENT_MESSAGES_COUNT", "6"))
SUMMARY_TRIGGER_MESSAGES: int = int(os.environ.get("SUMMARY_TRIGGER_MESSAGES", "6"))
SUMMARY_MAX_CHARS: int        = int(os.environ.get("SUMMARY_MAX_CHARS", "500"))

# ── Images / Support ──────────────────────────────────────────────────────────
MAX_IMAGES_PER_REPLY: int = int(os.environ.get("MAX_IMAGES_PER_REPLY", "3"))

IMAGE_REQUEST_KEYWORDS: list[str] = [
    "عکس", "عکسش", "عکسشو", "عکسو", "تصویر", "تصویرش",
    "نشونم بده", "نشون بده", "نشونم بدید", "نشونمون بده",
    "ببینمش", "ببینم", "فوتو", "عکس بفرست", "عکس بده", "می‌خوام ببینم",
]

# ── Notifications / Follow-up ─────────────────────────────────────────────────
# Similarity score (0..1) a customer's profile must reach for a restocked
# product to trigger an automatic notification. See services/search_service.py
# notification_similarity().
NOTIFICATION_SIMILARITY_THRESHOLD: float = float(
    os.environ.get("NOTIFICATION_SIMILARITY_THRESHOLD", "0.55")
)

# ── Product Status Values ─────────────────────────────────────────────────────
STATUS_ACTIVE: str = "active"
STATUS_SOLD: str   = "sold"
STATUS_DRAFT: str  = "draft"

# ── Field Metadata ────────────────────────────────────────────────────────────
FIELD_LABELS: dict[str, str] = {
    "name":             "نام محصول",
    "category":         "دسته‌بندی",
    "subcategory":      "زیردسته",
    "gender":           "جنسیت",
    "collection":       "کالکشن",
    "weight":           "وزن (گرم)",
    "wage_percent":     "درصد اجرت",
    "profit_percent":   "درصد سود",
    "stone":            "سنگ",
    "stone_color":      "رنگ سنگ",
    "gold_color":       "رنگ طلا",
    "purity":           "عیار",
    "stock":            "موجودی",
    "price_override":   "قیمت ثابت",
    "description":      "توضیحات",
    "tags":             "برچسب‌ها",
    "telegram_file_id": "تصویر محصول",
    "status":           "وضعیت",
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
