import json
from urllib.parse import parse_qsl, quote, urlencode

from app.auth import parse_and_validate_init_data
from .helpers import BOT_TOKEN, make_init_data


def test_valid_init_data_is_accepted():
    init_data = make_init_data(42)
    result = parse_and_validate_init_data(init_data, BOT_TOKEN)
    assert result is not None
    assert result["user"]["id"] == 42


def test_wrong_bot_token_is_rejected():
    init_data = make_init_data(42, bot_token="000000:some-other-token")
    result = parse_and_validate_init_data(init_data, BOT_TOKEN)
    assert result is None


def test_tampered_user_id_is_rejected():
    init_data = make_init_data(42)
    pairs = dict(parse_qsl(init_data))
    user = json.loads(pairs["user"])
    user["id"] = 999  # attacker tries to impersonate a different user
    pairs["user"] = json.dumps(user, separators=(",", ":"))
    tampered = urlencode(pairs, quote_via=quote)  # hash is now stale for this payload
    result = parse_and_validate_init_data(tampered, BOT_TOKEN)
    assert result is None


def test_missing_hash_is_rejected():
    result = parse_and_validate_init_data("user=%7B%22id%22%3A42%7D", BOT_TOKEN)
    assert result is None
