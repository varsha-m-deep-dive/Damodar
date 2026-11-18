"""Control: unusual entries — rate outliers, back-dated vouchers, abnormal packing loss."""
import numpy as np
import pandas as pd

from .. import config, loaders
from ..util import records
from . import production


def _robust_z(x, med, mad):
    return (x - med) / (1.4826 * mad.replace(0, np.nan))


def rate_outliers(as_of=None, days=90, window_days=30):
    """Sales lines whose rate per unit is far from the same SKU's median rate in the
    surrounding ±window_days (robust z-score), plus the same check on purchase rates."""
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    s = loaders.sales()
    s = s[(s.date > as_of - pd.Timedelta(days=days + window_days)) & (s.date <= as_of) & ~s.is_discount
          & ~s.is_credit_note & (s.quantity > 0)].copy()
    s["rate"] = s.amount / s.quantity
    rows = []
    for item, g in s.groupby("stockitemname"):
        g = g.sort_values("date")
        if len(g) < 8:
            continue
        for idx, r in g[g.date > as_of - pd.Timedelta(days=days)].iterrows():
            ref = g[(g.date >= r.date - pd.Timedelta(days=window_days)) & (g.date <= r.date + pd.Timedelta(days=window_days))
                    & (g.index != idx)].rate
            if len(ref) < 5:
                continue
            med = ref.median()
            mad = (ref - med).abs().median()
            z = (r.rate - med) / (1.4826 * mad) if mad > 0 else (0 if r.rate == med else np.inf * np.sign(r.rate - med))
            dev = (r.rate / med - 1) * 100 if med else None
            if abs(z) > config.OUTLIER_MAD_K and dev is not None and abs(dev) > 3:
                rows.append({"type": "Sales rate", "date": r.date, "voucherno": r.voucherno, "party": r.party,
                             "item": item, "quantity": r.quantity, "rate": r.rate, "typical_rate": med,
                             "deviation_pct": dev, "value_impact": (r.rate - med) * r.quantity})
    pu = loaders.purchases()
    pu = pu[(pu.date > as_of - pd.Timedelta(days=days + window_days)) & (pu.date <= as_of) & (pu.qty > 0)].copy()
    pu["rate"] = pu.value / pu.qty
    for item, g in pu.groupby("stockitemname"):
        if len(g) < 5:
            continue
        for idx, r in g[g.date > as_of - pd.Timedelta(days=days)].iterrows():
            ref = g[(g.date >= r.date - pd.Timedelta(days=window_days)) & (g.date <= r.date + pd.Timedelta(days=window_days))
                    & (g.index != idx)].rate
            if len(ref) < 4:
                continue
            med = ref.median()
            dev = (r.rate / med - 1) * 100 if med else None
            if dev is not None and abs(dev) > 8:
                rows.append({"type": "Purchase rate", "date": r.date, "voucherno": r.voucherno, "party": r.supplier,
                             "item": item, "quantity": r.qty, "rate": r.rate, "typical_rate": med,
                             "deviation_pct": dev, "value_impact": (r.rate - med) * r.qty})
    df = pd.DataFrame(rows)
    if df.empty:
        return {"rows": [], "count": 0}
    df["abs_impact"] = df.value_impact.abs()
    df = df.sort_values("abs_impact", ascending=False).drop(columns="abs_impact")
    return {"as_of": as_of, "count": len(df), "rows": records(df.head(300)),
            "rule": f"Sales: rate more than {config.OUTLIER_MAD_K} robust standard deviations and 3% away from the same item's "
                    f"median rate within ±{window_days} days. Purchases: more than 8% away from that median."}


def backdated(as_of=None):
    """Tally numbers vouchers internally (masterid) in the order they are created. A
    voucher dated well before the vouchers created around it was entered late."""
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    v = loaders.voucher_headers()
    v = v[(v.date <= as_of) & v.vouchermasterid.notna()]
    out = []
    for comp, g in v.groupby("companyname"):
        g = g.sort_values("vouchermasterid").copy()
        if len(g) < 30:
            continue
        d = g.date.map(pd.Timestamp.toordinal).astype(float)
        g["entry_period_date"] = d.rolling(41, center=True, min_periods=10).median()
        g["days_backdated"] = g.entry_period_date - d
        out.append(g)
    if not out:
        return {"rows": [], "count": 0}
    df = pd.concat(out)
    df = df[df.days_backdated > config.BACKDATED_TOLERANCE_DAYS].copy()
    df["entered_around"] = df.entry_period_date.round().astype(int).map(pd.Timestamp.fromordinal)
    by_user = df.groupby(df.enteredby.fillna("(unknown)").str.strip().str.lower()).agg(vouchers=("voucherid", "size"),
                                                              avg_days=("days_backdated", "mean")).reset_index()
    cols = ["date", "entered_around", "days_backdated", "vouchertype", "vouchertypename", "voucherno",
            "partyledgername", "enteredby", "companyname"]
    return {"as_of": as_of, "count": len(df), "rows": records(df.sort_values("days_backdated", ascending=False)[cols].head(300)),
            "by_user": records(by_user.sort_values("vouchers", ascending=False)),
            "rule": f"Voucher date more than {config.BACKDATED_TOLERANCE_DAYS} days earlier than the median date of the 40 "
                    "vouchers created around it (Tally's internal master id order). Tally does not store an entry timestamp, "
                    "so this is an estimate; opening or year-end adjustment entries may be legitimate."}


def abnormal_packing_loss(as_of=None, days=90):
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    p = production._voucher_view(as_of, days)
    v = production._loss_by_voucher(p)
    if v.empty:
        return {"rows": [], "count": 0}
    med = v.groupby("family").loss_pct.transform("median")
    mad = v.groupby("family").loss_pct.transform(lambda x: (x - x.median()).abs().median())
    v["robust_z"] = _robust_z(v.loss_pct, med, mad)
    flag = (v.loss_pct.abs() > 1.0) | (v.robust_z.abs() > config.OUTLIER_MAD_K)
    f = v[flag].sort_values("loss_kg", ascending=False)
    return {"as_of": as_of, "count": len(f),
            "rows": records(f[["date", "voucherno", "family", "output_item", "consumed_kg", "output_kg", "loss_kg", "loss_pct", "enteredby"]]),
            "rule": "Packing voucher whose loss is above 1% (or negative beyond 1%), or far from the usual loss for that oil."}
