"""The database: user accounts and the demo shop's checkouts.

DATABASE_URL picks where data lives:
  - not set:  a local SQLite file, instance/app.db (fine on your laptop)
  - set:      a Postgres database, e.g. a free Neon database (needed on Render, because
              Render's free plan wipes local files whenever the service restarts or sleeps)
"""
from __future__ import annotations

import os
import time

from sqlalchemy import (Column, Integer, MetaData, String, Table, Text, UniqueConstraint,
                        create_engine)

metadata = MetaData()

users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True),
    Column("email", String(254), nullable=False, unique=True),
    Column("password_hash", String(255), nullable=False),
    Column("created_at", Integer, nullable=False),
)

# One row per checkout at North Pole Gift Co (the demo seller).
shop_checkouts = Table(
    "shop_checkouts", metadata,
    Column("id", String(40), primary_key=True),
    Column("status", String(30), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("line_items", Text, nullable=False),  # JSON
    Column("total", Integer, nullable=False),  # in cents
    Column("buyer_email", String(254)),
    Column("payment_intent_id", String(80)),
    Column("order_id", String(40)),
    Column("error", Text),
    Column("created_at", Integer, nullable=False),
    Column("completed_at", Integer),
)

# Remembers each Idempotency-Key the shop has seen, so a retried request gets the same
# answer instead of charging twice.
shop_idempotency = Table(
    "shop_idempotency", metadata,
    Column("id", Integer, primary_key=True),
    Column("checkout_id", String(40), nullable=False),
    Column("key", String(255), nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column("status_code", Integer, nullable=False),
    Column("response", Text, nullable=False),  # JSON
    Column("created_at", Integer, nullable=False),
    UniqueConstraint("checkout_id", "key"),
)


def database_url(settings: dict) -> str:
    url = (settings.get("DATABASE_URL") or "").strip()
    if not url:
        os.makedirs("instance", exist_ok=True)
        return "sqlite:///instance/app.db"
    # Neon, Render and Heroku hand out postgres:// URLs; SQLAlchemy wants the driver named.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def connect(settings: dict):
    """Create the engine and make sure the tables exist."""
    url = database_url(settings)
    engine = create_engine(url, pool_pre_ping=True, future=True)
    metadata.create_all(engine)
    return engine


def now() -> int:
    return int(time.time())


def kind(engine) -> str:
    return "postgres" if engine.dialect.name.startswith("postgres") else engine.dialect.name
