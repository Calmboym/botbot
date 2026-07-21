# 💍 Gold Bot v2 — AI-Powered Jewelry Store Assistant

A production-ready Telegram bot that turns a Google Sheet into a fully
managed jewelry store — with an AI sales assistant, admin dashboard,
live gold pricing, smart Persian-language search, automatic price updates,
customer wishlist tracking, and restock notifications.

---

## ✨ Features

| Category | Description |
|----------|-------------|
| **AI Assistant** | Persian sales assistant (Mona) powered by Groq (llama-3.3-70b) |
| **Conversation Memory** | Per-user multi-turn history (configurable, default 10 pairs) |
| **Smart Search** | Python keyword/budget/category filtering before every AI call |
| **Image Handling** | Admin sends a photo → Telegram stores it → file_id saved in sheet |
| **Admin Dashboard** | Full inline-keyboard panel — no command memorisation needed |
| **Product Management** | Add / Edit / Delete entirely from Telegram |
| **Auto Gold Price** | Scrapes tgju.org on a configurable schedule (default: every hour) |
| **Customer Tracking** | Saves interests per user in Google Sheets `customers` sheet |
| **Restock Notifications** | Bot messages opted-in customers when a matching product is available |
| **Sheet Sync** | 🔄 button instantly reloads changes made directly in Google Sheets |
| **Caching** | Configurable TTL cache for all Sheets data |
| **Rotating Logs** | `logs/gold_bot.log` with automatic rotation |

---

## 🖼 Image Storage — How It Works

This bot uses **Telegram's own file storage** for product photos.
There is no Google Drive, no external hosting, and no image URLs needed.

```
Admin sends a photo to the bot
           ↓
Telegram stores the file on its servers
           ↓
Bot reads  photo.file_id  from the message
           ↓
file_id is saved to the  telegram_file_id  column in Google Sheets
           ↓
When publishing, bot calls  send_photo(photo=telegram_file_id)
Telegram serves the image directly — no download or re-upload
```

**Benefits:**
- ✅ Zero external dependencies for image storage
- ✅ No Drive quota issues
- ✅ No broken image URLs
- ✅ Instant — no upload step, just save the ID

---

## 🗂 Project Structure

```
gold_bot_v2/
├── config/
│   └── config.py              # All env vars & constants
├── handlers/
│   ├── admin.py               # Admin panel flows
│   ├── customer.py            # Customer AI chat + photo handling
│   └── callbacks.py           # Inline button router (a:… / c:…)
├── services/
│   ├── sheet_service.py       # Google Sheets CRUD + caching
│   ├── gold_service.py        # Gold price read/write + scraper
│   ├── price_service.py       # Price calculation & formatting
│   ├── search_service.py      # Persian keyword extraction & filtering
│   ├── ai_service.py          # Groq Chat Completions integration
│   ├── publish_service.py     # Channel publishing + customer photo send
│   ├── customer_service.py    # CRM: wishlist, matching, notifications
│   └── telegram_service.py    # Admin notifications & support forwarding
├── models/
│   └── product.py             # Product dataclass (telegram_file_id field)
├── keyboards/
│   ├── admin_keyboard.py      # All admin InlineKeyboardMarkup builders
│   └── customer_keyboard.py   # Channel post buttons + notify opt-in
├── utils/
│   ├── cache.py               # TTLCache, ConversationState, AdminState
│   ├── logger.py              # Rotating file + console logger
│   └── validators.py          # Input validation helpers
├── data/                      # Exports & backups (auto-created)
├── logs/                      # Rotating log files (auto-created)
├── main.py                    # Entry point — service wiring & polling
├── update_price.py            # Standalone gold price scraper
├── requirements.txt
├── .env.example
├── service_account.json.example
└── .gitignore
```

---

## ⚙️ Prerequisites

- Python 3.12+
- Google Cloud account (free tier)
- Groq account (free API key)
- Telegram account

---

## 🚀 Installation

### 1. Unzip and enter directory

```bash
unzip gold_bot_v2.zip
cd gold_bot_v2
```

### 2. Virtual environment

