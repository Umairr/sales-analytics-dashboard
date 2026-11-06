"""Shopify connector: Admin GraphQL API.

Two ways to authenticate:

1. Dev Dashboard app (all new apps since 1 Jan 2026) - client credentials grant.
   The connector exchanges the app's Client ID + Client Secret for a short-lived
   Admin API token on every sync:
     {"code": "mystore", "name": "My Store", "platform": "shopify",
      "shop": "my-store.myshopify.com",
      "client_id_env": "SHOPIFY_CLIENT_ID_MYSTORE", "client_secret_env": "SHOPIFY_CLIENT_SECRET_MYSTORE"}

2. Existing legacy custom app, or any app that already gives you an Admin API token (shpat_...):
     {..., "token_env": "SHOPIFY_TOKEN_MYSTORE"}

Admin API scopes needed:
    read_orders            (add read_all_orders for history older than 60 days)
    read_customers         (customer email on orders)
    read_own_subscription_contracts  (optional, for subscription metrics)
"""
import os
import time

import httpx

from .base import Connector, ConnectorError, to_iso_z

DEFAULT_API_VERSION = "2025-10"

SHOP_QUERY = "{ shop { name currencyCode } }"

ORDERS_QUERY = """
query Orders($cursor: String, $query: String) {
  orders(first: 100, after: $cursor, query: $query, sortKey: UPDATED_AT) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      name
      createdAt
      email
      test
      cancelledAt
      displayFinancialStatus
      totalPriceSet { shopMoney { amount currencyCode } }
      customer { email }
      lineItems(first: 50) {
        nodes { title quantity originalUnitPriceSet { shopMoney { amount } } }
      }
    }
  }
}
"""

SUBSCRIPTIONS_QUERY = """
query Subs($cursor: String) {
  subscriptionContracts(first: 100, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      status
      createdAt
      updatedAt
      customer { email }
      lines(first: 1) { nodes { title currentPrice { amount } } }
    }
  }
}
"""

STATUS_MAP = {
    "PAID": "paid",
    "PARTIALLY_REFUNDED": "paid",
    "REFUNDED": "refunded",
    "PENDING": "pending",
    "AUTHORIZED": "pending",
    "PARTIALLY_PAID": "pending",
    "EXPIRED": "cancelled",
    "VOIDED": "cancelled",
}


