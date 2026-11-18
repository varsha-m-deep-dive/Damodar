"""Receivables: ageing, days-to-pay, collections vs billing, payment-risk score,
expected collections, predicted payment dates, priority list, credit suggestions."""
import math

import numpy as np
import pandas as pd

from .. import config, loaders
from ..util import records

BUCKETS = [(-10**6, 0, "Not due"), (1, 30, "1-30 days"), (31, 60, "31-60 days"), (61, 90, "61-90 days"),
           (91, 180, "91-180 days"), (181, 10**6, "180+ days")]


def bucket(dpd):
    for lo, hi, name in BUCKETS:
        if lo <= dpd <= hi:
            return name
    return "Not due"


def _open_bills(as_of):
    o = loaders.outstanding().copy()
    o["duedate"] = o.duedate.fillna(o.billdate)
    o["dpd"] = (as_of - o.duedate).dt.days
    o["days_since_bill"] = (as_of - o.billdate).dt.days
    o["bucket"] = o.dpd.map(bucket)
    return o


def summary(as_of=None):
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    o = _open_bills(as_of)
    bills = o[o.pendingamount > 0]
    adv = o[o.pendingamount < 0]
    overdue = bills[bills.dpd > 0]
    ag = bills.groupby("bucket").agg(amount=("pendingamount", "sum"), bills=("billname", "size")).reindex(
        [b[2] for b in BUCKETS]).fillna(0).reset_index()
    ag["share_pct"] = ag.amount / bills.pendingamount.sum() * 100 if len(bills) else 0
    cust = bills.groupby("customer").agg(outstanding=("pendingamount", "sum"),
                                         overdue=("pendingamount", lambda x: x[bills.loc[x.index, "dpd"] > 0].sum()),
                                         max_dpd=("dpd", "max"), bills=("billname", "size"),
                                         route=("customergroupl3", "first")).reset_index()
    cust["overdue_share_pct"] = cust.overdue / cust.outstanding * 100
    cust = cust.sort_values("overdue", ascending=False)
    route = bills.groupby(bills.customergroupl3.fillna("(not set)")).apply(lambda x: pd.Series({
        "outstanding": x.pendingamount.sum(), "overdue": x.loc[x.dpd > 0, "pendingamount"].sum(),
        "over_90": x.loc[x.dpd > 90, "pendingamount"].sum()}), include_groups=False).reset_index().rename(
        columns={"customergroupl3": "route"})
    patterns = []
    tot_od = overdue.pendingamount.sum()
    if tot_od:
        top10 = cust.head(10).overdue.sum() / tot_od * 100
        patterns.append(f"Top 10 customers hold {top10:.0f}% of overdue amount.")
        old = bills[bills.dpd > 180].pendingamount.sum()
        patterns.append(f"₹{old/1e5:,.1f} lakh is more than 180 days past due ({old/tot_od*100:.0f}% of overdue): likely needs legal follow-up or write-off review.")
        mostly = (cust.overdue_share_pct > 80).sum()
        patterns.append(f"{mostly} customers have more than 80% of their balance overdue.")
    return {
        "as_of": as_of,
        "outstanding": float(bills.pendingamount.sum()), "advances": float(-adv.pendingamount.sum()),
        "net_outstanding": float(o.pendingamount.sum()), "overdue": float(tot_od),
        "overdue_pct": float(tot_od / bills.pendingamount.sum() * 100) if len(bills) else None,
        "due_today": float(bills[bills.dpd == 0].pendingamount.sum()),
        "became_due_last_7_days": float(bills[(bills.dpd >= 1) & (bills.dpd <= 7)].pendingamount.sum()),
        "became_due_last_30_days": float(bills[(bills.dpd >= 1) & (bills.dpd <= 30)].pendingamount.sum()),
        "due_next_7_days": float(bills[(bills.dpd < 0) & (bills.dpd >= -7)].pendingamount.sum()),
        "avg_days_past_due_weighted": float((overdue.dpd * overdue.pendingamount).sum() / tot_od) if tot_od else None,
        "ageing": records(ag), "by_customer": records(cust.head(100)), "by_route": records(route.sort_values("overdue", ascending=False)),
        "patterns": patterns, "customers_with_overdue": int((cust.overdue > 0).sum()),
    }


