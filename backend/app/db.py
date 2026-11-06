"""Database setup. SQLite by default; set DATABASE_URL to use MySQL or PostgreSQL.

Examples:
    sqlite:///./data/analytics.db
    mysql+pymysql://user:pass@localhost:3306/analytics
    postgresql+psycopg://user:pass@localhost:5432/analytics
"""
import os
from pathlib import Path

from sqlalchemy import (
    Column, Date, DateTime, Float, ForeignKey, Integer, MetaData, String, Table,
    UniqueConstraint, create_engine,
)
from sqlalchemy.engine import Engine

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = f"sqlite:///{BASE_DIR / 'data' / 'analytics.db'}"

metadata = MetaData()

brands = Table(
    "brands", metadata,
    Column("id", Integer, primary_key=True),
    Column("code", String(50), unique=True, nullable=False),
    Column("name", String(120), nullable=False),
    Column("source_currency", String(3), nullable=False),
)

orders = Table(
    "orders", metadata,
    Column("id", Integer, primary_key=True),
    Column("brand_id", Integer, ForeignKey("brands.id"), nullable=False, index=True),
    Column("external_id", String(64), nullable=False),
    Column("customer_email", String(255), nullable=False),
    Column("created_at", DateTime, nullable=False),
    # Pre-computed date buckets keep GROUP BY portable across SQLite / MySQL / Postgres.
    Column("order_date", Date, nullable=False, index=True),
    Column("order_week", String(10), nullable=False),
    Column("order_month", String(7), nullable=False, index=True),
    Column("status", String(20), nullable=False),
    Column("item_count", Integer, nullable=False),
    Column("total_source", Float, nullable=False),
    Column("total_usd", Float, nullable=False),
    UniqueConstraint("brand_id", "external_id", name="uq_order_brand_external"),
)

order_items = Table(
    "order_items", metadata,
    Column("id", Integer, primary_key=True),
    Column("order_id", Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("product", String(200), nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("revenue_usd", Float, nullable=False),
)

subscriptions = Table(
    "subscriptions", metadata,
    Column("id", Integer, primary_key=True),
    Column("brand_id", Integer, ForeignKey("brands.id"), nullable=False, index=True),
    Column("external_id", String(64), nullable=False),
    Column("customer_email", String(255), nullable=False),
    Column("plan", String(50), nullable=False),
    Column("price_usd", Float, nullable=False),
    Column("started_at", Date, nullable=False),
    Column("cancelled_at", Date, nullable=True),
    UniqueConstraint("brand_id", "external_id", name="uq_sub_brand_external"),
)

etl_runs = Table(
    "etl_runs", metadata,
    Column("id", Integer, primary_key=True),
    Column("ran_at", DateTime, nullable=False),
    Column("orders_loaded", Integer, nullable=False),
    Column("orders_skipped", Integer, nullable=False),
    Column("subscriptions_loaded", Integer, nullable=False),
)

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = os.getenv("DATABASE_URL", DEFAULT_DB)
        if url.startswith("sqlite"):
            Path(url.replace("sqlite:///", "")).parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(url, future=True, pool_pre_ping=True)
        metadata.create_all(_engine)
    return _engine


def reset_engine(url: str) -> Engine:
    """Point the app at a different database (used by tests)."""
    global _engine
    os.environ["DATABASE_URL"] = url
    _engine = None
    return get_engine()
