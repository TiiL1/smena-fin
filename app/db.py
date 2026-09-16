from collections.abc import Generator

from sqlalchemy import DateTime, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from . import config

connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(config.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _add_missing_columns(target_engine=None) -> None:
    """For tables that already exist (from a previous deploy), add any columns
    the current models declare but the live database doesn't have yet, so a
    schema change never needs a manual SQL step. New tables are handled by
    create_all below and skipped here. Added columns are always nullable,
    regardless of what the model declares, so this never fails on existing
    rows — datetime columns get backfilled with "now" instead of staying
    NULL, since callers generally assume a real value once the model no
    longer marks the field optional."""
    target_engine = target_engine or engine
    inspector = inspect(target_engine)
    existing_tables = set(inspector.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        existing_columns = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing_columns:
                continue
            col_type = column.type.compile(dialect=target_engine.dialect)
            with target_engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'))
                if isinstance(column.type, DateTime):
                    # A plain UPDATE works the same on SQLite and Postgres;
                    # ADD COLUMN ... DEFAULT CURRENT_TIMESTAMP does not (SQLite
                    # rejects a non-constant default in ALTER TABLE).
                    conn.execute(
                        text(
                            f'UPDATE "{table.name}" SET "{column.name}" = CURRENT_TIMESTAMP '
                            f'WHERE "{column.name}" IS NULL'
                        )
                    )


def init_db() -> None:
    from . import models  # noqa: F401  (ensure models are registered)

    Base.metadata.create_all(bind=engine)
    _add_missing_columns()
