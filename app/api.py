from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from . import crud, models, schemas
from .auth import get_current_user_id
from .db import get_db

router = APIRouter(prefix="/api")


def _goal_out(goal: models.Goal) -> schemas.GoalOut:
    proj = crud.goal_projection(goal)
    return schemas.GoalOut(
        id=goal.id,
        name=goal.name,
        icon=goal.icon,
        target_amount=goal.target_amount,
        current_amount=goal.current_amount,
        split_percent=goal.split_percent,
        target_date=goal.target_date,
        projection=schemas.GoalProjectionOut(
            pace_monthly=proj.pace_monthly,
            required_monthly=proj.required_monthly,
            eta_date=proj.eta_date,
            on_track=proj.on_track,
            reached=proj.reached,
        ),
    )


def _state_out(user: models.User) -> schemas.StateOut:
    return schemas.StateOut(
        shifts=[schemas.ShiftOut.model_validate(s, from_attributes=True) for s in user.shifts],
        transactions=[
            schemas.TransactionOut.model_validate(t, from_attributes=True) for t in user.transactions
        ],
        goals=[_goal_out(g) for g in user.goals],
        expenses=[
            schemas.ExpenseOut.model_validate(e, from_attributes=True)
            for e in sorted(user.expenses, key=lambda x: (x.spent_at, x.id), reverse=True)[:200]
        ],
        incomes=[
            schemas.IncomeOut.model_validate(i, from_attributes=True)
            for i in sorted(user.incomes, key=lambda x: (x.received_at, x.id), reverse=True)[:200]
        ],
        fixed_costs=[
            schemas.FixedCostOut.model_validate(c, from_attributes=True)
            for c in sorted(user.fixed_costs, key=lambda x: (x.day, x.id))
        ],
        budgets=[
            schemas.BudgetOut.model_validate(b, from_attributes=True)
            for b in sorted(user.budgets, key=lambda x: x.category)
        ],
        unallocated_balance=user.unallocated_balance,
        employer_debt=user.employer_debt,
        settings=schemas.SettingsOut(rate=user.rate, default_advance=user.default_advance),
    )


def _get_goal_or_404(user: models.User, goal_id: int) -> models.Goal:
    goal = next((g for g in user.goals if g.id == goal_id), None)
    if goal is None:
        raise HTTPException(status_code=404, detail="Цель не найдена")
    return goal


def _get_expense_or_404(user: models.User, expense_id: int) -> models.Expense:
    expense = next((e for e in user.expenses if e.id == expense_id), None)
    if expense is None:
        raise HTTPException(status_code=404, detail="Трата не найдена")
    return expense


def _get_income_or_404(user: models.User, income_id: int) -> models.Income:
    income = next((i for i in user.incomes if i.id == income_id), None)
    if income is None:
        raise HTTPException(status_code=404, detail="Доход не найден")
    return income


def _get_fixed_cost_or_404(user: models.User, cost_id: int) -> models.FixedCost:
    cost = next((c for c in user.fixed_costs if c.id == cost_id), None)
    if cost is None:
        raise HTTPException(status_code=404, detail="Платёж не найден")
    return cost


