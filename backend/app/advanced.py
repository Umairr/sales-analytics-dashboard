"""Advanced analytics: period comparison, cohorts, RFM segmentation, forecasting,
brand benchmarking and automated insights."""
from collections import defaultdict
from datetime import date, timedelta
from math import sqrt

from sqlalchemy import and_, func, or_, select
from sqlalchemy.engine import Engine

from . import analytics
from .db import brands, orders


# ---------- helpers ----------

def data_bounds(engine: Engine) -> tuple[date, date]:
    with engine.connect() as conn:
        lo, hi = conn.execute(select(func.min(orders.c.order_date), func.max(orders.c.order_date))).one()
    return lo, hi


def resolve_range(engine: Engine, start: date | None, end: date | None) -> tuple[date, date]:
    lo, hi = data_bounds(engine)
    return start or lo, end or hi


def previous_range(start: date, end: date) -> tuple[date, date]:
    length = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    return prev_end - timedelta(days=length - 1), prev_end


def pct_change(cur: float, prev: float) -> float | None:
    if not prev:
        return None
    return round((cur - prev) / prev * 100, 1)


def _paid_orders(engine: Engine, brand_codes, start=None, end=None):
    q = (select(orders.c.customer_email, orders.c.order_date, orders.c.total_usd, brands.c.code)
         .select_from(orders.join(brands))
         .where(orders.c.status == "paid"))
    if brand_codes:
        q = q.where(brands.c.code.in_(brand_codes))
    if start:
        q = q.where(orders.c.order_date >= start)
    if end:
        q = q.where(orders.c.order_date <= end)
    with engine.connect() as conn:
        return conn.execute(q).all()


def _month_index(d: date) -> int:
    return d.year * 12 + d.month - 1


def _month_label(idx: int) -> str:
    return f"{idx // 12}-{idx % 12 + 1:02d}"


# ---------- period comparison ----------

COMPARE_KEYS = ["revenue", "orders", "aov", "customers", "refunded", "active_subscriptions", "mrr"]
RATE_KEYS = ["churn_rate", "repeat_rate"]


def summary_with_comparison(engine: Engine, brand_codes=None, start=None, end=None) -> dict:
    start, end = resolve_range(engine, start, end)
    p_start, p_end = previous_range(start, end)
    lo, _ = data_bounds(engine)
    current = analytics.summary(engine, brand_codes, start, end)
    has_prev = p_end >= lo
    previous = analytics.summary(engine, brand_codes, p_start, p_end) if has_prev else None
    deltas = {k: (pct_change(current[k], previous[k]) if previous else None) for k in COMPARE_KEYS}
    current.update(repeat_rate(engine, brand_codes, start, end))
    if previous:
        previous.update(repeat_rate(engine, brand_codes, p_start, p_end))
    # Rates change in percentage points, not percent.
    for k in RATE_KEYS:
        deltas[k] = round(current[k] - previous[k], 2) if previous else None
    return {
        "current": current,
        "previous": previous,
        "delta_pct": deltas,
        "range": {"start": start, "end": end},
        "previous_range": {"start": p_start, "end": p_end} if has_prev else None,
    }


def repeat_rate(engine: Engine, brand_codes, start, end) -> dict:
    counts: dict[str, int] = defaultdict(int)
    for r in _paid_orders(engine, brand_codes, start, end):
        counts[r.customer_email] += 1
    total = len(counts)
    repeat = sum(1 for c in counts.values() if c > 1)
    return {"repeat_rate": round(repeat / total * 100, 1) if total else 0.0}


# ---------- cohorts ----------

