"""CLI: sync every store in stores.json, then rebuild the reporting database.

    python -m app.sync           # incremental (only orders changed since the last sync)
    python -m app.sync --full    # pull full history again
    python -m app.sync --csv orders.csv --name "My Store" [--currency EUR]

Schedule it with cron for hourly/daily updates, e.g.
    0 * * * * cd /path/to/backend && .venv/bin/python -m app.sync
"""
import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from .sources import BASE_DIR, import_csv, sync_all

load_dotenv(BASE_DIR / ".env")


def main() -> None:
    ap = argparse.ArgumentParser(description="Sync store data into the analytics database")
    ap.add_argument("--full", action="store_true", help="ignore the last sync time and pull everything")
    ap.add_argument("--csv", type=Path, help="import a CSV export instead of syncing APIs")
    ap.add_argument("--name", help="store name for --csv")
    ap.add_argument("--code", help="store code for --csv (default: slug of the name)")
    ap.add_argument("--currency", help="currency of the CSV amounts, e.g. EUR (default: from CSV or USD)")
    args = ap.parse_args()

    if args.csv:
        if not args.name:
            ap.error("--name is required with --csv")
        result = import_csv(args.csv.read_bytes(), args.name, args.code, args.currency)
    else:
        result = sync_all(full=args.full)
        if not result["stores"]:
            print("No stores configured. Copy stores.example.json to stores.json and add your stores.")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