# ------------------------------------------------------------------ payment behaviour
def settlements(side="debtor", as_of=None, days=365):
    """One row per settlement line (receipt/payment against a bill) with days from bill
    date and days past due date."""
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    b = loaders.billwise()
    b = b[(b.side == side) & (b.voucherdate <= as_of)]
    if b.empty:
        return b.assign(days_to_pay=[], delay=[])
    pay_vt = {"debtor": ["Receipt", "Journal", "Contra"], "creditor": ["Payment", "Journal", "Contra"]}[side]
    new = b[b.billtype == "New Ref"].groupby(["ledgerguid", "billname"]).agg(
        bill_date=("billdate", "min"), bill_due=("duedate", "min"), bill_credit_days=("credit_days", "max")).reset_index()
    st = b[(b.billtype == "Agst Ref") & b.vouchertype.isin(pay_vt) & (b.amount < 0)]
    st = st[st.voucherdate > as_of - pd.Timedelta(days=days)]
    st = st.merge(new, on=["ledgerguid", "billname"], how="left")
    st["bill_date"] = st.bill_date.fillna(st.billdate)
    st["bill_due"] = st.bill_due.fillna(st.duedate).fillna(st.bill_date)
    st["paid"] = -st.amount
    st["days_to_pay"] = (st.voucherdate - st.bill_date).dt.days.clip(lower=0)
    st["delay"] = (st.voucherdate - st.bill_due).dt.days
    st = st[st.days_to_pay < 1000]
    return st


def _wavg(x, w):
    return float((x * w).sum() / w.sum()) if w.sum() else None


def pay_stats(side="debtor", as_of=None):
    """Per-party payment behaviour: weighted average days to pay, median, p75, delay vs terms."""
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    st = settlements(side, as_of)
    if st.empty:
        return pd.DataFrame(columns=["ledgername", "avg_days_to_pay", "median_days_to_pay", "p75_days_to_pay",
                                     "avg_delay_days", "paid_365d", "settlements", "recent_delay", "older_delay"])
    recent = as_of - pd.Timedelta(days=90)
    g = st.groupby("ledgername").apply(lambda x: pd.Series({
        "avg_days_to_pay": _wavg(x.days_to_pay, x.paid),
        "median_days_to_pay": float(x.days_to_pay.median()),
        "p75_days_to_pay": float(x.days_to_pay.quantile(0.75)),
        "avg_delay_days": _wavg(x.delay, x.paid),
        "terms_days": float(x.bill_credit_days.median()) if x.bill_credit_days.notna().any() else np.nan,
        "paid_365d": float(x.paid.sum()), "settlements": int(len(x)),
        "recent_delay": _wavg(x.delay[x.voucherdate > recent], x.paid[x.voucherdate > recent]),
        "older_delay": _wavg(x.delay[x.voucherdate <= recent], x.paid[x.voucherdate <= recent]),
    }), include_groups=False).reset_index()
    return g


def days_to_pay(as_of=None):
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    g = pay_stats("debtor", as_of)
    cm = loaders.customer_master()[["ledgername", "credit_days"]]
    g = g.merge(cm, on="ledgername", how="left")
    g["agreed_credit_days"] = g.terms_days.fillna(g.credit_days)
    g["deviation_days"] = g.avg_days_to_pay - g.agreed_credit_days
    g = g.sort_values("paid_365d", ascending=False)
    overall = settlements("debtor", as_of)
    return {"as_of": as_of,
            "overall_avg_days_to_pay": _wavg(overall.days_to_pay, overall.paid) if len(overall) else None,
            "overall_avg_delay_days": _wavg(overall.delay, overall.paid) if len(overall) else None,
            "customers": int(len(g)),
            "note": "Days to pay = receipt date − bill date, weighted by amount, receipts against bills in the last 365 days. "
                    "Agreed credit period comes from the bill, else the customer master.",
            "rows": records(g[["ledgername", "avg_days_to_pay", "median_days_to_pay", "agreed_credit_days",
                               "deviation_days", "avg_delay_days", "paid_365d", "settlements"]])}


