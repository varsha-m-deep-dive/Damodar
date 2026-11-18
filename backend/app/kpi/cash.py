"""13-week cash-flow forecast: predicted customer collections minus supplier dues."""
import numpy as np
import pandas as pd

from .. import config, loaders
from ..util import records
from . import forecast, receivables as R


def _lag_profile(st, max_weeks=26):
    """Share of value settled in week 0, 1, 2 … after the bill, from actual settlements."""
    if st is None or len(st) == 0:
        return np.array([0, 0, 0, 0, 1.0])
    w = (st.days_to_pay // 7).clip(upper=max_weeks).astype(int)
    prof = st.groupby(w).paid.sum().reindex(range(max_weeks + 1), fill_value=0).values.astype(float)
    return prof / prof.sum() if prof.sum() else np.array([0, 0, 0, 0, 1.0])


def cash_forecast(as_of=None, weeks=13, opening_cash=0.0, weekly_other_outflow=0.0, scenario="last_year"):
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    W = range(1, weeks + 1)

    def wk(dates):
        return ((pd.to_datetime(dates) - as_of).dt.days - 1) // 7 + 1

    # 1. open customer bills, placed on predicted dates and weighted by collection chance
    ar = R.predicted_payments(as_of)
    ar["week"] = wk(ar.predicted_date)
    in_open = ar[ar.week.between(1, weeks)].groupby("week").expected_amount.sum()

    # 2. collections from future sales: forecast billing (incl. GST) spread over the following
    #    weeks in the same pattern customers actually paid over the last year
    st = R.settlements("debtor", as_of)
    dtp = float(np.average(st.days_to_pay, weights=st.paid)) if len(st) else 30.0
    prof = _lag_profile(st)
    fc = forecast.sales_forecast(12, "net_sales", as_of)
    billing = np.zeros(weeks + 1)
    if fc.get("families"):
        for fam in fc["families"]:
            for i, row in enumerate(fam["scenarios"][scenario]["weeks"]):
                if i + 1 <= weeks:
                    billing[i + 1] += row["forecast"] * config.GST_BILLING_FACTOR
        avg = billing[1:13].mean() if weeks > 12 else 0
        for w in range(13, weeks + 1):
            billing[w] = avg
    fut = np.zeros(weeks + 1)
    for w in range(1, weeks + 1):
        for lag, share in enumerate(prof):
            if w + lag <= weeks:
                fut[w + lag] += billing[w] * share * 0.97

    # 3. open supplier bills, due date + the usual delay
    pay = loaders.payables()
    pay = pay[pay.pendingamount > 0].copy()
    sst = R.settlements("creditor", as_of)
    sdelay = float(np.average(sst.delay.clip(lower=0), weights=sst.paid)) if len(sst) else 0.0
    pd_date = pay.duedate.fillna(pay.billdate) + pd.to_timedelta(sdelay, unit="D")
    overdue = pd_date <= as_of
    pay["week"] = np.where(overdue, 1 + (np.arange(len(pay)) % 2), wk(pd_date))   # overdue: spread over weeks 1-2
    out_open = pay[pay.week.between(1, weeks)].groupby("week").pendingamount.sum()

    # 4. future purchases at the recent run-rate, paid in the pattern suppliers were actually paid
    pu = loaders.purchases()
    recent = pu[(pu.date > as_of - pd.Timedelta(days=84)) & (pu.date <= as_of)]
    data_end = recent.date.max() if (config.DEMO_EXCEL and len(recent)) else as_of   # demo extract stops early
    span_weeks = min(12.0, max(1.0, ((data_end - recent.date.min()).days + 1) / 7)) if len(recent) else 12.0
    weekly_purchases = float(recent.value.sum() / span_weeks * config.GST_BILLING_FACTOR) if len(recent) else 0.0
    sdtp = float(np.average(sst.days_to_pay, weights=sst.paid)) if len(sst) else 30.0
    sprof = _lag_profile(sst)
    out_new = pd.Series(0.0, index=list(W))
    for w in W:
        for lag, share in enumerate(sprof):
            if w + lag <= weeks:
                out_new[w + lag] += weekly_purchases * share

    rows = []
    bal = opening_cash
    for w in W:
        i1, i2 = float(in_open.get(w, 0)), float(fut[w])
        o1, o2 = float(out_open.get(w, 0)), float(out_new.get(w, 0))
        net = i1 + i2 - o1 - o2 - weekly_other_outflow
        bal += net
        rows.append({"week": w, "week_start": as_of + pd.Timedelta(days=7 * (w - 1) + 1),
                     "collections_open_bills": i1, "collections_new_sales": i2,
                     "supplier_dues_open_bills": o1, "supplier_new_purchases": o2,
                     "other_outflows": weekly_other_outflow, "net": net, "closing_cash": bal})
    df = pd.DataFrame(rows)
    low = df.loc[df.closing_cash.idxmin()]
    return {"as_of": as_of, "weeks": weeks, "opening_cash": opening_cash, "rows": records(df),
            "total_in": float(df.collections_open_bills.sum() + df.collections_new_sales.sum()),
            "total_out": float(df.supplier_dues_open_bills.sum() + df.supplier_new_purchases.sum() + df.other_outflows.sum()),
            "lowest_week": int(low.week), "lowest_balance": float(low.closing_cash),
            "assumptions": [
                f"Open customer bills: predicted payment date × collection probability by age.",
                f"New sales: '{forecast.SCENARIOS[scenario]['label']}' sales forecast × {config.GST_BILLING_FACTOR} for GST, "
                f"collected over the following weeks in the pattern customers paid in the last year (average {dtp:.0f} days), 97% collected.",
                f"Supplier bills: due date + average {sdelay:.0f} days' delay; overdue bills spread over weeks 1-2.",
                f"New purchases: average of the last 12 weeks (or the weeks with data) (₹{weekly_purchases/1e5:,.1f} lakh/week incl. GST), paid in the pattern "
                f"suppliers were paid in the last year (average {sdtp:.0f} days).",
                "Salaries, power, freight and other expenses are not in Tally's party ledgers: enter them as weekly other outflows.",
            ]}
