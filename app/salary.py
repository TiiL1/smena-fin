"""Mirrors frontend/src/lib/salary.ts. Keep both in sync if the rules change."""

from dataclasses import dataclass
from datetime import date, timedelta


def to_month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def shift_month_key(month_key: str, delta_months: int) -> str:
    y, m = (int(x) for x in month_key.split("-"))
    total = (y * 12 + (m - 1)) + delta_months
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def _next_day_occurrence(today: date, day: int) -> date:
    candidate = date(today.year, today.month, day)
    if today.day <= day:
        return candidate
    if today.month == 12:
        return date(today.year + 1, 1, day)
    return date(today.year, today.month + 1, day)


def accrued_for_month(shifts: list[dict], month_key: str, rate: float) -> float:
    units = sum(s["coefficient"] for s in shifts if s["date"].startswith(month_key))
    return units * rate


@dataclass
class PayoutEvent:
    type: str  # 'advance' | 'salary'
    date: str  # 'YYYY-MM-DD'
    for_month: str  # 'YYYY-MM'
    calculated_amount: float


def get_next_payout_event(
    today: date,
    shifts: list[dict],
    transactions: list[dict],
    rate: float,
    default_advance: float,
    employer_debt: float,
) -> PayoutEvent:
    advance_date = _next_day_occurrence(today, 25)
    salary_date = _next_day_occurrence(today, 10)

    if advance_date <= salary_date:
        for_month = to_month_key(advance_date)
        return PayoutEvent(
            type="advance",
            date=advance_date.isoformat(),
            for_month=for_month,
            calculated_amount=default_advance + employer_debt,
        )

    for_month = shift_month_key(to_month_key(salary_date), -1)
    accrued = accrued_for_month(shifts, for_month, rate)
    advance_tx = next(
        (t for t in reversed(transactions) if t["type"] == "advance" and t["for_month"] == for_month),
        None,
    )
    advance_paid = advance_tx["actual_amount"] if advance_tx else default_advance

    return PayoutEvent(
        type="salary",
        date=salary_date.isoformat(),
        for_month=for_month,
        calculated_amount=accrued - advance_paid + employer_debt,
    )


def describe_payout_type(payout_type: str) -> str:
    return "Аванс" if payout_type == "advance" else "Зарплата"


# Re-exported for callers that just want "tomorrow"/date math without importing timedelta.
__all__ = [
    "PayoutEvent",
    "accrued_for_month",
    "describe_payout_type",
    "get_next_payout_event",
    "shift_month_key",
    "to_month_key",
    "timedelta",
]