def collections_vs_billing(as_of=None, months=6):
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    b = loaders.billwise()
    b = b[(b.side == "debtor") & (b.voucherdate <= as_of)]
    b = b.assign(month=b.voucherdate.dt.to_period("M").dt.to_timestamp())
    billing = b[(b.vouchertype == "Sales") & (b.amount > 0)].groupby("month").amount.sum().rename("billing")
    coll = (-b[(b.vouchertype == "Receipt")].groupby("month").amount.sum()).rename("collections")
    t = pd.concat([billing, coll], axis=1).fillna(0).sort_index().tail(months).reset_index().rename(columns={"index": "month"})
    t["collection_ratio_pct"] = t.collections / t.billing.where(t.billing > 0) * 100
    m0 = as_of.replace(day=1)
    cur = t[t.month == m0]
    c = cur.iloc[0] if len(cur) else pd.Series({"billing": 0.0, "collections": 0.0, "collection_ratio_pct": None})
    return {"as_of": as_of, "month": m0, "billing_this_month": float(c.billing), "collections_this_month": float(c.collections),
            "collection_ratio_pct": None if c.get("collection_ratio_pct") is None or pd.isna(c.get("collection_ratio_pct")) else float(c.collection_ratio_pct),
            "trend": records(t),
            "note": "Billing = sales invoices posted to customer accounts (incl. GST). Collections = receipts posted to customer accounts."}


# ------------------------------------------------------------------ risk
def risk_scores(as_of=None):
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    o = _open_bills(as_of)
    bills = o[o.pendingamount > 0]
    cust = bills.groupby("customer").apply(lambda x: pd.Series({
        "outstanding": x.pendingamount.sum(), "overdue": x.loc[x.dpd > 0, "pendingamount"].sum(),
        "over_60": x.loc[x.dpd > 60, "pendingamount"].sum(), "max_dpd": x.dpd.max()}), include_groups=False)
    ps = pay_stats("debtor", as_of).set_index("ledgername")
    b = loaders.billwise()
    b = b[(b.side == "debtor") & (b.vouchertype == "Sales") & (b.voucherdate > as_of - pd.Timedelta(days=182))
          & (b.voucherdate <= as_of)]
    monthly_billing = (b.groupby("ledgername").amount.sum() / 6).rename("avg_monthly_billing")
    df = cust.join(ps, how="outer").join(monthly_billing, how="left").fillna({"outstanding": 0, "overdue": 0, "over_60": 0})
    df = df[(df.outstanding > 0) | (df.paid_365d.fillna(0) > 0)]
    delay = df.avg_delay_days.fillna(df.max_dpd.clip(lower=0)).fillna(0)
    c_delay = (delay.clip(0, 60) / 60 * 100)
    c_old = (df.over_60 / df.outstanding.where(df.outstanding > 0)).fillna(0) * 100
    mos = (df.outstanding / df.avg_monthly_billing.where(df.avg_monthly_billing > 0))
    c_exp = mos.fillna(pd.Series(np.where(df.outstanding > 0, 3.0, 0.0), index=df.index)).clip(0, 3) / 3 * 100
    trend = (df.recent_delay - df.older_delay).fillna(0).clip(-30, 30)
    c_trend = (trend + 30) / 60 * 100
    df["score"] = (0.35 * c_delay + 0.30 * c_old + 0.20 * c_exp + 0.15 * c_trend).round(1)
    df["band"] = pd.cut(df.score, [-1, 35, 60, 101], labels=["Low", "Medium", "High"]).astype(str)
    df["c_delay"], df["c_old_overdue"], df["c_exposure"], df["c_trend"] = c_delay, c_old, c_exp, c_trend
    df["months_of_billing_outstanding"] = mos
    df = df.reset_index().rename(columns={"index": "customer", "customer": "customer"})
    if "customer" not in df.columns:
        df = df.rename(columns={df.columns[0]: "customer"})
    return df.sort_values("score", ascending=False)


