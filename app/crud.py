from datetime import datetime, timezone

from sqlalchemy.orm import Session

from . import config, models, salary


def get_or_create_user(db: Session, telegram_id: int) -> models.User:
    user = db.get(models.User, telegram_id)
    if user:
        return user
    user = models.User(telegram_id=telegram_id)
    db.add(user)
    db.flush()
    for g in models.DEFAULT_GOALS:
        db.add(models.Goal(user_id=telegram_id, **g))
    db.commit()
    db.refresh(user)
    return user


def _state_dicts(user: models.User) -> tuple[list[dict], list[dict]]:
    """Plain-dict views of shifts/transactions, shaped for app.salary functions."""
    shifts = [{"date": s.date, "coefficient": s.coefficient} for s in user.shifts]
    transactions = [
        {"type": t.type, "for_month": t.for_month, "actual_amount": t.actual_amount}
        for t in user.transactions
    ]
    return shifts, transactions


def next_payout_event(user: models.User) -> salary.PayoutEvent:
    shifts, transactions = _state_dicts(user)
    return salary.get_next_payout_event(
        today=config.today(),
        shifts=shifts,
        transactions=transactions,
        rate=user.rate,
        default_advance=user.default_advance,
        employer_debt=user.employer_debt,
    )


def cycle_shift(db: Session, user: models.User, date_key: str) -> None:
    existing = next((s for s in user.shifts if s.date == date_key), None)
    if existing is None:
        db.add(models.Shift(user_id=user.telegram_id, date=date_key, coefficient=1))
    elif existing.coefficient == 1:
        existing.coefficient = 0.5
    else:
        db.delete(existing)
    db.commit()


def receive_payout(db: Session, user: models.User, actual_amount: float) -> models.Transaction:
    event = next_payout_event(user)
    debt_after = event.calculated_amount - actual_amount
    tx = models.Transaction(
        user_id=user.telegram_id,
        type=event.type,
        for_month=event.for_month,
        calculated_amount=event.calculated_amount,
        actual_amount=actual_amount,
        debt_after=debt_after,
        received_at=datetime.now(timezone.utc),
    )
    db.add(tx)
    user.unallocated_balance += actual_amount
    user.employer_debt = debt_after
    db.commit()
    return tx


def split_balance(db: Session, user: models.User) -> None:
    if user.unallocated_balance <= 0 or not user.goals:
        return
    total_percent = sum(g.split_percent for g in user.goals)
    scale = 100 / total_percent if total_percent > 100 else 1
    remaining = user.unallocated_balance
    for g in user.goals:
        portion = int((user.unallocated_balance * g.split_percent * scale) // 100)
        remaining -= portion
        g.current_amount += portion
    user.unallocated_balance = max(remaining, 0)
    db.commit()


def top_up_goal(db: Session, user: models.User, goal: models.Goal, amount: float) -> None:
    if amount <= 0 or amount > user.unallocated_balance:
        return
    goal.current_amount += amount
    user.unallocated_balance -= amount
    db.commit()


def add_goal(db: Session, user: models.User, values: dict) -> models.Goal:
    goal = models.Goal(user_id=user.telegram_id, current_amount=0, **values)
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


def update_goal(db: Session, goal: models.Goal, patch: dict) -> None:
    for k, v in patch.items():
        if v is not None:
            setattr(goal, k, v)
    db.commit()


def delete_goal(db: Session, user: models.User, goal: models.Goal) -> None:
    user.unallocated_balance += goal.current_amount
    db.delete(goal)
    db.commit()


def update_settings(db: Session, user: models.User, patch: dict) -> None:
    for k, v in patch.items():
        if v is not None:
            setattr(user, k, v)
    db.commit()


def reset_all(db: Session, user: models.User) -> None:
    for s in list(user.shifts):
        db.delete(s)
    for t in list(user.transactions):
        db.delete(t)
    for g in list(user.goals):
        db.delete(g)
    user.rate = 8650
    user.default_advance = 80000
    user.unallocated_balance = 0
    user.employer_debt = 0
    db.commit()
    db.flush()
    for g in models.DEFAULT_GOALS:
        db.add(models.Goal(user_id=user.telegram_id, **g))
    db.commit()
