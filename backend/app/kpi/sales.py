"""Sales page KPIs: headline sales, realisation, mix, dimensions, top customers,
returns rate and route productivity."""
import pandas as pd

from .. import config, loaders
from ..util import fy_start, pct_change, records, safe_div, same_day_last_year


def _period(df, start, end):
    return df[(df.date >= start) & (df.date <= end)]


def _summ(df):
    inv = df[df.vouchertype == "Sales"].voucherno.nunique()
    return {"net_sales": float(df.amount.sum()), "kg": float(df.kg.fillna(0).sum()), "invoices": int(inv)}


def overview(as_of=None):
    s = loaders.sales()
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    ly = same_day_last_year(as_of)
    fy0, fy0_ly = fy_start(as_of), fy_start(ly)
    m0, m0_ly = as_of.replace(day=1), ly.replace(day=1)
    fy_end_ly = fy_start(as_of) - pd.Timedelta(days=1)
    out = {"as_of": as_of, "last_billing_date": s[s.date <= as_of].date.max(),
           "fy_label": f"FY {fy0.year}-{str(fy0.year + 1)[-2:]}"}
    blocks = {"today": (as_of, as_of, ly, ly), "month": (m0, as_of, m0_ly, ly), "year": (fy0, as_of, fy0_ly, ly)}
    for k, (a, b, c, d) in blocks.items():
        cur, prev = _summ(_period(s, a, b)), _summ(_period(s, c, d))
        out[k] = {**cur, "ly_net_sales": prev["net_sales"], "ly_kg": prev["kg"],
                  "growth_pct": pct_change(cur["net_sales"], prev["net_sales"]),
                  "kg_growth_pct": pct_change(cur["kg"], prev["kg"])}
    ly_full = float(_period(s, fy0_ly, fy_end_ly).amount.sum())
    fy_days = (fy0 + pd.DateOffset(years=1) - fy0).days
    out["fy_progress"] = {
        "days_elapsed_pct": (as_of - fy0).days / fy_days * 100 + 100 / fy_days,
        "ly_full_year_sales": ly_full,
        "ytd_vs_ly_full_year_pct": (out["year"]["net_sales"] / ly_full * 100) if ly_full else None,
        "ly_data_available": bool(ly_full),
    }
    # cumulative daily curve this FY vs last FY (by day of financial year)
    cur = _period(s, fy0, as_of).groupby("date").amount.sum()
    prev = _period(s, fy0_ly, fy_end_ly).groupby("date").amount.sum()
    curve = pd.DataFrame({"day": (cur.index - fy0).days, "this_year": cur.cumsum().values})
    pcurve = pd.DataFrame({"day": (prev.index - fy0_ly).days, "last_year": prev.cumsum().values})
    c = pd.merge_ordered(curve, pcurve, on="day")
    c["last_year"] = c.last_year.ffill()
    c["this_year"] = c.this_year.ffill().where(c.day <= curve.day.max())   # stop the line at today
    out["cumulative"] = records(c[c.day <= 365])
    monthly = s.assign(month=s.date.dt.to_period("M").dt.to_timestamp()).groupby("month").agg(
        net_sales=("amount", "sum"), kg=("kg", "sum")).reset_index()
    out["monthly"] = records(monthly.tail(36))
    return out