def risk(as_of=None):
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    df = risk_scores(as_of)
    cols = ["customer", "score", "band", "outstanding", "overdue", "over_60", "max_dpd", "avg_delay_days",
            "months_of_billing_outstanding", "c_delay", "c_old_overdue", "c_exposure", "c_trend"]
    return {"as_of": as_of,
            "method": "Score 0-100 = 35% average delay beyond terms (0-60 days) + 30% share of balance over 60 days past due "
                      "+ 20% balance vs average monthly billing (0-3 months) + 15% change in delay, last 90 days vs before. "
                      "Low < 35, Medium 35-60, High > 60.",
            "bands": records(df.groupby("band").agg(customers=("customer", "size"), outstanding=("outstanding", "sum")).reset_index()),
            "rows": records(df[[c for c in cols if c in df]].head(300))}


# ------------------------------------------------------------------ predictions
def _prob(dpd):
    for lim, p in config.COLLECTION_PROBABILITY:
        if dpd <= lim:
            return p
    return config.COLLECTION_PROBABILITY[-1][1]


def predicted_payments(as_of=None):
    """Predicted payment date per open bill."""
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    o = _open_bills(as_of)
    o = o[o.pendingamount > 0].copy()
    ps = pay_stats("debtor", as_of).set_index("ledgername")
    st = settlements("debtor", as_of)
    glob_delay = float(st.delay.median()) if len(st) else 15.0
    med = o.customer.map(ps.median_days_to_pay) if len(ps) else pd.Series(np.nan, index=o.index)
    delay = o.customer.map(ps.avg_delay_days) if len(ps) else pd.Series(np.nan, index=o.index)
    pred = o.billdate + pd.to_timedelta(med, unit="D")
    basis = np.where(med.notna(), "customer's median days to pay", "due date + typical delay")
    fallback = o.duedate + pd.to_timedelta(delay.fillna(glob_delay).clip(lower=0), unit="D")
    pred = pred.fillna(fallback)
    late = pred <= as_of
    # already past the usual payment day: expect it within 1-4 weeks depending on how late it is
    extra = np.ceil((o.dpd.clip(lower=0) / 30).clip(1, 4)) * 7
    pred = pred.where(~late, as_of + pd.to_timedelta(extra, unit="D"))
    o["predicted_date"] = pred.dt.normalize()
    o["basis"] = np.where(late, "late: rescheduled after today", basis)
    o["probability"] = o.dpd.map(_prob)
    o["expected_amount"] = o.pendingamount * o.probability
    return o


def expected_collections(as_of=None, weeks=4):
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    o = predicted_payments(as_of)
    end = as_of + pd.Timedelta(days=7 * weeks)
    w = o[(o.predicted_date > as_of) & (o.predicted_date <= end)].copy()
    w["week"] = ((w.predicted_date - as_of).dt.days - 1) // 7 + 1
    wk = w.groupby("week").agg(expected=("expected_amount", "sum"), gross=("pendingamount", "sum"),
                               bills=("billname", "size")).reindex(range(1, weeks + 1), fill_value=0).reset_index()
    wk["week_start"] = [as_of + pd.Timedelta(days=7 * (i - 1) + 1) for i in wk.week]
    return {"as_of": as_of, "weeks": weeks, "expected_total": float(wk.expected.sum()), "gross_total": float(wk.gross.sum()),
            "by_week": records(wk),
            "top_customers": records(w.groupby("customer").expected_amount.sum().sort_values(ascending=False).head(20).reset_index()),
            "probabilities": [{"max_days_past_due": a, "probability": b} for a, b in config.COLLECTION_PROBABILITY],
            "note": "Each open bill is placed on its predicted payment date and weighted by the chance of collection for its age."}


def predicted_dates(as_of=None, limit=500):
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    o = predicted_payments(as_of).sort_values("predicted_date")
    cols = ["customer", "billname", "billdate", "duedate", "pendingamount", "dpd", "predicted_date", "basis", "probability"]
    return {"as_of": as_of, "rows": records(o[cols].head(limit)), "count": len(o)}


