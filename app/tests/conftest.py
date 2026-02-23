"""
Test fixtures.

Uses SQLite in-memory so tests run without a live PostgreSQL instance.
JSONB columns are shimmed to plain JSON via a SQLAlchemy TypeDecorator override.
"""

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.types import TypeDecorator, Text
import json

from app.database import Base

# ---------------------------------------------------------------------------
# SQLite-compatible JSONB shim
# ---------------------------------------------------------------------------

class _JsonText(TypeDecorator):
    """Store JSON as text for SQLite tests."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return json.dumps(value) if value is not None else None

    def process_result_value(self, value, dialect):
        return json.loads(value) if value is not None else None


# Patch JSONB on all models before any table is created
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import String

# Replace JSONB columns with the shim so SQLite can handle them
from app.models import models as _models  # noqa: E402

for _model in (_models.FactSheet, _models.Document):
    for col in _model.__table__.columns:
        if isinstance(col.type, JSONB):
            col.type = _JsonText()

# Also patch UUID columns (SQLite stores as TEXT natively via String)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
for table in Base.metadata.tables.values():
    for col in table.columns:
        if isinstance(col.type, PG_UUID):
            col.type = String()


# ---------------------------------------------------------------------------
# Session fixture
# ---------------------------------------------------------------------------

SQLITE_URL = "sqlite:///:memory:"


@pytest.fixture()
def db():
    engine = create_engine(
        SQLITE_URL,
        connect_args={"check_same_thread": False},
    )
    # Enable foreign keys in SQLite
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