class ShopifyConnector(Connector):
    platform = "shopify"

    def __init__(self, store, client=None):
        super().__init__(store, client)
        s = store.settings
        self.shop = (s.get("shop") or "").replace("https://", "").strip("/")
        if not self.shop:
            raise ConnectorError(f"{store.code}: set \"shop\" (e.g. my-store.myshopify.com) in stores.json")
        env = s.get("token_env", "")
        self.token = s.get("token") or os.getenv(env, "")
        self.client_id = s.get("client_id") or os.getenv(s.get("client_id_env", ""), "")
        self.client_secret = s.get("client_secret") or os.getenv(s.get("client_secret_env", ""), "")
        if not self.token and not (self.client_id and self.client_secret):
            raise ConnectorError(
                f"{store.code}: Shopify credentials missing. Put the Dev Dashboard app's Client ID / Secret in .env as "
                f"{s.get('client_id_env', 'SHOPIFY_CLIENT_ID_<CODE>')} / {s.get('client_secret_env', 'SHOPIFY_CLIENT_SECRET_<CODE>')}"
                f" (or an Admin API token as {env or 'SHOPIFY_TOKEN_<CODE>'})")
        self.version = s.get("api_version", DEFAULT_API_VERSION)
        self.url = f"https://{self.shop}/admin/api/{self.version}/graphql.json"

    def _ensure_token(self) -> None:
        """Client credentials grant: Client ID + Secret -> Admin API access token (valid ~24h)."""
        if self.token:
            return
        r = self.client.post(f"https://{self.shop}/admin/oauth/access_token", data={
            "grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.client_secret})
        if r.status_code >= 400:
            detail = ""
            try:
                detail = r.json().get("error_description") or r.json().get("error") or ""
            except ValueError:
                pass
            raise ConnectorError(f"{self.store.code}: Shopify refused the Client ID/Secret (HTTP {r.status_code}). "
                                 f"Is the app installed on {self.shop}? {detail}".strip())
        self.token = r.json()["access_token"]

    def _gql(self, query: str, variables: dict | None = None, retries: int = 5) -> dict:
        self._ensure_token()
        for attempt in range(retries):
            r = self.client.post(self.url, json={"query": query, "variables": variables or {}},
                                 headers={"X-Shopify-Access-Token": self.token, "Content-Type": "application/json"})
            if r.status_code == 401:
                raise ConnectorError(f"{self.store.code}: Shopify rejected the token (401). Check the Admin API access token.")
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After", 2)))
                continue
            if r.status_code >= 400:
                raise ConnectorError(f"{self.store.code}: Shopify returned HTTP {r.status_code}")
            body = r.json()
            errors = body.get("errors")
            if errors:
                codes = {(e.get("extensions") or {}).get("code") for e in errors}
                if "THROTTLED" in codes:
                    time.sleep(2 * (attempt + 1))
                    continue
                if "ACCESS_DENIED" in codes:
                    raise PermissionError(errors[0].get("message", "access denied"))
                raise ConnectorError(f"{self.store.code}: {errors[0].get('message', 'GraphQL error')}")
            return body["data"]
        raise ConnectorError(f"{self.store.code}: Shopify kept throttling the request; try again later.")

    def _orders(self, since: str | None) -> list[dict]:
        out, cursor = [], None
        query = f"updated_at:>='{since}'" if since else None
        while True:
            page = self._gql(ORDERS_QUERY, {"cursor": cursor, "query": query})["orders"]
            for o in page["nodes"]:
                status = STATUS_MAP.get(o.get("displayFinancialStatus") or "", "cancelled")
                if o.get("cancelledAt"):
                    status = "cancelled"
                email = o.get("email") or (o.get("customer") or {}).get("email") or f"guest-{o['name']}@unknown"
                out.append({
                    "id": o["name"],
                    "created_at": to_iso_z(o["createdAt"]),
                    "customer_email": email,
                    "financial_status": status,
                    "total_price": o["totalPriceSet"]["shopMoney"]["amount"],
                    "test": bool(o.get("test")),
                    "line_items": [{
                        "title": li["title"],
                        "quantity": li["quantity"],
                        "price": li["originalUnitPriceSet"]["shopMoney"]["amount"],
                    } for li in o["lineItems"]["nodes"]],
                })
            if not page["pageInfo"]["hasNextPage"]:
                return out
            cursor = page["pageInfo"]["endCursor"]

    def _subscriptions(self) -> list[dict]:
        out, cursor = [], None
        try:
            while True:
                page = self._gql(SUBSCRIPTIONS_QUERY, {"cursor": cursor})["subscriptionContracts"]
                for s in page["nodes"]:
                    line = (s["lines"]["nodes"] or [{}])[0]
                    cancelled = s["status"] in ("CANCELLED", "EXPIRED", "FAILED")
                    out.append({
                        "id": s["id"].rsplit("/", 1)[-1],
                        "customer_email": (s.get("customer") or {}).get("email") or "unknown@unknown",
                        "plan": line.get("title") or "Subscription",
                        "price": (line.get("currentPrice") or {}).get("amount", "0"),
                        "started_at": s["createdAt"][:10],
                        "cancelled_at": s["updatedAt"][:10] if cancelled else None,
                    })
                if not page["pageInfo"]["hasNextPage"]:
                    return out
                cursor = page["pageInfo"]["endCursor"]
        except PermissionError:
            # Store has no subscription app / scope: subscription metrics just stay empty.
            return []

    def fetch(self, since: str | None = None) -> dict:
        shop = self._gql(SHOP_QUERY)["shop"]
        return self.export(shop["currencyCode"], self._orders(since), self._subscriptions())
