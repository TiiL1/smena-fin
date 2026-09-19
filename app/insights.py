"""Инсайты DeepSeek: генерация одной строки на основе агрегатов расходов.

Стратегия безопасности:
- Лимит 1 вызов на юзера в сутки (cache_key = user_id + month_key).
- Промпт фиксированный, данные — только агрегаты (никаких ID/текстов трат).
- Без ключа — молча пропускаем (feels-like no-op).
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

_CACHE_TTL_SECONDS = 24 * 60 * 60  # сутки

# Глобальный in-memory кэш: cache_key -> (text, expire_ts).
# Не нужен внешний мемкеш/Redis для 1 юзера.
_cache: dict[str, tuple[str, float]] = {}


def _api_key() -> str:
    return (os.environ.get("DEEPSEEK_API_KEY") or "").strip()


def generate_insight(
    user_id: int,
    month_key: str,  # YYYY-MM
    *,
    total_spent: float,
    total_earned: float,
    top_categories: list[dict[str, Any]],  # [{"category": str, "amount": float, "delta_pct": float|None}]
    savings_rate: float | None = None,  # (earned-spent)/earned, None if earned==0
    fixed_total: float = 0,
    goals_on_track: int = 0,
    goals_behind: int = 0,
) -> str | None:
    """Возвращает одну строку-совет. None если нечего говорить или нет ключа."""
    if total_spent == 0 and total_earned == 0:
        return None

    # Кэш
    cache_key = f"{user_id}:{month_key}"
    import time
    now = time.time()
    if cache_key in _cache:
        text, exp = _cache[cache_key]
        if now < exp:
            return text

    api_key = _api_key()
    if not api_key:
        return None

    # Формируем промпт без чувствительных данных
    context = {
        "month": month_key,
        "total_spent": round(total_spent),
        "total_earned": round(total_earned),
        "savings_rate": round(savings_rate * 100) if savings_rate is not None else None,
        "fixed_total": round(fixed_total),
        "goals_on_track": goals_on_track,
        "goals_behind": goals_behind,
        "top_categories": [{"name": c["category"], "amount": round(c["amount"]), "delta_pct": c.get("delta_pct")} for c in top_categories[:4]],
    }

    system = (
        "Ты — финансовый советник для рабочего сменной занятости. "
        "Отвечай РОВНО ОДНИМ предложением на русском, до 140 символов. "
        "Будь конкретным, без воды, без совета «сократить траты» — говори цифры."
    )
    user_msg = f"Данные за месяц:\n{json.dumps(context, ensure_ascii=False)}"

    try:
        resp = httpx.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                "max_tokens": 120,
                "temperature": 0.3,
            },
            timeout=8.0,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"].strip()[:140]
        if text:
            _cache[cache_key] = (text, now + _CACHE_TTL_SECONDS)
            return text
    except Exception:
        pass  # молча — сеть, лимит, что угодно
    return None