def priority(as_of=None):
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    o = _open_bills(as_of)
    od = o[(o.pendingamount > 0) & (o.dpd > 0)]
    cust = od.groupby("customer").agg(overdue=("pendingamount", "sum"), max_dpd=("dpd", "max"),
                                      bills=("billname", "size"), mobile=("mobile", "first"),
                                      route=("customergroupl3", "first")).reset_index()
    rs = risk_scores(as_of)[["customer", "score", "band"]]
    cust = cust.merge(rs, on="customer", how="left")
    cust["priority_score"] = cust.overdue * (1 + cust.score.fillna(50) / 100) * (1 + cust.max_dpd.clip(0, 365) / 365)
    cust = cust.sort_values("priority_score", ascending=False)
    s = loaders.sales()
    lb = as_of - pd.Timedelta(days=config.OVERDUE_BUT_SUPPLIED_LOOKBACK_DAYS)
    recent = s[(s.date > lb) & (s.date <= as_of) & (s.vouchertype == "Sales")].groupby("party").agg(
        supplied_value=("amount", "sum"), last_supply=("date", "max"))
    sup = cust[cust.max_dpd >= config.OVERDUE_BUT_SUPPLIED_MIN_DAYS].merge(recent, left_on="customer", right_index=True)
    return {"as_of": as_of, "rows": records(cust.head(100)),
            "overdue_but_supplied": records(sup.sort_values("overdue", ascending=False)),
            "rule": f"Still supplied = has a bill more than {config.OVERDUE_BUT_SUPPLIED_MIN_DAYS} days past due and was "
                    f"invoiced in the last {config.OVERDUE_BUT_SUPPLIED_LOOKBACK_DAYS} days."}


def credit_suggestions(as_of=None):
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    rs = risk_scores(as_of).set_index("customer")
    ps = pay_stats("debtor", as_of).set_index("ledgername")
    cm = loaders.customer_master().drop_duplicates("ledgername").set_index("ledgername")
    s = loaders.sales()
    s = s[(s.date > as_of - pd.Timedelta(days=182)) & (s.date <= as_of) & ~s.is_cash]
    monthly = (s.groupby("party").amount.sum() / 6 * config.GST_BILLING_FACTOR).rename("avg_monthly_billing")
    df = pd.DataFrame(monthly[monthly > 0]).join(rs[["score", "band"]], how="left").join(
        ps[["median_days_to_pay", "p75_days_to_pay"]], how="left").join(cm[["creditlimit", "credit_days"]], how="left")
    df["band"] = df.band.where(df.band.isin(["Low", "Medium", "High"]), "Medium")
    cap = {"Low": 60, "Medium": 45, "High": 15}

    def period(row):
        need = row.p75_days_to_pay if pd.notna(row.p75_days_to_pay) else (row.credit_days if pd.notna(row.credit_days) else 15)
        need = min(need, cap[row.band])
        for st in config.CREDIT_PERIOD_STEPS:
            if st >= need:
                return st
        return config.CREDIT_PERIOD_STEPS[-1]

    df["suggested_credit_days"] = df.apply(period, axis=1)
    lim = df.avg_monthly_billing * (df.suggested_credit_days / 30 + 0.25) * df.band.map(config.CREDIT_LIMIT_RISK_MULTIPLIER)
    df["suggested_credit_limit"] = (np.ceil(lim / 10000) * 10000)
    df["current_credit_limit"] = df.creditlimit
    df["current_credit_days"] = df.credit_days
    df["change"] = np.where(df.current_credit_limit.fillna(0) == 0, "Set limit (none in Tally)",
                            np.where(df.suggested_credit_limit > df.current_credit_limit * 1.1, "Raise",
                                     np.where(df.suggested_credit_limit < df.current_credit_limit * 0.9, "Reduce", "Keep")))
    df = df.reset_index().rename(columns={"index": "customer", "party": "customer"})
    cols = ["customer", "band", "score", "avg_monthly_billing", "median_days_to_pay", "p75_days_to_pay",
            "current_credit_days", "suggested_credit_days", "current_credit_limit", "suggested_credit_limit", "change"]
    return {"as_of": as_of,
            "method": "Period: the step (7/15/21/30/45/60 days) covering the customer's 75th-percentile days to pay, capped at "
                      "60/45/15 days for Low/Medium/High risk. Limit: average monthly billing incl. GST × (period/30 + 1 week) "
                      "× 1.2/1.0/0.6 for Low/Medium/High risk, rounded up to ₹10,000.",
            "rows": records(df.sort_values("avg_monthly_billing", ascending=False)[cols])}
