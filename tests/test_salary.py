from datetime import date

import pytest

from app.salary import find_pending_salary_month, get_next_payout_event, goal_projection, payout_event_for_type


def test_advance_then_salary_with_underpaid_debt():
    shifts = [{"date": f"2026-08-{d:02d}", "coefficient": 1} for d in range(1, 21)]
    transactions: list[dict] = []
    employer_debt = 0.0
    rate, default_advance = 8650, 80000

    # Aug 20 -> next event is the Aug 25 advance
    ev = get_next_payout_event(date(2026, 8, 20), shifts, transactions, rate, default_advance, employer_debt)
    assert ev.type == "advance"
    assert ev.date == "2026-08-25"
    assert ev.calculated_amount == 80000

    # Advance actually paid was only 75000 -> 5000 shortfall becomes employer debt
    actual_advance = 75000
    employer_debt = ev.calculated_amount - actual_advance
    transactions.append({"type": "advance", "for_month": ev.for_month, "actual_amount": actual_advance})
    assert employer_debt == 5000

    # Two more shifts before month end: total 21.5 units in August
    shifts.append({"date": "2026-08-28", "coefficient": 1})
    shifts.append({"date": "2026-08-31", "coefficient": 0.5})

    # Sep 5 -> next event is the Sep 10 salary for August
    ev = get_next_payout_event(date(2026, 9, 5), shifts, transactions, rate, default_advance, employer_debt)
    assert ev.type == "salary"
    assert ev.date == "2026-09-10"
    assert ev.for_month == "2026-08"
    # 21.5 * 8650 - 75000 + 5000 = 115975
    assert ev.calculated_amount == 115975

    # Paid exactly as calculated -> debt resets to zero
    assert ev.calculated_amount - ev.calculated_amount == 0

    # Overpaid by 3000 -> debt goes negative (will be deducted next time)
    assert ev.calculated_amount - (ev.calculated_amount + 3000) == -3000


def test_right_after_salary_next_event_is_next_advance():
    ev = get_next_payout_event(date(2026, 9, 11), [], [], 8650, 80000, 0)
    assert ev.type == "advance"
    assert ev.date == "2026-09-25"
    assert ev.for_month == "2026-09"


def test_event_due_exactly_today_counts_as_next():
    ev = get_next_payout_event(date(2026, 8, 25), [], [], 8650, 80000, 0)
    assert ev.date == "2026-08-25"
    ev2 = get_next_payout_event(date(2026, 9, 10), [], [], 8650, 80000, 0)
    assert ev2.date == "2026-09-10"


# --- manual payout-type override -------------------------------------------------


def test_manual_advance_override_always_uses_current_month():
    # Even mid-cycle (auto-suggestion here would be "salary"), forcing
    # "advance" should compute the advance for the current calendar month.
    ev = payout_event_for_type("advance", date(2026, 9, 5), [], [], 8650, 80000, 0)
    assert ev.type == "advance"
    assert ev.for_month == "2026-09"
    assert ev.calculated_amount == 80000


def test_find_pending_salary_month_skips_already_paid_months():
    shifts = [{"date": "2026-07-05", "coefficient": 1}, {"date": "2026-08-05", "coefficient": 1}]
    transactions = [{"type": "salary", "for_month": "2026-07", "actual_amount": 100000}]
    # Today is Sep 12 (past the 10th, auto-suggestion would already be "advance"),
    # but August's salary was never logged -> that's the pending one, not July.
    pending = find_pending_salary_month(date(2026, 9, 12), shifts, transactions)
    assert pending == "2026-08"


def test_find_pending_salary_month_when_nothing_is_pending_falls_back_to_last_month():
    shifts = [{"date": "2026-08-05", "coefficient": 1}]
    transactions = [{"type": "salary", "for_month": "2026-08", "actual_amount": 1}]
    pending = find_pending_salary_month(date(2026, 9, 12), shifts, transactions)
    assert pending == "2026-08"


def test_find_pending_salary_month_ignores_months_nobody_worked():
    # No shifts at all yet -> nothing is genuinely "pending", just show the
    # most recently ended month as a sensible default.
    pending = find_pending_salary_month(date(2026, 9, 12), [], [])
    assert pending == "2026-08"


def test_manual_salary_override_after_the_10th_finds_the_overdue_month():
    shifts = [{"date": f"2026-08-{d:02d}", "coefficient": 1} for d in range(1, 21)]
    transactions = [{"type": "advance", "for_month": "2026-08", "actual_amount": 80000}]
    # Sep 12: auto-suggestion has already moved on to "advance", but the person
    # hasn't received August's salary yet -> manual override should still find it.
    ev = payout_event_for_type("salary", date(2026, 9, 12), shifts, transactions, 8650, 80000, 0)
    assert ev.type == "salary"
    assert ev.for_month == "2026-08"
    assert ev.calculated_amount == 20 * 8650 - 80000


# --- goal target-date projection --------------------------------------------------


def test_goal_already_reached():
    proj = goal_projection(
        today=date(2026, 9, 1),
        current_amount=100_000,
        target_amount=100_000,
        target_date=None,
        created_at=date(2026, 1, 1),
        contributions=[],
    )
    assert proj.reached is True
    assert proj.on_track is True
    assert proj.eta_date is None


def test_goal_with_no_contributions_has_no_eta():
    proj = goal_projection(
        today=date(2026, 9, 1),
        current_amount=0,
        target_amount=100_000,
        target_date=None,
        created_at=date(2026, 8, 1),
        contributions=[],
    )
    assert proj.reached is False
    assert proj.pace_monthly == 0
    assert proj.eta_date is None
    assert proj.required_monthly is None
    assert proj.on_track is None


def test_goal_pace_projects_a_future_eta():
    proj = goal_projection(
        today=date(2026, 9, 1),
        current_amount=20_000,
        target_amount=100_000,
        target_date=None,
        created_at=date(2026, 7, 3),  # 60 days before "today"
        contributions=[{"amount": 10_000, "date": date(2026, 8, 2)}],  # 30 days before "today"
    )
    expected_pace = (10_000 / 60) * 30.44
    assert proj.pace_monthly == pytest.approx(expected_pace)
    assert proj.eta_date is not None
    assert proj.eta_date > "2026-09-01"


def test_goal_on_track_when_pace_beats_required():
    proj = goal_projection(
        today=date(2026, 9, 1),
        current_amount=0,
        target_amount=10_000,
        target_date="2026-10-01",
        created_at=date(2026, 8, 1),
        contributions=[{"amount": 12_000, "date": date(2026, 8, 15)}],
    )
    assert proj.required_monthly == pytest.approx(10_000, rel=0.05)
    assert proj.pace_monthly > proj.required_monthly
    assert proj.on_track is True


def test_goal_behind_schedule_when_pace_below_required():
    proj = goal_projection(
        today=date(2026, 9, 1),
        current_amount=0,
        target_amount=100_000,
        target_date="2026-10-01",
        created_at=date(2026, 8, 1),
        contributions=[{"amount": 1_000, "date": date(2026, 8, 15)}],
    )
    assert proj.pace_monthly < proj.required_monthly
    assert proj.on_track is False


def test_goal_target_date_already_passed_is_never_on_track():
    proj = goal_projection(
        today=date(2026, 9, 1),
        current_amount=50_000,
        target_amount=100_000,
        target_date="2026-08-01",
        created_at=date(2026, 1, 1),
        contributions=[{"amount": 50_000, "date": date(2026, 8, 15)}],
    )
    assert proj.on_track is False
    assert proj.required_monthly == 50_000
