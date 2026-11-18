"""Payables: dues, ageing, days taken to pay suppliers, advances, supplier
concentration and a suggested payment schedule for the week."""
import numpy as np
import pandas as pd

from .. import loaders
from ..util import records
from . import receivables as R


def _bills(as_of):
    p = loaders.payables().copy()
    p["duedate"] = p.duedate.fillna(p.billdate)
    p["dpd"] = (as_of - p.duedate).dt.days
    p["bucket"] = p.dpd.map(R.bucket)
    return p


def summary(as_of=None):
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    p = _bills(as_of)
    bills = p[p.pendingamount > 0]
    adv = p[p.pendingamount < 0]

    def due_within(d):
        return float(bills[(bills.dpd <= 0) & (bills.dpd >= -d)].pendingamount.sum())

    ag = bills.groupby("bucket").agg(amount=("pendingamount", "sum"), bills=("billname", "size")).reindex(
        [b[2] for b in R.BUCKETS]).fillna(0).reset_index()
    sup = bills.groupby("supplier").agg(payable=("pendingamount", "sum"), bills=("billname", "size"),
                                        overdue=("pendingamount", lambda x: x[bills.loc[x.index, "dpd"] > 0].sum()),
                                        next_due=("duedate", "min")).reset_index().sort_values("payable", ascending=False)
    advances = adv.groupby("supplier").agg(advance=("pendingamount", lambda x: -x.sum()), oldest=("billdate", "min"),
                                           entries=("billname", "size")).reset_index().sort_values("advance", ascending=False)
    advances["age_days"] = (as_of - advances.oldest).dt.days
    return {"as_of": as_of, "payable": float(bills.pendingamount.sum()),
            "overdue": float(bills[bills.dpd > 0].pendingamount.sum()),
            "due_today": float(bills[bills.dpd == 0].pendingamount.sum()),
            "due_next_7": due_within(7), "due_next_15": due_within(15), "due_next_30": due_within(30),
            "advances": float(-adv.pendingamount.sum()), "net_payable": float(p.pendingamount.sum()),
            "ageing": records(ag), "by_supplier": records(sup.head(100)), "advances_by_supplier": records(advances.head(100))}


def days_to_pay(as_of=None):
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    g = R.pay_stats("creditor", as_of).sort_values("paid_365d", ascending=False)
    st = R.settlements("creditor", as_of)
    return {"as_of": as_of,
            "overall_avg_days_to_pay": R._wavg(st.days_to_pay, st.paid) if len(st) else None,
            "overall_avg_delay_days": R._wavg(st.delay, st.paid) if len(st) else None,
            "rows": records(g[["ledgername", "avg_days_to_pay", "median_days_to_pay", "avg_delay_days", "terms_days",
                               "paid_365d", "settlements"]])}


def concentration(as_of=None, days=365):
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    pu = loaders.purchases()
    pu = pu[(pu.date > as_of - pd.Timedelta(days=days)) & (pu.date <= as_of)]
    if pu.empty:
        return {"rows": [], "by_material": []}
    tot = pu.value.sum()
    s = pu.groupby("supplier").value.sum().sort_values(ascending=False).reset_index()
    s["share_pct"] = s.value / tot * 100
    hhi = float(((s.value / tot) ** 2).sum() * 10000)
    mat = pu.copy()
    mat["material"] = np.where(mat.actualuom.astype(str).str.upper().str.startswith("KG") & mat.stockitemname.fillna("").str.upper().str.contains("OIL")
                               & ~mat.stockitemname.fillna("").str.upper().str.contains("FILM|ROLL"),
                               mat.oil_family + " oil (bulk)", mat.stockgroupl1.fillna("Other / services"))
    rows = []
    for m, g in mat.groupby("material"):
        v = g.groupby("supplier").value.sum().sort_values(ascending=False)
        rows.append({"material": m, "purchases": float(v.sum()), "suppliers": int(len(v)), "top_supplier": v.index[0],
                     "top_supplier_share_pct": float(v.iloc[0] / v.sum() * 100),
                     "dependence": "Single source" if len(v) == 1 else ("High" if v.iloc[0] / v.sum() > 0.7 else "Spread")})
    return {"as_of": as_of, "days": days, "total_purchases": float(tot), "suppliers": int(len(s)),
            "top1_share_pct": float(s.share_pct.iloc[0]), "top3_share_pct": float(s.share_pct.head(3).sum()),
            "hhi": hhi, "hhi_note": "HHI above 2,500 = highly concentrated; 1,500-2,500 = moderate.",
            "rows": records(s.head(30)), "by_material": records(pd.DataFrame(rows).sort_values("purchases", ascending=False))}


def payment_schedule(as_of=None, cash_available=None):
    """Bills overdue or due within 7 days, ordered for payment. Critical (single-source
    or top-3) suppliers first, then most overdue, then nearest due date. Cash available
    defaults to this week's expected collections."""
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    p = _bills(as_of)
    due = p[(p.pendingamount > 0) & (p.dpd >= -7)].copy()
    conc = concentration(as_of)
    crit = set(r["supplier"] for r in conc.get("rows", [])[:3])
    crit |= {r["top_supplier"] for r in conc.get("by_material", []) if r["dependence"] in ("Single source", "High")}
    due["critical_supplier"] = due.supplier.isin(crit)
    adv = p[p.pendingamount < 0].groupby("supplier").pendingamount.sum().abs()
    due["supplier_advance_held"] = due.supplier.map(adv).fillna(0)
    due = due.sort_values(["critical_supplier", "dpd", "duedate"], ascending=[False, False, True])
    if cash_available is None:
        ec = R.expected_collections(as_of, weeks=1)
        cash_available = ec["expected_total"]
        source = "expected collections in the next 7 days"
    else:
        source = "amount entered"
    run = due.pendingamount.cumsum()
    due["cumulative"] = run
    due["action"] = np.where(due.supplier_advance_held >= due.pendingamount, "Adjust against advance",
                             np.where(run <= cash_available, "Pay this week", "Defer / part-pay"))
    cols = ["supplier", "billname", "billdate", "duedate", "dpd", "pendingamount", "critical_supplier",
            "supplier_advance_held", "cumulative", "action"]
    return {"as_of": as_of, "cash_available": float(cash_available), "cash_source": source,
            "total_due": float(due.pendingamount.sum()),
            "pay_this_week": float(due.loc[due.action == "Pay this week", "pendingamount"].sum()),
            "rule": "Order: critical suppliers (top-3 by purchases, or main source of a material) first, then most overdue, "
                    "then nearest due date; paid in order until the cash available runs out.",
            "rows": records(due[cols].head(200))}
