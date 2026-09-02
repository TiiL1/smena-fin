from datetime import date

from app.salary import get_next_payout_event


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
