from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from . import categorize, config, models, salary


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


def next_payout_event(user: models.User, requested_type: str | None = None) -> salary.PayoutEvent:
    shifts, transactions = _state_dicts(user)
    if requested_type is not None:
        return salary.payout_event_for_type(
            requested_type=requested_type,
            today=config.today(),
            shifts=shifts,
            transactions=transactions,
            rate=user.rate,
            default_advance=user.default_advance,
            employer_debt=user.employer_debt,
        )
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


class DuplicatePayoutError(Exception):
    pass


def receive_payout(
    db: Session, user: models.User, actual_amount: float, requested_type: str | None = None
) -> models.Transaction:
    event = next_payout_event(user, requested_type)
    already = next(
        (t for t in user.transactions if t.type == event.type and t.for_month == event.for_month), None
    )
    if already is not None:
        raise DuplicatePayoutError(
            f"{salary.describe_payout_type(event.type)} за {event.for_month} уже внесена."
        )
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
        if portion > 0:
            g.current_amount += portion
            db.add(models.GoalContribution(goal_id=g.id, amount=portion))
    user.unallocated_balance = max(remaining, 0)
    db.commit()


def top_up_goal(db: Session, user: models.User, goal: models.Goal, amount: float) -> None:
    if amount <= 0 or amount > user.unallocated_balance:
        return
    goal.current_amount += amount
    user.unallocated_balance -= amount
    db.add(models.GoalContribution(goal_id=goal.id, amount=amount))
    db.commit()


def withdraw_from_goal(db: Session, user: models.User, goal: models.Goal, amount: float) -> None:
    """Returns part (or all) of a goal's savings back to the unallocated
    balance — the reverse of a top-up/split. The negative contribution keeps
    the goal's pace projection honest after the money is taken back."""
    amount = round(amount)
    if amount <= 0:
        raise ValueError("Сумма возврата должна быть больше нуля")
    if amount > goal.current_amount:
        raise ValueError("В цели нет столько денег")
    goal.current_amount -= amount
    user.unallocated_balance += amount
    db.add(models.GoalContribution(goal_id=goal.id, amount=-amount))
    db.commit()


def goal_projection(goal: models.Goal) -> salary.GoalProjection:
    contributions = [{"amount": c.amount, "date": c.created_at.date()} for c in goal.contributions]
    # Rows added before this feature existed may have no created_at on file;
    # fall back to "old enough that only the recent pace window matters".
    created = (
        goal.created_at.date()
        if goal.created_at is not None
        else config.today() - timedelta(days=salary.PACE_WINDOW_DAYS)
    )
    return salary.goal_projection(
        today=config.today(),
        current_amount=goal.current_amount,
        target_amount=goal.target_amount,
        target_date=goal.target_date,
        created_at=created,
        contributions=contributions,
    )


def add_goal(db: Session, user: models.User, values: dict) -> models.Goal:
    goal = models.Goal(user_id=user.telegram_id, current_amount=0, **values)
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


def update_goal(db: Session, goal: models.Goal, patch: dict) -> None:
    for k, v in patch.items():
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


def add_expense(
    db: Session,
    user: models.User,
    amount: float,
    category: str,
    note: str,
    spent_at: str | None,
    tag: str | None = None,
) -> models.Expense:
    amount = max(round(amount), 0)
    if amount <= 0:
        raise ValueError("Сумма траты должна быть больше нуля")
    # Категорию и метку выводим из текста: «проезд автобус» -> Транспорт/Автобус.
    # Явно выбранная пользователем категория побеждает, метка всё равно уточняется.
    auto_category, auto_tag = categorize.categorize_expense(note, category)
    expense = models.Expense(
        user_id=user.telegram_id,
        amount=amount,
        category=auto_category[:50],
        tag=((tag or "").strip() or auto_tag)[:50],
        note=(note or "").strip()[:200],
        spent_at=spent_at or config.today().isoformat(),
    )
    db.add(expense)
    user.unallocated_balance -= amount
    db.commit()
    db.refresh(expense)
    return expense


