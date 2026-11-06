from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import advanced, etl
from app.db import reset_engine
from app.seed import generate


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("adv")
    sources = tmp / "sources"
    generate(sources, seed=11)
    eng = reset_engine(f"sqlite:///{tmp / 'adv.db'}")
    etl.run(sources, eng)
    return eng


def test_previous_range_has_equal_length():
    s, e = advanced.previous_range(date(2026, 8, 3), date(2026, 10, 31))
    assert e == date(2026, 8, 2)
    assert (e - s).days == (date(2026, 10, 31) - date(2026, 8, 3)).days


def test_pct_change():
    assert advanced.pct_change(110, 100) == 10.0
    assert advanced.pct_change(5, 0) is None


def test_comparison_has_previous_period(engine):
    res = advanced.summary_with_comparison(engine, None, date(2026, 8, 3), date(2026, 10, 31))
    assert res["previous"]["revenue"] > 0
    assert res["delta_pct"]["revenue"] is not None
    assert 0 <= res["current"]["repeat_rate"] <= 100


def test_comparison_without_history_returns_none(engine):
    lo, hi = advanced.data_bounds(engine)
    res = advanced.summary_with_comparison(engine, None, lo, hi)
    assert res["previous"] is None
    assert all(v is None for v in res["delta_pct"].values())


def test_cohorts_start_at_100_and_decay(engine):
    rows = advanced.cohort_retention(engine)
    assert len(rows) == 12
    assert all(r["retention"][0] == 100.0 for r in rows)
    first = rows[0]["retention"]
    assert len(first) == 12
    assert first[-1] < first[1] < 100


def test_rfm_segments_cover_every_customer(engine):
    res = advanced.rfm_segments(engine)
    seg_total = sum(s["customers"] for s in res["segments"])
    assert seg_total > 0
    assert abs(sum(s["share_customers"] for s in res["segments"]) - 100) < 1
    assert {"Champions", "At Risk"} <= {s["segment"] for s in res["segments"]}
    tops = res["top_customers"]
    assert tops == sorted(tops, key=lambda c: c["revenue"], reverse=True)


def test_quintile_scores():
    scores = advanced._quintile_scores({str(i): i for i in range(10)})
    assert scores["0"] == 1 and scores["9"] == 5
    rec = advanced._quintile_scores({"recent": 1, "old": 300}, reverse=True)
    assert rec["recent"] > rec["old"]


def test_forecast_band_contains_point(engine):
    fc = advanced.revenue_forecast(engine, horizon=3)
    assert len(fc["forecast"]) == 3
    for p in fc["forecast"]:
        assert p["lower"] <= p["forecast"] <= p["upper"]
    assert fc["forecast"][0]["period"] == "2026-11"


def test_brand_comparison_shares_sum_to_100(engine):
    rows = advanced.brand_comparison(engine, date(2026, 8, 3), date(2026, 10, 31))
    assert len(rows) == 3
    assert abs(sum(r["share"] for r in rows) - 100) < 0.5
    assert all(r["growth_pct"] is not None for r in rows)


def test_insights_generated(engine):
    items = advanced.insights(engine, None, date(2026, 8, 3), date(2026, 10, 31))
    assert len(items) >= 4
    assert all({"tone", "title", "detail"} <= set(i) for i in items)


def test_search_orders(engine):
    res = advanced.search_orders(engine, ["sakura"], q="sakura-", status="paid", limit=5)
    assert res["total"] > 5 and len(res["rows"]) == 5
    assert all(r["status"] == "paid" and r["code"] == "sakura" for r in res["rows"])
    by_value = advanced.search_orders(engine, sort="total_usd", direction="desc", limit=3)["rows"]
    assert by_value[0]["total_usd"] >= by_value[-1]["total_usd"]


def test_new_endpoints(engine, monkeypatch):
    monkeypatch.setenv("AUTO_SEED", "0")
    from app.main import app
    with TestClient(app) as c:
        params = {"start": "2026-08-03", "end": "2026-10-31"}
        assert c.get("/api/overview", params=params).json()["current"]["revenue"] > 0
        assert c.get("/api/insights", params=params).status_code == 200
        assert len(c.get("/api/forecast").json()["forecast"]) == 3
        assert c.get("/api/cohorts").json()[0]["retention"][0] == 100.0
        assert c.get("/api/rfm").json()["segments"]
        assert len(c.get("/api/brand-comparison", params=params).json()) == 3
        assert len(c.get("/api/weekday").json()) == 7
        r = c.get("/api/orders/search", params={"q": "MAISON", "limit": 10}).json()
        assert r["total"] > 0 and len(r["rows"]) == 10
        assert c.get("/api/orders/search", params={"status": "bogus"}).status_code == 422
