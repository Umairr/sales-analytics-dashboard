"""Common shape every connector produces.

Every connector turns a store's API into the same "store export" JSON the ETL reads:

    {
      "brand": {"code": "...", "name": "..."},
      "currency": "USD",
      "platform": "shopify" | "woocommerce" | "csv" | "demo",
      "synced_at": "2026-11-06T15:00:00Z",
      "orders": [{"id", "created_at", "customer_email", "financial_status",
                  "total_price", "test", "line_items": [{"title", "quantity", "price"}]}],
      "subscriptions": [{"id", "customer_email", "plan", "price", "started_at", "cancelled_at"}]
    }

financial_status is normalised to paid / refunded / pending; anything else
(cancelled, voided, failed) is kept as-is and dropped by the ETL.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx


class ConnectorError(RuntimeError):
    """Raised with a message that is safe to show in the dashboard."""


@dataclass
class StoreConfig:
    code: str
    name: str
    platform: str
    settings: dict = field(default_factory=dict)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_iso_z(value: str | None) -> str | None:
    """Normalise API timestamps ('2026-03-02T10:00:00-05:00', '...Z', naive GMT) to UTC 'Z'."""
    if not value:
        return None
    v = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def merge_records(old: list[dict], new: list[dict]) -> list[dict]:
    """Incremental sync: newer records replace older ones with the same id."""
    by_id = {r["id"]: r for r in old}
    for r in new:
        by_id[r["id"]] = r
    return sorted(by_id.values(), key=lambda r: r.get("created_at") or r.get("started_at") or "")


class Connector:
    platform = "base"

    def __init__(self, store: StoreConfig, client: httpx.Client | None = None):
        self.store = store
        self.client = client or httpx.Client(timeout=60)

    def fetch(self, since: str | None = None) -> dict:
        """Return a store export. `since` = ISO timestamp of the previous sync."""
        raise NotImplementedError

    def export(self, currency: str, orders: list[dict], subscriptions: list[dict]) -> dict:
        return {
            "brand": {"code": self.store.code, "name": self.store.name},
            "currency": currency,
            "platform": self.platform,
            "synced_at": utc_now_iso(),
            "orders": orders,
            "subscriptions": subscriptions,
        }
