"""
Gold Bot v2 – Gold Service
============================
Provides the current gold price and last-update timestamp read from the
settings sheet. Also exposes scraping logic reused by update_price.py.
All write operations go through SheetService.
"""

import logging
import re
import time as _time

import requests
from bs4 import BeautifulSoup

from services.sheet_service import SheetService

logger = logging.getLogger(__name__)

TGJU_URL        = "https://www.tgju.org/"
MARKET_ROW_ID   = "geram18"
REQUEST_TIMEOUT = 20
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.7",
}


class GoldService:
    def __init__(self, sheet_service: SheetService) -> None:
        self._sheet = sheet_service

    def get_gold_price(self) -> float:
        settings = self._sheet.get_settings()
        raw = str(settings.get("gold_price", "0") or "0").replace(",", "").strip()
        try:
            return float(raw)
        except ValueError:
            return 0.0

    def get_last_update(self) -> str:
        settings = self._sheet.get_settings()
        return settings.get("last_update", "نامشخص")

    def update_gold_price(self, price: float) -> None:
        import datetime
        self._sheet.update_setting("gold_price", str(price))
        self._sheet.update_setting(
            "last_update",
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        )
        logger.info("Gold price updated to %.0f.", price)

    # ── Scraping (reused by update_price.py and admin panel) ─────────────────

    @staticmethod
    def scrape_gold_price() -> float:
        """
        Scrape 18-karat gold price from tgju.org.
        Returns the price as a float (Toman/gram).
        Raises RuntimeError on parse failure.
        """
        logger.info("Scraping gold price from %s …", TGJU_URL)
        resp = requests.get(TGJU_URL, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        row = soup.find(attrs={"data-market-row": MARKET_ROW_ID})
        if row is None:
            raise RuntimeError(f"data-market-row='{MARKET_ROW_ID}' not found on page.")

        cell = (
            row.find("td", attrs={"data-col": "p"})
            or row.find("td", class_="nf")
        )
        if cell is None:
            tds = row.find_all("td")
            cell = tds[1] if len(tds) >= 2 else None
        if cell is None:
            raise RuntimeError("Price cell not found in geram18 row.")

        raw = cell.get_text(strip=True)
        # Normalise Persian/Arabic digits and separators
        for p, a, i in zip("۰۱۲۳۴۵۶۷۸۹", "٠١٢٣٤٥٦٧٨٩", "0123456789"):
            raw = raw.replace(p, i).replace(a, i)
        raw = re.sub(r"[,،٬\s\u200c]", "", raw)

        try:
            price = float(raw)
        except ValueError:
            raise RuntimeError(f"Cannot parse '{cell.get_text(strip=True)}' as a number.")

        if price <= 0:
            raise RuntimeError(f"Scraped price {price} is not positive.")

        logger.info("Scraped gold price: %.0f Toman/gram", price)
        return price

    @staticmethod
    def scrape_with_retry(max_retries: int = 3, delay: int = 5) -> float:
        last_exc: Exception = RuntimeError("No attempt made.")
        for attempt in range(1, max_retries + 1):
            try:
                return GoldService.scrape_gold_price()
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries:
                    logger.warning("Attempt %d/%d failed: %s. Retrying …", attempt, max_retries, exc)
                    _time.sleep(delay)
        raise last_exc
