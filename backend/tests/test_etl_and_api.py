import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from app import analytics, etl
from app.db import reset_engine
from app.seed import generate


@pytest.fixture()
def env(tmp_path, monkeypatch):
    sources = tmp_path / "sources"
    generate(sources, seed=7)
    engine = reset_engine(f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(etl, "SOURCES_DIR", sources)
    result = etl.run(sources, engine)
    return engine, sources, result


@pytest.fixture()
def client(env, monkeypatch):
    monkeypatch.setenv("AUTO_SEED", "0")
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_transform_drops_tests_duplicates_and_converts_currency():
    export = {
        "currency": "EUR",
        "orders": [
            {"id": "A-1", "created_at": "2026-03-02T10:00:00Z", "customer_email": " Jo@Example.com ",
             "financial_status": "paid", "total_price": "100.00", "test": False,
             "line_items": [{"title": "Vase", "quantity": 2, "price": "50.00"}]},
            {"id": "A-1", "created_at": "2026-03-02T10:00:00Z", "customer_email": "jo@example.com",
             "financial_status": "paid", "total_price": "100.00", "test": False, "line_items": []},
            {"id": "T-1", "created_at": "2026-03-02T10:00:00Z", "customer_email": "qa@example.com",
             "financial_status": "paid", "total_price": "1.00", "test": True, "line_items": []},
        ],
    }
    clean, skipped = etl.transform_orders(export)
    assert skipped == 2
    assert len(clean) == 1
    o = clean[0]
    assert o["customer_email"] == "jo@example.com"
    assert o["total_usd"] == 108.0
    assert o["order_month"] == "2026-03" and o["order_week"] == "2026-W10"
    assert o["item_count"] == 2


def test_unknown_currency_rejected():
    with pytest.raises(ValueError):
        etl.to_usd("10", "XYZ")


def test_etl_is_idempotent(env):
    engine, sources, first = env
    before = analytics.summary(engine)
    second = etl.run(sources, engine)
    after = analytics.summary(engine)
    assert first.orders_loaded == second.orders_loaded
    assert before == after


def test_etl_skips_seeded_noise(env):
    _, sources, result = env
    raw_total = sum(len(json.loads(p.read_text())["orders"]) for p in sources.glob("*.json"))
    # 12 duplicates + 5 test orders per brand, 3 brands
    assert result.orders_skipped == 3 * 17
    assert result.orders_loaded == raw_total - 3 * 17


def test_revenue_series_sums_to_summary(env):
    engine, _, _ = env
    total = analytics.summary(engine)["revenue"]
    series = analytics.revenue_series(engine, bucket="month")
    assert len(series) == 12
    assert abs(sum(p["total"] for p in series) - total) < 1


def test_brand_filter(env):
    engine, _, _ = env
    all_rev = analytics.summary(engine)["revenue"]
    parts = sum(analytics.summary(engine, [b])["revenue"] for b in ["northwind", "maison", "sakura"])
    assert abs(all_rev - parts) < 1


def test_churn_series_shape(env):
    engine, _, _ = env
    rows = analytics.churn_series(engine)
    assert rows and all(0 <= r["churn_rate"] <= 100 for r in rows)


def test_api_endpoints(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    brands = client.get("/api/brands").json()
    assert {b["code"] for b in brands} == {"northwind", "maison", "sakura"}

    s = client.get("/api/summary", params={"brand": "maison", "start": "2026-01-01", "end": "2026-06-30"}).json()
    assert s["revenue"] > 0 and s["orders"] > 0 and s["aov"] > 0

    weekly = client.get("/api/revenue", params={"bucket": "week"}).json()
    assert len(weekly) > 50

    top = client.get("/api/top-products", params={"limit": 5}).json()
    assert len(top) == 5 and top[0]["revenue"] >= top[-1]["revenue"]

    assert client.get("/api/summary", params={"start": "2026-05-01", "end": "2026-01-01"}).status_code == 422


def test_csv_export(client):
    r = client.get("/api/export/orders.csv", params={"brand": "sakura", "start": "2026-10-01", "end": "2026-10-31"})
    assert r.status_code == 200 and "text/csv" in r.headers["content-type"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert rows and all(row["brand"] == "Sakura Home" for row in rows)
    assert all(row["created_at"].startswith("2026-10") for row in rows)