```bash
python3 -m venv venv
source venv/bin/activate          # Linux / macOS
venv\Scripts\activate             # Windows CMD
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

---

## ☁️ Google Cloud Setup

### 1. Create a project
[console.cloud.google.com](https://console.cloud.google.com) → New Project.

### 2. Enable APIs
**APIs & Services → Library** — enable:
- **Google Sheets API**
- **Google Drive API**

### 3. Create a Service Account
**APIs & Services → Credentials → Create Credentials → Service Account**
Give it a name (e.g. `gold-bot-service`) → Done.

### 4. Download the JSON key
Service account → **Keys → Add Key → Create new key → JSON**.
Rename the file to `service_account.json`, place it in the project root.

> ⚠️ Never commit `service_account.json`. It is in `.gitignore`.

---

## 📊 Google Sheets Setup

### Create the spreadsheet
Name it exactly **`Gold Products`** (or whatever you set in `SPREADSHEET_NAME`).

### Sheet 1 — `products`

Rename `Sheet1` to **`products`** (lowercase).

Row 1 headers — copy exactly:

```
id | name | category | subcategory | gender | collection | weight |
wage_percent | profit_percent | stone | stone_color | gold_color |
purity | stock | price_override | description | tags |
telegram_file_id | status | published_message_id | created_at | updated_at
```

> ⚠️ The image column is now called **`telegram_file_id`** (not `image`).
> It is filled automatically when the admin sends a product photo.

**Column descriptions:**

| Column | Type | Description |
|--------|------|-------------|
| `id` | integer | Unique product ID |
| `name` | text | Product name in Persian |
| `category` | text | e.g. انگشتر, گردنبند |
| `weight` | decimal | Weight in grams |
| `wage_percent` | decimal | Labour charge % |
| `profit_percent` | decimal | Profit margin % |
| `gold_color` | text | زرد / سفید / رزگلد |
| `purity` | text | 18 عیار / 21 عیار |
| `stock` | integer | Available units (blank = 1) |
| `price_override` | decimal | Fixed price override (optional) |
| `telegram_file_id` | text | **Auto-filled** when admin sends a photo |
| `status` | text | active / sold / draft |
| `published_message_id` | integer | **Auto-filled** after publishing |
| `created_at` / `updated_at` | text | **Auto-filled** by the bot |

### Sheet 2 — `settings`

Tab name: **`settings`**

| key | value |
|-----|-------|
| `gold_price` | 0 |
| `last_update` | — |
| `store_name` | نام فروشگاه |
| `store_phone` | شماره تماس |
| `store_address` | آدرس |
| `currency` | تومان |

### Sheet 3 — `faq`

Tab name: **`faq`**

| question | answer |
|----------|--------|
| تفاوت طلای ۱۸ و ۲۱ عیار چیست؟ | … |

### Sheet 4 — `customers`

Created automatically on first customer message. Headers (auto-created):

```
user_id | name | category | gender | gold_color | stone |
max_budget | min_budget | max_weight | min_weight | style_keywords |
occasion | shopping_stage | interest_level | notify | last_seen | updated_at
```

**A customer can have more than one row.** Each row is one distinct
*want* — refining the same want (adding a budget, a weight limit, etc. to
an already-open search) updates that row in place, but asking about a
genuinely different category/gender/gold_color/stone (e.g. a necklace
after a ring) appends a **new** row instead of overwriting the previous
one, so the sheet keeps the customer's full history rather than only
their single latest interest. `notify=yes` is sticky — it's always
carried forward onto new want-rows once set.

Anything that means "how many customers / who are they" (the admin
panel's total count, manual-notify matching) automatically **deduplicates
to each customer's latest row** so nobody is over-counted or notified
twice — see `CustomerService.get_all_profiles(dedupe=True)`.

> ⚠️ **If upgrading from an older version:** this schema replaced an
> earlier, simpler `customers` sheet. Delete (or rename) any existing
> `customers` tab so the bot recreates it with the new columns on first use.

### Sheet 5 — `back_in_stock`

Created automatically the first time a customer asks about a product that
turns out to be unavailable — no manual setup needed. Headers (auto-created):

```
user_id | user_name | chat_id | product_id | product_name |
requested_at | status | notified_at
```

`status` is `waiting` until that exact product becomes available again
(stock or status edited by the admin), at which point the bot messages
that customer automatically, flips the row to `notified`, and never sends
it again. See "📦 Back-In-Stock Requests" below.

### Share with Service Account

**Share → paste `client_email` from `service_account.json` → Editor → Send**

---

## 🤖 AI Provider Setup

The AI layer is **provider-independent** — business logic never talks to
Groq (or any vendor) directly, only to a `BaseAIProvider` interface (see
`providers/`). Switching providers is a single `.env` change:

```env
AI_PROVIDER=groq     # or: gemini | openai
```

### Groq (default — fully implemented)

1. Go to [console.groq.com](https://console.groq.com)
2. Sign up (free)
3. **API Keys → Create API Key**
4. Copy the key (starts with `gsk_`) into `.env` as `GROQ_API_KEY`

Default text model: `llama-3.3-70b-versatile`
Default vision model: `meta-llama/llama-4-scout-17b-16e-instruct`

### Gemini / OpenAI (skeletons — not yet implemented)

`providers/gemini_provider.py` and `providers/openai_provider.py` exist as
empty skeletons with clear TODOs. Implementing either one and setting
`AI_PROVIDER=gemini` (or `openai`) in `.env` is enough to switch — **no
other file in the project needs to change.**

---

## 🧠 AI Architecture (how the assistant actually works)

```
Customer message
      │
      ▼
