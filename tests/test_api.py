from datetime import date

from fastapi.testclient import TestClient

from app import crud
from app.main import app
from .helpers import auth_header

USER = 555111


def client():
    return TestClient(app)


def test_health_needs_no_auth():
    with client() as c:
        r = c.get("/api/health")
        assert r.status_code == 200
        assert r.json() == {"ok": True}


def test_state_requires_auth():
    with client() as c:
        r = c.get("/api/state")
        assert r.status_code == 401


def test_new_user_gets_default_goals_and_settings():
    with client() as c:
        r = c.get("/api/state", headers=auth_header(USER))
        assert r.status_code == 200
        body = r.json()
        assert body["settings"] == {"rate": 8650, "defaultAdvance": 80000}
        assert body["unallocatedBalance"] == 0
        assert body["employerDebt"] == 0
        assert len(body["goals"]) == 3
        assert {g["name"] for g in body["goals"]} == {"Фонд поездки", "Инвестиции", "Подушка безопасности"}


def test_cycle_shift_goes_full_half_gone():
    with client() as c:
        h = auth_header(USER + 1)
        r = c.post("/api/shifts/cycle", json={"date": "2026-08-05"}, headers=h)
        assert r.json()["shifts"] == [{"date": "2026-08-05", "coefficient": 1}]

        r = c.post("/api/shifts/cycle", json={"date": "2026-08-05"}, headers=h)
        assert r.json()["shifts"] == [{"date": "2026-08-05", "coefficient": 0.5}]

        r = c.post("/api/shifts/cycle", json={"date": "2026-08-05"}, headers=h)
        assert r.json()["shifts"] == []


def test_full_payout_and_split_flow(monkeypatch):
    # Pin "today" so the test doesn't depend on the real wall-clock date: with
    # today = Aug 20 2026, the next payout event is deterministically the
    # Aug 25 advance, regardless of when this test actually runs.
    monkeypatch.setattr(crud.config, "today", lambda: date(2026, 8, 20))
    with client() as c:
        h = auth_header(USER + 2)

        for d in range(1, 21):
            c.post("/api/shifts/cycle", json={"date": f"2026-08-{d:02d}"}, headers=h)
        c.post("/api/shifts/cycle", json={"date": "2026-08-28"}, headers=h)
        # third tap would be needed for a half shift; do it via two cycles
        c.post("/api/shifts/cycle", json={"date": "2026-08-31"}, headers=h)
        c.post("/api/shifts/cycle", json={"date": "2026-08-31"}, headers=h)  # now 0.5

        # Pay the Aug 25 advance as 75000 instead of the default 80000.
        r = c.post("/api/payout", json={"actualAmount": 75000}, headers=h)
        body = r.json()
        assert body["employerDebt"] == 5000
        assert body["unallocatedBalance"] == 75000
        assert body["transactions"][-1]["type"] == "advance"
        assert body["transactions"][-1]["calculatedAmount"] == 80000

        # Settings changes and goal management should also round-trip correctly.
        r = c.patch("/api/settings", json={"rate": 9000}, headers=h)
        assert r.json()["settings"]["rate"] == 9000

        r = c.post(
            "/api/goals",
            json={"name": "Ноутбук", "icon": "laptop", "targetAmount": 200000, "splitPercent": 50},
            headers=h,
        )
        goals = r.json()["goals"]
        assert any(g["name"] == "Ноутбук" for g in goals)

        r = c.post("/api/split", headers=h)
        body = r.json()
        assert body["unallocatedBalance"] < 75000
        laptop_goal = next(g for g in body["goals"] if g["name"] == "Ноутбук")
        assert laptop_goal["currentAmount"] > 0

        goal_id = laptop_goal["id"]
        r = c.delete(f"/api/goals/{goal_id}", headers=h)
        body = r.json()
        assert not any(g["id"] == goal_id for g in body["goals"])
        # money from the deleted goal must come back to the unallocated balance
        assert body["unallocatedBalance"] > 0

        r = c.post("/api/reset", headers=h)
        body = r.json()
        assert body["unallocatedBalance"] == 0
        assert body["employerDebt"] == 0
        assert body["shifts"] == []
        assert len(body["goals"]) == 3


def test_goal_split_never_overallocates_past_100_percent():
    with client() as c:
        h = auth_header(USER + 3)
        c.post("/api/payout", json={"actualAmount": 100000}, headers=h)  # seed a balance
        # Push total split percent well past 100% across the 3 default goals + a new one.
        c.post(
            "/api/goals",
            json={"name": "Экстра", "icon": "gift", "targetAmount": 100000, "splitPercent": 100},
            headers=h,
        )
        r = c.post("/api/split", headers=h)
        body = r.json()
        total_allocated = sum(g["currentAmount"] for g in body["goals"])
        assert total_allocated <= 100000
        assert body["unallocatedBalance"] >= 0


