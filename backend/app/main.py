"""FastAPI service for the multi-store sales analytics dashboard."""
import asyncio
import csv
import io
import logging
import os
from datetime import date
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from . import advanced, analytics, etl, sources
from .connectors import ConnectorError
from .db import get_engine, orders
from .seed import SOURCES_DIR, generate

load_dotenv(sources.BASE_DIR / ".env")
log = logging.getLogger("analytics")

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
async def bootstrap():
    """First start: sync configured stores, or fall back to demo data so the dashboard is never empty.
    Set SYNC_INTERVAL_MINUTES to keep syncing in the background."""
    engine = get_engine()
    with engine.connect() as conn:
        has_data = conn.execute(select(func.count()).select_from(orders)).scalar()
    has_stores = bool(sources.configured_stores())
    if not has_data and has_stores:
        result = await asyncio.to_thread(sources.sync_all)
        log.warning("initial sync: %s", [(r["code"], r["ok"]) for r in result["stores"]])
        with engine.connect() as conn:
            has_data = conn.execute(select(func.count()).select_from(orders)).scalar()
    if not has_data and os.getenv("AUTO_SEED", "1") == "1":
        if not any(SOURCES_DIR.glob("*.json")):
            generate()
        etl.run()
    interval = float(os.getenv("SYNC_INTERVAL_MINUTES", "0") or 0)
    if has_stores and interval > 0:
        asyncio.create_task(_sync_loop(interval))


async def _sync_loop(minutes: float):
    while True:
        await asyncio.sleep(minutes * 60)
        try:
            await asyncio.to_thread(sources.sync_all)
        except Exception:  # keep the loop alive
            log.exception("scheduled sync failed")


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


@app.get("/api/overview")
def overview(brand: str | None = None, start: date | None = None, end: date | None = None):
    """KPIs for the range plus the same KPIs for the previous period of equal length."""
    _check_range(start, end)
    return advanced.summary_with_comparison(get_engine(), _brands(brand), start, end)


@app.get("/api/insights")
def insights(brand: str | None = None, start: date | None = None, end: date | None = None):
    _check_range(start, end)
    return advanced.insights(get_engine(), _brands(brand), start, end)


@app.get("/api/forecast")
def forecast(brand: str | None = None, horizon: int = Query(3, ge=1, le=12)):
    return advanced.revenue_forecast(get_engine(), _brands(brand), horizon)


@app.get("/api/cohorts")
def cohorts(brand: str | None = None, max_months: int = Query(12, ge=1, le=24)):
    return advanced.cohort_retention(get_engine(), _brands(brand), max_months)


@app.get("/api/rfm")
def rfm(brand: str | None = None, end: date | None = None):
    return advanced.rfm_segments(get_engine(), _brands(brand), end)


@app.get("/api/brand-comparison")
def brand_comparison(start: date | None = None, end: date | None = None):
    _check_range(start, end)
    return advanced.brand_comparison(get_engine(), start, end)


@app.get("/api/weekday")
def weekday(brand: str | None = None, start: date | None = None, end: date | None = None):
    _check_range(start, end)
    return advanced.weekday_pattern(get_engine(), _brands(brand), start, end)


@app.get("/api/orders/search")
def orders_search(brand: str | None = None, start: date | None = None, end: date | None = None,
                  q: str | None = None, status: Literal["paid", "refunded", "pending"] | None = None,
                  limit: int = Query(25, ge=1, le=200), offset: int = Query(0, ge=0),
                  sort: Literal["created_at", "total_usd", "item_count"] = "created_at",
                  direction: Literal["asc", "desc"] = "desc"):
    _check_range(start, end)
    return advanced.search_orders(get_engine(), _brands(brand), start, end, q, status, limit, offset, sort, direction)


@app.get("/api/export/orders.csv")
def export_orders(brand: str | None = None, start: date | None = None, end: date | None = None,
                  q: str | None = None, status: Literal["paid", "refunded", "pending"] | None = None):
    _check_range(start, end)
    rows = advanced.search_orders(get_engine(), _brands(brand), start, end, q, status, limit=None)["rows"]
    buf = io.StringIO()
    fields = ["order_id", "brand", "created_at", "customer_email", "status", "item_count",
              "total_source", "currency", "total_usd"]
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    buf.seek(0)
    name = f"orders_{start or 'all'}_{end or 'all'}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/api/etl/run")
def run_etl():
    return etl.run().as_dict()


# ---------- data sources ----------

@app.get("/api/sources")
def list_sources():
    return sources.list_sources()


@app.post("/api/sync")
def sync(full: bool = False):
    """Pull fresh data from every store in stores.json, then rebuild the reports."""
    try:
        return sources.sync_all(full=full)
    except ConnectorError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/sources/csv")
async def upload_csv(file: UploadFile = File(...), name: str = Form(...), code: str | None = Form(None),
                     currency: str | None = Form(None), replace_demo: bool = Form(True)):
    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="CSV larger than 50 MB")
    try:
        return sources.import_csv(content, name.strip(), (code or "").strip() or None,
                                  (currency or "").strip().upper() or None, replace_demo=replace_demo)
    except (ConnectorError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/sources/{code}")
def delete_source(code: str):
    try:
        return sources.delete_source(code)
    except ConnectorError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/sources/demo")
def restore_demo():
    return sources.restore_demo()
