"""
Gold Bot v2 – AI Data Models
==============================
Typed Pydantic models used everywhere the AI layer or search layer produces
or consumes structured data. No project code should pass around loose
dictionaries for these concepts — always construct/validate one of these.

Models
------
ShoppingStage, Urgency, Emotion   – enums describing customer state
IntentExtraction                  – signals extracted from ONE message
CustomerProfile                   – cumulative, persisted per-user profile
ProductContext                    – a scored product shown to the AI
SearchQuery                       – parameters used to rank products
SearchResult                      – ranked products + the query that produced them
ConversationSummary               – rolling summary of a conversation
NotificationRequest               – one restock-notification decision
AIResponse                        – the full structured output of one AI turn
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ── Enums ─────────────────────────────────────────────────────────────────────

class ShoppingStage(str, Enum):
    BROWSING      = "browsing"
    COMPARING     = "comparing"
    READY_TO_BUY  = "ready_to_buy"
    NEED_ADVICE   = "need_advice"
    GIFT_SHOPPING = "gift_shopping"
    JUST_ASKING   = "just_asking"


class Urgency(str, Enum):
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"


class Emotion(str, Enum):
    HAPPY      = "happy"
    NEUTRAL    = "neutral"
    EXCITED    = "excited"
    FRUSTRATED = "frustrated"
    UNCERTAIN  = "uncertain"


# ── Per-message extraction ────────────────────────────────────────────────────

class IntentExtraction(BaseModel):
    """
    Structured signals the AI extracts from a SINGLE customer message.
    Every field is optional/defaulted so a failed or partial extraction
    never crashes the caller — see utils/json_utils + AIService retry logic.
    """
    category:       Optional[str]   = None
    gender:         Optional[str]   = None
    gold_color:     Optional[str]   = None
    stone:          Optional[str]   = None

    # Budget values are RAW — exactly the number the customer said, in
    # whichever currency `budget_currency` names (NOT pre-converted by the
    # AI). Actual Toman<->Rial normalization into the store's configured
    # currency happens once, deterministically, in
    # services.price_service.normalize_intent_budget() — never trust an
    # LLM to reliably do the ×10/÷10 arithmetic itself.
    max_budget:     Optional[float] = None
    min_budget:     Optional[float] = None
    max_weight:     Optional[float] = None
    min_weight:     Optional[float] = None
    style_keywords: list[str]       = Field(default_factory=list)
    occasion:       Optional[str]   = None

    # Currency awareness (Part 1/2) — canonical codes only: "IRT" (Toman)
    # or "IRR" (Rial). None means the customer did NOT explicitly name a
    # currency for their budget; callers must then assume the store's
    # configured currency (never guess a specific one).
    budget_currency:     Optional[str] = None
    # Set only when the customer explicitly asked to see PRICES in a
    # different currency than the store default for this reply
    # (e.g. "به تومان بگو") — a per-turn display override, not persisted.
    price_currency:       Optional[str] = None
    # Confidence (0..1) in the extracted budget_currency. Should be 1.0
    # whenever the customer used an explicit currency word; lower only if
    # inferred indirectly. budget_currency should simply be left null
    # rather than set with low confidence when genuinely ambiguous.
    currency_confidence: float = Field(1.0, ge=0.0, le=1.0)

    # Only set when the model is confident — None means "no signal this turn"
    # so profile merging never overwrites a known stage/urgency/emotion with
    # a low-confidence guess.
    shopping_stage: Optional[ShoppingStage] = None
    urgency:        Optional[Urgency]       = None
    emotion:        Optional[Emotion]       = None

    purchase_readiness: int = Field(0, ge=0, le=100)
    interest_level:     int = Field(0, ge=0, le=100)
    wants_notification: bool = False

    @field_validator("purchase_readiness", "interest_level", mode="before")
    @classmethod
    def _clamp_0_100(cls, v):
        try:
            v = int(v)
        except (TypeError, ValueError):
            return 0
        return max(0, min(100, v))

    @field_validator("currency_confidence", mode="before")
    @classmethod
    def _clamp_0_1(cls, v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return 1.0
        return max(0.0, min(1.0, v))


# ── Cumulative per-user profile ───────────────────────────────────────────────

class CustomerProfile(BaseModel):
    """
    Cumulative, persisted profile for one Telegram user.
    Never overwritten wholesale — always merged via merge_intent(), which
    only replaces fields the latest message actually spoke to and leaves
    everything else untouched.
    """
    user_id: int = 0
    name:    str = ""

    category:       Optional[str]   = None
    gender:         Optional[str]   = None
    gold_color:     Optional[str]   = None
    stone:          Optional[str]   = None
    max_budget:     Optional[float] = None
    min_budget:     Optional[float] = None
    max_weight:     Optional[float] = None
    min_weight:     Optional[float] = None
    style_keywords: list[str]       = Field(default_factory=list)
    occasion:       Optional[str]   = None

    shopping_stage: ShoppingStage = ShoppingStage.BROWSING
    interest_level: int           = 0
    notify_enabled: bool          = False

    last_seen:  str = ""
    updated_at: str = ""

    def merge_intent(self, intent: "IntentExtraction") -> "CustomerProfile":
        """
        Return a NEW CustomerProfile with intent's non-empty fields merged
        in on top of this one. Cumulative, never destructive:
        - Explicit new values REPLACE only their own field.
        - Anything the message didn't mention is preserved unchanged.
        - style_keywords are UNIONED (deduplicated), never replaced wholesale.
        - interest_level only ever increases (max of old vs new).
        """
        data = self.model_dump()

        if intent.category:
            data["category"] = intent.category
        if intent.gender:
            data["gender"] = intent.gender
        if intent.gold_color:
            data["gold_color"] = intent.gold_color
        if intent.stone:
            data["stone"] = intent.stone
        if intent.max_budget is not None:
            data["max_budget"] = intent.max_budget
        if intent.min_budget is not None:
            data["min_budget"] = intent.min_budget
        if intent.max_weight is not None:
            data["max_weight"] = intent.max_weight
        if intent.min_weight is not None:
            data["min_weight"] = intent.min_weight
        if intent.occasion:
            data["occasion"] = intent.occasion
        if intent.style_keywords:
            merged = list(dict.fromkeys([*self.style_keywords, *intent.style_keywords]))
            data["style_keywords"] = merged[:8]
        if intent.shopping_stage is not None:
            data["shopping_stage"] = intent.shopping_stage
        if intent.wants_notification:
            data["notify_enabled"] = True

        data["interest_level"] = max(self.interest_level, intent.interest_level)

        return CustomerProfile.model_validate(data)

    def summary_text(self, currency: str = "تومان") -> str:
        """Human-readable (Persian) one-liner for embedding in AI prompts."""
        parts: list[str] = []
        if self.max_budget:
            parts.append(f"بودجه تا {self.max_budget:,.0f} {currency}")
        if self.min_budget:
            parts.append(f"بودجه از {self.min_budget:,.0f} {currency}")
        if self.gender:
            parts.append(f"جنسیت: {self.gender}")
        if self.category:
            parts.append(f"دسته: {self.category}")
        if self.gold_color:
            parts.append(f"رنگ طلا: {self.gold_color}")
        if self.stone:
            parts.append(f"سنگ: {self.stone}")
        if self.max_weight:
            parts.append(f"وزن حداکثر {self.max_weight} گرم")
        if self.occasion:
            parts.append(f"مناسبت: {self.occasion}")
        if self.style_keywords:
            parts.append(f"سبک: {', '.join(self.style_keywords)}")
        parts.append(f"مرحله خرید: {self.shopping_stage.value}")
        return " | ".join(parts) if parts else "بدون ترجیح خاص"

    def has_any_preference(self) -> bool:
        return any([
            self.category, self.gender, self.gold_color, self.stone,
            self.max_budget, self.min_budget, self.max_weight, self.min_weight,
            self.style_keywords, self.occasion,
        ])


# ── Search ────────────────────────────────────────────────────────────────────

class SearchQuery(BaseModel):
    """Parameters used to score and rank products for one search."""
    category:       Optional[str]   = None
    gender:         Optional[str]   = None
    gold_color:     Optional[str]   = None
    stone:          Optional[str]   = None
    max_budget:     Optional[float] = None
    min_budget:     Optional[float] = None
    max_weight:     Optional[float] = None
    min_weight:     Optional[float] = None
    style_keywords: list[str]       = Field(default_factory=list)
    occasion:       Optional[str]   = None
    sort_by:        str             = "relevance"


class ProductContext(BaseModel):
    """A single product as shown to the AI, including its relevance score."""
    id:              int
    name:            str
    category:        str   = ""
    gender:          str   = ""
    gold_color:      str   = ""
    stone:           str   = ""
    weight:          float = 0.0
    price:           float = 0.0
    stock:           int   = 0
    relevance_score: float = 0.0

    def as_ai_line(self, currency: str = "") -> str:
        """
        Render this product as one context line for the AI prompt.

        Args:
            currency: Resolved store currency label (see
                      services.price_service.currency_label). Must be
                      passed explicitly by the caller — this method never
                      assumes a currency, so the AI is never shown a price
                      with the wrong (or a hardcoded) unit attached.
        """
        price_part = f"{self.price:,.0f} {currency}".strip() if currency else f"{self.price:,.0f}"
        return (
            f"ID:{self.id} | {self.name} | دسته:{self.category} | جنسیت:{self.gender} | "
            f"رنگ:{self.gold_color} | سنگ:{self.stone or 'ندارد'} | وزن:{self.weight}گ | "
            f"قیمت:{price_part} | موجودی:{self.stock}"
        )


class SearchResult(BaseModel):
    products:      list[ProductContext] = Field(default_factory=list)
    total_matched: int                  = 0
    query:         SearchQuery          = Field(default_factory=SearchQuery)


# ── Conversation memory ───────────────────────────────────────────────────────

class ConversationSummary(BaseModel):
    """Rolling summary of a conversation, regenerated every N messages."""
    user_id:               int = 0
    summary_text:          str = ""
    messages_since_update: int = 0
    last_updated:          str = ""


# ── Notifications ─────────────────────────────────────────────────────────────

class NotificationRequest(BaseModel):
    user_id:           int
    product_id:        int
    reason:            str   = ""
    similarity_score:  float = 0.0


# ── AI turn output ─────────────────────────────────────────────────────────────

class AIResponse(BaseModel):
    """
    The complete structured output of ONE AI turn — a single API call
    returns both the natural-language reply AND the extracted intent,
    avoiding a second (costly) extraction call per message.
    """
    reply:              str              = ""
    needs_support:      bool             = False
    image_product_ids:  list[int]        = Field(default_factory=list)
    intent:             IntentExtraction = Field(default_factory=IntentExtraction)
