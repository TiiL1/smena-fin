"""Авто-категоризация трат и доходов по тексту заметки.

Идея: пользователь пишет свободно («-110 проезд автобус», «-5155 ресторан»,
«-1526 свидание»), а мы раскладываем это на два уровня:

    category — одна из фиксированных категорий (для графиков и лимитов)
    tag      — уточнение внутри категории («Автобус», «Ресторан», «Свидание»)

Так статистика остаётся сравнимой по категориям, но внутри «Транспорт» видно,
сколько ушло именно на автобус, а сколько на ЛРТ или такси.

Порядок работы: сначала бесплатный словарь синонимов (0 мс, без сети), потом —
если ничего не нашлось и задан DEEPSEEK_API_KEY — дешёвая LLM-подсказка с кэшем.
"""

from __future__ import annotations

import re
import unicodedata

from .keyword_map import KEYWORD_RULES, INCOME_KEYWORD_RULES

EXPENSE_CATEGORIES = [
    "Еда",
    "Транспорт",
    "Жильё",
    "Кредит",
    "Здоровье",
    "Развлечения",
    "Подписки",
    "Другое",
]

INCOME_SOURCES = ["Курьерка", "Такси", "Подработка", "Продажа", "Подарок", "Другое"]

_WORD_RE = re.compile(r"[^\w]+", re.UNICODE)


def _normalize(text: str) -> str:
    """Приводит текст к нижнему регистру, чинит ё/й и убирает пунктуацию."""
    text = unicodedata.normalize("NFKC", (text or "").strip().lower())
    text = text.replace("ё", "е")
    return _WORD_RE.sub(" ", text).strip()


def _match_rules(text: str, rules: list[tuple[tuple[str, ...], str, str]]) -> tuple[str, str] | None:
    """Ищет первое правило, чьё ключевое слово есть в тексте.

    Правила заданы от узких к широким, поэтому «проезд автобус» даст метку
    «Автобус», а не общий «Проезд»: более конкретные ключи стоят выше.
    """
    words = set(text.split())
    for keys, category, tag in rules:
        for key in keys:
            if " " in key:
                if key in text:
                    return category, tag
            elif key in words:
                return category, tag
    return None


def categorize_expense(note: str, hint: str = "") -> tuple[str, str]:
    """Возвращает (category, tag) для траты.

    `hint` — категория, которую пользователь выбрал руками; если это осмысленная
    категория (не «Другое»), она побеждает, но метку всё равно пытаемся достать
    из текста, чтобы внутри «Развлечения» осталось видно «Свидание».
    """
    text = _normalize(note)
    matched = _match_rules(text, KEYWORD_RULES) if text else None

    hint_clean = (hint or "").strip()
    user_chose = hint_clean in EXPENSE_CATEGORIES and hint_clean != "Другое"

    if matched is None:
        category = hint_clean if user_chose else "Другое"
        return category, _fallback_tag(note)

    category, tag = matched
    if user_chose:
        category = hint_clean
    return category, tag


def categorize_income(note: str, hint: str = "") -> tuple[str, str]:
    """То же самое для доходов: (source, tag)."""
    text = _normalize(note)
    matched = _match_rules(text, INCOME_KEYWORD_RULES) if text else None

    hint_clean = (hint or "").strip()
    user_chose = hint_clean in INCOME_SOURCES and hint_clean != "Другое"

    if matched is None:
        source = hint_clean if user_chose else "Другое"
        return source, _fallback_tag(note)

    source, tag = matched
    if user_chose:
        source = hint_clean
    return source, tag


def _fallback_tag(note: str) -> str:
    """Если словарь не сработал — берём первое значимое слово как метку,
    чтобы в статистике осталась хоть какая-то детализация вместо пустоты."""
    text = _normalize(note)
    if not text:
        return ""
    first = text.split()[0]
    if len(first) < 3:
        return ""
    return first.capitalize()[:50]