def cohort_retention(engine: Engine, brand_codes=None, max_months: int = 12) -> list[dict]:
    """Group customers by first-purchase month; share still buying N months later."""
    rows = _paid_orders(engine, brand_codes)
    if not rows:
        return []
    first: dict[str, int] = {}
    active: dict[str, set[int]] = defaultdict(set)
    revenue_by_cohort: dict[int, float] = defaultdict(float)
    for r in rows:
        m = _month_index(r.order_date)
        first[r.customer_email] = min(first.get(r.customer_email, m), m)
        active[r.customer_email].add(m)
    for r in rows:
        revenue_by_cohort[first[r.customer_email]] += r.total_usd

    last_month = max(_month_index(r.order_date) for r in rows)
    cohorts: dict[int, list[str]] = defaultdict(list)
    for email, m in first.items():
        cohorts[m].append(email)

    out = []
    for m in sorted(cohorts):
        members = cohorts[m]
        size = len(members)
        span = min(max_months, last_month - m + 1)
        retention = []
        for offset in range(span):
            still = sum(1 for e in members if (m + offset) in active[e])
            retention.append(round(still / size * 100, 1))
        out.append({
            "cohort": _month_label(m),
            "customers": size,
            "revenue_per_customer": round(revenue_by_cohort[m] / size, 2),
            "retention": retention,
        })
    return out


# ---------- RFM segmentation ----------

SEGMENT_ORDER = ["Champions", "Loyal", "Potential Loyalists", "New Customers",
                 "Need Attention", "At Risk", "Hibernating"]
SEGMENT_ACTIONS = {
    "Champions": "Reward them; ask for reviews and referrals.",
    "Loyal": "Upsell higher tiers and subscriptions.",
    "Potential Loyalists": "Offer membership or a loyalty programme.",
    "New Customers": "Onboard well; push a second purchase within 30 days.",
    "Need Attention": "Personalised offers before they drift away.",
    "At Risk": "Win-back campaign with a strong incentive.",
    "Hibernating": "Low-cost reactivation or suppress from paid campaigns.",
}


