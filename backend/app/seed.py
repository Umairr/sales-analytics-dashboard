"""Generate realistic sample store exports (Shopify-style JSON) for three brands.

Each brand exports in its own currency and includes the kind of mess real exports
have: duplicate orders, test orders, refunds and string-typed prices. The ETL is
responsible for cleaning all of that up.

Run:  python -m app.seed
"""
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

SOURCES_DIR = Path(__file__).resolve().parent.parent / "data" / "sources"

BRANDS = [
    {"code": "northwind", "name": "Northwind Outfitters", "currency": "USD",
     "products": [("Trail Jacket", 129), ("Merino Base Layer", 74), ("Hiking Socks 3-Pack", 24),
                  ("Daypack 20L", 89), ("Rain Shell", 159)],
     "plans": [("Gear Club Monthly", 19), ("Gear Club Annual", 179)], "volume": 9},
    {"code": "maison", "name": "Maison Lumière", "currency": "EUR",
     "products": [("Linen Candle", 32), ("Ceramic Vase", 58), ("Diffuser Set", 45),
                  ("Throw Blanket", 89), ("Table Lamp", 120)],
     "plans": [("Scent Box Monthly", 29)], "volume": 6},
    {"code": "sakura", "name": "Sakura Home", "currency": "GBP",
     "products": [("Matcha Starter Kit", 38), ("Tea Set", 64), ("Bamboo Tray", 22),
                  ("Sencha Tin", 16), ("Kyusu Teapot", 48)],
     "plans": [("Tea of the Month", 18), ("Tea Club Quarterly", 49)], "volume": 5},
]

END_DATE = date(2026, 10, 31)
DAYS = 365


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def build_export(brand: dict, rng: random.Random) -> dict:
    start = END_DATE - timedelta(days=DAYS - 1)
    orders, subs = [], []
    order_no = 1000
    # Customer lifecycle: new shoppers arrive every day, each has a loyalty weight
    # and a lifetime after which they stop buying. That produces realistic
    # cohorts, repeat rates and RFM segments.
    customers: list[dict] = []

    def pick_customer(day: date) -> str:
        active = [c for c in customers if c["until"] >= day]
        if not active or rng.random() < 0.42:
            n = len(customers) + 1
            c = {"email": f"{brand['code']}.customer{n}@example.com",
                 "weight": rng.expovariate(1.0) + 0.05,
                 "until": day + timedelta(days=int(rng.expovariate(1 / 140)))}
            customers.append(c)
            return c["email"]
        return rng.choices(active, weights=[c["weight"] for c in active])[0]["email"]

    for day_offset in range(DAYS):
        day = start + timedelta(days=day_offset)
        # Seasonality: busier in Nov/Dec, a little growth over the year.
        season = 1.6 if day.month in (11, 12) else 1.0
        growth = 1 + day_offset / DAYS * 0.35
        weekend = 1.25 if day.weekday() >= 5 else 1.0
        n_orders = max(0, int(rng.gauss(brand["volume"] * season * growth * weekend, 2)))
        for _ in range(n_orders):
            order_no += 1
            items = []
            for product, price in rng.sample(brand["products"], rng.randint(1, 3)):
                qty = rng.choice([1, 1, 1, 2, 2, 3])
                items.append({"title": product, "quantity": qty, "price": f"{price:.2f}"})
            total = sum(float(i["price"]) * i["quantity"] for i in items)
            status = rng.choices(["paid", "refunded", "pending"], weights=[92, 5, 3])[0]
            created = datetime.combine(day, datetime.min.time()) + timedelta(minutes=rng.randint(0, 1439))
            email = pick_customer(day)
            orders.append({
                "id": f"{brand['code'].upper()}-{order_no}",
                "created_at": _iso(created),
                "customer_email": email.upper() if rng.random() < 0.1 else email,
                "financial_status": status,
                "total_price": f"{total:.2f}",
                "test": False,
                "line_items": items,
            })

    # Real exports are messy: add duplicates and test orders the ETL must drop.
    for dup in rng.sample(orders, 12):
        orders.append(dict(dup))
    for i in range(5):
        orders.append({
            "id": f"{brand['code'].upper()}-TEST-{i}", "created_at": _iso(datetime(2026, 6, 1, 12)),
            "customer_email": "qa@example.com", "financial_status": "paid", "total_price": "1.00",
            "test": True, "line_items": [{"title": "Test Product", "quantity": 1, "price": "1.00"}],
        })

    sub_no = 5000
    for _ in range(brand["volume"] * 30):
        sub_no += 1
        plan, price = rng.choice(brand["plans"])
        started = start + timedelta(days=rng.randint(0, DAYS - 1))
        cancelled = None
        if rng.random() < 0.38:
            c = started + timedelta(days=rng.randint(20, 240))
            cancelled = c.isoformat() if c <= END_DATE else None
        subs.append({"id": f"SUB-{sub_no}", "customer_email": rng.choice(customers)["email"], "plan": plan,
                     "price": f"{price:.2f}", "started_at": started.isoformat(), "cancelled_at": cancelled})

    return {"brand": {"code": brand["code"], "name": brand["name"]}, "currency": brand["currency"], "platform": "demo",
            "exported_at": _iso(datetime(2026, 11, 1)), "orders": orders, "subscriptions": subs}


def generate(out_dir: Path = SOURCES_DIR, seed: int = 42) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    paths = []
    for brand in BRANDS:
        path = out_dir / f"{brand['code']}.json"
        path.write_text(json.dumps(build_export(brand, rng), indent=1))
        paths.append(path)
    return paths


if __name__ == "__main__":
    for p in generate():
        print(f"wrote {p}")
