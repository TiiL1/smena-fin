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


def _advance_paid_for_month(transactions: list[dict], for_month: str, default_advance: float) -> float:
    advance_tx = next(
        (t for t in reversed(transactions) if t["type"] == "advance" and t["for_month"] == for_month),
        None,
    )
    return advance_tx["actual_amount"] if advance_tx else default_advance


def _salary_calculated_amount(
    for_month: str,
    shifts: list[dict],
    transactions: list[dict],
    rate: float,
    default_advance: float,
    employer_debt: float,
) -> float:
    accrued = accrued_for_month(shifts, for_month, rate)
    advance_paid = _advance_paid_for_month(transactions, for_month, default_advance)
    return accrued - advance_paid + employer_debt


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
    return PayoutEvent(
        type="salary",
        date=salary_date.isoformat(),
        for_month=for_month,
        calculated_amount=_salary_calculated_amount(
            for_month, shifts, transactions, rate, default_advance, employer_debt
        ),
    )


def find_pending_salary_month(today: date, shifts: list[dict], transactions: list[dict]) -> str:
    """The oldest worked month that has no salary transaction logged yet —
    lets the person log an overdue salary even after the calendar has
    already moved on to advance season. Only months with actual shifts are
    considered "pending"; a month nobody worked was never owed a salary."""
    last_ended_month = shift_month_key(to_month_key(today), -1)
    paid_months = {t["for_month"] for t in transactions if t["type"] == "salary"}
    worked_months = sorted({s["date"][:7] for s in shifts if s["date"][:7] <= last_ended_month})
    for month in worked_months:
        if month not in paid_months:
            return month
    return last_ended_month


def payout_event_for_type(
    requested_type: str,
    today: date,
    shifts: list[dict],
    transactions: list[dict],
    rate: float,
    default_advance: float,
    employer_debt: float,
) -> PayoutEvent:
    """Same idea as get_next_payout_event, but for a type the person picked
    by hand rather than the one the calendar would auto-suggest — so a
    delayed salary can still be logged after the 10th has already passed."""
    if requested_type == "advance":
        for_month = to_month_key(today)
        return PayoutEvent(
            type="advance",
            date=today.isoformat(),
            for_month=for_month,
            calculated_amount=default_advance + employer_debt,
        )

    for_month = find_pending_salary_month(today, shifts, transactions)
    return PayoutEvent(
        type="salary",
        date=today.isoformat(),
        for_month=for_month,
        calculated_amount=_salary_calculated_amount(
            for_month, shifts, transactions, rate, default_advance, employer_debt
        ),
    )


def describe_payout_type(payout_type: str) -> str:
    return "Аванс" if payout_type == "advance" else "Зарплата"


AVG_DAYS_PER_MONTH = 30.44
PACE_WINDOW_DAYS = 90


@dataclass
class GoalProjection:
    pace_monthly: float  # actual average monthly pace from recent contributions
    required_monthly: float | None  # None when the goal has no target_date
    eta_date: str | None  # 'YYYY-MM-DD' at current pace, None if pace is 0
    on_track: bool | None  # None when there's no target_date to compare against
    reached: bool


def goal_projection(
    today: date,
    current_amount: float,
    target_amount: float,
    target_date: str | None,
    created_at: date,
    contributions: list[dict],  # [{"amount": float, "date": date}, ...]
) -> GoalProjection:
    remaining = target_amount - current_amount
    if remaining <= 0:
        return GoalProjection(pace_monthly=0, required_monthly=0, eta_date=None, on_track=True, reached=True)

    window_start = max(created_at, today - timedelta(days=PACE_WINDOW_DAYS))
    elapsed_days = max((today - window_start).days, 1)
    windowed_total = sum(c["amount"] for c in contributions if c["date"] >= window_start)
    pace_monthly = (windowed_total / elapsed_days) * AVG_DAYS_PER_MONTH

    eta_date = None
    if pace_monthly > 0:
        months_to_go = remaining / pace_monthly
        eta_date = (today + timedelta(days=months_to_go * AVG_DAYS_PER_MONTH)).isoformat()

    required_monthly = None
    on_track = None
    if target_date:
        target = date.fromisoformat(target_date)
        months_remaining = max((target - today).days, 0) / AVG_DAYS_PER_MONTH
        if months_remaining > 0:
            required_monthly = remaining / months_remaining
            on_track = pace_monthly >= required_monthly
        else:
            required_monthly = remaining
            on_track = False

    return GoalProjection(
        pace_monthly=pace_monthly,
        required_monthly=required_monthly,
        eta_date=eta_date,
        on_track=on_track,
        reached=False,
    )


# Re-exported for callers that just want "tomorrow"/date math without importing timedelta.
__all__ = [
    "GoalProjection",
    "PayoutEvent",
    "accrued_for_month",
    "describe_payout_type",
    "find_pending_salary_month",
    "get_next_payout_event",
    "goal_projection",
    "payout_event_for_type",
    "shift_month_key",
    "to_month_key",
    "timedelta",
]
