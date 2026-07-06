"""
Gold Bot v2 – Conversation Summary Service
=============================================
Keeps a short rolling summary of each conversation instead of ever sending
the full message history to the AI. The summary is regenerated via a
cheap, low-token AI call every SUMMARY_TRIGGER_MESSAGES messages.

This is provider-independent: it depends only on BaseAIProvider.
"""

import datetime
import logging

from config.config import SUMMARY_MAX_CHARS, SUMMARY_TRIGGER_MESSAGES
from models.ai_models import ConversationSummary
from providers.base_provider import BaseAIProvider, ProviderError

logger = logging.getLogger(__name__)


class SummaryService:
    def __init__(self, provider: BaseAIProvider) -> None:
        self._provider = provider

    async def maybe_update(
        self,
        summary: ConversationSummary,
        recent_messages: list[dict],
    ) -> ConversationSummary:
        """
        If enough new messages have accumulated since the last summary,
        regenerate it. Returns the (possibly unchanged) ConversationSummary.

        Never raises — a failed summary update just keeps the previous
        summary and logs a warning; it never breaks the chat flow.
        """
        if summary.messages_since_update < SUMMARY_TRIGGER_MESSAGES:
            return summary
        if not recent_messages:
            return summary

        history_text = "\n".join(
            f"{'مشتری' if m.get('role') == 'user' else 'مونا'}: {m.get('content')}"
            for m in recent_messages
            if isinstance(m.get("content"), str)
        )
        if not history_text.strip():
            return summary

        prompt = (
            f"خلاصه قبلی مکالمه:\n{summary.summary_text or '(ندارد)'}\n\n"
            f"پیام‌های اخیر:\n{history_text}\n\n"
            f"یک خلاصه کوتاه فارسی (حداکثر {SUMMARY_MAX_CHARS} کاراکتر) از کل روند "
            f"مکالمه تا این لحظه بنویس — نیازها، ترجیحات و وضعیت فعلی مشتری را در "
            f"چند جمله خلاصه کن. فقط متن خلاصه را بنویس، بدون مقدمه یا توضیح اضافه."
        )

        try:
            text = await self._provider.generate(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=300,
                json_mode=False,
            )
            summary.summary_text = text.strip()[:SUMMARY_MAX_CHARS]
            summary.messages_since_update = 0
            summary.last_updated = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            logger.info(
                "Conversation summary updated for user %d (%d chars).",
                summary.user_id, len(summary.summary_text),
            )
        except ProviderError as exc:
            logger.warning(
                "Summary update failed for user %d, keeping previous summary: %s",
                summary.user_id, exc,
            )

        return summary
