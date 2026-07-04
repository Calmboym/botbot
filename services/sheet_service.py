"""
Gold Bot v2 – Sheet Service
=============================
Single point of access for all Google Sheets operations.
Uses a TTLCache to avoid redundant API calls.
All methods are synchronous; call via asyncio.to_thread() from async handlers.
"""

import json
import logging
import datetime
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

from config.config import (
    GOOGLE_SCOPES, SERVICE_ACCOUNT_FILE, SPREADSHEET_NAME,
    PRODUCTS_SHEET, SETTINGS_SHEET, FAQ_SHEET,
)
from models.product import Product
from utils.cache import TTLCache

logger = logging.getLogger(__name__)

_CACHE_PRODUCTS = "sheet:products"
_CACHE_SETTINGS = "sheet:settings"
_CACHE_FAQS     = "sheet:faqs"


class SheetService:
    def __init__(self, cache: TTLCache) -> None:
        self._cache = cache

    # ── Private helpers ───────────────────────────────────────────────────────

    def _client(self) -> gspread.Client:
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=GOOGLE_SCOPES)
        return gspread.Client(auth=creds)

    def _spreadsheet(self) -> gspread.Spreadsheet:
        try:
            return self._client().open(SPREADSHEET_NAME)
        except gspread.exceptions.SpreadsheetNotFound:
            logger.error("Spreadsheet '%s' not found.", SPREADSHEET_NAME)
            raise

    def _worksheet(self, name: str) -> gspread.Worksheet:
        try:
            return self._spreadsheet().worksheet(name)
        except gspread.exceptions.WorksheetNotFound:
            logger.error("Worksheet '%s' not found.", name)
            raise

    def _col_index(self, ws: gspread.Worksheet, col_name: str) -> int:
        headers = ws.row_values(1)
        try:
            return headers.index(col_name) + 1
        except ValueError:
            raise RuntimeError(f"Column '{col_name}' not found. Headers: {headers}")

    def _find_product_row(self, ws: gspread.Worksheet, product_id: int) -> tuple[int, dict]:
        """Return (1-based row index, record dict) or raise ValueError."""
        records = ws.get_all_records(numericise_ignore=["all"])
        for offset, rec in enumerate(records):
            try:
                if int(str(rec.get("id", "") or "0").strip()) == product_id:
                    return offset + 2, rec
            except (ValueError, TypeError):
                continue
        raise ValueError(f"Product id={product_id} not found in '{PRODUCTS_SHEET}'.")

    # ── Products ──────────────────────────────────────────────────────────────

    def get_products(self) -> list[Product]:
        cached = self._cache.get(_CACHE_PRODUCTS)
        if cached is not None:
            return cached
        logger.debug("Fetching products from Sheets …")
        ws = self._worksheet(PRODUCTS_SHEET)
        records = ws.get_all_records(numericise_ignore=["all"])
        products = [Product.from_dict(r) for r in records]
        self._cache.set(_CACHE_PRODUCTS, products)
        logger.info("Loaded %d products from Sheets.", len(products))

        available_count = sum(1 for p in products if p.is_available)
        if products and available_count == 0:
            logger.warning(
                "⚠️  %d products loaded but ZERO are marked available. "
                "Check the 'status' column (must be exactly 'active') and the "
                "'stock' column (must be > 0) in the '%s' sheet. "
                "Customers will see no search results until this is fixed.",
                len(products), PRODUCTS_SHEET,
            )
        return products

    def get_product_by_id(self, product_id: int) -> Optional[Product]:
        for p in self.get_products():
            if p.id == product_id:
                return p
        return None

    def update_product_field(self, product_id: int, field_name: str, value: object) -> None:
        logger.info("Updating product %d field '%s' = %r", product_id, field_name, value)
        ws = self._worksheet(PRODUCTS_SHEET)
        row_idx, _ = self._find_product_row(ws, product_id)
        col_idx = self._col_index(ws, field_name)
        # Also update updated_at
        try:
            upd_col = self._col_index(ws, "updated_at")
            ws.update_cell(row_idx, upd_col, datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
        except Exception:
            pass
        ws.update_cell(row_idx, col_idx, str(value) if value is not None else "")
        self._cache.delete(_CACHE_PRODUCTS)

    def update_published_message_id(self, product_id: int, message_id: int) -> None:
        self.update_product_field(product_id, "published_message_id", message_id)

    def add_product(self, data: dict) -> int:
        """Append a new product row and return the new numeric ID."""
        ws = self._worksheet(PRODUCTS_SHEET)
        headers = ws.row_values(1)
        records = ws.get_all_records(numericise_ignore=["all"])

        max_id = 0
        for r in records:
            try:
                rid = int(str(r.get("id", 0) or 0).strip())
                max_id = max(max_id, rid)
            except (ValueError, TypeError):
                pass
        new_id = max_id + 1

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        data["id"]         = new_id
        data["created_at"] = data.get("created_at", now)
        data["updated_at"] = now
        data.setdefault("status", "active")
        data.setdefault("stock", 1)

        row = [str(data.get(h, "") or "") for h in headers]
        ws.append_row(row, value_input_option="USER_ENTERED")
        self._cache.delete(_CACHE_PRODUCTS)
        logger.info("Added product id=%d '%s'.", new_id, data.get("name", ""))
        return new_id

    def delete_product(self, product_id: int) -> None:
        logger.info("Deleting product id=%d.", product_id)
        ws = self._worksheet(PRODUCTS_SHEET)
        row_idx, _ = self._find_product_row(ws, product_id)
        ws.delete_rows(row_idx)
        self._cache.delete(_CACHE_PRODUCTS)

    # ── Settings ──────────────────────────────────────────────────────────────

    def get_settings(self) -> dict[str, str]:
        cached = self._cache.get(_CACHE_SETTINGS)
        if cached is not None:
            return cached
        logger.debug("Fetching settings from Sheets …")
        ws = self._worksheet(SETTINGS_SHEET)
        records = ws.get_all_records(numericise_ignore=["all"])
        settings = {
            str(r.get("key", "") or "").strip(): str(r.get("value", "") or "").strip()
            for r in records if r.get("key")
        }
        self._cache.set(_CACHE_SETTINGS, settings)
        return settings

    def update_setting(self, key: str, value: str) -> None:
        logger.info("Updating setting '%s' = %r", key, value)
        ws = self._worksheet(SETTINGS_SHEET)
        records = ws.get_all_records(numericise_ignore=["all"])
        headers = ws.row_values(1)
        val_col = (headers.index("value") + 1) if "value" in headers else 2

        for offset, rec in enumerate(records):
            if str(rec.get("key", "") or "").strip() == key:
                ws.update_cell(offset + 2, val_col, value)
                self._cache.delete(_CACHE_SETTINGS)
                return
        ws.append_row([key, value])
        self._cache.delete(_CACHE_SETTINGS)

    # ── FAQs ──────────────────────────────────────────────────────────────────

    def get_faqs(self) -> list[dict]:
        cached = self._cache.get(_CACHE_FAQS)
        if cached is not None:
            return cached
        logger.debug("Fetching FAQs from Sheets …")
        ws = self._worksheet(FAQ_SHEET)
        records = ws.get_all_records(numericise_ignore=["all"])
        self._cache.set(_CACHE_FAQS, records)
        return records

    # ── Statistics ────────────────────────────────────────────────────────────

    def get_statistics(self) -> dict:
        products = self.get_products()
        total      = len(products)
        active     = sum(1 for p in products if p.status == "active")
        published  = sum(1 for p in products if p.is_published)
        sold       = sum(1 for p in products if p.status == "sold")
        draft      = sum(1 for p in products if p.status == "draft")
        no_stock   = sum(1 for p in products if p.status == "active" and p.stock == 0)

        categories: dict[str, int] = {}
        for p in products:
            if p.category:
                categories[p.category] = categories.get(p.category, 0) + 1

        return {
            "total":      total,
            "active":     active,
            "published":  published,
            "sold":       sold,
            "draft":      draft,
            "no_stock":   no_stock,
            "categories": dict(sorted(categories.items(), key=lambda x: x[1], reverse=True)),
        }

    # ── Backup / Export ───────────────────────────────────────────────────────

    def export_products_json(self) -> str:
        products = self.get_products()
        return json.dumps([p.to_dict() for p in products], ensure_ascii=False, indent=2)

    # ── Cache Management ──────────────────────────────────────────────────────

    def invalidate_cache(self) -> None:
        for key in (_CACHE_PRODUCTS, _CACHE_SETTINGS, _CACHE_FAQS):
            self._cache.delete(key)
        logger.info("Sheet cache fully invalidated.")
