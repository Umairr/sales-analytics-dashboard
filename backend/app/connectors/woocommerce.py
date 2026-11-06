"""WordPress / WooCommerce connector: WooCommerce REST API v3.

Create keys in WP Admin -> WooCommerce -> Settings -> Advanced -> REST API (Read access).

Store config (stores.json):
    {"code": "wpstore", "name": "My Woo Store", "platform": "woocommerce",
     "url": "https://shop.example.com",
     "key_env": "WOO_KEY_WPSTORE", "secret_env": "WOO_SECRET_WPSTORE"}

Subscriptions are read from the WooCommerce Subscriptions extension when it is installed.
"""
import os

from .base import Connector, ConnectorError, to_iso_z

STATUS_MAP = {
    "completed": "paid",
    "processing": "paid",
    "refunded": "refunded",
    "pending": "pending",
    "on-hold": "pending",
    "cancelled": "cancelled",
    "failed": "cancelled",
    "trash": "cancelled",
    "checkout-draft": "cancelled",
}
SUB_ENDED = {"cancelled", "expired", "pending-cancel"}


class WooCommerceConnector(Connector):
    platform = "woocommerce"

    def __init__(self, store, client=None):
        super().__init__(store, client)
        s = store.settings
        self.base = (s.get("url") or "").rstrip("/")
        if not self.base.startswith("http"):
            raise ConnectorError(f"{store.code}: set \"url\" (e.g. https://shop.example.com) in stores.json")
        self.key = s.get("key") or os.getenv(s.get("key_env", ""), "")
        self.secret = s.get("secret") or os.getenv(s.get("secret_env", ""), "")
        if not (self.key and self.secret):
            raise ConnectorError(f"{store.code}: WooCommerce consumer key/secret missing. "
                                 f"Put them in .env as {s.get('key_env', 'WOO_KEY_<CODE>')} / {s.get('secret_env', 'WOO_SECRET_<CODE>')}")
        self.currency = s.get("currency")

    def _get_all(self, path: str, params: dict) -> list[dict]:
        out, page = [], 1
        while True:
            r = self.client.get(f"{self.base}/wp-json/wc/v3/{path}", auth=(self.key, self.secret),
                                params={**params, "per_page": 100, "page": page})
            if r.status_code == 404 and path == "subscriptions":
                return []  # WooCommerce Subscriptions not installed
            if r.status_code in (401, 403):
                raise ConnectorError(f"{self.store.code}: WooCommerce rejected the API keys (HTTP {r.status_code}).")
            if r.status_code >= 400:
                raise ConnectorError(f"{self.store.code}: WooCommerce returned HTTP {r.status_code} for /{path}")
            batch = r.json()
            out.extend(batch)
            total_pages = int(r.headers.get("X-WP-TotalPages", page))
            if page >= total_pages or not batch:
                return out
            page += 1

    def fetch(self, since: str | None = None) -> dict:
        params = {"orderby": "modified", "order": "asc"}
        if since:
            params["modified_after"] = since.replace("Z", "")
        raw = self._get_all("orders", params)
        currency = self.currency or (raw[0]["currency"] if raw else None) or "USD"
        orders = []
        for o in raw:
            created = o.get("date_created_gmt") or o.get("date_created")
            email = (o.get("billing") or {}).get("email") or f"guest-{o['id']}@unknown"
            orders.append({
                "id": f"WC-{o.get('number') or o['id']}",
                "created_at": to_iso_z(created),
                "customer_email": email,
                "financial_status": STATUS_MAP.get(o.get("status", ""), "cancelled"),
                "total_price": str(o.get("total", "0")),
                "test": False,
                "line_items": [{
                    "title": li.get("name", "Item"),
                    "quantity": int(li.get("quantity", 1)),
                    "price": str(li.get("price") if li.get("price") is not None else
                                 float(li.get("total", 0)) / max(1, int(li.get("quantity", 1)))),
                } for li in o.get("line_items", [])],
            })

        subs = []
        for s in self._get_all("subscriptions", {}):
            ended = s.get("status") in SUB_ENDED
            end = s.get("cancelled_date_gmt") or s.get("end_date_gmt") or s.get("date_modified_gmt")
            line = (s.get("line_items") or [{}])[0]
            subs.append({
                "id": f"WCS-{s['id']}",
                "customer_email": (s.get("billing") or {}).get("email") or "unknown@unknown",
                "plan": line.get("name") or "Subscription",
                "price": str(s.get("total", "0")),
                "started_at": (s.get("start_date_gmt") or s.get("date_created_gmt") or "")[:10],
                "cancelled_at": end[:10] if ended and end else None,
            })
        return self.export(currency, orders, subs)
