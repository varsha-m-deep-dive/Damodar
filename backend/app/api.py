"""One list of API routes, used by FastAPI (main.py). Each handler takes the query-string
dict and returns a JSON-safe structure."""
from datetime import date

from . import config, db, loaders
from .kpi import cash, control, customers, forecast, margin, payables, production, receivables, sales
from .util import clean


def _i(q, k, d):
    try:
        return int(q.get(k, d))
    except (TypeError, ValueError):
        return d


def _f(q, k, d):
    try:
        return float(q.get(k, d))
    except (TypeError, ValueError):
        return d


def _d(q, k):
    v = q.get(k)
    return v if v else None


def meta(q):
    c = loaders.companies()
    return {"current_company": loaders.current_company(), "as_of": loaders.data_as_of(),
            "today": date.today(), "demo_mode": bool(config.DEMO_EXCEL),
            "companies": c, "families": config.FORECAST_FAMILIES, "refresh": db.refresh_log,
            "settings": {"kg_per_litre": config.KG_PER_LITRE, "route_field": config.DIM_ROUTE,
                         "city_field": config.DIM_CITY, "agent_field": config.DIM_AGENT, "zone_field": config.DIM_ZONE,
                         "history_years": config.HISTORY_YEARS, "company_filter": config.COMPANY_INCLUDE_REGEX}}


def health(q):
    if config.DEMO_EXCEL:
        return {"ok": True, "source": "demo excel", "file": config.DEMO_EXCEL}
    return {"ok": True, "source": "postgres", **db.ping()}


def clear_cache(q):
    full = str(q.get("full", "")).lower() in ("1", "true", "yes")
    db.clear_cache(full=full)
    return {"ok": True, "full": full}


ROUTES = {
    "/api/meta": meta,
    "/api/health": health,
    "/api/cache/clear": clear_cache,
    # sales
    "/api/sales/overview": lambda q: sales.overview(_d(q, "as_of")),
    "/api/sales/realisation": lambda q: sales.realisation(_d(q, "start"), _d(q, "end")),
    "/api/sales/mix": lambda q: sales.mix(_d(q, "start"), _d(q, "end")),
    "/api/sales/dimension": lambda q: sales.by_dimension(q.get("dim", "route"), _d(q, "start"), _d(q, "end")),
    "/api/sales/top-customers": lambda q: sales.top_customers(_d(q, "start"), _d(q, "end"), _i(q, "n", 20)),
    "/api/sales/forecast": lambda q: forecast.sales_forecast(_i(q, "horizon", 12), q.get("measure", "net_sales"), _d(q, "as_of")),
    "/api/sales/lapsed": lambda q: customers.lapsed(_d(q, "as_of")),
    "/api/sales/call-list": lambda q: customers.call_list(_d(q, "as_of")),
    "/api/sales/rfm": lambda q: customers.rfm(_i(q, "months", 12), _d(q, "as_of")),
    "/api/sales/churn": lambda q: customers.churn(_d(q, "as_of")),
    "/api/sales/festivals": lambda q: forecast.festival_effect(_d(q, "as_of")),
    "/api/sales/elasticity": lambda q: forecast.elasticity(_d(q, "as_of")),
    "/api/sales/cross-sell": lambda q: customers.cross_sell(_d(q, "as_of")),
    "/api/sales/returns": lambda q: sales.returns_rate(_d(q, "start"), _d(q, "end")),
    "/api/sales/route-productivity": lambda q: sales.route_productivity(_i(q, "days", 90), _d(q, "end")),
    # receivables
    "/api/receivables/summary": lambda q: receivables.summary(_d(q, "as_of")),
    "/api/receivables/days-to-pay": lambda q: receivables.days_to_pay(_d(q, "as_of")),
    "/api/receivables/collections": lambda q: receivables.collections_vs_billing(_d(q, "as_of")),
    "/api/receivables/risk": lambda q: receivables.risk(_d(q, "as_of")),
    "/api/receivables/expected": lambda q: receivables.expected_collections(_d(q, "as_of"), _i(q, "weeks", 4)),
    "/api/receivables/predicted-dates": lambda q: receivables.predicted_dates(_d(q, "as_of")),
    "/api/receivables/priority": lambda q: receivables.priority(_d(q, "as_of")),
    "/api/receivables/credit": lambda q: receivables.credit_suggestions(_d(q, "as_of")),
    # payables
    "/api/payables/summary": lambda q: payables.summary(_d(q, "as_of")),
    "/api/payables/days-to-pay": lambda q: payables.days_to_pay(_d(q, "as_of")),
    "/api/payables/concentration": lambda q: payables.concentration(_d(q, "as_of")),
    "/api/payables/schedule": lambda q: payables.payment_schedule(_d(q, "as_of"), _f(q, "cash", None) if q.get("cash") else None),
    # cash
    "/api/cash/forecast": lambda q: cash.cash_forecast(_d(q, "as_of"), _i(q, "weeks", 13), _f(q, "opening", 0.0),
                                                       _f(q, "other", 0.0), q.get("scenario", "last_year")),
    # margin
    "/api/margin/spread": lambda q: margin.gross_spread(_d(q, "as_of")),
    "/api/margin/orders": lambda q: margin.order_book(_d(q, "as_of")),
    "/api/margin/supplier-rates": lambda q: margin.supplier_rates(_d(q, "as_of")),
    "/api/margin/buy-timing": lambda q: margin.buy_timing(_d(q, "as_of")),
    # production
    "/api/production/volume": lambda q: production.packed_volume(_d(q, "as_of"), _i(q, "days", 90)),
    "/api/production/loss": lambda q: production.packing_loss(_d(q, "as_of"), _i(q, "days", 90)),
    "/api/production/packaging": lambda q: production.packaging_per_unit(_d(q, "as_of"), _i(q, "days", 90)),
    "/api/production/vs-sales": lambda q: production.production_vs_sales(_d(q, "as_of"), _i(q, "days", 90)),
    "/api/production/plan": lambda q: production.packing_plan(_d(q, "as_of")),
    # control
    "/api/control/rate-outliers": lambda q: control.rate_outliers(_d(q, "as_of")),
    "/api/control/backdated": lambda q: control.backdated(_d(q, "as_of")),
    "/api/control/packing-loss": lambda q: control.abnormal_packing_loss(_d(q, "as_of")),
}


def handle(path, query):
    """Run a route and return (status, body)."""
    fn = ROUTES.get(path)
    if fn is None:
        return 404, {"error": f"Unknown endpoint {path}"}
    try:
        return 200, clean(fn(dict(query)))
    except Exception as e:  # surface the reason in the dashboard instead of a blank panel
        import traceback
        traceback.print_exc()
        return 500, {"error": f"{type(e).__name__}: {e}"}
