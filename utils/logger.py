"""
Gold Bot v2 – Logger Setup
============================
Call ``setup_logger()`` once in main.py.
Every module then uses ``logging.getLogger(__name__)``.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

from config.config import LOG_DIR, LOG_LEVEL, LOG_MAX_BYTES, LOG_BACKUP_COUNT

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s"
_DATE   = "%Y-%m-%d %H:%M:%S"


def setup_logger() -> None:
    """
    Configure the root logger with:
    - A rotating file handler  → logs/gold_bot.log
    - A stream (stdout) handler
    Both use the same format and the LOG_LEVEL from config.
    """
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, "gold_bot.log")

    level = getattr(logging, LOG_LEVEL, logging.INFO)

    formatter = logging.Formatter(_FORMAT, datefmt=_DATE)

    # Rotating file handler
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)

    # Console handler
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(level)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(stream_handler)

    # Silence noisy libraries
    for lib in ("httpx", "httpcore", "telegram", "gspread", "urllib3"):
        logging.getLogger(lib).setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        "Logger initialised. level=%s  file=%s", LOG_LEVEL, log_path
    )
