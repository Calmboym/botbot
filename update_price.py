"""
Gold Bot v2 – Gold Price Updater
==================================
Standalone script.  Run manually or schedule via cron / Task Scheduler.

Usage:
    python update_price.py

Cron example (every hour):
    0 * * * * cd /path/to/gold_bot_v2 && venv/bin/python update_price.py >> logs/price_update.log 2>&1
"""

import logging
import sys
import time

import requests

from config.config import CACHE_TTL
from services.gold_service import GoldService
from services.sheet_service import SheetService
from utils.cache import TTLCache
from utils.logger import setup_logger

setup_logger()
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("=" * 55)
    logger.info("Gold Price Updater — starting")
    logger.info("=" * 55)

    # Build minimal service stack (no Telegram bot needed)
    cache         = TTLCache(default_ttl=CACHE_TTL)
    sheet_service = SheetService(cache)
    gold_service  = GoldService(sheet_service)

    # Read current price for comparison
    try:
        old_price = gold_service.get_gold_price()
        old_upd   = gold_service.get_last_update()
        logger.info("Current price in sheet: %s  (updated: %s)", f"{old_price:,.0f}", old_upd)
    except Exception as exc:
        logger.warning("Could not read current price: %s", exc)
        old_price = None

    # Scrape new price (with retries)
    try:
        new_price = GoldService.scrape_with_retry(max_retries=3, delay=5)
    except requests.exceptions.ConnectionError:
        logger.error("❌  Network error — cannot reach tgju.org.")
        sys.exit(1)
    except requests.exceptions.Timeout:
        logger.error("❌  Request timed out.")
        sys.exit(1)
    except requests.exceptions.HTTPError as exc:
        logger.error("❌  HTTP error: %s", exc)
        sys.exit(1)
    except RuntimeError as exc:
        logger.error("❌  Scraping error: %s", exc)
        sys.exit(1)
    except Exception as exc:
        logger.error("❌  Unexpected error: %s", exc, exc_info=True)
        sys.exit(1)

    # Write to Google Sheets
    try:
        gold_service.update_gold_price(new_price)
    except Exception as exc:
        logger.error("❌  Failed to update Google Sheets: %s", exc, exc_info=True)
        sys.exit(1)

    # Summary
    if old_price and old_price > 0:
        diff   = new_price - old_price
        pct    = (diff / old_price) * 100
        arrow  = "▲" if diff >= 0 else "▼"
        change = f"  ({arrow} {abs(diff):,.0f} / {pct:+.2f}%)"
    else:
        change = ""

    logger.info("✅  %s → %s Toman/gram%s", f"{old_price:,.0f}" if old_price else "?", f"{new_price:,.0f}", change)
    logger.info("=" * 55)
    logger.info("Done.")
    logger.info("=" * 55)


if __name__ == "__main__":
    main()
