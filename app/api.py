from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from . import crud, models, schemas
from .auth import get_current_user_id
from .db import get_db

router = APIRouter(prefix="/api")


def _state_out(user: models.User) -> schemas.StateOut:
    return schemas.StateOut(
        shifts=[schemas.ShiftOut.model_validate(s, from_attributes=True) for s in user.shifts],
        transactions=[
            schemas.TransactionOut.model_validate(t, from_attributes=True) for t in user.transactions
        ],
        goals=[schemas.GoalOut.model_validate(g, from_attributes=True) for g in user.goals],
        unallocated_balance=user.unallocated_balance,
        employer_debt=user.employer_debt,
        settings=schemas.SettingsOut(rate=user.rate, default_advance=user.default_advance),
    )


def _get_goal_or_404(user: models.User, goal_id: int) -> models.Goal:
    goal = next((g for g in user.goals if g.id == goal_id), None)
    if goal is None:
        raise HTTPException(status_code=404, detail="Цель не найдена")
    return goal


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
    crud.receive_payout(db, user, body.actual_amount)
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
    crud.update_goal(db, goal, body.model_dump())
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


@router.post("/reset", response_model=schemas.StateOut)
def reset_all(db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    user = crud.get_or_create_user(db, user_id)
    crud.reset_all(db, user)
    db.refresh(user)
    return _state_out(user)
