import json

import httpx
import pytest

from app import etl, sources
from app.connectors import ConnectorError, ShopifyConnector, StoreConfig, WooCommerceConnector, parse_csv
from app.db import reset_engine
from app.seed import generate


# ---------- fake Shopify ----------

def shopify_order(n, status="PAID", test=False, created="2026-10-01T10:00:00-04:00", cancelled=None):
    return {
        "id": f"gid://shopify/Order/{n}", "name": f"#{n}", "createdAt": created, "email": f"c{n}@ex.com",
        "test": test, "cancelledAt": cancelled, "displayFinancialStatus": status,
        "totalPriceSet": {"shopMoney": {"amount": "50.00", "currencyCode": "CAD"}},
        "customer": {"email": f"c{n}@ex.com"},
        "lineItems": {"nodes": [{"title": "Mug", "quantity": 2, "originalUnitPriceSet": {"shopMoney": {"amount": "25.00"}}}]},
    }


def shopify_transport(pages, subs_denied=False, calls=None):
    calls = calls if calls is not None else []

    def handler(request: httpx.Request):
        assert request.headers["X-Shopify-Access-Token"] == "shpat_test"
        body = json.loads(request.content)
        calls.append(body)
        q = body["query"]
        if "shop {" in q:
            return httpx.Response(200, json={"data": {"shop": {"name": "Maple", "currencyCode": "CAD"}}})
        if "subscriptionContracts" in q:
            if subs_denied:
                return httpx.Response(200, json={"errors": [{"message": "Access denied", "extensions": {"code": "ACCESS_DENIED"}}]})
            return httpx.Response(200, json={"data": {"subscriptionContracts": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [{"id": "gid://shopify/SubscriptionContract/9", "status": "CANCELLED",
                           "createdAt": "2026-01-05T00:00:00Z", "updatedAt": "2026-05-01T00:00:00Z",
                           "customer": {"email": "s@ex.com"},
                           "lines": {"nodes": [{"title": "Coffee club", "currentPrice": {"amount": "20.0"}}]}}]}}})
        idx = int(body["variables"].get("cursor") or 0)
        page = pages[idx]
        return httpx.Response(200, json={"data": {"orders": {
            "pageInfo": {"hasNextPage": idx + 1 < len(pages), "endCursor": str(idx + 1)}, "nodes": page}}})

    return httpx.MockTransport(handler)


def shop_store(**extra):
    return StoreConfig("maple", "Maple Goods", "shopify", {"shop": "maple.myshopify.com", "token": "shpat_test", **extra})


def test_shopify_paginates_and_maps_orders():
    pages = [[shopify_order(1), shopify_order(2, "REFUNDED")],
             [shopify_order(3, "PENDING"), shopify_order(4, test=True), shopify_order(5, cancelled="2026-10-02T00:00:00Z")]]
    client = httpx.Client(transport=shopify_transport(pages))
    export = ShopifyConnector(shop_store(), client).fetch()
    assert export["currency"] == "CAD" and export["platform"] == "shopify"
    statuses = {o["id"]: o["financial_status"] for o in export["orders"]}
    assert statuses == {"#1": "paid", "#2": "refunded", "#3": "pending", "#4": "paid", "#5": "cancelled"}
    o = export["orders"][0]
    assert o["created_at"] == "2026-10-01T14:00:00Z"  # converted to UTC
    assert o["line_items"] == [{"title": "Mug", "quantity": 2, "price": "25.00"}]
    assert export["orders"][3]["test"] is True
    sub = export["subscriptions"][0]
    assert sub["id"] == "9" and sub["cancelled_at"] == "2026-05-01" and sub["plan"] == "Coffee club"


def test_shopify_without_subscription_scope_still_syncs():
    client = httpx.Client(transport=shopify_transport([[shopify_order(1)]], subs_denied=True))
    export = ShopifyConnector(shop_store(), client).fetch()
    assert len(export["orders"]) == 1 and export["subscriptions"] == []


def test_shopify_incremental_query_and_bad_token():
    calls = []
    client = httpx.Client(transport=shopify_transport([[shopify_order(1)]], calls=calls))
    ShopifyConnector(shop_store(), client).fetch(since="2026-10-01T00:00:00Z")
    order_call = next(c for c in calls if "orders(" in c["query"])
    assert order_call["variables"]["query"] == "updated_at:>='2026-10-01T00:00:00Z'"

    denied = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    with pytest.raises(ConnectorError, match="401"):
        ShopifyConnector(shop_store(), denied).fetch()