def test_goal_not_owned_by_user_is_404():
    with client() as c:
        h1 = auth_header(USER + 4)
        h2 = auth_header(USER + 5)
        r = c.get("/api/state", headers=h1)
        goal_id = r.json()["goals"][0]["id"]
        r = c.patch(f"/api/goals/{goal_id}", json={"name": "Hacked"}, headers=h2)
        assert r.status_code == 404


def test_goal_target_date_projection_and_clearing():
    with client() as c:
        h = auth_header(USER + 6)
        c.post("/api/payout", json={"actualAmount": 50000}, headers=h)  # seed a balance

        r = c.post(
            "/api/goals",
            json={
                "name": "Отпуск",
                "icon": "plane",
                "targetAmount": 100000,
                "splitPercent": 0,
                "targetDate": "2026-12-01",
            },
            headers=h,
        )
        assert r.status_code == 200
        goal = next(g for g in r.json()["goals"] if g["name"] == "Отпуск")
        assert goal["targetDate"] == "2026-12-01"
        assert goal["projection"]["reached"] is False
        assert goal["projection"]["requiredMonthly"] is not None

        goal_id = goal["id"]
        r = c.post(f"/api/goals/{goal_id}/topup", json={"amount": 20000}, headers=h)
        goal = next(g for g in r.json()["goals"] if g["id"] == goal_id)
        assert goal["currentAmount"] == 20000
        assert goal["projection"]["paceMonthly"] >= 0

        r = c.patch(f"/api/goals/{goal_id}", json={"targetDate": None}, headers=h)
        goal = next(g for g in r.json()["goals"] if g["id"] == goal_id)
        assert goal["targetDate"] is None
        assert goal["projection"]["requiredMonthly"] is None
        assert goal["projection"]["onTrack"] is None


def test_goal_reached_projection():
    with client() as c:
        h = auth_header(USER + 7)
        c.post("/api/payout", json={"actualAmount": 100000}, headers=h)
        r = c.post(
            "/api/goals",
            json={"name": "Мелочь", "icon": "gift", "targetAmount": 1000, "splitPercent": 0},
            headers=h,
        )
        goal_id = next(g for g in r.json()["goals"] if g["name"] == "Мелочь")["id"]
        r = c.post(f"/api/goals/{goal_id}/topup", json={"amount": 1000}, headers=h)
        goal = next(g for g in r.json()["goals"] if g["id"] == goal_id)
        assert goal["currentAmount"] == goal["targetAmount"]
        assert goal["projection"]["reached"] is True
        assert goal["projection"]["onTrack"] is True


def test_manual_payout_type_lets_you_log_an_overdue_salary(monkeypatch):
    # Sep 12: auto-suggestion has moved on to "advance", but August's salary
    # was never logged — the person should still be able to force "salary".
    monkeypatch.setattr(crud.config, "today", lambda: date(2026, 9, 12))
    with client() as c:
        h = auth_header(USER + 8)
        for d in range(1, 21):
            c.post("/api/shifts/cycle", json={"date": f"2026-08-{d:02d}"}, headers=h)
        c.post("/api/payout", json={"actualAmount": 80000, "type": "advance"}, headers=h)

        r = c.post("/api/payout", json={"actualAmount": 90000, "type": "salary"}, headers=h)
        assert r.status_code == 200
        tx = r.json()["transactions"][-1]
        assert tx["type"] == "salary"
        assert tx["forMonth"] == "2026-08"


def test_duplicate_payout_for_same_period_is_rejected(monkeypatch):
    monkeypatch.setattr(crud.config, "today", lambda: date(2026, 8, 20))
    with client() as c:
        h = auth_header(USER + 9)
        c.post("/api/payout", json={"actualAmount": 80000}, headers=h)
        r = c.post("/api/payout", json={"actualAmount": 80000}, headers=h)
        assert r.status_code == 409


def test_expense_flow_spends_and_refunds_balance():
    with client() as c:
        h = auth_header(USER + 10)
        c.post("/api/payout", json={"actualAmount": 50000}, headers=h)

        r = c.post(
            "/api/expenses",
            json={"amount": 3500, "category": "Еда", "note": "обед"},
            headers=h,
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["expenses"]) == 1
        assert body["expenses"][0]["category"] == "Еда"
        assert body["unallocatedBalance"] == 46500

        expense_id = body["expenses"][0]["id"]
        r = c.delete(f"/api/expenses/{expense_id}", headers=h)
        body = r.json()
        assert body["expenses"] == []
        assert body["unallocatedBalance"] == 50000


def test_expense_validation_rejects_zero_amount():
    with client() as c:
        h = auth_header(USER + 11)
        r = c.post("/api/expenses", json={"amount": 0, "category": "Еда"}, headers=h)
        assert r.status_code == 400


