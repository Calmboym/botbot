"""
DEPRECATED — This module has been removed.

Product images are now stored as Telegram file_id values.
When the admin sends a photo, Telegram stores it and we save only the
file_id in Google Sheets. No external image hosting is required.

See: models/product.py  (telegram_file_id field)
     handlers/admin.py  (handle_admin_photo)
     services/publish_service.py
"""
# This file is intentionally empty.
# All references to DriveService have been removed from the codebase.
