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

Created automatically on first customer message. Headers:

```
user_id | name | category | gold_color | stone | max_weight |
max_budget | gender | style | notes | notify | last_seen | updated_at
```

### Share with Service Account

**Share → paste `client_email` from `service_account.json` → Editor → Send**

---

## 🤖 Groq Setup

1. Go to [console.groq.com](https://console.groq.com)
2. Sign up (free)
3. **API Keys → Create API Key**
4. Copy the key (starts with `gsk_`)

Default model: `llama-3.3-70b-versatile`
Vision model: `meta-llama/llama-4-scout-17b-16e-instruct`

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
CONV_HISTORY_PAIRS=10        # AI memory depth (pairs of messages)
```

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TOKEN` | ✅ | — | Telegram bot token |
| `ADMIN_ID` | ✅ | — | Your numeric Telegram ID |
| `CHANNEL_USERNAME` | ✅ | — | Channel with `@` |
| `GROQ_API_KEY` | ✅ | — | Groq API key |
| `SPREADSHEET_NAME` | ✅ | — | Exact spreadsheet name |
| `GROQ_MODEL` | ❌ | llama-3.3-70b-versatile | Text model |
| `GROQ_VISION_MODEL` | ❌ | llama-4-scout-17b-… | Vision model |
| `LOG_LEVEL` | ❌ | INFO | DEBUG/INFO/WARNING/ERROR |
| `CACHE_TIME` | ❌ | 300 | Sheet cache TTL (seconds) |
| `PRICE_UPDATE_INTERVAL` | ❌ | 3600 | Auto gold price update interval (seconds, 0=off) |
| `CONV_HISTORY_PAIRS` | ❌ | 10 | Messages kept in AI memory per user |

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
| 👥 مشتریان | View wishlists, send manual restock notifications |
| 💬 پشتیبانی | View and reply to customer support requests |
| ⚙️ تنظیمات | Store name, phone, address, currency |
| 📁 پشتیبان‌گیری | Download JSON backup of all products |
| 🔄 همگام‌سازی شیت | **Instantly** reload any changes made in Google Sheets |

### Adding a Product Photo

When prompted for a photo during **➕ افزودن محصول** or editing a product's image field:
1. Simply **send a photo** in the Telegram chat with the bot
2. Bot saves the `telegram_file_id` to Google Sheets automatically
3. No external hosting required — Telegram stores the file

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

---

## 🔔 Restock Notifications

1. Customer chats about a preference (e.g. "انگشتر طلای سفید زیر ۳۰ میلیون")
2. Every 5 messages, bot offers: **"اطلاع بدم وقتی موجود شد؟"**
3. Customer taps **🔔 بله**
4. Their preferences are saved in the `customers` sheet with `notify=yes`
5. When admin uses **👥 مشتریان → ارسال نوتیف دستی** and selects a product,
   the bot automatically messages all matching opted-in customers

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
