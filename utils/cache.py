"""
Gold Bot v2 – In-Memory Cache
================================
Provides:
    TTLCache            – generic key/value store with expiry
    ConversationState   – per-user chat state (Groq messages history + preferences)
    AdminState          – admin panel flow state (multi-step actions)
    BotStats            – simple runtime statistics (users, messages)
    Cache               – top-level singleton that holds all of the above
"""

import logging
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── TTLCache ──────────────────────────────────────────────────────────────────

class TTLCache:
    """Thread-safe key/value cache with per-entry TTL."""

    def __init__(self, default_ttl: int = 300) -> None:
        self._store: dict[str, tuple[Any, float]] = {}
        self._ttl = default_ttl
        self._lock = Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        with self._lock:
            ttl = ttl if ttl is not None else self._ttl
            self._store[key] = (value, time.monotonic() + ttl)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def purge_expired(self) -> int:
        now = time.monotonic()
        with self._lock:
            expired = [k for k, (_, exp) in self._store.items() if now > exp]
            for k in expired:
                del self._store[k]
        return len(expired)

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


# ── Conversation State ─────────────────────────────────────────────────────────

@dataclass
class Preferences:
    """Customer preferences extracted from conversation."""
    budget:         Optional[float] = None
    gender:         Optional[str]   = None
    gold_color:     Optional[str]   = None
    stone:          Optional[str]   = None
    category:       Optional[str]   = None
    max_weight:     Optional[float] = None
    style_keywords: list[str]       = field(default_factory=list)
    occasion:       Optional[str]   = None

    def to_text(self) -> str:
        parts = []
        if self.budget:
            parts.append(f"بودجه تا {self.budget:,.0f} تومان")
        if self.gender:
            parts.append(f"جنسیت: {self.gender}")
        if self.gold_color:
            parts.append(f"رنگ طلا: {self.gold_color}")
        if self.stone:
            parts.append(f"سنگ: {self.stone}")
        if self.category:
            parts.append(f"دسته: {self.category}")
        if self.max_weight:
            parts.append(f"وزن حداکثر {self.max_weight} گرم")
        if self.occasion:
            parts.append(f"مناسبت: {self.occasion}")
        if self.style_keywords:
            parts.append(f"سبک: {', '.join(self.style_keywords)}")
        return " | ".join(parts) if parts else "بدون ترجیح خاص"


@dataclass
class ConversationState:
    """
    Per-user state stored for the lifetime of a conversation.
    messages: list of {role, content} dicts — the Groq chat history.
    """
    user_id:            int
    messages:           list          = field(default_factory=list)   # Groq chat history
    response_count:     int           = 0
    preferences:        Preferences   = field(default_factory=Preferences)
    support_requested:  bool          = False
    current_product_id: Optional[int] = None   # "Ask about this product" context
    last_activity:      float         = field(default_factory=time.monotonic)

    def touch(self) -> None:
        self.last_activity = time.monotonic()


# ── Admin Flow State ───────────────────────────────────────────────────────────

@dataclass
class AdminState:
    action:         str           = ""
    step:           str           = ""
    product_id:     Optional[int] = None
    field_name:     Optional[str] = None
    reply_user_id:  Optional[int] = None
    list_page:      int           = 0
    add_data:       dict          = field(default_factory=dict)
    last_activity:  float         = field(default_factory=time.monotonic)

    def clear(self) -> None:
        self.action = ""
        self.step = ""
        self.product_id = None
        self.field_name = None
        self.reply_user_id = None
        self.list_page = 0
        self.add_data = {}
        self.last_activity = time.monotonic()


# ── Bot Statistics ─────────────────────────────────────────────────────────────

@dataclass
class BotStats:
    unique_users: set = field(default_factory=set)
    daily_msgs:   dict = field(default_factory=dict)

    def record_message(self, user_id: int) -> None:
        import datetime
        self.unique_users.add(user_id)
        today = datetime.date.today().isoformat()
        self.daily_msgs[today] = self.daily_msgs.get(today, 0) + 1

    def today_count(self) -> int:
        import datetime
        return self.daily_msgs.get(datetime.date.today().isoformat(), 0)


# ── Top-Level Cache Singleton ─────────────────────────────────────────────────

class Cache:
    def __init__(self, sheet_ttl: int, conv_ttl: int, admin_ttl: int) -> None:
        self.sheet_cache   = TTLCache(default_ttl=sheet_ttl)
        self.conv_ttl      = conv_ttl
        self.admin_ttl     = admin_ttl
        self._conversations: dict[int, ConversationState] = {}
        self._admin_state:   AdminState                   = AdminState()
        self.support_queue:  dict[int, list[dict]]        = {}
        self.stats:          BotStats                     = BotStats()
        self._lock = Lock()

    def invalidate_sheets(self) -> None:
        self.sheet_cache.clear()
        logger.info("Sheet cache invalidated.")

    # ── Conversation ──────────────────────────────────────────────────────────

    def get_conversation(self, user_id: int) -> ConversationState:
        with self._lock:
            state = self._conversations.get(user_id)
            if state is None:
                state = ConversationState(user_id=user_id)
                self._conversations[user_id] = state
            elif time.monotonic() - state.last_activity > self.conv_ttl:
                state = ConversationState(user_id=user_id)
                self._conversations[user_id] = state
            return state

    def save_conversation(self, state: ConversationState) -> None:
        state.touch()
        with self._lock:
            self._conversations[state.user_id] = state

    def reset_conversation(self, user_id: int) -> None:
        with self._lock:
            self._conversations[user_id] = ConversationState(user_id=user_id)

    # ── Admin state ───────────────────────────────────────────────────────────

    def get_admin_state(self) -> AdminState:
        with self._lock:
            if time.monotonic() - self._admin_state.last_activity > self.admin_ttl:
                self._admin_state.clear()
            return self._admin_state

    def save_admin_state(self, state: AdminState) -> None:
        state.last_activity = time.monotonic()
        with self._lock:
            self._admin_state = state

    def clear_admin_state(self) -> None:
        with self._lock:
            self._admin_state.clear()

    # ── Support queue ─────────────────────────────────────────────────────────

    def add_support_message(self, user_id: int, role: str, text: str) -> None:
        import datetime
        with self._lock:
            if user_id not in self.support_queue:
                self.support_queue[user_id] = []
            self.support_queue[user_id].append({
                "role": role,
                "text": text,
                "time": datetime.datetime.now().strftime("%H:%M"),
            })
            self.support_queue[user_id] = self.support_queue[user_id][-20:]

    def get_support_users(self) -> list[int]:
        with self._lock:
            return list(self.support_queue.keys())

    def clear_support(self, user_id: int) -> None:
        with self._lock:
            self.support_queue.pop(user_id, None)
