"""Extract -> Transform -> Load for multi-store order and subscription exports.

* Extract: read one JSON export per brand (Shopify-style shape).
* Transform: drop test orders, de-duplicate by external id, normalise emails,
  convert every amount to USD, and pre-compute day/week/month buckets.
* Load: idempotent upsert keyed on (brand, external_id), so re-running the
  pipeline never double counts.

Run:  python -m app.etl
"""
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import delete, insert, select
from sqlalchemy.engine import Engine

from .db import brands, etl_runs, get_engine, order_items, orders, subscriptions
from .seed import SOURCES_DIR

# Fixed reference rates keep reporting reproducible. Swap for a rates API in production.
FX_TO_USD = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "AED": 0.272, "PKR": 0.0036}
VALID_STATUSES = {"paid", "refunded", "pending"}


@dataclass
class EtlResult:
    orders_loaded: int = 0
    orders_skipped: int = 0
    subscriptions_loaded: int = 0
    brands: int = 0

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def extract(source_dir: Path = SOURCES_DIR) -> list[dict]:
    files = sorted(source_dir.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"No store exports found in {source_dir}. Run `python -m app.seed` first.")
    return [json.loads(f.read_text()) for f in files]


def to_usd(amount: str | float, currency: str) -> float:
    if currency not in FX_TO_USD:
        raise ValueError(f"Unsupported currency: {currency}")
    return round(float(amount) * FX_TO_USD[currency], 2)


def transform_orders(export: dict) -> tuple[list[dict], int]:
    currency = export["currency"]
    seen, clean, skipped = set(), [], 0
    for raw in export["orders"]:
        if raw.get("test") or raw["id"] in seen or raw.get("financial_status") not in VALID_STATUSES:
            skipped += 1
            continue
        seen.add(raw["id"])
        created = datetime.fromisoformat(raw["created_at"].replace("Z", "+00:00")).replace(tzinfo=None)
        iso_year, iso_week, _ = created.isocalendar()
        items = [{
            "product": li["title"].strip(),
            "quantity": int(li["quantity"]),
            "revenue_usd": to_usd(float(li["price"]) * int(li["quantity"]), currency),
        } for li in raw["line_items"]]
        clean.append({
            "external_id": raw["id"],
            "customer_email": raw["customer_email"].strip().lower(),
            "created_at": created,
            "order_date": created.date(),
            "order_week": f"{iso_year}-W{iso_week:02d}",
            "order_month": created.strftime("%Y-%m"),
            "status": raw["financial_status"],
            "item_count": sum(i["quantity"] for i in items),
            "total_source": float(raw["total_price"]),
            "total_usd": to_usd(raw["total_price"], currency),
            "items": items,
        })
    return clean, skipped


def transform_subscriptions(export: dict) -> list[dict]:
    currency, seen, clean = export["currency"], set(), []
    for raw in export["subscriptions"]:
        if raw["id"] in seen:
            continue
        seen.add(raw["id"])
        clean.append({
            "external_id": raw["id"],
            "customer_email": raw["customer_email"].strip().lower(),
            "plan": raw["plan"],
            "price_usd": to_usd(raw["price"], currency),
            "started_at": date.fromisoformat(raw["started_at"]),
            "cancelled_at": date.fromisoformat(raw["cancelled_at"]) if raw.get("cancelled_at") else None,
        })
    return clean


def load(exports: list[dict], engine: Engine | None = None) -> EtlResult:
    engine = engine or get_engine()
    result = EtlResult()
    with engine.begin() as conn:
        for export in exports:
            info = export["brand"]
            brand_id = conn.execute(select(brands.c.id).where(brands.c.code == info["code"])).scalar()
            if brand_id is None:
                brand_id = conn.execute(insert(brands).values(
                    code=info["code"], name=info["name"], source_currency=export["currency"])).inserted_primary_key[0]

            clean_orders, skipped = transform_orders(export)
            result.orders_skipped += skipped

            # Idempotent: replace this brand's rows for the ids we are about to load.
            existing = select(orders.c.id).where(orders.c.brand_id == brand_id)
            conn.execute(delete(order_items).where(order_items.c.order_id.in_(existing)))
            conn.execute(delete(orders).where(orders.c.brand_id == brand_id))
            conn.execute(delete(subscriptions).where(subscriptions.c.brand_id == brand_id))

            for o in clean_orders:
                items = o.pop("items")
                order_id = conn.execute(insert(orders).values(brand_id=brand_id, **o)).inserted_primary_key[0]
                conn.execute(insert(order_items), [{"order_id": order_id, **i} for i in items])
            result.orders_loaded += len(clean_orders)

            clean_subs = transform_subscriptions(export)
            if clean_subs:
                conn.execute(insert(subscriptions), [{"brand_id": brand_id, **s} for s in clean_subs])
            result.subscriptions_loaded += len(clean_subs)
            result.brands += 1

        conn.execute(insert(etl_runs).values(
            ran_at=datetime.utcnow(), orders_loaded=result.orders_loaded,
            orders_skipped=result.orders_skipped, subscriptions_loaded=result.subscriptions_loaded))
    return result


def run(source_dir: Path = SOURCES_DIR, engine: Engine | None = None) -> EtlResult:
    return load(extract(source_dir), engine)


if __name__ == "__main__":
    print(run().as_dict())
