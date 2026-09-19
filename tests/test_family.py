from datetime import datetime, timezone

from app import crud, models
from app.db import SessionLocal


def _user(db, tg_id: int):
    user = models.User(telegram_id=tg_id, started_bot=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_family_create_join_leave():
    db = SessionLocal()
    try:
        u1 = _user(db, 900001)
        u2 = _user(db, 900002)
        try:
            family = crud.create_family(db, u1.telegram_id, "Семья Тест")
            assert family.name == "Семья Тест"
            db.refresh(u1)
            assert u1.family_id == family.id

            # join без инвайта — нельзя
            try:
                crud.join_family(db, u2.telegram_id, family.id)
                assert False, "должно падать без инвайта"
            except ValueError:
                pass

            # инвайт + join
            invite = crud.invite_to_family(db, u1.telegram_id, u2.telegram_id)
            assert invite.status == "pending"
            crud.join_family(db, u2.telegram_id, family.id)
            db.refresh(u2)
            assert u2.family_id == family.id

            # второй инвайт тому же — уже в семье
            try:
                crud.invite_to_family(db, u1.telegram_id, u2.telegram_id)
                assert False, "должно падать: уже в семье"
            except ValueError:
                pass

            # выходим: семья остаётся с одним участником
            crud.leave_family(db, u2.telegram_id)
            assert db.get(models.Family, family.id) is not None
            assert len(db.get(models.Family, family.id).members) == 1
            crud.leave_family(db, u1.telegram_id)
            # пустая семья удаляется
            assert db.get(models.Family, family.id) is None
        finally:
            for u in (u1, u2):
                db.delete(u)
            db.commit()
    finally:
        db.close()


def test_family_goal_topup_and_contributions():
    db = SessionLocal()
    try:
        u1 = _user(db, 901001)
        try:
            family = crud.create_family(db, u1.telegram_id, "Цели")
            goal = crud.create_family_goal(db, family.id, "Квартира", "home", 1_000_000, None)
            assert goal.current_amount == 0

            u1.unallocated_balance = 500_000
            db.commit()
            crud.topup_family_goal(db, goal, u1.telegram_id, 200_000)
            db.refresh(goal)
            db.refresh(u1)
            assert goal.current_amount == 200_000
            assert u1.unallocated_balance == 300_000
            assert len(goal.contributions) == 1
            assert goal.contributions[0].amount == 200_000

            # больше баланса — нельзя
            try:
                crud.topup_family_goal(db, goal, u1.telegram_id, 999_999)
                assert False, "должно падать: не хватает средств"
            except ValueError:
                pass

            # негативная сумма — нельзя
            try:
                crud.topup_family_goal(db, goal, u1.telegram_id, -10)
                assert False, "должно падать: отрицательная сумма"
            except ValueError:
                pass
        finally:
            db.delete(u1)
            db.commit()
    finally:
        db.close()