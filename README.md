# Multi-Store Sales Analytics Dashboard

A reporting platform for a business that runs several e-commerce brands.

- A Python ETL pipeline pulls order and subscription exports from each store, cleans them, converts every amount to USD and loads one reporting schema.
- A FastAPI service turns that data into business metrics, forecasts and customer segments.
- A React dashboard presents it in four views: Overview, Customers, Brands and Orders, with light and dark themes.

![Overview](docs/overview.png)

## What's inside

### Overview
- **8 KPI cards** compared with the previous period of the same length (▲ / ▼ deltas), with sparklines. Rates such as churn and repeat rate change in percentage points, not percent.
- **Stacked revenue by brand**, by day, week or month, with the previous period drawn as a dashed line.
- **Automated insights** written from the data:
  - which brand is growing fastest or declining
  - refund-rate warnings
  - high-value customers at risk
  - the size of the Champions segment
  - next month's forecast
  - the best weekday
- **Revenue forecast** for the next 3 months, using Holt's linear trend (double exponential smoothing). The smoothing parameters are chosen automatically, and the chart shows a 95% prediction band and the model's average error.
- **Sales by weekday**, **top products** and **orders per period**.

### Customers
- **Cohort retention heatmap.** Customers are grouped by the month of their first purchase. Each cell shows the % of that cohort who bought again N months later.
- **RFM segmentation.** Each customer is scored on recency, frequency and monetary value and placed in one of 7 segments, from Champions and Loyal through At Risk to Hibernating. Each segment shows its share of customers vs. its share of revenue, plus a suggested action.
- **Top customers by lifetime value**, with their RFM scores.
- **Subscription churn**, with new and cancelled subscriptions per month.

### Brands
- One scorecard per brand: revenue, growth, share, AOV, repeat rate and MRR.
- A benchmark table with orders, customers, refund rate, active subscriptions and churn.
- Charts: revenue-share donut, monthly revenue by brand, AOV and refund-rate comparisons.

### Orders
- Search by order ID or customer email, filter by status, and sort by date, items or value.
- Pagination, and a CSV export of exactly the filtered result.

### Platform
- **Multi-store ETL.** Each brand exports in its own currency (USD, EUR, GBP). The pipeline drops test orders and duplicate orders, normalises emails, converts currencies and pre-computes date buckets.
- **Idempotent loads.** Re-running the ETL never double-counts, and every run is logged.
- **Database-agnostic.** Uses SQLite by default. MySQL or PostgreSQL work through `DATABASE_URL`, because the date buckets are stored as columns and `GROUP BY` doesn't depend on dialect-specific date functions.
- **Global filters.** Choose brands and a date range (presets or custom dates). Every view and export follows them.
- **Tested.** 21 pytest tests cover ETL rules, period comparison, cohorts, RFM scoring, forecasting, the brand benchmark, search and every endpoint. GitHub Actions runs the tests and the frontend build on every push.

| Customers | Brands |
|---|---|
| ![Customers](docs/customers.png) | ![Brands](docs/brands.png) |

| Orders | Dark mode |
|---|---|
| ![Orders](docs/orders.png) | ![Dark mode](docs/overview-dark.png) |

## Tech stack

| Layer | Tools |
|---|---|
| ETL & API | Python 3.12, FastAPI, SQLAlchemy 2.0 |
| Analytics | Cohorts, RFM quintile scoring, Holt's exponential smoothing (pure Python, no heavy deps) |
| Database | SQLite (default), MySQL 8 via Docker Compose |
| Frontend | React 19, Vite, Recharts |
| Tooling | pytest, GitHub Actions, Docker |

## Quick start

**macOS shortcut:** double-click `start-mac.command` in Finder. It installs everything, starts both servers and opens the dashboard.

### Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt -r requirements-dev.txt
uvicorn app.main:app --reload
```

On first start, the API generates a year of demo exports for three brands and runs the ETL: Northwind Outfitters (USD), Maison Lumière (EUR) and Sakura Home (GBP). The demo customers behave realistically: new shoppers arrive every day, they have different loyalty levels and they eventually lapse. The API docs are at http://localhost:8000/docs.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. To point it at another API, set `VITE_API_URL` (see `.env.example`). Add `?theme=dark` to the URL to open in dark mode.

### With Docker and MySQL

```bash
docker compose up --build
```

## Running the ETL manually

```bash
cd backend
python -m app.seed   # regenerate the demo store exports in data/sources/
python -m app.etl    # extract, transform and load
```

To load real data, drop one JSON export per store into `backend/data/sources/`, using the shape `app/seed.py` produces, and run the ETL. The **Re-run ETL** button in the sidebar calls `POST /api/etl/run`.

## API

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/overview` | KPIs for the range, the previous period, and % / pt deltas |
| GET | `/api/insights` | Automated, plain-English insights |
| GET | `/api/forecast?horizon=3` | Holt's forecast with a 95% band, the fitted values and the error |
| GET | `/api/cohorts` | Monthly cohort retention matrix |
| GET | `/api/rfm` | RFM segments, the suggested actions and the top customers |
| GET | `/api/brand-comparison` | Per-brand benchmark, including growth vs the previous period |
| GET | `/api/revenue?bucket=day\|week\|month` | Revenue and orders per period, split by brand |
| GET | `/api/weekday` | Average revenue and orders per weekday |
| GET | `/api/churn` | Monthly subscription churn |
| GET | `/api/top-products` | Best sellers by revenue |
| GET | `/api/orders/search` | Search (`q`), `status`, `sort`, `direction`, pagination |
| GET | `/api/export/orders.csv` | CSV export using the same filters |
| GET | `/api/summary`, `/api/brands`, `/api/meta` | Raw KPIs, the brand list, the data range |
| POST | `/api/etl/run` | Re-run the pipeline |

Most endpoints accept these filters:

- `brand`: one or more brand codes, comma-separated (for example `northwind,sakura`)
- `start` and `end`: dates in `YYYY-MM-DD` format

## Tests

```bash
cd backend && pytest -q
```

## Project structure

```
backend/
  app/
    db.py          # schema + engine (SQLite / MySQL / Postgres)
    seed.py        # demo store exports with a realistic customer lifecycle
    etl.py         # extract, transform, load
    analytics.py   # core reporting queries
    advanced.py    # comparison, cohorts, RFM, forecast, benchmark, insights, search
    main.py        # FastAPI routes
  tests/
frontend/
  src/
    App.jsx        # shell, sidebar, global filters, theme
    pages/         # Overview, Customers, Brands, Orders
    components.jsx # KPI cards, deltas, insights, cards
```

## Notes

- Currency conversion uses fixed reference rates in `etl.py`, so reports are reproducible. In production you would swap in a rates API.
- Revenue counts paid orders only. Refunds are reported separately.
- The forecast is deliberately simple and explainable. With more than a year of history, a seasonal model (Holt-Winters) would capture holiday peaks.
