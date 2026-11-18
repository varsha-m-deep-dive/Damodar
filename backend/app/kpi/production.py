"""Production: packed volume, packing loss, packaging material per unit,
production vs sales gap, and a suggested weekly packing plan.

Packing runs in two stages in Tally: bulk oil -> pouches/cans/tins (primary), then
pouches -> boxes (secondary). Volume totals count primary packing only, so a litre is
never counted twice."""
import numpy as np
import pandas as pd

from .. import config, loaders
from ..util import records, week_start


def _classify(p):
    name = p.stockitemname.fillna("").str.upper()
    uom = p.actualuom.fillna("").astype(str).str.upper()
    produced_items = set(p.loc[p.movementtype == "Production", "stockitemname"])
    p = p.copy()
    p["is_bulk_oil"] = uom.str.startswith("KG") & name.str.contains("OIL") & ~name.str.contains("FILM|ROLL") \
        & ~p.stockitemname.isin(produced_items)
    p["is_packaging"] = (p.movementtype == "Consumption") & ~p.is_bulk_oil & ~p.stockitemname.isin(produced_items)
    return p


def _voucher_view(as_of, days):
    p = loaders.production()
    p = p[(p.date <= as_of) & (p.date > as_of - pd.Timedelta(days=days))]
    return _classify(p)


def _bom_oil_per_unit():
    b = loaders.bom()
    if b.empty:
        return {}
    name = b.componentstockitemname.fillna("").str.upper()
    oil = b[name.str.contains("OIL") & ~name.str.contains("FILM|ROLL|BOX|CAN|TIN|BOTTLE|POUCH")
            & b.uom.fillna("").str.upper().str.startswith("KG")]
    per = (oil.qty / oil.headeritemqty.replace(0, np.nan)).groupby(oil.stockitemguid).sum()
    return per.to_dict()   # keyed by output item GUID (names change, GUIDs do not)


def packed_volume(as_of=None, days=90):
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    p = _voucher_view(as_of, days)
    if p.empty:
        return {"rows": [], "daily": [], "monthly": []}
    primary_v = set(p.loc[p.is_bulk_oil & (p.movementtype == "Consumption"), "voucherid"])
    out = p[p.movementtype == "Production"].copy()
    out["stage"] = np.where(out.voucherid.isin(primary_v), "Primary (from bulk oil)", "Secondary (boxing)")
    bom_oil = _bom_oil_per_unit()
    out["oil_kg_per_unit"] = out.stockitemguid.map(bom_oil).fillna(out.kg_per_unit)
    out["kg"] = out.quantity * out.oil_kg_per_unit
    sku = out.groupby(["stockitemname", "oil_family", "stage", "actualuom"]).agg(units=("quantity", "sum"), kg=("kg", "sum"),
                                                                                 days_packed=("date", "nunique")).reset_index()
    prim = out[out.stage.str.startswith("Primary")]
    daily = prim.groupby(["date", "oil_family"]).kg.sum().unstack(fill_value=0).reset_index()
    monthly = prim.assign(month=prim.date.dt.to_period("M").dt.to_timestamp()).groupby(["month", "oil_family"]).agg(
        kg=("kg", "sum"), units=("quantity", "sum")).reset_index()
    return {"as_of": as_of, "days": days, "total_kg": float(prim.kg.sum()),
            "rows": records(sku.sort_values("kg", ascending=False)),
            "daily": records(daily), "monthly": records(monthly),
            "families": sorted(prim.oil_family.unique().tolist())}


def _loss_by_voucher(p):
    bom_oil = _bom_oil_per_unit()
    cons = p[p.is_bulk_oil & (p.movementtype == "Consumption")].groupby("voucherid").agg(
        consumed_kg=("quantity", "sum"), date=("date", "first"), voucherno=("voucherno", "first"),
        oil=("stockitemname", "first"), enteredby=("enteredby", "first"))
    outp = p[p.movementtype == "Production"].copy()
    outp["oil_kg_per_unit"] = outp.stockitemguid.map(bom_oil).fillna(outp.kg_per_unit)
    outp["std_kg"] = outp.quantity * outp.oil_kg_per_unit
    o = outp.groupby("voucherid").agg(output_kg=("std_kg", "sum"), output_units=("quantity", "sum"),
                                      output_item=("stockitemname", "first"), family=("oil_family", "first"))
    v = cons.join(o, how="inner")
    v["loss_kg"] = v.consumed_kg - v.output_kg
    v["loss_pct"] = v.loss_kg / v.consumed_kg * 100
    return v.reset_index()


