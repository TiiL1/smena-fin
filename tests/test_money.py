from datetime import date

from app import models
from app.bot import _parse_expense, _parse_income, weekly_digest_text
from app.db import SessionLocal


def test_parse_expense_with_category_and_note():
    assert _parse_expense("-3500 еда обед") == (3500, "Еда", "обед")


def test_parse_expense_amount_only():
    assert _parse_expense("-5000") == (5000, "", "")


def test_parse_expense_unknown_category_goes_to_other():
    # Неизвестная категория целиком уходит в заметку, а настоящая
    # категоризация (Транспорт / такси) происходит позже в crud через
    # app.categorize — чтобы поддержка меток была в одном месте.
    assert _parse_expense("-1200 такси до работы") == (1200, "", "такси до работы")


def test_parse_expense_rejects_plain_text():
    assert _parse_expense("привет") is None
    assert _parse_expense("3500") is None


def test_parse_income_with_source_and_note():
    assert _parse_income("+15000 курьерка вечер") == (15000, "Курьерка", "вечер")


def test_parse_income_amount_only():
    assert _parse_income("+8000") == (8000, "", "")


def test_parse_income_unknown_source_goes_to_other():
    assert _parse_income("+5000 фриланс сайт") == (5000, "", "фриланс сайт")


def test_parse_income_rejects_plain_text():
    assert _parse_income("привет") is None
    assert _parse_income("15000") is None


def test_weekly_digest_skips_quiet_user_without_goals_and_expenses():
    db = SessionLocal()
    try:
        user = models.User(telegram_id=999901, started_bot=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        assert user.expenses == []
        assert user.goals == []
        assert weekly_digest_text(user, date(2026, 9, 14)) is None
    finally:
        db.close()


def test_weekly_digest_reports_week_spend():
    db = SessionLocal()
    try:
        user = models.User(telegram_id=999902, started_bot=True)
        db.add(user)
        db.flush()
        db.add(
            models.Expense(
                user_id=user.telegram_id,
                amount=7000,
                category="Еда",
                note="",
                spent_at="2026-09-13",
            )
        )
        db.commit()
        db.refresh(user)
        text = weekly_digest_text(user, date(2026, 9, 14))
        assert text is not None
        assert "7 000" in text
    finally:
        db.close()


def test_weekly_digest_reports_week_income():
    db = SessionLocal()
    try:
        user = models.User(telegram_id=999903, started_bot=True)
        db.add(user)
        db.flush()
        db.add(
            models.Income(
                user_id=user.telegram_id,
                amount=15000,
                source="Курьерка",
                note="",
                received_at="2026-09-13",
            )
        )
        db.commit()
        db.refresh(user)
        text = weekly_digest_text(user, date(2026, 9, 14))
        assert text is not None
        assert "Подработка" in text
        assert "15 000" in text
    finally:
        db.close()