def delete_expense(db: Session, user: models.User, expense: models.Expense) -> None:
    user.unallocated_balance += expense.amount
    db.delete(expense)
    db.commit()


def add_income(
    db: Session,
    user: models.User,
    amount: float,
    source: str,
    note: str,
    received_at: str | None,
    tag: str | None = None,
) -> models.Income:
    amount = max(round(amount), 0)
    if amount <= 0:
        raise ValueError("Сумма дохода должна быть больше нуля")
    auto_source, auto_tag = categorize.categorize_income(note, source)
    income = models.Income(
        user_id=user.telegram_id,
        amount=amount,
        source=auto_source[:50],
        tag=((tag or "").strip() or auto_tag)[:50],
        note=(note or "").strip()[:200],
        received_at=received_at or config.today().isoformat(),
    )
    db.add(income)
    user.unallocated_balance += amount
    db.commit()
    db.refresh(income)
    return income


def delete_income(db: Session, user: models.User, income: models.Income) -> None:
    user.unallocated_balance -= income.amount
    db.delete(income)
    db.commit()


def add_fixed_cost(db: Session, user: models.User, name: str, amount: float, day: int) -> models.FixedCost:
    name = (name or "").strip()
    if not name:
        raise ValueError("Нужно название обязательного платежа")
    amount = max(round(amount), 0)
    if amount <= 0:
        raise ValueError("Сумма платежа должна быть больше нуля")
    day = min(max(int(day or 1), 1), 31)
    cost = models.FixedCost(user_id=user.telegram_id, name=name[:100], amount=amount, day=day)
    db.add(cost)
    db.commit()
    db.refresh(cost)
    return cost


def update_fixed_cost(db: Session, cost: models.FixedCost, patch: dict) -> None:
    if patch.get("name") is not None:
        name = str(patch["name"]).strip()
        if not name:
            raise ValueError("Нужно название обязательного платежа")
        cost.name = name[:100]
    if patch.get("amount") is not None:
        amount = max(round(float(patch["amount"])), 0)
        if amount <= 0:
            raise ValueError("Сумма платежа должна быть больше нуля")
        cost.amount = amount
    if patch.get("day") is not None:
        cost.day = min(max(int(patch["day"] or 1), 1), 31)
    db.commit()


def delete_fixed_cost(db: Session, cost: models.FixedCost) -> None:
    db.delete(cost)
    db.commit()


def set_budget(db: Session, user: models.User, category: str, limit: float) -> models.Budget:
    category = (category or "").strip()[:50]
    limit = max(round(limit), 0)
    if not category:
        raise ValueError("Нужна категория")
    if limit <= 0:
        raise ValueError("Лимит должен быть больше нуля")
    existing = next((b for b in user.budgets if b.category == category), None)
    if existing:
        existing.limit = limit
        db.commit()
        db.refresh(existing)
        return existing
    budget = models.Budget(user_id=user.telegram_id, category=category, limit=limit)
    db.add(budget)
    db.commit()
    db.refresh(budget)
    return budget


def patch_budget(db: Session, budget: models.Budget, patch: dict) -> None:
    if patch.get("category") is not None:
        cat = str(patch["category"]).strip()[:50]
        if not cat:
            raise ValueError("Нужна категория")
        budget.category = cat
    if patch.get("limit") is not None:
        lim = max(round(float(patch["limit"])), 0)
        if lim <= 0:
            raise ValueError("Лимит должен быть больше нуля")
        budget.limit = lim
    db.commit()


def delete_budget(db: Session, budget: models.Budget) -> None:
    db.delete(budget)
    db.commit()


# ── Семья ──────────────────────────────────────────────────────────


def create_family(db: Session, creator_id: int, name: str) -> models.Family:
    name = (name or "").strip()[:100] or "Семья"
    user = get_or_create_user(db, creator_id)
    if user.family_id:
        raise ValueError("Вы уже в семье")
    family = models.Family(name=name, creator_id=creator_id)
    db.add(family)
    db.flush()
    user.family_id = family.id
    db.commit()
    db.refresh(family)
    return family


