"""Margin page: gross spread per kg, open sales-order book and fill rate, supplier
rate comparison, purchase-price forecast and buy-timing signal."""
import numpy as np
import pandas as pd

from .. import config, loaders
from ..util import records, week_start
from .forecast import holt


def _bulk_oil(pu):
    name = pu.stockitemname.fillna("").str.upper()
    uom = pu.actualuom.fillna("").astype(str).str.upper()
    return pu[uom.str.startswith("KG") & name.str.contains("OIL") & ~name.str.contains("FILM|ROLL") & (pu.qty > 0)]


def gross_spread(as_of=None, months=12):
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    start = (as_of - pd.DateOffset(months=months - 1)).replace(day=1)
    s = loaders.sales()
    s = s[(s.date >= start) & (s.date <= as_of) & s.oil_family.isin(config.FORECAST_FAMILIES) & (s.kg.fillna(0) != 0)]
    s = s.assign(month=s.date.dt.to_period("M").dt.to_timestamp())
    sale = s.groupby(["month", "oil_family"]).agg(sales_value=("amount", "sum"), sales_kg=("kg", "sum")).reset_index()
    sale["realisation_per_kg"] = sale.sales_value / sale.sales_kg
    pu = _bulk_oil(loaders.purchases())
    pu = pu[(pu.date >= start) & (pu.date <= as_of)]
    pu = pu.assign(month=pu.date.dt.to_period("M").dt.to_timestamp())
    buy = pu.groupby(["month", "oil_family"]).agg(purchase_value=("value", "sum"), purchase_kg=("qty", "sum")).reset_index()
    buy["purchase_rate_per_kg"] = buy.purchase_value / buy.purchase_kg
    m = sale.merge(buy, on=["month", "oil_family"], how="left")
    m["gross_spread_per_kg"] = m.realisation_per_kg - m.purchase_rate_per_kg
    m["spread_pct_of_realisation"] = m.gross_spread_per_kg / m.realisation_per_kg * 100
    # weighted summary for the latest 3 months
    last3 = m[m.month >= (as_of - pd.DateOffset(months=2)).replace(day=1)]
    summ = []
    for fam, g in last3.groupby("oil_family"):
        g2 = g.dropna(subset=["purchase_rate_per_kg"])
        if g2.empty:
            continue
        r = g2.sales_value.sum() / g2.sales_kg.sum()
        p = g2.purchase_value.sum() / g2.purchase_kg.sum()
        summ.append({"family": fam, "realisation_per_kg": r, "purchase_rate_per_kg": p, "gross_spread_per_kg": r - p,
                     "spread_pct": (r - p) / r * 100})
    return {"as_of": as_of, "rows": records(m.sort_values(["oil_family", "month"])), "last_3_months": summ,
            "note": "Realisation = net sales ÷ kg sold (packed and loose, ex-GST). Purchase rate = bulk oil purchases ÷ kg "
                    "(ex-GST). The spread has to cover packing material, freight, wages and overheads. Months with no "
                    "bulk-oil purchase for a family show no spread."}


def order_book(as_of=None, fill_window_days=90):
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    o = loaders.orders()
    o = o[o.date <= as_of]
    so = o[o.vouchertype == "Sales Order"]
    if so.empty:
        return {"rows": [], "note": "No sales orders found."}
    ordered = so.groupby(["voucherno", "stockitemname"]).agg(
        order_date=("date", "min"), party=("partyledgername", "first"), ordered_qty=("qty", "sum"),
        order_value=("value", "sum"), due=("orderduedate", "min"), preclosed=("preclosereason", lambda x: x.notna().any())).reset_index()
    inv = o[o.vouchertype == "Sales"].groupby(["batchlineorderno", "stockitemname"]).agg(
        invoiced_qty=("qty", "sum"), last_invoice=("date", "max")).reset_index().rename(columns={"batchlineorderno": "voucherno"})
    m = ordered.merge(inv, on=["voucherno", "stockitemname"], how="left")
    m["invoiced_qty"] = m.invoiced_qty.fillna(0)
    m["pending_qty"] = (m.ordered_qty - m.invoiced_qty).clip(lower=0).where(~m.preclosed, 0)
    m["rate"] = m.order_value / m.ordered_qty.where(m.ordered_qty > 0)
    m["pending_value"] = m.pending_qty * m.rate
    m["age_days"] = (as_of - m.order_date).dt.days
    m["due"] = m.due.fillna(m.order_date)
    m["days_past_due"] = (as_of - m.due).dt.days
    m["filled_qty"] = np.minimum(m.invoiced_qty, m.ordered_qty)
    win = m[(m.order_date > as_of - pd.Timedelta(days=fill_window_days)) & (m.days_past_due >= 0)]
    fill_qty = float(win.filled_qty.sum() / win.ordered_qty.sum() * 100) if win.ordered_qty.sum() else None
    by_order = win.groupby("voucherno").apply(lambda x: (x.filled_qty >= x.ordered_qty).all(), include_groups=False)
    open_ = m[m.pending_qty > 0]
    by_sku = win.groupby("stockitemname").agg(ordered=("ordered_qty", "sum"), filled=("filled_qty", "sum")).reset_index()
    by_sku["fill_rate_pct"] = by_sku.filled / by_sku.ordered * 100
    return {"as_of": as_of, "open_orders": int(open_.voucherno.nunique()), "open_lines": int(len(open_)),
            "open_value": float(open_.pending_value.sum()), "fill_rate_qty_pct": fill_qty,
            "orders_fully_filled_pct": float(by_order.mean() * 100) if len(by_order) else None,
            "open_rows": records(open_.sort_values("pending_value", ascending=False)[
                ["voucherno", "order_date", "party", "stockitemname", "ordered_qty", "invoiced_qty", "pending_qty",
                 "pending_value", "age_days", "days_past_due"]].head(300)),
            "by_sku": records(by_sku.sort_values("ordered", ascending=False)),
            "note": f"Fill rate covers orders from the last {fill_window_days} days that are already due. Invoices are linked "
                    "to orders through the order number on the invoice line. Pre-closed order lines count as not pending."}