def test_shopify_client_credentials_grant():
    inner = shopify_transport([[shopify_order(1)]])

    def handler(request: httpx.Request):
        if request.url.path == "/admin/oauth/access_token":
            form = dict(x.split("=") for x in request.content.decode().split("&"))
            assert form == {"grant_type": "client_credentials", "client_id": "cid", "client_secret": "csec"}
            return httpx.Response(200, json={"access_token": "shpat_test", "scope": "read_orders", "expires_in": 86399})
        return inner.handle_request(request)

    store = StoreConfig("maple", "Maple", "shopify", {"shop": "maple.myshopify.com", "client_id": "cid", "client_secret": "csec"})
    export = ShopifyConnector(store, httpx.Client(transport=httpx.MockTransport(handler))).fetch()
    assert len(export["orders"]) == 1

    refused = httpx.MockTransport(lambda r: httpx.Response(400, json={"error": "invalid_client"}))
    with pytest.raises(ConnectorError, match="invalid_client"):
        ShopifyConnector(store, httpx.Client(transport=refused)).fetch()


def test_shopify_missing_token(monkeypatch):
    monkeypatch.delenv("SHOPIFY_TOKEN_X", raising=False)
    with pytest.raises(ConnectorError, match="SHOPIFY_TOKEN_X"):
        ShopifyConnector(StoreConfig("x", "X", "shopify", {"shop": "x.myshopify.com", "token_env": "SHOPIFY_TOKEN_X"}))


# ---------- fake WooCommerce ----------

def woo_order(n, status="completed"):
    return {"id": n, "number": str(n), "status": status, "currency": "EUR", "total": "30.00",
            "date_created_gmt": "2026-09-10T08:00:00", "billing": {"email": f"w{n}@ex.com"},
            "line_items": [{"name": "Candle", "quantity": 3, "price": 10, "total": "30.00"}]}


def woo_transport(order_pages, with_subs=True, seen=None):
    seen = seen if seen is not None else []

    def handler(request: httpx.Request):
        seen.append(request)
        assert request.headers["authorization"].startswith("Basic ")
        page = int(request.url.params.get("page", 1))
        if request.url.path.endswith("/subscriptions"):
            if not with_subs:
                return httpx.Response(404, json={"code": "rest_no_route"})
            return httpx.Response(200, headers={"X-WP-TotalPages": "1"}, json=[
                {"id": 7, "status": "active", "total": "15.00", "start_date_gmt": "2026-02-01T00:00:00",
                 "billing": {"email": "sub@ex.com"}, "line_items": [{"name": "Candle club"}]},
                {"id": 8, "status": "cancelled", "total": "15.00", "start_date_gmt": "2026-02-01T00:00:00",
                 "cancelled_date_gmt": "2026-06-15T00:00:00", "billing": {"email": "sub2@ex.com"}, "line_items": []},
            ])
        return httpx.Response(200, headers={"X-WP-TotalPages": str(len(order_pages))}, json=order_pages[page - 1])

    return httpx.MockTransport(handler)


def woo_store():
    return StoreConfig("candles", "Candle Co", "woocommerce",
                       {"url": "https://candles.example.com/", "key": "ck_x", "secret": "cs_y"})


def test_woocommerce_paginates_maps_and_reads_subscriptions():
    seen = []
    client = httpx.Client(transport=woo_transport([[woo_order(1), woo_order(2, "refunded")],
                                                   [woo_order(3, "on-hold"), woo_order(4, "failed")]], seen=seen))
    export = WooCommerceConnector(woo_store(), client).fetch(since="2026-09-01T00:00:00Z")
    assert export["currency"] == "EUR" and export["platform"] == "woocommerce"
    assert [o["financial_status"] for o in export["orders"]] == ["paid", "refunded", "pending", "cancelled"]
    assert export["orders"][0]["id"] == "WC-1" and export["orders"][0]["created_at"] == "2026-09-10T08:00:00Z"
    assert export["orders"][0]["line_items"][0] == {"title": "Candle", "quantity": 3, "price": "10"}
    assert seen[0].url.params["modified_after"] == "2026-09-01T00:00:00"
    assert seen[0].url.path == "/wp-json/wc/v3/orders"
    subs = {s["id"]: s for s in export["subscriptions"]}
    assert subs["WCS-7"]["cancelled_at"] is None and subs["WCS-8"]["cancelled_at"] == "2026-06-15"


def test_woocommerce_without_subscriptions_plugin():
    client = httpx.Client(transport=woo_transport([[woo_order(1)]], with_subs=False))
    export = WooCommerceConnector(woo_store(), client).fetch()
    assert len(export["orders"]) == 1 and export["subscriptions"] == []


# ---------- CSV ----------

