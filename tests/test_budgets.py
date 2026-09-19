from datetime import date
from app import crud, models
from app.db import SessionLocal
from app.bot import _parse_expense


def test_budget_set_and_delete():
    db = SessionLocal()
    try:
        user = models.User(telegram_id=800001, started_bot=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        b = crud.set_budget(db, user, "Еда", 30000)
        assert b.limit == 30000
        assert b.category == "Еда"
        assert len(user.budgets) == 1
        crud.delete_budget(db, b)
        db.refresh(user)
        assert len(user.budgets) == 0
    finally:
        db.close()


def test_budget_set_upsert():
    db = SessionLocal()
    try:
        user = models.User(telegram_id=800002, started_bot=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        b1 = crud.set_budget(db, user, "Еда", 20000)
        b2 = crud.set_budget(db, user, "Еда", 35000)
        assert b1.id == b2.id
        assert b2.limit == 35000
    finally:
        db.close()


def test_budget_validation():
    db = SessionLocal()
    try:
        user = models.User(telegram_id=800003, started_bot=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        try:
            crud.set_budget(db, user, "", 1000)
            assert False, "should raise"
        except ValueError:
            pass
        try:
            crud.set_budget(db, user, "Еда", 0)
            assert False, "should raise"
        except ValueError:
            pass
    finally:
        db.close()


def test_budget_reset():
    db = SessionLocal()
    try:
        user = models.User(telegram_id=800004, started_bot=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        crud.set_budget(db, user, "Еда", 30000)
        crud.set_budget(db, user, "Транспорт", 10000)
        assert len(user.budgets) == 2
        crud.reset_all(db, user)
        db.refresh(user)
        assert len(user.budgets) == 0
    finally:
        db.close()