def test_fixed_cost_crud():
    with client() as c:
        h = auth_header(USER + 12)
        r = c.post("/api/fixed-costs", json={"name": "Аренда", "amount": 120000, "day": 5}, headers=h)
        assert r.status_code == 200
        assert r.json()["fixedCosts"][0]["name"] == "Аренда"

        cost_id = r.json()["fixedCosts"][0]["id"]
        r = c.patch(f"/api/fixed-costs/{cost_id}", json={"amount": 130000}, headers=h)
        assert r.json()["fixedCosts"][0]["amount"] == 130000

        r = c.delete(f"/api/fixed-costs/{cost_id}", headers=h)
        assert r.json()["fixedCosts"] == []


def test_fixed_cost_validation_rejects_empty_name():
    with client() as c:
        h = auth_header(USER + 13)
        r = c.post("/api/fixed-costs", json={"name": "", "amount": 1000, "day": 1}, headers=h)
        assert r.status_code == 400


def test_reset_clears_expenses_and_fixed_costs():
    with client() as c:
        h = auth_header(USER + 14)
        c.post("/api/payout", json={"actualAmount": 50000}, headers=h)
        c.post("/api/expenses", json={"amount": 1000, "category": "Еда"}, headers=h)
        c.post("/api/fixed-costs", json={"name": "Аренда", "amount": 50000, "day": 5}, headers=h)
        r = c.post("/api/reset", headers=h)
        body = r.json()
        assert body["expenses"] == []
        assert body["fixedCosts"] == []
        assert body["unallocatedBalance"] == 0


def test_expense_of_other_user_is_404():
    with client() as c:
        h1 = auth_header(USER + 15)
        h2 = auth_header(USER + 16)
        c.post("/api/payout", json={"actualAmount": 50000}, headers=h1)
        r = c.post("/api/expenses", json={"amount": 1000, "category": "Еда"}, headers=h1)
        expense_id = r.json()["expenses"][0]["id"]
        r = c.delete(f"/api/expenses/{expense_id}", headers=h2)
        assert r.status_code == 404


def test_withdraw_from_goal_returns_money_to_balance():
    with client() as c:
        h = auth_header(USER + 17)
        c.post("/api/payout", json={"actualAmount": 50000}, headers=h)
        r = c.post("/api/split", headers=h)
        body = r.json()
        assert body["unallocatedBalance"] < 50000
        goal = next(g for g in body["goals"] if g["currentAmount"] > 0)
        goal_id = goal["id"]
        before_balance = body["unallocatedBalance"]
        before_goal = goal["currentAmount"]

        r = c.post(f"/api/goals/{goal_id}/withdraw", json={"amount": 5000}, headers=h)
        assert r.status_code == 200
        body = r.json()
        goal_after = next(g for g in body["goals"] if g["id"] == goal_id)
        assert goal_after["currentAmount"] == before_goal - 5000
        assert body["unallocatedBalance"] == before_balance + 5000


def test_withdraw_full_goal_amount():
    with client() as c:
        h = auth_header(USER + 18)
        c.post("/api/payout", json={"actualAmount": 50000}, headers=h)
        r = c.post("/api/split", headers=h)
        goal = next(g for g in r.json()["goals"] if g["currentAmount"] > 0)
        r = c.post(f"/api/goals/{goal['id']}/withdraw", json={"amount": goal["currentAmount"]}, headers=h)
        assert r.status_code == 200
        goal_after = next(g for g in r.json()["goals"] if g["id"] == goal["id"])
        assert goal_after["currentAmount"] == 0


def test_withdraw_more_than_saved_is_rejected():
    with client() as c:
        h = auth_header(USER + 19)
        c.post("/api/payout", json={"actualAmount": 50000}, headers=h)
        r = c.post("/api/split", headers=h)
        goal = next(g for g in r.json()["goals"] if g["currentAmount"] > 0)
        r = c.post(
            f"/api/goals/{goal['id']}/withdraw", json={"amount": goal["currentAmount"] + 1000}, headers=h
        )
        assert r.status_code == 400


def test_withdraw_zero_is_rejected():
    with client() as c:
        h = auth_header(USER + 20)
        c.post("/api/payout", json={"actualAmount": 50000}, headers=h)
        r = c.post("/api/split", headers=h)
        goal = next(g for g in r.json()["goals"] if g["currentAmount"] > 0)
        r = c.post(f"/api/goals/{goal['id']}/withdraw", json={"amount": 0}, headers=h)
        assert r.status_code == 400


def test_withdraw_goal_of_other_user_is_404():
    with client() as c:
        h1 = auth_header(USER + 21)
        h2 = auth_header(USER + 22)
        c.post("/api/payout", json={"actualAmount": 50000}, headers=h1)
        r = c.post("/api/split", headers=h1)
        goal = next(g for g in r.json()["goals"] if g["currentAmount"] > 0)
        r = c.post(f"/api/goals/{goal['id']}/withdraw", json={"amount": 1000}, headers=h2)
        assert r.status_code == 404