SHOPIFY_CSV = """Name,Email,Financial Status,Created at,Total,Currency,Lineitem quantity,Lineitem name,Lineitem price
#1001,a@ex.com,paid,2026-03-02 10:00:00 -0500,45.00,GBP,1,Tea Set,30.00
#1001,a@ex.com,,2026-03-02 10:00:00 -0500,,GBP,1,Tea Tin,15.00
#1002,b@ex.com,refunded,2026-03-03 11:00:00 -0500,20.00,GBP,2,Tea Tin,10.00
"""

GENERIC_CSV = """Order Number,Order Date,Billing Email,Order Status,Order Total
5001,03/15/2026,x@ex.com,completed,"1,200.50"
5002,03/16/2026,y@ex.com,cancelled,10.00
"""


def test_csv_shopify_export_groups_line_items():
    export = parse_csv(SHOPIFY_CSV.encode(), "tea", "Tea House")
    assert export["currency"] == "GBP"
    first, second = export["orders"]
    assert first["id"] == "#1001" and len(first["line_items"]) == 2 and first["total_price"] == "45.00"
    assert first["created_at"] == "2026-03-02T15:00:00Z"
    assert second["financial_status"] == "refunded"


def test_csv_generic_header_aliases():
    export = parse_csv(GENERIC_CSV, "woo", "Woo CSV", currency="usd")
    assert export["currency"] == "USD"
    assert [o["financial_status"] for o in export["orders"]] == ["paid", "cancelled"]
    assert export["orders"][0]["total_price"] == "1200.50"
    assert export["orders"][0]["line_items"][0]["title"] == "Order total"


def test_csv_missing_columns():
    with pytest.raises(ConnectorError, match="missing required"):
        parse_csv("foo,bar\n1,2\n", "x", "X")


# ---------- sync orchestration ----------

@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    src = tmp_path / "sources"
    generate(src, seed=3)
    engine = reset_engine(f"sqlite:///{tmp_path / 'sync.db'}")
    etl.run(src, engine)
    monkeypatch.setattr(sources, "STATUS_PATH", tmp_path / "status.json")
    return src, engine


def test_sync_replaces_demo_and_is_incremental(workspace):
    src, engine = workspace
    cfg = {"stores": [{"code": "maple", "name": "Maple Goods", "platform": "shopify",
                       "shop": "maple.myshopify.com", "token": "shpat_test"}]}
    client = httpx.Client(transport=shopify_transport([[shopify_order(1), shopify_order(2)]]))
    res = sources.sync_all(source_dir=src, cfg=cfg, client=client, engine=engine)
    assert res["stores"][0]["ok"] and res["stores"][0]["mode"] == "full"
    assert set(res["demo_removed"]) == {"northwind", "maison", "sakura"}
    assert res["etl"]["brands"] == 1 and res["etl"]["orders_loaded"] == 2

    from app import analytics
    assert [b["code"] for b in analytics.list_brands(engine)] == ["maple"]  # demo brands pruned from DB

    # second sync only fetches changed orders and merges them
    calls = []
    client2 = httpx.Client(transport=shopify_transport([[shopify_order(2, "REFUNDED"), shopify_order(3)]], calls=calls))
    res2 = sources.sync_all(source_dir=src, cfg=cfg, client=client2, engine=engine)
    assert res2["stores"][0]["mode"] == "incremental"
    assert any("updated_at:>=" in (c["variables"].get("query") or "") for c in calls)
    saved = json.loads((src / "maple.json").read_text())
    assert {o["id"]: o["financial_status"] for o in saved["orders"]} == {"#1": "paid", "#2": "refunded", "#3": "paid"}


def test_failed_store_keeps_demo_and_reports_error(workspace):
    src, engine = workspace
    cfg = {"stores": [{"code": "bad", "name": "Bad", "platform": "shopify", "shop": "bad.myshopify.com", "token": "t"}]}
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    res = sources.sync_all(source_dir=src, cfg=cfg, client=client, engine=engine)
    assert res["stores"][0]["ok"] is False and "401" in res["stores"][0]["error"]
    assert res["demo_removed"] == [] and res["etl"]["brands"] == 3


def test_csv_import_and_delete(workspace):
    src, engine = workspace
    res = sources.import_csv(SHOPIFY_CSV.encode(), "Tea House", source_dir=src, engine=engine)
    assert res["code"] == "tea-house" and res["etl"]["brands"] == 1
    assert sources.delete_source("tea-house", src, engine)["brands"] == 0
    with pytest.raises(ConnectorError):
        sources.delete_source("../etc", src, engine)


def test_unknown_currency_rejected_on_import(workspace):
    src, engine = workspace
    bad = SHOPIFY_CSV.replace("GBP", "XYZ")
    with pytest.raises(ValueError, match="XYZ"):
        sources.import_csv(bad.encode(), "Odd", source_dir=src, engine=engine)
