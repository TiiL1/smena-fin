import tempfile

from sqlalchemy import create_engine, inspect, text

from app import db as db_module
from app import models  # noqa: F401  (ensure models are registered on Base.metadata)


def test_add_missing_columns_extends_an_existing_table_in_place():
    path = tempfile.mktemp(suffix=".db")
    isolated_engine = create_engine(f"sqlite:///{path}")

    # Simulate a "goals" table from before target_date/created_at existed.
    with isolated_engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE goals ("
                "id INTEGER PRIMARY KEY, user_id INTEGER, name VARCHAR(100), "
                "icon VARCHAR(30), target_amount FLOAT, current_amount FLOAT, "
                "split_percent FLOAT)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO goals (id, user_id, name, icon, target_amount, current_amount, split_percent) "
                "VALUES (1, 111, 'Old goal', 'shield', 1000, 500, 20)"
            )
        )

    db_module.Base.metadata.create_all(bind=isolated_engine)
    db_module._add_missing_columns(isolated_engine)

    inspector = inspect(isolated_engine)
    columns = {c["name"] for c in inspector.get_columns("goals")}
    assert "target_date" in columns
    assert "created_at" in columns

    with isolated_engine.begin() as conn:
        row = conn.execute(text("SELECT name, target_date, created_at FROM goals WHERE id = 1")).fetchone()
    assert row[0] == "Old goal"
    assert row[1] is None  # optional field: stays empty, no fabricated date
    assert row[2] is not None  # datetime field: backfilled instead of left NULL

    assert "goal_contributions" in inspector.get_table_names()


def _create_legacy_expenses_incomes(conn, engine):
    """Legacy tables created without the `tag` column (tag was added later by
    _add_missing_columns on production, leaving NULL for pre-existing rows)."""
    conn.execute(
        text(
            "CREATE TABLE expenses ("
            "id INTEGER PRIMARY KEY, user_id INTEGER, amount FLOAT, "
            "category VARCHAR(50), note VARCHAR(200), spent_at VARCHAR(10))"
        )
    )
    conn.execute(
        text(
            "CREATE TABLE incomes ("
            "id INTEGER PRIMARY KEY, user_id INTEGER, amount FLOAT, "
            "source VARCHAR(50), note VARCHAR(200), received_at VARCHAR(10))"
        )
    )
    conn.execute(
        text(
            "INSERT INTO expenses (id, user_id, amount, category, note, spent_at) "
            "VALUES (1, 111, 1000, 'Еда', 'note', '2025-01-10')"
        )
    )
    conn.execute(
        text(
            "INSERT INTO incomes (id, user_id, amount, source, note, received_at) "
            "VALUES (1, 111, 5000, 'Подработка', 'note', '2025-01-10')"
        )
    )


def test_migration_leaves_null_tags_which_repair_fixes(monkeypatch):
    path = tempfile.mktemp(suffix=".db")
    isolated_engine = create_engine(f"sqlite:///{path}")

    with isolated_engine.begin() as conn:
        _create_legacy_expenses_incomes(conn, isolated_engine)

    db_module.Base.metadata.create_all(bind=isolated_engine)
    db_module._add_missing_columns(isolated_engine)

    with isolated_engine.begin() as conn:
        rows = conn.execute(text("SELECT tag FROM expenses")).fetchall()
        assert rows == [(None,)]
        rows = conn.execute(text("SELECT tag FROM incomes")).fetchall()
        assert rows == [(None,)]

    # Repair is written against the app-global engine, so point it at the
    # isolated engine to verify it rewrites the NULLs.
    monkeypatch.setattr(db_module, "engine", isolated_engine)
    db_module._repair_null_tags()

    with isolated_engine.begin() as conn:
        rows = conn.execute(text("SELECT tag FROM expenses")).fetchall()
        assert rows == [("",)]
        rows = conn.execute(text("SELECT tag FROM incomes")).fetchall()
        assert rows == [("",)]