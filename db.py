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


# ---- The agent's own wallet (the "save a card in the app" path)

# One saved card per user. Only Stripe's references and display details are kept:
# the card number never reaches this app.
wallets = Table(
    "wallets", metadata,
    Column("user_id", Integer, primary_key=True),
    Column("customer_id", String(80), nullable=False),
    Column("payment_method_id", String(80)),
    Column("brand", String(30)),
    Column("last4", String(4)),
    Column("exp_month", Integer),
    Column("exp_year", Integer),
    Column("updated_at", Integer, nullable=False),
)

# What the buyer has authorised the agent to spend: a cap and an end date.
mandates = Table(
    "mandates", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, nullable=False, index=True),
    Column("cap", Integer, nullable=False),  # cents
    Column("spent", Integer, nullable=False, default=0),  # cents, including in-flight purchases
    Column("currency", String(3), nullable=False),
    Column("expires_at", Integer, nullable=False),
    Column("status", String(20), nullable=False),  # active, revoked, replaced
    Column("created_at", Integer, nullable=False),
)

# One row per "Buy all" click. The client's key makes a double click harmless.
purchases = Table(
    "purchases", metadata,
    Column("id", String(40), primary_key=True),
    Column("user_id", Integer, nullable=False, index=True),
    Column("client_key", String(80), nullable=False),
    Column("mandate_id", Integer),
    Column("status", String(20), nullable=False),  # started, completed, blocked, failed
    Column("total", Integer),
    Column("result", Text),  # JSON returned to the browser
    Column("created_at", Integer, nullable=False),
    UniqueConstraint("user_id", "client_key"),
)

# The agent activity log shown on the Basket page.
agent_events = Table(
    "agent_events", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, nullable=False, index=True),
    Column("purchase_id", String(40)),
    Column("kind", String(30), nullable=False),  # info, ok, blocked, error
    Column("message", Text, nullable=False),
    Column("created_at", Integer, nullable=False),
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