def _get_budget_or_404(user: models.User, budget_id: int) -> models.Budget:
    budget = next((b for b in user.budgets if b.id == budget_id), None)
    if budget is None:
        raise HTTPException(status_code=404, detail="Бюджет не найден")
    return budget


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/state", response_model=schemas.StateOut)
def get_state(db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    user = crud.get_or_create_user(db, user_id)
    return _state_out(user)


@router.post("/shifts/cycle", response_model=schemas.StateOut)
def cycle_shift(
    body: schemas.CycleShiftIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    user = crud.get_or_create_user(db, user_id)
    crud.cycle_shift(db, user, body.date)
    db.refresh(user)
    return _state_out(user)


@router.post("/payout", response_model=schemas.StateOut)
def receive_payout(
    body: schemas.PayoutIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    user = crud.get_or_create_user(db, user_id)
    try:
        crud.receive_payout(db, user, body.actual_amount, body.type)
    except crud.DuplicatePayoutError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.refresh(user)
    return _state_out(user)


@router.post("/split", response_model=schemas.StateOut)
def split_balance(db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    user = crud.get_or_create_user(db, user_id)
    crud.split_balance(db, user)
    db.refresh(user)
    return _state_out(user)


@router.post("/goals", response_model=schemas.StateOut)
def add_goal(
    body: schemas.GoalIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    user = crud.get_or_create_user(db, user_id)
    crud.add_goal(db, user, body.model_dump())
    db.refresh(user)
    return _state_out(user)


@router.patch("/goals/{goal_id}", response_model=schemas.StateOut)
def update_goal(
    goal_id: int,
    body: schemas.GoalPatchIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    user = crud.get_or_create_user(db, user_id)
    goal = _get_goal_or_404(user, goal_id)
    crud.update_goal(db, goal, body.model_dump(exclude_unset=True))
    db.refresh(user)
    return _state_out(user)


@router.delete("/goals/{goal_id}", response_model=schemas.StateOut)
def delete_goal(
    goal_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    user = crud.get_or_create_user(db, user_id)
    goal = _get_goal_or_404(user, goal_id)
    crud.delete_goal(db, user, goal)
    db.refresh(user)
    return _state_out(user)


@router.post("/goals/{goal_id}/topup", response_model=schemas.StateOut)
def top_up_goal(
    goal_id: int,
    body: schemas.TopUpIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    user = crud.get_or_create_user(db, user_id)
    goal = _get_goal_or_404(user, goal_id)
    crud.top_up_goal(db, user, goal, body.amount)
    db.refresh(user)
    return _state_out(user)


@router.post("/goals/{goal_id}/withdraw", response_model=schemas.StateOut)
def withdraw_from_goal(
    goal_id: int,
    body: schemas.WithdrawIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    user = crud.get_or_create_user(db, user_id)
    goal = _get_goal_or_404(user, goal_id)
    try:
        crud.withdraw_from_goal(db, user, goal, body.amount)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.refresh(user)
    return _state_out(user)


@router.patch("/settings", response_model=schemas.StateOut)
def update_settings(
    body: schemas.SettingsPatchIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    user = crud.get_or_create_user(db, user_id)
    crud.update_settings(db, user, body.model_dump())
    db.refresh(user)
    return _state_out(user)


@router.post("/expenses", response_model=schemas.StateOut)
def add_expense(
    body: schemas.ExpenseIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    user = crud.get_or_create_user(db, user_id)
    try:
        crud.add_expense(db, user, body.amount, body.category, body.note, body.spent_at, body.tag)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.refresh(user)
    return _state_out(user)


@router.delete("/expenses/{expense_id}", response_model=schemas.StateOut)
def delete_expense(
    expense_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    user = crud.get_or_create_user(db, user_id)
    expense = _get_expense_or_404(user, expense_id)
    crud.delete_expense(db, user, expense)
    db.refresh(user)
    return _state_out(user)


@router.post("/incomes", response_model=schemas.StateOut)
def add_income(
    body: schemas.IncomeIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    user = crud.get_or_create_user(db, user_id)
    try:
        crud.add_income(db, user, body.amount, body.source, body.note, body.received_at, body.tag)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.refresh(user)
    return _state_out(user)


@router.delete("/incomes/{income_id}", response_model=schemas.StateOut)
def delete_income(
    income_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    user = crud.get_or_create_user(db, user_id)
    income = _get_income_or_404(user, income_id)
    crud.delete_income(db, user, income)
    db.refresh(user)
    return _state_out(user)


@router.post("/fixed-costs", response_model=schemas.StateOut)
def add_fixed_cost(
    body: schemas.FixedCostIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    user = crud.get_or_create_user(db, user_id)
    try:
        crud.add_fixed_cost(db, user, body.name, body.amount, body.day)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.refresh(user)
    return _state_out(user)


@router.patch("/fixed-costs/{cost_id}", response_model=schemas.StateOut)
def update_fixed_cost(
    cost_id: int,
    body: schemas.FixedCostPatchIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    user = crud.get_or_create_user(db, user_id)
    cost = _get_fixed_cost_or_404(user, cost_id)
    try:
        crud.update_fixed_cost(db, cost, body.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.refresh(user)
    return _state_out(user)


@router.delete("/fixed-costs/{cost_id}", response_model=schemas.StateOut)
def delete_fixed_cost(
    cost_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    user = crud.get_or_create_user(db, user_id)
    cost = _get_fixed_cost_or_404(user, cost_id)
    crud.delete_fixed_cost(db, cost)
    db.refresh(user)
    return _state_out(user)


@router.get("/insights", response_model=dict)
def insights(db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    user = crud.get_or_create_user(db, user_id)
    from .insights import generate_insight
    from .config import today

    month_key = today().isoformat()[:7]
    total_spent = sum(e.amount for e in user.expenses if e.spent_at.startswith(month_key))
    total_earned = sum(i.amount for i in user.incomes if i.received_at.startswith(month_key))

    # Топ-категории за месяц
    cat_map: dict[str, float] = {}
    for e in user.expenses:
        if not e.spent_at.startswith(month_key):
            continue
        cat_map[e.category or "Другое"] = (cat_map[e.category or "Другое"] or 0) + e.amount
    top_categories = sorted([{"category": k, "amount": v, "delta_pct": None} for k, v in cat_map.items()], key=lambda x: -x["amount"])[:4]
    savings_rate = (total_earned - total_spent) / total_earned if total_earned else None
    fixed_total = sum(c.amount for c in user.fixed_costs)
    goals_on_track = sum(1 for g in user.goals if crud.goal_projection(g).on_track is True)
    goals_behind = sum(1 for g in user.goals if crud.goal_projection(g).on_track is False)

    text = generate_insight(
        user_id,
        month_key,
        total_spent=total_spent,
        total_earned=total_earned,
        top_categories=top_categories,
        savings_rate=savings_rate,
        fixed_total=fixed_total,
        goals_on_track=goals_on_track,
        goals_behind=goals_behind,
    )
    return {"text": text, "month": month_key}


@router.post("/budgets", response_model=schemas.StateOut)
def set_budget(
    body: schemas.BudgetIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    user = crud.get_or_create_user(db, user_id)
    try:
        crud.set_budget(db, user, body.category, body.limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.refresh(user)
    return _state_out(user)


@router.patch("/budgets/{budget_id}", response_model=schemas.StateOut)
def patch_budget(
    budget_id: int,
    body: schemas.BudgetPatchIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    user = crud.get_or_create_user(db, user_id)
    budget = _get_budget_or_404(user, budget_id)
    try:
        crud.patch_budget(db, budget, body.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.refresh(user)
    return _state_out(user)


@router.delete("/budgets/{budget_id}", response_model=schemas.StateOut)
def delete_budget(
    budget_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    user = crud.get_or_create_user(db, user_id)
    budget = _get_budget_or_404(user, budget_id)
    crud.delete_budget(db, budget)
    db.refresh(user)
    return _state_out(user)


# ── Семья ──────────────────────────────────────────────────────────


def _family_goal_out(goal: models.FamilyGoal) -> dict:
    return {
        "id": goal.id,
        "name": goal.name,
        "icon": goal.icon,
        "targetAmount": goal.target_amount,
        "currentAmount": goal.current_amount,
        "targetDate": goal.target_date,
        "familyId": goal.family_id,
        "contributions": [
            {"userId": c.user_id, "amount": c.amount, "createdAt": c.created_at.isoformat()}
            for c in goal.contributions
        ],
    }


def _family_out(family: models.Family, db: Session) -> dict:
    return {
        "id": family.id,
        "name": family.name,
        "creatorId": family.creator_id,
        "members": [{"telegramId": m.telegram_id, "name": str(m.telegram_id)} for m in family.members],
        "goals": [_family_goal_out(g) for g in family.goals],
        "invites": [
            {"id": inv.id, "inviterId": inv.inviter_id, "inviteeId": inv.invitee_id, "status": inv.status}
            for inv in family.invites
            if inv.status == "pending"
        ],
    }


@router.get("/family")
def get_family(db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    family = crud.get_family(db, user_id)
    if not family:
        return {"family": None}
    return {"family": _family_out(family, db)}


@router.post("/family/create")
def create_family(body: dict, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    try:
        family = crud.create_family(db, user_id, body.get("name") or "Семья")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"family": _family_out(family, db)}


@router.post("/family/leave")
def leave_family(db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    try:
        crud.leave_family(db, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"family": None}


@router.get("/family/invites")
def get_incoming_invites(db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """Входящие ожидающие приглашения для текущего пользователя."""
    invites = (
        db.query(models.FamilyInvite)
        .filter(models.FamilyInvite.invitee_id == user_id, models.FamilyInvite.status == "pending")
        .all()
    )
    result = []
    for inv in invites:
        family = db.get(models.Family, inv.family_id)
        result.append(
            {
                "id": inv.id,
                "familyId": inv.family_id,
                "familyName": family.name if family else "Семья",
                "inviterId": inv.inviter_id,
            }
        )
    return {"invites": result}


@router.post("/family/invite")
def invite_to_family(body: dict, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    try:
        invite = crud.invite_to_family(db, user_id, int(body.get("inviteeTelegramId") or 0))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "inviteId": invite.id}


@router.post("/family/accept")
def accept_invite(body: dict, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    family_id = int(body.get("familyId") or 0)
    try:
        family = crud.join_family(db, user_id, family_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"family": _family_out(family, db)}


# Семейные цели
@router.get("/family/goals")
def get_family_goals(db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    family = crud.get_family(db, user_id)
    if not family:
        raise HTTPException(status_code=400, detail="Вы не в семье")
    return {"goals": [_family_goal_out(g) for g in family.goals]}


@router.post("/family/goals")
def create_family_goal(body: schemas.FamilyGoalIn, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    family = crud.get_family(db, user_id)
    if not family:
        raise HTTPException(status_code=400, detail="Вы не в семье")
    try:
        goal = crud.create_family_goal(db, family.id, body.name, body.icon, body.target_amount, body.target_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _family_goal_out(goal)


@router.post("/family/goals/{goal_id}/topup")
def topup_family_goal(goal_id: int, body: schemas.TopUpIn, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    goal = db.get(models.FamilyGoal, goal_id)
    if not goal:
        raise HTTPException(status_code=404, detail="Общая цель не найдена")
    family = crud.get_family(db, user_id)
    if not family or goal.family_id != family.id:
        raise HTTPException(status_code=403, detail="Вы не участник этой семьи")
    try:
        crud.topup_family_goal(db, goal, user_id, body.amount)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.refresh(goal)
    return _family_goal_out(goal)


@router.post("/reset", response_model=schemas.StateOut)
def reset_all(db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    user = crud.get_or_create_user(db, user_id)
    crud.reset_all(db, user)
    db.refresh(user)
    return _state_out(user)