def realisation(start=None, end=None):
    s = loaders.sales()
    end = pd.Timestamp(end) if end else loaders.data_as_of()
    start = pd.Timestamp(start) if start else fy_start(end)
    d = _period(s, start, end)
    d = d[~d.is_discount & d.kg.notna() & (d.kg != 0)]

    def agg(keys):
        g = d.groupby(keys).agg(net_sales=("amount", "sum"), kg=("kg", "sum"), qty=("quantity", "sum")).reset_index()
        g["rs_per_kg"] = g.net_sales / g.kg
        g["rs_per_litre"] = g.rs_per_kg * config.KG_PER_LITRE
        return g.sort_values("net_sales", ascending=False)

    by_family = agg(["oil_family"])
    by_sku_type = agg(["oil_family", "pack_type", "pack_size"])
    by_sku = agg(["oil_family", "stockitemname"])
    by_sku["rs_per_unit"] = by_sku.net_sales / by_sku.qty.where(by_sku.qty != 0)
    trend = s[~s.is_discount & s.kg.notna() & (s.kg != 0) & (s.date >= start - pd.DateOffset(months=12)) & (s.date <= end)]
    trend = trend.assign(month=trend.date.dt.to_period("M").dt.to_timestamp()).groupby(["month", "oil_family"]).agg(
        net_sales=("amount", "sum"), kg=("kg", "sum")).reset_index()
    trend["rs_per_kg"] = trend.net_sales / trend.kg
    return {"start": start, "end": end, "by_family": records(by_family), "by_sku_type": records(by_sku_type),
            "by_sku": records(by_sku), "monthly": records(trend),
            "note": f"₹/kg uses {config.KG_PER_LITRE} kg per litre and units-per-box from Tally; net of discounts"}


def mix(start=None, end=None):
    s = loaders.sales()
    end = pd.Timestamp(end) if end else loaders.data_as_of()
    start = pd.Timestamp(start) if start else fy_start(end)
    d = _period(s, start, end)
    d = d[~d.is_discount & d.stockitemname.notna()]   # product lines only
    g = d.groupby(["oil_family", "pack_size"]).agg(net_sales=("amount", "sum"), kg=("kg", "sum")).reset_index()
    g["value_share_pct"] = g.net_sales / g.net_sales.sum() * 100
    g["kg_share_pct"] = g.kg / g.kg.sum() * 100
    fam = d.groupby("oil_family").agg(net_sales=("amount", "sum"), kg=("kg", "sum")).reset_index()
    fam["value_share_pct"] = fam.net_sales / fam.net_sales.sum() * 100
    fam["kg_share_pct"] = fam.kg / fam.kg.sum() * 100
    pack = d.groupby("pack_size").agg(net_sales=("amount", "sum"), kg=("kg", "sum")).reset_index()
    pack["value_share_pct"] = pack.net_sales / pack.net_sales.sum() * 100
    pack["kg_share_pct"] = pack.kg / pack.kg.sum() * 100
    return {"start": start, "end": end, "matrix": records(g.sort_values("net_sales", ascending=False)),
            "by_family": records(fam.sort_values("net_sales", ascending=False)),
            "by_pack_size": records(pack.sort_values("net_sales", ascending=False))}


def by_dimension(dim="route", start=None, end=None):
    if dim not in ("route", "city", "agent", "zone"):
        raise ValueError("dim must be route, city, agent or zone")
    s = loaders.sales()
    end = pd.Timestamp(end) if end else loaders.data_as_of()
    start = pd.Timestamp(start) if start else fy_start(end)
    ly_s, ly_e = same_day_last_year(start), same_day_last_year(end)
    cur = _period(s, start, end)
    prev = _period(s, ly_s, ly_e)
    g = cur.groupby(dim).agg(net_sales=("amount", "sum"), kg=("kg", "sum"), customers=("party", "nunique"),
                             invoices=("voucherno", "nunique")).reset_index()
    p = prev.groupby(dim).amount.sum().rename("ly_net_sales").reset_index()
    g = g.merge(p, on=dim, how="left")
    g["growth_pct"] = (g.net_sales / g.ly_net_sales - 1) * 100
    g["share_pct"] = g.net_sales / g.net_sales.sum() * 100
    g = g.rename(columns={dim: "name"}).sort_values("net_sales", ascending=False)
    note = None
    if dim == "agent" and (g.name == "(not set)").all():
        note = "No agent data: the cost-centre field (costcentreclass) is empty in Tally. Set DIM_AGENT to another field or start using cost centres."
    return {"dim": dim, "start": start, "end": end, "rows": records(g), "note": note,
            "field": {"route": config.DIM_ROUTE, "city": config.DIM_CITY, "agent": config.DIM_AGENT, "zone": config.DIM_ZONE}[dim]}