1. Cheap local checks (no AI call)
   - explicit photo keyword + focused product → send photo, done
   - local_extract(): regex-based Persian parsing seeds a SearchQuery
     for THIS message (so even the very first message gets matched
     against real products before any AI call)
      │
      ▼
2. search_service.search()
   - merges the local query with the customer's cumulative profile
   - scores every available product (category, budget, color, stone,
     style, weight, occasion, + long-term profile bonus)
   - returns only the top-N ranked products as the AI's candidate list
      │
      ▼
3. ONE AI call → AIService.handle_message()
   - provider-independent (BaseAIProvider.generate(..., json_mode=True))
   - returns a single validated JSON object (models.ai_models.AIResponse):
       reply, needs_support, image_product_ids, intent
   - "intent" is a full IntentExtraction: category/budget/color/stone/
     style/occasion PLUS shopping_stage, urgency, emotion, purchase
     readiness, interest level, wants_notification — extracted in the
     SAME call as the reply, so no second AI call is needed per message
      │
      ▼
4. CustomerProfile.merge_intent(intent)
   - cumulative, non-destructive merge — a new field REPLACES only
     itself; everything else (and interest_level, which only ever
     increases) is preserved
   - persisted to the `customers` sheet in the background
      │
      ▼
5. SummaryService (every SUMMARY_TRIGGER_MESSAGES turns)
   - regenerates a short rolling ConversationSummary via a small AI call
   - the AI NEVER receives full chat history — only:
     recent messages (capped) + this summary + the cumulative profile
      │
      ▼
6. Follow-up system
   - if intent.wants_notification, or purchase_readiness ≥ 70, or the
     customer has any concrete preference (offered periodically), the
     bot offers to notify them on restock
   - restock notifications use search_service.notification_similarity()
     — a normalized 0..1 score against NOTIFICATION_SIMILARITY_THRESHOLD