def _quintile_scores(values: dict[str, float], reverse: bool = False) -> dict[str, int]:
    """Score 1-5 by rank. reverse=True means lower values are better (recency)."""
    ranked = sorted(values, key=lambda k: values[k], reverse=reverse)
    n = len(ranked)
    return {k: min(5, i * 5 // n + 1) for i, k in enumerate(ranked)}


def _segment(r: int, f: int) -> str:
    if r >= 4 and f >= 4:
        return "Champions"
    if f >= 4 and r >= 2:
        return "Loyal"
    if r >= 4 and f >= 2:
        return "Potential Loyalists"
    if r >= 4:
        return "New Customers"
    if r <= 2 and f >= 3:
        return "At Risk"
    if r <= 2:
        return "Hibernating"
    return "Need Attention"


def rfm_segments(engine: Engine, brand_codes=None, as_of: date | None = None) -> dict:
    rows = _paid_orders(engine, brand_codes, end=as_of)
    if not rows:
        return {"as_of": as_of, "segments": [], "top_customers": []}
    as_of = as_of or max(r.order_date for r in rows)
    last: dict[str, date] = {}
    freq: dict[str, int] = defaultdict(int)
    money: dict[str, float] = defaultdict(float)
    brand_of: dict[str, str] = {}
    for r in rows:
        e = r.customer_email
        last[e] = max(last.get(e, r.order_date), r.order_date)
        freq[e] += 1
        money[e] += r.total_usd
        brand_of[e] = r.code

    recency = {e: (as_of - d).days for e, d in last.items()}
    r_score = _quintile_scores(recency, reverse=True)
    f_score = _quintile_scores(freq)
    m_score = _quintile_scores(money)

    seg_stats: dict[str, dict] = {s: {"customers": 0, "revenue": 0.0, "recency": 0, "orders": 0} for s in SEGMENT_ORDER}
    customers = []
    for e in last:
        seg = _segment(r_score[e], f_score[e])
        s = seg_stats[seg]
        s["customers"] += 1
        s["revenue"] += money[e]
        s["recency"] += recency[e]
        s["orders"] += freq[e]
        customers.append({"email": e, "brand": brand_of[e], "segment": seg, "orders": freq[e],
                          "revenue": round(money[e], 2), "days_since_last": recency[e],
                          "rfm": f"{r_score[e]}{f_score[e]}{m_score[e]}"})

    total_customers = len(last)
    total_revenue = sum(money.values())
    segments = []
    for seg in SEGMENT_ORDER:
        s = seg_stats[seg]
        if not s["customers"]:
            continue
        segments.append({
            "segment": seg,
            "customers": s["customers"],
            "share_customers": round(s["customers"] / total_customers * 100, 1),
            "revenue": round(s["revenue"], 2),
            "share_revenue": round(s["revenue"] / total_revenue * 100, 1),
            "avg_recency_days": round(s["recency"] / s["customers"]),
            "avg_orders": round(s["orders"] / s["customers"], 1),
            "action": SEGMENT_ACTIONS[seg],
        })
    customers.sort(key=lambda c: c["revenue"], reverse=True)
    return {"as_of": as_of, "segments": segments, "top_customers": customers[:10]}


# ---------- forecasting ----------

def _holt(ys: list[float], alpha: float, beta: float) -> tuple[list[float], float, float]:
    """Holt's linear exponential smoothing. Returns one-step fitted values, last level, last trend."""
    level, trend = ys[0], ys[1] - ys[0]
    fitted = [ys[0]]
    for y in ys[1:]:
        fitted.append(level + trend)
        prev_level = level
        level = alpha * y + (1 - alpha) * (level + trend)
        trend = beta * (level - prev_level) + (1 - beta) * trend
    return fitted, level, trend


def revenue_forecast(engine: Engine, brand_codes=None, horizon: int = 3) -> dict:
    """Holt's linear trend (double exponential smoothing) on monthly revenue.

    Recent months weigh more than old ones, so a one-off holiday spike at the start
    of the data doesn't flatten the trend. Smoothing parameters are picked by grid
    search on one-step-ahead error; the band is a 95% interval from those errors,
    widening with the horizon."""
    rows = _paid_orders(engine, brand_codes)
    if not rows:
        return {"history": [], "forecast": [], "method": "holt"}
    monthly: dict[int, float] = defaultdict(float)
    for r in rows:
        monthly[_month_index(r.order_date)] += r.total_usd
    months = sorted(monthly)
    ys = [monthly[m] for m in months]
    if len(ys) < 4:
        return {"history": [{"period": _month_label(m), "actual": round(monthly[m], 2)} for m in months],
                "forecast": [], "method": "holt"}

    best = None
    for a in [i / 10 for i in range(1, 10)]:
        for b in [i / 10 for i in range(1, 10)]:
            fitted, level, trend = _holt(ys, a, b)
            sse = sum((y - f) ** 2 for y, f in zip(ys[2:], fitted[2:]))
            if best is None or sse < best[0]:
                best = (sse, a, b, fitted, level, trend)
    sse, alpha, beta, fitted, level, trend = best
    se = sqrt(sse / max(1, len(ys) - 3))

    history = [{"period": _month_label(m), "actual": round(y, 2), "trend": round(f, 2)}
               for m, y, f in zip(months, ys, fitted)]
    forecast = []
    for h in range(1, horizon + 1):
        yhat = level + h * trend
        band = 1.96 * se * sqrt(1 + (h - 1) * alpha ** 2 * (1 + h * beta))
        forecast.append({"period": _month_label(months[-1] + h), "forecast": round(max(0, yhat), 2),
                         "lower": round(max(0, yhat - band), 2), "upper": round(yhat + band, 2)})
    mean = sum(ys) / len(ys)
    return {"history": history, "forecast": forecast, "method": "holt", "alpha": alpha, "beta": beta,
            "monthly_growth": round(trend, 2), "monthly_growth_pct": round(trend / level * 100, 2) if level else 0,
            "mape": round(sum(abs(y - f) / y for y, f in zip(ys[2:], fitted[2:]) if y) / (len(ys) - 2) * 100, 1)
            if mean else None}


# ---------- brand benchmarking ----------

def brand_comparison(engine: Engine, start=None, end=None) -> list[dict]:
    start, end = resolve_range(engine, start, end)
    p_start, p_end = previous_range(start, end)
    lo, _ = data_bounds(engine)
    out = []
    all_revenue = analytics.summary(engine, None, start, end)["revenue"] or 1
    for b in analytics.list_brands(engine):
        cur = analytics.summary(engine, [b["code"]], start, end)
        prev = analytics.summary(engine, [b["code"]], p_start, p_end) if p_end >= lo else None
        gross = cur["revenue"] + cur["refunded"]
        out.append({
            "code": b["code"], "name": b["name"], "currency": b["source_currency"],
            "revenue": cur["revenue"], "orders": cur["orders"], "aov": cur["aov"],
            "customers": cur["customers"],
            "refund_rate": round(cur["refunded"] / gross * 100, 2) if gross else 0.0,
            "share": round(cur["revenue"] / all_revenue * 100, 1),
            "growth_pct": pct_change(cur["revenue"], prev["revenue"]) if prev else None,
            "active_subscriptions": cur["active_subscriptions"], "mrr": cur["mrr"],
            "churn_rate": cur["churn_rate"],
            **repeat_rate(engine, [b["code"]], start, end),
        })
    out.sort(key=lambda r: r["revenue"], reverse=True)
    return out


# ---------- weekday pattern ----------

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
WEEKDAY_NAMES = dict(zip(WEEKDAYS, ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]))


def weekday_pattern(engine: Engine, brand_codes=None, start=None, end=None) -> list[dict]:
    totals = defaultdict(float)
    counts = defaultdict(int)
    days = defaultdict(set)
    for r in _paid_orders(engine, brand_codes, start, end):
        wd = r.order_date.weekday()
        totals[wd] += r.total_usd
        counts[wd] += 1
        days[wd].add(r.order_date)
    return [{"day": WEEKDAYS[i], "avg_revenue": round(totals[i] / len(days[i]), 2) if days[i] else 0,
             "avg_orders": round(counts[i] / len(days[i]), 1) if days[i] else 0} for i in range(7)]


# ---------- automated insights ----------

def _money(v: float) -> str:
    return f"${v:,.0f}"


def insights(engine: Engine, brand_codes=None, start=None, end=None) -> list[dict]:
    out: list[dict] = []
    comp = summary_with_comparison(engine, brand_codes, start, end)
    d, cur = comp["delta_pct"], comp["current"]
    if d["revenue"] is not None:
        tone = "positive" if d["revenue"] >= 0 else "negative"
        word = "up" if d["revenue"] >= 0 else "down"
        out.append({"tone": tone, "title": f"Revenue {word} {abs(d['revenue'])}%",
                    "detail": f"{_money(cur['revenue'])} vs {_money(comp['previous']['revenue'])} in the previous period."})
    if d["aov"] is not None and abs(d["aov"]) >= 3:
        out.append({"tone": "positive" if d["aov"] > 0 else "negative",
                    "title": f"Average order value {'rose' if d['aov'] > 0 else 'fell'} {abs(d['aov'])}%",
                    "detail": f"Now {_money(cur['aov'])} per order."})

    if not brand_codes or len(brand_codes) > 1:
        bc = [b for b in brand_comparison(engine, start, end) if not brand_codes or b["code"] in brand_codes]
        growing = [b for b in bc if b["growth_pct"] is not None]
        if growing:
            best = max(growing, key=lambda b: b["growth_pct"])
            worst = min(growing, key=lambda b: b["growth_pct"])
            out.append({"tone": "positive", "title": f"{best['name']} is the fastest-growing brand",
                        "detail": f"Revenue {best['growth_pct']:+}% period over period, {best['share']}% of total sales."})
            if worst["code"] != best["code"] and worst["growth_pct"] < 0:
                out.append({"tone": "negative", "title": f"{worst['name']} is declining",
                            "detail": f"Revenue {worst['growth_pct']:+}% period over period."})
        if bc:
            refund = max(bc, key=lambda b: b["refund_rate"])
            if refund["refund_rate"] >= 4:
                out.append({"tone": "warning", "title": f"High refund rate at {refund['name']}",
                            "detail": f"{refund['refund_rate']}% of gross sales refunded. Check product quality and descriptions."})

    rfm = rfm_segments(engine, brand_codes, comp["range"]["end"])
    risk = next((s for s in rfm["segments"] if s["segment"] == "At Risk"), None)
    if risk:
        out.append({"tone": "warning", "title": f"{risk['customers']} high-value customers at risk",
                    "detail": f"They drove {_money(risk['revenue'])} lifetime but haven't ordered in ~{risk['avg_recency_days']} days. Worth a win-back campaign."})
    champs = next((s for s in rfm["segments"] if s["segment"] == "Champions"), None)
    if champs:
        out.append({"tone": "positive", "title": f"Champions: {champs['share_customers']}% of customers, {champs['share_revenue']}% of revenue",
                    "detail": "Protect this group with loyalty perks and early access."})

    fc = revenue_forecast(engine, brand_codes)
    if fc["forecast"]:
        nxt = fc["forecast"][0]
        out.append({"tone": "neutral", "title": f"Forecast for {nxt['period']}: {_money(nxt['forecast'])}",
                    "detail": f"Range {_money(nxt['lower'])} to {_money(nxt['upper'])} (Holt trend model, 95% band, {fc['mape']}% avg error)."})

    wk = weekday_pattern(engine, brand_codes, comp["range"]["start"], comp["range"]["end"])
    if any(w["avg_revenue"] for w in wk):
        top = max(wk, key=lambda w: w["avg_revenue"])
        low = min(wk, key=lambda w: w["avg_revenue"])
        if low["avg_revenue"]:
            out.append({"tone": "neutral", "title": f"{WEEKDAY_NAMES[top['day']]} is the strongest sales day",
                        "detail": f"{_money(top['avg_revenue'])}/day on average, {round((top['avg_revenue'] / low['avg_revenue'] - 1) * 100)}% above {WEEKDAY_NAMES[low['day']]}."})
    return out


# ---------- order search ----------

def search_orders(engine: Engine, brand_codes=None, start=None, end=None, q: str | None = None,
                  status: str | None = None, limit: int | None = 25, offset: int = 0,
                  sort: str = "created_at", direction: str = "desc") -> dict:
    conds = [analytics._order_filters(brand_codes, start, end)]
    if q:
        like = f"%{q.lower()}%"
        conds.append(or_(func.lower(orders.c.external_id).like(like), orders.c.customer_email.like(like)))
    if status:
        conds.append(orders.c.status == status)
    where = and_(*conds)
    sort_col = {"created_at": orders.c.created_at, "total_usd": orders.c.total_usd,
                "item_count": orders.c.item_count}.get(sort, orders.c.created_at)
    order_by = sort_col.desc() if direction == "desc" else sort_col.asc()
    base = orders.join(brands)
    with engine.connect() as conn:
        total = conn.execute(select(func.count()).select_from(base).where(where)).scalar()
        rows = conn.execute(
            select(orders.c.external_id.label("order_id"), brands.c.name.label("brand"), brands.c.code,
                   orders.c.created_at, orders.c.customer_email, orders.c.status, orders.c.item_count,
                   orders.c.total_source, brands.c.source_currency.label("currency"), orders.c.total_usd)
            .select_from(base).where(where).order_by(order_by).limit(limit).offset(offset or None)).all()
    return {"total": total, "limit": limit, "offset": offset, "rows": [dict(r._mapping) for r in rows]}
