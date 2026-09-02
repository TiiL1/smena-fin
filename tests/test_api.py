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
