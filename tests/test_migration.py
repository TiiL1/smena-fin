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
