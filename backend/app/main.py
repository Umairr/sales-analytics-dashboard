"""FastAPI service for the multi-store sales analytics dashboard."""
import csv
import io
import os
from datetime import date
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from . import analytics, etl
from .db import get_engine, orders
from .seed import SOURCES_DIR, generate

app = FastAPI(title="Multi-Store Sales Analytics API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


def _brands(brand: str | None) -> list[str] | None:
    return [b for b in brand.split(",") if b] if brand else None


def _check_range(start: date | None, end: date | None):
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="start must be on or before end")


@app.on_event("startup")
def bootstrap():
    """On a fresh database, seed demo exports and run the ETL so the dashboard has data."""
    engine = get_engine()
    with engine.connect() as conn:
        has_data = conn.execute(select(func.count()).select_from(orders)).scalar()
    if not has_data and os.getenv("AUTO_SEED", "1") == "1":
        if not any(SOURCES_DIR.glob("*.json")):
            generate()
        etl.run()


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/meta")
def meta():
    with get_engine().connect() as conn:
        lo, hi = conn.execute(select(func.min(orders.c.order_date), func.max(orders.c.order_date))).one()
    return {"min_date": lo, "max_date": hi}


@app.get("/api/brands")
def brands():
    return analytics.list_brands(get_engine())


@app.get("/api/summary")
def summary(brand: str | None = None, start: date | None = None, end: date | None = None):
    _check_range(start, end)
    return analytics.summary(get_engine(), _brands(brand), start, end)


@app.get("/api/revenue")
def revenue(brand: str | None = None, start: date | None = None, end: date | None = None,
            bucket: Literal["day", "week", "month"] = "month"):
    _check_range(start, end)
    return analytics.revenue_series(get_engine(), _brands(brand), start, end, bucket)


@app.get("/api/churn")
def churn(brand: str | None = None, start: date | None = None, end: date | None = None):
    _check_range(start, end)
    return analytics.churn_series(get_engine(), _brands(brand), start, end)


@app.get("/api/top-products")
def top_products(brand: str | None = None, start: date | None = None, end: date | None = None,
                 limit: int = Query(10, ge=1, le=50)):
    _check_range(start, end)
    return analytics.top_products(get_engine(), _brands(brand), start, end, limit)


@app.get("/api/orders")
def order_list(brand: str | None = None, start: date | None = None, end: date | None = None,
               limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    _check_range(start, end)
    return analytics.order_rows(get_engine(), _brands(brand), start, end, limit, offset)


@app.get("/api/export/orders.csv")
def export_orders(brand: str | None = None, start: date | None = None, end: date | None = None):
    _check_range(start, end)
    rows = analytics.order_rows(get_engine(), _brands(brand), start, end)
    buf = io.StringIO()
    fields = ["order_id", "brand", "created_at", "customer_email", "status", "item_count",
              "total_source", "currency", "total_usd"]
    writer = csv.DictWriter(buf, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    buf.seek(0)
    name = f"orders_{start or 'all'}_{end or 'all'}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/api/etl/run")
def run_etl():
    return etl.run().as_dict()
