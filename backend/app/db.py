import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DATABASE_URL

_connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    # FastAPI serves requests from multiple threads; SQLite needs this flag.
    _connect_args["check_same_thread"] = False

engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def add_missing_columns() -> list[str]:
    """Additive schema upgrade for databases created by an older version.

    create_all() creates missing TABLES but never alters existing ones, so a
    new model column would make every query on an old sentinel.db fail. This
    adds any model column absent from its table (all such columns are
    nullable, so ALTER TABLE ADD COLUMN is safe on SQLite and PostgreSQL).
    Never drops or changes anything. Returns the added "table.column" names.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    added = []
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # create_all() made it with every column
            have = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in have or not column.nullable:
                    continue
                col_type = column.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {col_type}'))
                added.append(f"{table.name}.{column.name}")
    if added:
        logging.getLogger("sentinel.db").info("schema upgrade: added columns %s", ", ".join(added))
    return added


def get_db():
    """FastAPI dependency yielding a request-scoped SQLAlchemy session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
