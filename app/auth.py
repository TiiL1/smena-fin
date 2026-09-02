"""Validates Telegram Mini App `initData` per the official algorithm:
https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

secret_key = HMAC_SHA256(key=b"WebAppData", msg=bot_token)
computed   = HMAC_SHA256(key=secret_key, msg=data_check_string).hexdigest()
valid iff  computed == hash field from init_data
"""

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from fastapi import Header, HTTPException

from . import config

# initData is captured once when the Mini App launches and doesn't refresh
# itself while the user keeps the app open, so this needs to be generous
# rather than a tight "just signed" window.
MAX_INIT_DATA_AGE_SECONDS = 24 * 60 * 60


def parse_and_validate_init_data(init_data: str, bot_token: str) -> dict | None:
    if not init_data or not bot_token:
        return None

    pairs = parse_qsl(init_data, keep_blank_values=True)
    received_hash = None
    fields: list[tuple[str, str]] = []
    for key, value in pairs:
        if key == "hash":
            received_hash = value
        else:
            fields.append((key, value))

    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    parsed = dict(fields)
    auth_date = parsed.get("auth_date")
    if auth_date is not None:
        try:
            if time.time() - int(auth_date) > MAX_INIT_DATA_AGE_SECONDS:
                return None
        except ValueError:
            return None
    if "user" in parsed:
        try:
            parsed["user"] = json.loads(parsed["user"])
        except (json.JSONDecodeError, TypeError):
            return None
    return parsed


def get_current_user_id(authorization: str | None = Header(default=None)) -> int:
    """Expects `Authorization: tma <initData>`. Falls back to a fixed dev user
    only when DEV_AUTH=1 is explicitly set (never enable this in production)."""
    if authorization and authorization.startswith("tma "):
        init_data = authorization[len("tma "):]
        parsed = parse_and_validate_init_data(init_data, config.BOT_TOKEN)
        if parsed and "user" in parsed and "id" in parsed["user"]:
            return int(parsed["user"]["id"])

    if config.DEV_AUTH:
        return config.DEV_USER_ID

    raise HTTPException(status_code=401, detail="Не удалось проверить Telegram initData")
