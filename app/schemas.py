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


class GoalProjectionOut(CamelModel):
    pace_monthly: float
    required_monthly: float | None
    eta_date: str | None
    on_track: bool | None
    reached: bool


class GoalOut(CamelModel):
    id: int
    name: str
    icon: str
    target_amount: float
    current_amount: float
    split_percent: float
    target_date: str | None
    projection: GoalProjectionOut


class SettingsOut(CamelModel):
    rate: float
    default_advance: float


class ExpenseOut(CamelModel):
    id: int
    amount: float
    category: str
    tag: str = ""
    note: str
    spent_at: str


class IncomeOut(CamelModel):
    id: int
    amount: float
    source: str
    tag: str = ""
    note: str
    received_at: str


class FixedCostOut(CamelModel):
    id: int
    name: str
    amount: float
    day: int


class StateOut(CamelModel):
    shifts: list[ShiftOut]
    transactions: list[TransactionOut]
    goals: list[GoalOut]
    expenses: list[ExpenseOut]
    incomes: list[IncomeOut]
    fixed_costs: list[FixedCostOut]
    unallocated_balance: float
    employer_debt: float
    settings: SettingsOut


class CycleShiftIn(CamelModel):
    date: str


class PayoutIn(CamelModel):
    actual_amount: float
    type: str | None = None  # 'advance' | 'salary' — overrides the auto-picked one


class GoalIn(CamelModel):
    name: str
    icon: str
    target_amount: float
    split_percent: float = 0
    target_date: str | None = None


class GoalPatchIn(CamelModel):
    name: str | None = None
    icon: str | None = None
    target_amount: float | None = None
    split_percent: float | None = None
    target_date: str | None = None


class TopUpIn(CamelModel):
    amount: float


class WithdrawIn(CamelModel):
    amount: float


class SettingsPatchIn(CamelModel):
    rate: float | None = None
    default_advance: float | None = None


class ExpenseIn(CamelModel):
    amount: float
    category: str = ""
    tag: str | None = None  # если пусто — выведем автоматом
    note: str = ""
    spent_at: str | None = None  # 'YYYY-MM-DD', defaults to today


class IncomeIn(CamelModel):
    amount: float
    source: str = ""
    tag: str | None = None
    note: str = ""
    received_at: str | None = None  # 'YYYY-MM-DD', defaults to today


class FixedCostIn(CamelModel):
    name: str
    amount: float
    day: int = 1


class FixedCostPatchIn(CamelModel):
    name: str | None = None
    amount: float | None = None
    day: int | None = None
