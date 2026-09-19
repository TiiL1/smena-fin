import os
import tempfile

_db_path = tempfile.mktemp(suffix=".db")

os.environ["BOT_TOKEN"] = "123456789:TEST-TOKEN-not-a-real-secret"
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"
os.environ["CRON_SECRET"] = "test-cron-secret"
os.environ["TELEGRAM_WEBHOOK_SECRET"] = "test-webhook-secret"
os.environ["WEBAPP_URL"] = "https://example.test"
os.environ["DEV_AUTH"] = "0"

from app.db import init_db  # noqa: E402

init_db()