def top_customers(start=None, end=None, n=20):
    s = loaders.sales()
    end = pd.Timestamp(end) if end else loaders.data_as_of()
    start = pd.Timestamp(start) if start else fy_start(end)
    cur = _period(s, start, end)
    prev = _period(s, same_day_last_year(start), same_day_last_year(end))
    total = cur.amount.sum()
    g = cur.groupby("party").agg(net_sales=("amount", "sum"), kg=("kg", "sum"), invoices=("voucherno", "nunique"),
                                 route=("route", "first"), city=("city", "first"), is_cash=("is_cash", "first")).reset_index()
    g = g.merge(prev.groupby("party").amount.sum().rename("ly_net_sales").reset_index(), on="party", how="left")
    g["growth_pct"] = (g.net_sales / g.ly_net_sales - 1) * 100
    g["share_pct"] = g.net_sales / total * 100
    g = g.sort_values("net_sales", ascending=False)
    named = g[~g.is_cash]
    return {"start": start, "end": end, "total_net_sales": total, "customers": int(named.party.nunique()),
            "top10_share_pct": float(named.head(10).net_sales.sum() / total * 100) if total else None,
            "top20_share_pct": float(named.head(20).net_sales.sum() / total * 100) if total else None,
            "cash_sales": float(g[g.is_cash].net_sales.sum()),
            "rows": records(named.head(n))}


def returns_rate(start=None, end=None):
    s = loaders.sales()
    end = pd.Timestamp(end) if end else loaders.data_as_of()
    start = pd.Timestamp(start) if start else fy_start(end)
    d = _period(s, start, end)
    d = d[~d.is_discount]

    def agg(key):
        g = d.groupby(key).apply(lambda x: pd.Series({
            "sales": x.loc[~x.is_credit_note, "amount"].sum(),
            "credit_notes": -x.loc[x.is_credit_note, "amount"].sum(),
            "credit_note_count": x.loc[x.is_credit_note, "voucherno"].nunique()}), include_groups=False).reset_index()
        g["rate_pct"] = g.credit_notes / g.sales.where(g.sales > 0) * 100
        return g[g.credit_notes != 0].sort_values("credit_notes", ascending=False)

    total_sales = d.loc[~d.is_credit_note, "amount"].sum()
    total_cn = -d.loc[d.is_credit_note, "amount"].sum()
    # credit notes without a stock item are value adjustments (rate/discount), not returns
    cn = d[d.is_credit_note]
    vo = safe_div(cn[cn.stockitemname.isna()].amount.sum(), cn.amount.sum())
    return {"start": start, "end": end,
            "overall_rate_pct": (total_cn / total_sales * 100) if total_sales else None,
            "credit_notes_value": total_cn, "value_only_share_pct": None if vo is None else vo * 100,
            "by_customer": records(agg("party").head(50)), "by_sku": records(agg("stockitemname").head(50))}


def route_productivity(days=90, end=None):
    s = loaders.sales()
    end = pd.Timestamp(end) if end else loaders.data_as_of()
    start = end - pd.Timedelta(days=days - 1)
    d = _period(s, start, end)
    d = d[~d.is_cash]
    inv = d[d.vouchertype == "Sales"].groupby(["route", "voucherno"]).amount.sum().reset_index()
    g = d.groupby("route").agg(net_sales=("amount", "sum"), kg=("kg", "sum"), customers=("party", "nunique")).reset_index()
    i = inv.groupby("route").agg(invoices=("voucherno", "nunique"), avg_bill_value=("amount", "mean")).reset_index()
    g = g.merge(i, on="route", how="left")
    g["sales_per_customer"] = g.net_sales / g.customers
    g["invoices_per_customer"] = g.invoices / g.customers
    g["kg_per_invoice"] = g.kg / g.invoices
    wk = d.groupby("route").date.apply(lambda x: x.dt.to_period("W").nunique()).rename("active_weeks").reset_index()
    g = g.merge(wk, on="route", how="left")
    return {"start": start, "end": end, "days": days, "rows": records(g.sort_values("net_sales", ascending=False))}