def supplier_rates(as_of=None, weeks=26):
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    pu = _bulk_oil(loaders.purchases())
    pu = pu[(pu.date > as_of - pd.Timedelta(weeks=weeks)) & (pu.date <= as_of)]
    if pu.empty:
        return {"rows": []}
    pu = pu.assign(week=week_start(pu.date))
    g = pu.groupby(["week", "oil_family", "supplier"]).agg(kg=("qty", "sum"), value=("value", "sum")).reset_index()
    g["rate"] = g.value / g.kg
    wk = g.groupby(["week", "oil_family"]).agg(min_rate=("rate", "min"), max_rate=("rate", "max"),
                                               suppliers=("supplier", "nunique")).reset_index()
    g = g.merge(wk, on=["week", "oil_family"])
    g["premium_vs_cheapest_pct"] = (g.rate / g.min_rate - 1) * 100
    g["extra_cost_vs_cheapest"] = (g.rate - g.min_rate) * g.kg
    multi = g[g.suppliers > 1]
    sup = multi.groupby(["oil_family", "supplier"]).agg(kg=("kg", "sum"), avg_premium_pct=("premium_vs_cheapest_pct", "mean"),
                                                        extra_cost=("extra_cost_vs_cheapest", "sum"),
                                                        weeks=("week", "nunique")).reset_index()
    return {"as_of": as_of, "weeks": weeks,
            "extra_cost_total": float(multi.extra_cost_vs_cheapest.sum()),
            "rows": records(g.sort_values(["week", "oil_family", "rate"], ascending=[False, True, True])),
            "by_supplier": records(sup.sort_values("extra_cost", ascending=False)),
            "note": "Compares bulk-oil purchase rates (ex-GST) from different suppliers in the same week. "
                    "Extra cost = what was paid above the cheapest supplier that week; quality and credit terms may differ."}


def _market_prices():
    p = config.DATA_DIR / "market_prices.csv"
    if not p.exists():
        return pd.DataFrame(columns=["date", "family", "price_per_kg", "source"])
    m = pd.read_csv(p, comment="#")
    if m.empty:
        return m
    m["date"] = pd.to_datetime(m.date, errors="coerce")
    return m.dropna(subset=["date"])


def buy_timing(as_of=None, horizon=4):
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    pu = _bulk_oil(loaders.purchases())
    pu = pu[(pu.date > as_of - pd.Timedelta(weeks=52)) & (pu.date <= as_of)]
    mkt = _market_prices()
    out = []
    for fam, g in pu.groupby("oil_family"):
        w = g.assign(week=week_start(g.date)).groupby("week").agg(kg=("qty", "sum"), value=("value", "sum"))
        w["rate"] = w.value / w.kg
        idx = pd.date_range(w.index.min(), w.index.max(), freq="W-MON")
        r = w.rate.reindex(idx).interpolate(limit_direction="both")
        if len(r) < 3:
            continue
        f, trend = holt(r, horizon)
        last = float(r.iloc[-1])
        avg8 = float(r.iloc[-8:].mean())
        slope_pct = trend / last * 100 if last else 0
        m = mkt[mkt.family == fam].sort_values("date") if len(mkt) else pd.DataFrame()
        mkt_last = float(m.price_per_kg.iloc[-1]) if len(m) else None
        if slope_pct > 1 and last <= avg8 * 1.01:
            signal = "Buy ahead: prices rising and still near the recent average"
        elif slope_pct > 1:
            signal = "Prices rising: cover near-term needs now"
        elif slope_pct < -1:
            signal = "Prices easing: buy only for immediate needs"
        else:
            signal = "Stable: buy as usual"
        out.append({"family": fam, "last_rate": last, "avg_8_weeks": avg8, "weekly_trend_pct": slope_pct,
                    "forecast_week_4": float(f[-1]), "market_price_latest": mkt_last,
                    "our_premium_vs_market_pct": (last / mkt_last - 1) * 100 if mkt_last else None,
                    "signal": signal,
                    "history": records(pd.DataFrame({"week": r.index, "rate": r.values}).tail(26)),
                    "forecast": records(pd.DataFrame({"week": pd.date_range(r.index[-1] + pd.Timedelta(days=7), periods=horizon, freq="W-MON"),
                                                      "rate": f}))})
    return {"as_of": as_of, "rows": out,
            "note": "Forecast: Holt's linear trend on weekly average purchase rates (gaps interpolated). "
                    "Add outside market prices (e.g. SEA daily quotes) to data/market_prices.csv to compare against the market."}
