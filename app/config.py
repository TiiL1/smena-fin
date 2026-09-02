import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "").rstrip("/")
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./smena.db")
CRON_SECRET = os.environ.get("CRON_SECRET", "")
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
REMINDER_TIMEZONE = os.environ.get("REMINDER_TIMEZONE", "Asia/Almaty")

# Set to "1" to allow calling the API without valid Telegram initData,
# using a fixed dev user id instead. Never enable this in production.
DEV_AUTH = os.environ.get("DEV_AUTH", "0") == "1"
DEV_USER_ID = int(os.environ.get("DEV_USER_ID", "1"))


def today() -> date:
    """'Today' in the user's timezone, not the host machine's (often UTC) one —
    matters right around midnight so the server agrees with what the phone shows."""
    return datetime.now(ZoneInfo(REMINDER_TIMEZONE)).date()