def packing_loss(as_of=None, days=90):
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    p = _voucher_view(as_of, days)
    v = _loss_by_voucher(p)
    if v.empty:
        return {"rows": [], "note": "No packing vouchers that consume bulk oil in this period."}
    agg = lambda g: pd.Series({"consumed_kg": g.consumed_kg.sum(), "output_kg": g.output_kg.sum(),
                               "loss_pct": (g.consumed_kg.sum() - g.output_kg.sum()) / g.consumed_kg.sum() * 100,
                               "vouchers": len(g)})
    fam = v.groupby("family").apply(agg, include_groups=False).reset_index()
    daily = v.groupby("date").apply(agg, include_groups=False).reset_index()
    monthly = v.assign(month=v.date.dt.to_period("M").dt.to_timestamp()).groupby("month").apply(agg, include_groups=False).reset_index()
    exact = (v.loss_pct.abs() < 0.05).mean() * 100
    note = (f"Output oil = units packed × the oil per unit in the BOM (or {config.KG_PER_LITRE} kg per litre). "
            f"{exact:.0f}% of vouchers show almost exactly zero loss: Tally is consuming oil at the BOM standard, "
            "so real spillage/ullage is not being recorded. Enter actual bulk-oil issued (dip/flow-meter readings) "
            "in the stock journal to make this KPI meaningful.") if exact > 60 else \
        f"Output oil = units packed × the oil per unit in the BOM (or {config.KG_PER_LITRE} kg per litre)."
    total = v.consumed_kg.sum()
    return {"as_of": as_of, "days": days, "consumed_kg": float(total), "output_kg": float(v.output_kg.sum()),
            "loss_pct": float((total - v.output_kg.sum()) / total * 100) if total else None,
            "standard_booking_pct": float(exact), "by_family": records(fam), "daily": records(daily),
            "monthly": records(monthly), "vouchers": records(v.sort_values("loss_pct", ascending=False).head(200)), "note": note}


def packaging_per_unit(as_of=None, days=90):
    """Packaging material used per unit packed vs the BOM standard."""
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    p = _voucher_view(as_of, days)
    b = loaders.bom()
    if p.empty or b.empty:
        return {"rows": []}
    b = b.assign(std_per_unit=b.qty / b.headeritemqty.replace(0, np.nan))
    # match on GUIDs: Tally item names change over time, GUIDs do not
    names = p.drop_duplicates("stockitemguid").set_index("stockitemguid").stockitemname
    std = b[["stockitemguid", "componentguid", "componentstockitemname", "std_per_unit", "uom"]].dropna(subset=["std_per_unit"])
    std["component"] = std.componentguid.map(names).fillna(std.componentstockitemname)
    produced = set(p.loc[p.movementtype == "Production", "stockitemguid"])
    cn = std.component.fillna("").str.upper()
    is_oil = cn.str.contains("OIL") & ~cn.str.contains("FILM|ROLL|BOX|CAN|TIN|BOTTLE|POUCH") & std.uom.fillna("").str.upper().str.startswith("KG")
    std = std[~is_oil & ~std.componentguid.isin(produced)]   # packaging only
    outp = p[p.movementtype == "Production"][["voucherid", "stockitemguid", "stockitemname", "quantity"]]
    pack = p[p.is_packaging][["voucherid", "stockitemguid", "stockitemname", "quantity"]].rename(
        columns={"stockitemguid": "componentguid", "stockitemname": "component", "quantity": "used"})
    # standard need of each output for each component, per voucher -> allocate actual use pro rata
    need = outp.merge(std.drop(columns=["componentstockitemname"]), on="stockitemguid")
    need["std_need"] = need.quantity * need.std_per_unit
    tot_need = need.groupby(["voucherid", "componentguid"]).std_need.transform("sum")
    used = pack.groupby(["voucherid", "componentguid"]).used.sum()
    need["actual_used"] = np.array([used.get((v, c), 0.0) for v, c in zip(need.voucherid, need.componentguid)]) * (need.std_need / tot_need).values
    g = need.groupby(["stockitemname", "component", "uom"]).agg(units_packed=("quantity", "sum"), std_qty=("std_need", "sum"),
                                                                actual_qty=("actual_used", "sum")).reset_index()
    g["std_per_unit"] = g.std_qty / g.units_packed
    g["actual_per_unit"] = g.actual_qty / g.units_packed
    g["variance_pct"] = (g.actual_qty / g.std_qty - 1) * 100
    planned = set(need.componentguid)
    extra = pack[~pack.componentguid.isin(planned)].groupby("component").used.sum()
    return {"as_of": as_of, "days": days, "rows": records(g.sort_values("units_packed", ascending=False)),
            "not_in_any_bom": records(extra.reset_index().rename(columns={"used": "qty"})),
            "note": "Actual packaging consumed in each packing voucher, shared across that voucher's outputs in proportion "
                    "to their BOM requirement, compared with the BOM standard per unit."}


