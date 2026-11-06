"""Data sources: connect real stores, sync them and manage the exports the ETL reads.

Stores are listed in backend/stores.json (copy stores.example.json). Secrets live in
backend/.env and are referenced by name, so stores.json can be committed safely.

Run:  python -m app.sync            # sync every configured store, then run the ETL
      python -m app.sync --full     # ignore the last sync time and pull everything again
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import etl
from .connectors import CONNECTORS, ConnectorError, StoreConfig, parse_csv
from .connectors.base import merge_records
from .seed import BRANDS as DEMO_BRANDS
from .seed import SOURCES_DIR, generate

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.getenv("STORES_CONFIG", BASE_DIR / "stores.json"))
STATUS_PATH = SOURCES_DIR.parent / "sync_status.json"
DEMO_CODES = {b["code"] for b in DEMO_BRANDS}
CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,48}$")


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s or "store")[:48]


def load_config(path: Path | None = None) -> dict:
    path = path or CONFIG_PATH
    if not path.exists():
        return {"stores": [], "keep_demo_data": False}
    cfg = json.loads(path.read_text())
    cfg.setdefault("stores", [])
    cfg.setdefault("keep_demo_data", False)
    return cfg


def configured_stores(cfg: dict | None = None) -> list[StoreConfig]:
    cfg = cfg if cfg is not None else load_config()
    out = []
    for s in cfg["stores"]:
        if s.get("enabled", True) is False:
            continue
        code = s.get("code") or slugify(s.get("name", ""))
        if not CODE_RE.match(code):
            raise ConnectorError(f"Invalid store code {code!r}: use lowercase letters, numbers, - or _")
        out.append(StoreConfig(code=code, name=s.get("name", code), platform=s["platform"].lower(),
                               settings={k: v for k, v in s.items() if k not in ("code", "name", "platform")}))
    return out


def _source_path(code: str, source_dir: Path) -> Path:
    if not CODE_RE.match(code):
        raise ConnectorError(f"Invalid source code {code!r}")
    return source_dir / f"{code}.json"


def _read_status() -> dict:
    try:
        return json.loads(STATUS_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_status(status: dict) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, indent=1))


def remove_demo(source_dir: Path = SOURCES_DIR) -> list[str]:
    removed = []
    for f in source_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        if data.get("platform") == "demo" or (data.get("platform") is None and data["brand"]["code"] in DEMO_CODES):
            f.unlink()
            removed.append(data["brand"]["code"])
    return removed


def sync_store(store: StoreConfig, source_dir: Path = SOURCES_DIR, full: bool = False, client=None) -> dict:
    """Fetch one store (incrementally when possible) and write its export file."""
    cls = CONNECTORS.get(store.platform)
    if not cls:
        raise ConnectorError(f"{store.code}: unknown platform {store.platform!r} (use shopify or woocommerce)")
    path = _source_path(store.code, source_dir)
    previous = json.loads(path.read_text()) if path.exists() else None
    since = None
    if previous and not full and previous.get("platform") == cls.platform and previous.get("synced_at"):
        # Overlap by an hour so orders edited during the last sync aren't missed.
        last = datetime.fromisoformat(previous["synced_at"].replace("Z", "+00:00")) - timedelta(hours=1)
        since = last.strftime("%Y-%m-%dT%H:%M:%SZ")

    export = cls(store, client=client).fetch(since=since)
    if previous and since:
        export["orders"] = merge_records(previous.get("orders", []), export["orders"])
        export["subscriptions"] = merge_records(previous.get("subscriptions", []), export["subscriptions"])
    source_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(export, indent=1))
    return {"code": store.code, "name": store.name, "platform": cls.platform, "ok": True,
            "mode": "incremental" if since else "full", "orders": len(export["orders"]),
            "subscriptions": len(export["subscriptions"]), "synced_at": export["synced_at"]}


def sync_all(full: bool = False, source_dir: Path = SOURCES_DIR, cfg: dict | None = None,
             client=None, engine=None) -> dict:
    cfg = cfg if cfg is not None else load_config()
    stores = configured_stores(cfg)
    status = _read_status()
    results = []
    for store in stores:
        try:
            res = sync_store(store, source_dir, full=full, client=client)
        except (ConnectorError, ValueError) as e:
            res = {"code": store.code, "name": store.name, "platform": store.platform, "ok": False, "error": str(e)}
        except Exception as e:  # network errors etc. — never take the whole sync down
            res = {"code": store.code, "name": store.name, "platform": store.platform, "ok": False,
                   "error": f"{type(e).__name__}: {e}"}
        res["checked_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        status[store.code] = res
        results.append(res)
    removed = []
    if stores and any(r["ok"] for r in results) and not cfg.get("keep_demo_data"):
        removed = remove_demo(source_dir)
    _write_status(status)
    etl_result = etl.run(source_dir, engine).as_dict()
    return {"stores": results, "demo_removed": removed, "etl": etl_result}


def import_csv(content: bytes, name: str, code: str | None = None, currency: str | None = None,
               source_dir: Path = SOURCES_DIR, engine=None, replace_demo: bool = True) -> dict:
    code = code or slugify(name)
    export = parse_csv(content, code, name, currency)
    etl.to_usd("1", export["currency"])  # fail early on an unsupported currency
    source_dir.mkdir(parents=True, exist_ok=True)
    _source_path(code, source_dir).write_text(json.dumps(export, indent=1))
    removed = remove_demo(source_dir) if replace_demo else []
    status = _read_status()
    status[code] = {"code": code, "name": name, "platform": "csv", "ok": True, "orders": len(export["orders"]),
                    "synced_at": export["synced_at"], "checked_at": export["synced_at"], "mode": "upload"}
    _write_status(status)
    return {"code": code, "orders": len(export["orders"]), "currency": export["currency"],
            "demo_removed": removed, "etl": etl.run(source_dir, engine).as_dict()}


def delete_source(code: str, source_dir: Path = SOURCES_DIR, engine=None) -> dict:
    path = _source_path(code, source_dir)
    if not path.exists():
        raise ConnectorError(f"No data source named {code!r}")
    path.unlink()
    status = _read_status()
    status.pop(code, None)
    _write_status(status)
    return etl.run(source_dir, engine).as_dict()


def restore_demo(source_dir: Path = SOURCES_DIR, engine=None) -> dict:
    generate(source_dir)
    return etl.run(source_dir, engine).as_dict()


def list_sources(source_dir: Path = SOURCES_DIR) -> dict:
    status = _read_status()
    files = {}
    for f in sorted(source_dir.glob("*.json")):
        try:
            d = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        files[d["brand"]["code"]] = {
            "code": d["brand"]["code"], "name": d["brand"]["name"], "platform": d.get("platform", "demo"),
            "currency": d["currency"], "orders": len(d.get("orders", [])),
            "subscriptions": len(d.get("subscriptions", [])), "synced_at": d.get("synced_at") or d.get("exported_at"),
        }
    try:
        stores = configured_stores()
        config_error = None
    except (ConnectorError, KeyError, json.JSONDecodeError) as e:
        stores, config_error = [], str(e)
    configured = []
    for s in stores:
        st = status.get(s.code, {})
        configured.append({"code": s.code, "name": s.name, "platform": s.platform,
                           "last_result": st or None, "has_data": s.code in files})
    return {"config_file": str(CONFIG_PATH), "config_found": CONFIG_PATH.exists(), "config_error": config_error,
            "configured": configured, "sources": list(files.values()),
            "demo_active": any(v["platform"] == "demo" for v in files.values())}