def join_family(db: Session, user_id: int, family_id: int) -> models.Family:
    user = get_or_create_user(db, user_id)
    if user.family_id:
        raise ValueError("Вы уже в семье")
    family = db.get(models.Family, family_id)
    if not family:
        raise ValueError("Семья не найдена")
    # Проверяем — есть ли инвайт для этого юзера
    invite = next(
        (inv for inv in family.invites if inv.invitee_id == user_id and inv.status == "pending"),
        None,
    )
    if not invite:
        raise ValueError("Приглашение не найдено или уже обработано")
    invite.status = "accepted"
    user.family_id = family.id
    db.commit()
    db.refresh(family)
    return family


def leave_family(db: Session, user_id: int) -> None:
    user = db.get(models.User, user_id)
    if not user or not user.family_id:
        raise ValueError("Вы не в семье")
    family_id = user.family_id
    user.family_id = None
    db.commit()
    # Если семья опустела — удаляем её
    family = db.get(models.Family, family_id)
    if family and not family.members:
        db.delete(family)
        db.commit()


def invite_to_family(db: Session, inviter_id: int, invitee_id: int) -> models.FamilyInvite:
    inviter = db.get(models.User, inviter_id)
    if not inviter or not inviter.family_id:
        raise ValueError("Вы не в семье — создайте её или вступите")
    invitee = get_or_create_user(db, invitee_id)
    # Уже в семье?
    if invitee.family_id:
        raise ValueError("Пользователь уже в семье")
    # Уже есть pending?
    for inv in inviter.family.invites:
        if inv.invitee_id == invitee_id and inv.status == "pending":
            raise ValueError("Приглашение уже отправлено")
    invite = models.FamilyInvite(
        family_id=inviter.family_id,
        inviter_id=inviter_id,
        invitee_id=invitee_id,
        status="pending",
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite


def get_family(db: Session, user_id: int) -> models.Family | None:
    user = db.get(models.User, user_id)
    if not user or not user.family_id:
        return None
    return db.get(models.Family, user.family_id)


def get_family_goals(db: Session, family_id: int) -> list[models.FamilyGoal]:
    return db.query(models.FamilyGoal).filter(models.FamilyGoal.family_id == family_id).all()


def create_family_goal(db: Session, family_id: int, name: str, icon: str, target_amount: float, target_date: str | None) -> models.FamilyGoal:
    name = (name or "").strip()[:100]
    if not name:
        raise ValueError("Нужно название цели")
    if target_amount <= 0:
        raise ValueError("Цель должна быть больше нуля")
    goal = models.FamilyGoal(family_id=family_id, name=name, icon=icon, target_amount=target_amount, target_date=target_date)
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


def topup_family_goal(db: Session, goal: models.FamilyGoal, user_id: int, amount: float) -> None:
    amount = round(amount)
    if amount <= 0:
        raise ValueError("Сумма должна быть больше нуля")
    user = db.get(models.User, user_id)
    if not user:
        raise ValueError("Пользователь не найден")
    if amount > user.unallocated_balance:
        raise ValueError("Недостаточно средств")
    user.unallocated_balance -= amount
    goal.current_amount += amount
    db.add(models.FamilyGoalContribution(goal_id=goal.id, user_id=user_id, amount=amount))
    db.commit()


def reset_all(db: Session, user: models.User) -> None:
    for s in list(user.shifts):
        db.delete(s)
    for t in list(user.transactions):
        db.delete(t)
    for g in list(user.goals):
        db.delete(g)
    for e in list(user.expenses):
        db.delete(e)
    for i in list(user.incomes):
        db.delete(i)
    for c in list(user.fixed_costs):
        db.delete(c)
    for b in list(user.budgets):
        db.delete(b)
    user.rate = 8650
    user.default_advance = 80000
    user.unallocated_balance = 0
    user.employer_debt = 0
    db.commit()
    db.flush()
    for g in models.DEFAULT_GOALS:
        db.add(models.Goal(user_id=user.telegram_id, **g))
    db.commit()
