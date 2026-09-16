from datetime import date

from app import models
from app.bot import _parse_expense, weekly_digest_text
from app.db import SessionLocal


def test_parse_expense_with_category_and_note():
    assert _parse_expense("-3500 еда обед") == (3500, "Еда", "обед")


def test_parse_expense_amount_only():
    assert _parse_expense("-5000") == (5000, "", "")


def test_parse_expense_unknown_category_goes_to_other():
    assert _parse_expense("-1200 такси до работы") == (1200, "Другое", "такси до работы")


def test_parse_expense_rejects_plain_text():
    assert _parse_expense("привет") is None
    assert _parse_expense("3500") is None


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
