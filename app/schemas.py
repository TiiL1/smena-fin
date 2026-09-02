from datetime import datetime

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ShiftOut(CamelModel):
    date: str
    coefficient: float


class TransactionOut(CamelModel):
    id: int
    type: str
    for_month: str
    calculated_amount: float
    actual_amount: float
    debt_after: float
    received_at: datetime


class GoalOut(CamelModel):
    id: int
    name: str
    icon: str
    target_amount: float
    current_amount: float
    split_percent: float


class SettingsOut(CamelModel):
    rate: float
    default_advance: float


class StateOut(CamelModel):
    shifts: list[ShiftOut]
    transactions: list[TransactionOut]
    goals: list[GoalOut]
    unallocated_balance: float
    employer_debt: float
    settings: SettingsOut


class CycleShiftIn(CamelModel):
    date: str


class PayoutIn(CamelModel):
    actual_amount: float


class GoalIn(CamelModel):
    name: str
    icon: str
    target_amount: float
    split_percent: float = 0


class GoalPatchIn(CamelModel):
    name: str | None = None
    icon: str | None = None
    target_amount: float | None = None
    split_percent: float | None = None


class TopUpIn(CamelModel):
    amount: float


class SettingsPatchIn(CamelModel):
    rate: float | None = None
    default_advance: float | None = None
