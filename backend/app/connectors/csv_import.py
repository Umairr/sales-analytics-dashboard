"""CSV import for any platform.

Two layouts are recognised automatically:

1. Shopify "Export orders" CSV (Admin -> Orders -> Export). One row per line item;
   columns used: Name, Email, Financial Status, Created at, Total, Currency,
   Lineitem name, Lineitem quantity, Lineitem price.

2. Generic CSV (WooCommerce exports, Amazon reports, spreadsheets...). One row per
   line item, or one row per order if product columns are left empty:
       order_id, created_at, customer_email, status, total, product, quantity, price
   Optional: currency. Common alternative header names are accepted (see ALIASES).
"""
import csv
import io

from .base import ConnectorError, to_iso_z, utc_now_iso

ALIASES = {
    "order_id": ["order_id", "order id", "order number", "order", "id", "name"],
    "created_at": ["created_at", "created at", "order date", "date", "date created", "order_date"],
    "customer_email": ["customer_email", "email", "customer email", "billing email", "billing_email"],
    "status": ["status", "financial status", "order status", "payment status"],
    "total": ["total", "order total", "total_price", "amount", "grand total"],
    "product": ["product", "lineitem name", "item name", "product name", "item"],
    "quantity": ["quantity", "lineitem quantity", "qty", "item quantity"],
    "price": ["price", "lineitem price", "item price", "unit price"],
    "currency": ["currency"],
}
STATUS_MAP = {
    "paid": "paid", "completed": "paid", "complete": "paid", "processing": "paid", "shipped": "paid",
    "partially_refunded": "paid", "partially refunded": "paid", "fulfilled": "paid",
    "refunded": "refunded",
    "pending": "pending", "on-hold": "pending", "authorized": "pending", "partially_paid": "pending",
}


def _resolve_headers(fieldnames: list[str]) -> dict[str, str]:
    lower = {f.strip().lower(): f for f in fieldnames if f}
    found = {}
    for key, names in ALIASES.items():
        for n in names:
            if n in lower:
                found[key] = lower[n]
                break
    missing = [k for k in ("order_id", "created_at", "total") if k not in found]
    if missing:
        raise ConnectorError(f"CSV is missing required column(s): {', '.join(missing)}. "
                             f"Found: {', '.join(fieldnames)}")
    return found


def _num(v) -> float:
    s = str(v or "0").replace(",", "").strip()
    for sym in "$€£₨":
        s = s.replace(sym, "")
    return float(s or 0)


def _date(v: str) -> str:
    from datetime import datetime
    v = (v or "").strip()
    for candidate in (v, v.replace(" ", "T", 1)):
        try:
            return to_iso_z(candidate)
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M %z", "%m/%d/%Y %H:%M", "%m/%d/%Y", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return to_iso_z(datetime.strptime(v, fmt).isoformat())
        except ValueError:
            continue
    raise ConnectorError(f"Unrecognised date: {v!r}. Use ISO format like 2026-03-02 14:05:00.")


def parse_csv(content: bytes | str, code: str, name: str, currency: str | None = None) -> dict:
    text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ConnectorError("CSV file is empty")
    cols = _resolve_headers(reader.fieldnames)

    orders: dict[str, dict] = {}
    detected_currency = None
    for row in reader:
        oid = (row.get(cols["order_id"]) or "").strip()
        if not oid:
            continue
        o = orders.get(oid)
        if o is None:
            status_raw = (row.get(cols.get("status", ""), "") or "paid").strip().lower()
            o = orders[oid] = {
                "id": oid,
                "created_at": _date(row[cols["created_at"]]),
                "customer_email": (row.get(cols.get("customer_email", ""), "") or f"guest-{oid}@unknown").strip(),
                "financial_status": STATUS_MAP.get(status_raw, "cancelled" if status_raw else "paid"),
                "total_price": f"{_num(row[cols['total']]):.2f}",
                "test": False,
                "line_items": [],
            }
        elif _num(row.get(cols["total"])) and not _num(o["total_price"]):
            o["total_price"] = f"{_num(row[cols['total']]):.2f}"
        if "currency" in cols and row.get(cols["currency"]):
            detected_currency = detected_currency or row[cols["currency"]].strip().upper()
        product = (row.get(cols.get("product", ""), "") or "").strip()
        if product:
            o["line_items"].append({
                "title": product,
                "quantity": int(_num(row.get(cols.get("quantity", ""), 1)) or 1),
                "price": f"{_num(row.get(cols.get('price', ''), 0)):.2f}",
            })

    if not orders:
        raise ConnectorError("No orders found in the CSV")
    for o in orders.values():
        if not o["line_items"]:
            o["line_items"] = [{"title": "Order total", "quantity": 1, "price": o["total_price"]}]

    return {
        "brand": {"code": code, "name": name},
        "currency": (currency or detected_currency or "USD").upper(),
        "platform": "csv",
        "synced_at": utc_now_iso(),
        "orders": sorted(orders.values(), key=lambda o: o["created_at"]),
        "subscriptions": [],
    }
