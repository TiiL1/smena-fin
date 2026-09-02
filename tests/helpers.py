import hashlib
import hmac
import json
import time
from urllib.parse import quote, urlencode

BOT_TOKEN = "123456789:TEST-TOKEN-not-a-real-secret"


def make_init_data(user_id: int, bot_token: str = BOT_TOKEN) -> str:
    fields = {
        "query_id": "AAHtest",
        "user": json.dumps({"id": user_id, "first_name": "Test"}, separators=(",", ":")),
        "auth_date": str(int(time.time())),
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    fields["hash"] = computed_hash
    return urlencode(fields, quote_via=quote)


def auth_header(user_id: int) -> dict:
    return {"Authorization": f"tma {make_init_data(user_id)}"}