```

**JSON safety:** every AI response is validated with Pydantic
(`AIResponse.model_validate`). An invalid response is retried once
(`AI_RETRY_COUNT`) with a stricter reminder; if that also fails, a safe
fallback message is returned — the bot never crashes on a bad model output.

---

## 💬 Telegram Setup

### Create the bot
1. Message **@BotFather** → `/newbot`
2. Copy the token

### Create the channel
New Channel → Public → pick a username

### Add bot as Admin
Channel settings → Administrators → Add your bot → grant **Post Messages**

### Find your Admin ID
Message **@userinfobot** → copy the numeric ID

---

## 🔧 Configuration

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Required
TOKEN=1234567890:ABCdef...
ADMIN_ID=123456789
CHANNEL_USERNAME=@my_jewelry_channel
GROQ_API_KEY=gsk_...
SPREADSHEET_NAME=Gold Products

# Optional
LOG_LEVEL=INFO
CACHE_TIME=300
PRICE_UPDATE_INTERVAL=3600   # 0 = disable auto update
AI_PROVIDER=groq
RECENT_MESSAGES_COUNT=6      # rolling window sent to the AI
SUMMARY_TRIGGER_MESSAGES=6   # regenerate summary every N messages
```

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TOKEN` | ✅ | — | Telegram bot token |
| `ADMIN_ID` | ✅ | — | Your numeric Telegram ID |
| `CHANNEL_USERNAME` | ✅ | — | Channel with `@` |
| `AI_PROVIDER` | ❌ | groq | `groq` \| `gemini` \| `openai` (see providers/) |
| `GROQ_API_KEY` | ✅ (if AI_PROVIDER=groq) | — | Groq API key |
| `SPREADSHEET_NAME` | ✅ | — | Exact spreadsheet name |
| `GROQ_MODEL` | ❌ | llama-3.3-70b-versatile | Text model |
| `GROQ_VISION_MODEL` | ❌ | llama-4-scout-17b-… | Vision model |
| `AI_TEMPERATURE` | ❌ | 0.7 | Sampling temperature |
| `AI_MAX_TOKENS` | ❌ | 1500 | Max tokens per AI response |
| `AI_RETRY_COUNT` | ❌ | 1 | Extra attempts on invalid JSON |
| `AI_TIMEOUT` | ❌ | 30 | Provider request timeout (seconds) |
| `RECENT_MESSAGES_COUNT` | ❌ | 6 | Messages kept in the rolling window |
| `SUMMARY_TRIGGER_MESSAGES` | ❌ | 6 | Regenerate summary every N messages |
| `SUMMARY_MAX_CHARS` | ❌ | 500 | Max length of the rolling summary |
| `NOTIFICATION_SIMILARITY_THRESHOLD` | ❌ | 0.55 | Min score (0..1) to trigger a restock notification |
| `LOG_LEVEL` | ❌ | INFO | DEBUG/INFO/WARNING/ERROR |
| `CACHE_TIME` | ❌ | 300 | Sheet cache TTL (seconds) |
| `PRICE_UPDATE_INTERVAL` | ❌ | 3600 | Auto gold price update interval (seconds, 0=off) |

---

## ▶️ Running the Bot

```bash
source venv/bin/activate
python main.py
```

Expected startup:
```
INFO | Logger initialised.
INFO | Initialising Gold Bot v2 …
INFO | All handlers registered.
INFO | Auto gold price update scheduled every 1.0 hour(s).
INFO | Bot is running — press Ctrl+C to stop.
```

---

## 💰 Updating Gold Price

### Automatic
The bot scrapes tgju.org automatically every `PRICE_UPDATE_INTERVAL` seconds.
After each update, the admin receives a Telegram message with the new price.
Set `PRICE_UPDATE_INTERVAL=0` in `.env` to disable.

### Manual — command line
```bash
python update_price.py
```

### Manual — admin panel
`/admin` → 🪙 بروزرسانی قیمت → **دریافت از tgju.org** or **ورود دستی**

---

## 🎛 Admin Panel

Send `/admin` to the bot in a private chat.

| Button | Function |
|--------|----------|
| 📦 محصولات | Browse all products (paginated) |
| 📢 انتشار محصول | Select → preview → publish to channel |
| ✏️ ویرایش محصول | Select → choose field → update |
| ➕ افزودن محصول | Step-by-step guided add (includes photo step) |
| ❌ حذف محصول | Select → confirm → delete |
| 🪙 بروزرسانی قیمت | Scrape tgju.org or enter manually |
| 📊 آمار | Product counts, stock, users, messages |
| 👥 مشتریان | View **every** saved customer, send manual restock notifications |
| 📦 درخواست‌های موجودی | View the back-in-stock waitlist (who's waiting, for what, since when) |
| 💬 پشتیبانی | View and reply to customer support requests |
| ⚙️ تنظیمات | Store name, phone, address, currency |
| 📁 پشتیبان‌گیری | Download JSON backup of all products |
| 🔄 همگام‌سازی شیت | **Instantly** reload any changes made in Google Sheets |

### Adding a Product Photo

When prompted for a photo during **➕ افزودن محصول** or editing a product's image field:
1. Simply **send a photo** in the Telegram chat with the bot
2. Bot saves the `telegram_file_id` to Google Sheets automatically
3. No external hosting required — Telegram stores the file

### Order Notifications (admin)

This project has no separate checkout/order step — a customer reaches
"ready to buy" by asking about one specific product and then triggering
the AI's escalate-to-support flow (🧑‍💼). When that happens while a
specific, **available** product is in focus, `ADMIN_ID` gets an extra,
detailed Telegram message (customer, product, product ID, weight,
calculated price, gold price used, timestamp) instead of the plain
support ping — the customer's own confirmation message is unchanged
either way. If escalation happens with no product in focus (or the
product turned out to be unavailable), admin gets the original, simpler
support notification instead.

---

## 👤 Customer Features

| Action | Result |
|--------|--------|
| Chat in Persian | AI assistant (Mona) responds |
| "انگشتر زنانه زیر ۵۰ میلیون" | Filtered ring list |
| "طلای سفید با الماس" | White gold diamond search |
| "هدیه برای خانمم" | Gift recommendations |
| Send a photo | AI finds similar products |
| Click 📈 on channel post | Live gold price popup |
| Click 💎 on channel post | Product price breakdown popup |
| Click 🤖 on channel post | Ask questions about that product |
| "عکسشو بفرست" | Bot sends product photo directly |
| Click 🔔 notification offer | Subscribe to restock alerts |
| `/products`, the `/start` button, or "لیست محصولاتتون رو بده" | Browsable product catalog |

---

## 📋 Product List (catalog browsing)

A read-only, tappable catalog for customers, styled exactly like the
admin's own product list — one product per row, ◀️ page ▶️ navigation —
reachable three ways:

1. **`/products` command** — always the full, unfiltered catalog
2. **The button under `/start`**
3. **Ordinary conversation** — saying something like "لیست محصولاتتون رو
   بده" or "کاتالوگتون رو میخوام" sends the same tappable list as a
   supplementary message, *without changing the AI's own reply at all*.
   Detection is a deterministic local keyword check (see
   `PRODUCT_LIST_KEYWORDS` in `config/config.py`) — no AI/prompt change.

**Category filtering** — "لیست انگشتراتونو بده" filters to rings only,
using whatever category the AI already extracted into the customer's
profile this conversation; saying "همه محصولاتتون" always forces the full
catalog regardless of context (`FULL_CATALOG_OVERRIDE_KEYWORDS`). The
active filter is remembered per-customer (`ConversationState.
product_list_category`) so paging through results keeps the same filter.

Tapping any product sends its photo, full details, and a live-calculated
price, with a **🤖 سوال درباره این محصول** button that hands off straight
into the existing focused-product AI conversation.

Only available (in-stock, active) products are ever shown — sold-out
items are silently excluded, exactly like the AI's own recommendations.

---

## 🔔 Restock Notifications

1. Customer chats about a preference (e.g. "انگشتر طلای سفید زیر ۳۰ میلیون")
2. Every 5 messages, bot offers: **"اطلاع بدم وقتی موجود شد؟"**
3. Customer taps **🔔 بله**
4. Their preferences are saved in the `customers` sheet with `notify=yes`
5. When admin uses **👥 مشتریان → ارسال نوتیف دستی** and selects a product,
   the bot automatically messages all matching opted-in customers

This is a **fuzzy, manual** system: admin picks a product and the bot
broadcasts to whoever's *stated preferences* look like a good fit.

---

## 📦 Back-In-Stock Requests

A second, separate system — **exact, fully automatic**, no admin action
needed. A request gets attached to one specific product_id via either path:

**Path A — focused product Q&A:**
1. Customer taps 🤖 on a channel post, then asks about that one product
2. If it's currently unavailable, the bot silently saves a waiting request

**Path B — ordinary free-text conversation** (no tap needed):
1. Customer describes what they want and says something like "خبر بده
   موجود شد" / "اطلاع بده" — the AI already extracts this as
   `wants_notification` (existing intent field, no prompt change)
2. The bot looks for the single best-matching **unavailable** product
   against the customer's profile (category/gender/gold_color/stone/
   budget), using the same weighted scoring as the existing manual-notify
   system, just inverted for availability — see
   `search_service.find_unavailable_match`
3. Only attaches to a specific product above `NOTIFICATION_SIMILARITY_THRESHOLD`
   confidence; below that, the want is still captured by the broader
   `notify_enabled` preference flag (nothing is lost either way)

Either path continues the same from here:

3. Whenever the admin edits that **exact product's** `stock` or `status`
   field (list, `/edit <id>`, or the field-option buttons — any path)
   and it becomes available again, every waiting customer is messaged
   automatically with a **🛍 مشاهده محصول** button
4. Each request is marked `notified` immediately after sending, so it is
   structurally impossible to notify the same customer twice for the
   same product
5. Admin can see the full waitlist any time via **📦 درخواست‌های موجودی**

**If no existing product confidently matches** (customer asked about a
product ID that doesn't exist at all, or there's nothing unavailable to
match against right now), the request is still saved — shown in the
panel as **❓ بدون کد** with a description built from whatever the
customer said — rather than being silently dropped. These can't be
auto-notified later (there's no real SKU to restock), but admin still
sees them and can follow up manually.

Unlike the preference-based system above, this one is about ONE specific
product a customer already showed interest in — not a broad preference
match.

---

## 💰 Price Formula

```
base_price    = weight × gold_price_per_gram
wage_amount   = base_price × (wage_percent / 100)
profit_amount = base_price × (profit_percent / 100)
total         = base_price + wage_amount + profit_amount
```

If `price_override` is set, it replaces the formula entirely.

---

## 🛠 Troubleshooting

| Problem | Solution |
|---------|----------|
| `SpreadsheetNotFound` | `SPREADSHEET_NAME` must match exactly; share sheet with service account |
| `WorksheetNotFound` | Tab names must be `products`, `settings`, `faq`, `customers` (lowercase) |
| Bot can't post to channel | Bot must be Administrator with "Post Messages" |
| Gold price stays 0 | Run `python update_price.py` or use admin panel → 🪙 |
| Product shows no photo | Admin must send a photo via the bot (Edit → تصویر محصول) |
| Sheet changes not visible | Use `/admin` → 🔄 همگام‌سازی شیت |
| `Forbidden` sending to customer | User must send `/start` to the bot first |
| Groq `AuthenticationError` | Check `GROQ_API_KEY` in `.env` |
| `ProviderError: Unknown AI_PROVIDER` | `AI_PROVIDER` must be `groq`, `gemini`, or `openai` (Gemini/OpenAI need their skeleton implemented first) |
| AI reply looks generic / ignores request | Check logs for "AI JSON parse/validation failed" — the model may need a stronger reminder; increase `AI_RETRY_COUNT` |
| Customer preferences "forgotten" after restart | Confirm `customers` sheet exists and the service account has Editor access — profile reloads from there on a fresh session |
| Auto price update not running | Check `PRICE_UPDATE_INTERVAL` > 0 in `.env` |
| `customers` sheet not created | Send at least one message as a customer to trigger auto-creation |

---

## 🏗 Architecture Notes

- **Google Sheets calls** are synchronous (gspread); run in `asyncio.to_thread()`.
- **Groq** uses `AsyncGroq` — fully non-blocking.
- **Conversation memory** is a list of `{role, content}` dicts per user, trimmed to `CONV_HISTORY_PAIRS * 2` messages.
- **Sheet cache** has a configurable TTL (default 5 min). Use 🔄 in admin panel to force instant reload.
- **Telegram file_id** values are permanent for the bot that received them. If you change the bot token, you may need to re-upload product photos.

---

## 📄 License

MIT
