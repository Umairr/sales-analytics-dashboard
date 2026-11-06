"""Reporting queries. Revenue counts paid orders only; refunds are reported separately."""
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import and_, case, func, select
from sqlalchemy.engine import Engine

from .db import brands, order_items, orders, subscriptions

BUCKETS = {"day": orders.c.order_date, "week": orders.c.order_week, "month": orders.c.order_month}


def _order_filters(brand_codes: list[str] | None, start: date | None, end: date | None):
    conds = []
    if brand_codes:
        conds.append(brands.c.code.in_(brand_codes))
    if start:
        conds.append(orders.c.order_date >= start)
    if end:
        conds.append(orders.c.order_date <= end)
    return and_(True, *conds)


def list_brands(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(select(brands.c.code, brands.c.name, brands.c.source_currency).order_by(brands.c.name))
        return [dict(r._mapping) for r in rows]


def summary(engine: Engine, brand_codes=None, start=None, end=None) -> dict:
    paid = orders.c.status == "paid"
    q = (select(
            func.coalesce(func.sum(case((paid, orders.c.total_usd), else_=0)), 0).label("revenue"),
            func.sum(case((paid, 1), else_=0)).label("paid_orders"),
            func.sum(case((orders.c.status == "refunded", orders.c.total_usd), else_=0)).label("refunded"),
            func.count(func.distinct(orders.c.customer_email)).label("customers"))
         .select_from(orders.join(brands))
         .where(_order_filters(brand_codes, start, end)))
    with engine.connect() as conn:
        r = conn.execute(q).one()._mapping
    paid_orders = int(r["paid_orders"] or 0)
    revenue = round(float(r["revenue"] or 0), 2)
    subs = subscription_stats(engine, brand_codes, end)
    return {
        "revenue": revenue,
        "orders": paid_orders,
        "aov": round(revenue / paid_orders, 2) if paid_orders else 0.0,
        "refunded": round(float(r["refunded"] or 0), 2),
        "customers": int(r["customers"] or 0),
        **subs,
    }


def revenue_series(engine: Engine, brand_codes=None, start=None, end=None, bucket="month") -> list[dict]:
    col = BUCKETS[bucket]
    q = (select(col.label("period"), brands.c.code,
                func.sum(orders.c.total_usd).label("revenue"), func.count().label("orders"))
         .select_from(orders.join(brands))
         .where(and_(orders.c.status == "paid", _order_filters(brand_codes, start, end)))
         .group_by(col, brands.c.code).order_by(col))
    series: dict[str, dict] = defaultdict(lambda: {"total": 0.0, "orders": 0})
    with engine.connect() as conn:
        for row in conn.execute(q):
            period = str(row.period)
            point = series[period]
            point["period"] = period
            point[row.code] = round(float(row.revenue), 2)
            point["total"] = round(point["total"] + float(row.revenue), 2)
            point["orders"] += int(row.orders)
    return [series[k] for k in sorted(series)]


def top_products(engine: Engine, brand_codes=None, start=None, end=None, limit=10) -> list[dict]:
    q = (select(order_items.c.product, brands.c.code.label("brand"),
                func.sum(order_items.c.quantity).label("units"),
                func.sum(order_items.c.revenue_usd).label("revenue"))
         .select_from(order_items.join(orders).join(brands))
         .where(and_(orders.c.status == "paid", _order_filters(brand_codes, start, end)))
         .group_by(order_items.c.product, brands.c.code)
         .order_by(func.sum(order_items.c.revenue_usd).desc()).limit(limit))
    with engine.connect() as conn:
        return [{"product": r.product, "brand": r.brand, "units": int(r.units),
                 "revenue": round(float(r.revenue), 2)} for r in conn.execute(q)]


def _subs(engine: Engine, brand_codes):
    q = select(subscriptions.c.started_at, subscriptions.c.cancelled_at, subscriptions.c.price_usd,
               subscriptions.c.plan).select_from(subscriptions.join(brands))
    if brand_codes:
        q = q.where(brands.c.code.in_(brand_codes))
    with engine.connect() as conn:
        return conn.execute(q).all()


def _active_on(rows, day: date) -> list:
    return [r for r in rows if r.started_at <= day and (r.cancelled_at is None or r.cancelled_at > day)]


def _monthly_price(plan: str, price: float) -> float:
    if "annual" in plan.lower():
        return price / 12
    if "quarterly" in plan.lower():
        return price / 3
    return price


def subscription_stats(engine: Engine, brand_codes=None, as_of: date | None = None) -> dict:
    rows = _subs(engine, brand_codes)
    if not rows:
        return {"active_subscriptions": 0, "mrr": 0.0, "churn_rate": 0.0}
    as_of = as_of or max(max(r.started_at for r in rows), max((r.cancelled_at or r.started_at) for r in rows))
    active = _active_on(rows, as_of)
    month_start = as_of.replace(day=1)
    active_at_start = _active_on(rows, month_start - timedelta(days=1))
    churned = [r for r in active_at_start if r.cancelled_at and month_start <= r.cancelled_at <= as_of]
    return {
        "active_subscriptions": len(active),
        "mrr": round(sum(_monthly_price(r.plan, r.price_usd) for r in active), 2),
        "churn_rate": round(len(churned) / len(active_at_start) * 100, 2) if active_at_start else 0.0,
    }


def churn_series(engine: Engine, brand_codes=None, start=None, end=None) -> list[dict]:
    """Monthly logo churn: cancellations in month / subscribers active at the start of the month."""
    rows = _subs(engine, brand_codes)
    if not rows:
        return []
    first = start or min(r.started_at for r in rows)
    last = end or max((r.cancelled_at or r.started_at) for r in rows)
    out, cursor = [], first.replace(day=1)
    while cursor <= last:
        nxt = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        base = _active_on(rows, cursor - timedelta(days=1))
        cancelled = [r for r in base if r.cancelled_at and cursor <= r.cancelled_at < nxt]
        new = [r for r in rows if cursor <= r.started_at < nxt]
        out.append({
            "period": cursor.strftime("%Y-%m"),
            "active_start": len(base),
            "new": len(new),
            "cancelled": len(cancelled),
            "churn_rate": round(len(cancelled) / len(base) * 100, 2) if base else 0.0,
        })
        cursor = nxt
    return out


def order_rows(engine: Engine, brand_codes=None, start=None, end=None, limit=None, offset=0):
    q = (select(orders.c.external_id.label("order_id"), brands.c.name.label("brand"),
                orders.c.created_at, orders.c.customer_email, orders.c.status,
                orders.c.item_count, orders.c.total_source, brands.c.source_currency.label("currency"),
                orders.c.total_usd)
         .select_from(orders.join(brands))
         .where(_order_filters(brand_codes, start, end))
         .order_by(orders.c.created_at.desc()))
    if limit:
        q = q.limit(limit).offset(offset)
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(q)]