def production_vs_sales(as_of=None, days=90):
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    start = as_of - pd.Timedelta(days=days - 1)
    p = loaders.production()
    if len(p) and p.date.min() > start:   # compare only the days that have production data
        start = p.date.min()
    days = (as_of - start).days + 1
    p = p[(p.date >= start) & (p.date <= as_of)]
    made = p[p.movementtype == "Production"].groupby("stockitemname").quantity.sum()
    used_internally = p[p.movementtype == "Consumption"].groupby("stockitemname").quantity.sum()
    net_made = made.sub(used_internally, fill_value=0).rename("net_produced_for_sale")
    s = loaders.sales()
    s = s[(s.date >= start) & (s.date <= as_of) & ~s.is_discount]
    sold = s.groupby("stockitemname").quantity.sum().rename("sold")
    fam = pd.concat([s.groupby("stockitemname").oil_family.first(), p.groupby("stockitemname").oil_family.first()])
    fam = fam[~fam.index.duplicated()]
    stock = loaders.closing_stock().groupby("stockitemname").closingqty.sum().rename("closing_stock")
    df = pd.concat([made.rename("produced"), used_internally.rename("used_in_boxing"), net_made, sold], axis=1).fillna(0)
    df = df[(df.produced > 0) | (df.sold > 0)]
    df = df.join(stock, how="left").join(fam.rename("oil_family"), how="left")
    df["gap_units"] = df.net_produced_for_sale - df.sold
    df["gap_pct_of_sales"] = df.gap_units / df.sold.where(df.sold > 0) * 100
    weekly_sales = df.sold / (days / 7)
    df["weeks_of_cover"] = df.closing_stock / weekly_sales.where(weekly_sales > 0)
    df["flag"] = np.select([(df.sold > 0) & (df.produced == 0) & (df.closing_stock.fillna(0) <= 0),
                            df.gap_pct_of_sales < -20, df.gap_pct_of_sales > 20],
                           ["Selling without packing (check stock)", "Packing below sales", "Packing above sales"], "")
    df = df.reset_index().rename(columns={"index": "stockitemname"})
    return {"as_of": as_of, "days": days, "start": start,
            "rows": records(df.sort_values("sold", ascending=False)),
            "note": "Net produced for sale = units packed minus units used to fill boxes. Units are each SKU's billing unit "
                    "(boxes, cans, tins, pouches). Closing stock is from Tally today."}


def packing_plan(as_of=None, safety_weeks=0.5, mix_weeks=8):
    """Next week's packing plan by SKU from the sales forecast."""
    from .forecast import sales_forecast
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    fc = sales_forecast(4, "kg", as_of)
    fam_kg = {f["family"]: f["scenarios"]["last_year"]["weeks"][0]["forecast"] for f in fc.get("families", [])}
    s = loaders.sales()
    s = s[(s.date > as_of - pd.Timedelta(weeks=mix_weeks)) & (s.date <= as_of) & ~s.is_discount & (s.kg > 0)
          & s.oil_family.isin(list(fam_kg))]
    mix = s.groupby(["oil_family", "stockitemname"]).agg(kg=("kg", "sum"), units=("quantity", "sum"),
                                                         kg_per_unit=("kg_per_unit", "median")).reset_index()
    mix["share"] = mix.kg / mix.groupby("oil_family").kg.transform("sum")
    mix["forecast_kg"] = mix.oil_family.map(fam_kg) * mix.share
    mix["forecast_units"] = mix.forecast_kg / mix.kg_per_unit
    stock = loaders.closing_stock().groupby("stockitemname").closingqty.sum()
    mix["stock_units"] = mix.stockitemname.map(stock).fillna(0)
    mix["safety_units"] = mix.forecast_units * safety_weeks
    mix["to_pack_units"] = np.ceil((mix.forecast_units + mix.safety_units - mix.stock_units).clip(lower=0))
    mix["bulk_oil_kg"] = mix.to_pack_units * mix.kg_per_unit
    loose = mix.stockitemname.str.upper().str.contains("LOOSE") | (mix.kg_per_unit == 1.0) & ~mix.stockitemname.str.contains(r"\d")
    mix.loc[loose, ["to_pack_units", "bulk_oil_kg"]] = 0  # loose oil is not packed
    b = loaders.bom()
    mats = []
    if not b.empty:
        b = b.assign(per=b.qty / b.headeritemqty.replace(0, np.nan))
        need = mix[mix.to_pack_units > 0].merge(b[["stockitemname", "componentstockitemname", "per", "uom"]], on="stockitemname")
        need["qty"] = need.to_pack_units * need.per
        cn = need.componentstockitemname.fillna("").str.upper()
        need = need[~(cn.str.contains("OIL") & need.uom.fillna("").str.upper().str.startswith("KG")
                      & ~cn.str.contains("FILM|ROLL"))]   # bulk oil is shown separately
        mats = records(need.groupby(["componentstockitemname", "uom"]).qty.sum().reset_index().sort_values("qty", ascending=False))
    by_oil = mix.groupby("oil_family").bulk_oil_kg.sum().reset_index()
    return {"as_of": as_of, "week_starting": (as_of + pd.Timedelta(days=1)),
            "rows": records(mix.sort_values("bulk_oil_kg", ascending=False)[
                ["oil_family", "stockitemname", "forecast_units", "stock_units", "safety_units", "to_pack_units", "bulk_oil_kg"]]),
            "bulk_oil_by_family": records(by_oil), "materials": mats,
            "method": f"Next week's kg forecast per oil (last-year pattern) split across SKUs by the last {mix_weeks} weeks' mix, "
                      f"plus {safety_weeks} week of safety stock, minus finished stock in Tally. Box SKUs list the BOM "
                      "components they need (pouches and empty boxes)."}
