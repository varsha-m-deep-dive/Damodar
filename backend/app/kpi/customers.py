"""Customer analytics: lapsed/declining customers, reorder call list, RFM segments,
churn probability and cross-sell gaps. Cash (walk-in) sales are excluded."""
import numpy as np
import pandas as pd

from .. import config, loaders
from ..util import records


def _invoices(as_of):
    s = loaders.sales()
    s = s[(~s.is_cash) & (~s.is_discount) & (s.date <= as_of)]
    inv = s[s.vouchertype == "Sales"].groupby(["party", "voucherno", "date"]).agg(
        amount=("amount", "sum"), route=("route", "first"), city=("city", "first"),
        mobile=("mobile", "first"), contact=("contactname", "first")).reset_index()
    return inv


def _profile(inv, as_of):
    """Per-customer purchase profile as at as_of."""
    as_of = pd.Timestamp(as_of)
    last365 = inv[inv.date > as_of - pd.Timedelta(days=365)]
    days = last365.groupby(["party", "date"]).amount.sum().reset_index().sort_values(["party", "date"])
    days["gap"] = days.groupby("party").date.diff().dt.days
    gap = days.groupby("party").gap.median().rename("usual_gap_days")
    n_days = days.groupby("party").date.nunique().rename("billing_days_365")
    w = lambda a, b: inv[(inv.date > as_of - pd.Timedelta(days=a)) & (inv.date <= as_of - pd.Timedelta(days=b))]
    last90 = w(90, 0).groupby("party").amount.sum().rename("last_90d")
    prev90 = w(180, 90).groupby("party").amount.sum().rename("prev_90d")
    ly = inv[(inv.date > as_of - pd.Timedelta(days=455)) & (inv.date <= as_of - pd.Timedelta(days=365))]
    ly90 = ly.groupby("party").amount.sum().rename("same_90d_last_year")
    base = inv.groupby("party").agg(last_date=("date", "max"), first_date=("date", "min"),
                                    route=("route", "last"), city=("city", "last"),
                                    mobile=("mobile", "last"), contact=("contact", "last"))
    p = base.join([gap, n_days, last90, prev90, ly90]).reset_index()
    for c in ("last_90d", "prev_90d", "same_90d_last_year", "billing_days_365"):
        p[c] = p[c].fillna(0)
    p["days_since_last"] = (as_of - p.last_date).dt.days
    med = last365.groupby("party").amount.median().rename("median_invoice")
    sales365 = last365.groupby("party").amount.sum().rename("sales_365d")
    return p.merge(med, on="party", how="left").merge(sales365, on="party", how="left")


def lapsed(as_of=None):
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    p = _profile(_invoices(as_of), as_of)
    gap = p.usual_gap_days.fillna(30)
    stopped = (p.billing_days_365 >= config.STOPPED_MIN_PRIOR_INVOICES) & \
        (p.days_since_last > np.maximum(2 * gap, 45)) & (p.days_since_last <= 365)
    drop = (~stopped) & (p.prev_90d > 0) & (p.last_90d < config.SHARP_DROP_RATIO * p.prev_90d) & \
        (p.prev_90d >= p.prev_90d.quantile(0.5))
    p["status"] = np.where(stopped, "Stopped buying", np.where(drop, "Sharp drop", None))
    out = p[p.status.notna()].copy()
    out["lost_value_90d"] = out.prev_90d - out.last_90d
    out["change_vs_prev_90d_pct"] = (out.last_90d / out.prev_90d.where(out.prev_90d > 0) - 1) * 100
    out = out.sort_values("lost_value_90d", ascending=False)
    cols = ["party", "status", "route", "city", "last_date", "days_since_last", "usual_gap_days", "last_90d",
            "prev_90d", "same_90d_last_year", "change_vs_prev_90d_pct", "lost_value_90d", "mobile", "contact"]
    return {"as_of": as_of, "stopped": int((out.status == "Stopped buying").sum()),
            "sharp_drop": int((out.status == "Sharp drop").sum()),
            "lost_value_90d": float(out.lost_value_90d.sum()),
            "rule": f"Stopped: bought on ≥{config.STOPPED_MIN_PRIOR_INVOICES} days in the last year and silent for more than "
                    f"2× their usual gap (min 45 days). Sharp drop: last 90 days below {config.SHARP_DROP_RATIO:.0%} of the previous 90.",
            "rows": records(out[cols])}


def call_list(as_of=None):
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    p = _profile(_invoices(as_of), as_of)
    p = p[(p.billing_days_365 >= config.MIN_INVOICES_FOR_GAP) & p.usual_gap_days.notna()]
    due = p.days_since_last > config.REORDER_GAP_TOLERANCE * p.usual_gap_days
    not_lost = p.days_since_last <= np.maximum(4 * p.usual_gap_days, 60)
    c = p[due & not_lost].copy()
    c["days_overdue_vs_gap"] = c.days_since_last - c.usual_gap_days
    c["expected_order_value"] = c.median_invoice
    c["priority_score"] = c.expected_order_value * (1 + c.days_overdue_vs_gap / c.usual_gap_days.clip(lower=1))
    try:
        o = loaders.outstanding()
        od = o[o.daysfromduedate > 0].groupby("customer").pendingamount.sum().rename("overdue_outstanding")
        c = c.merge(od, left_on="party", right_index=True, how="left")
    except Exception:
        c["overdue_outstanding"] = None
    c = c.sort_values("priority_score", ascending=False)
    cols = ["party", "route", "city", "mobile", "contact", "last_date", "days_since_last", "usual_gap_days",
            "days_overdue_vs_gap", "expected_order_value", "overdue_outstanding", "priority_score"]
    return {"as_of": as_of, "count": len(c), "expected_value": float(c.expected_order_value.sum()),
            "rule": f"Customers with ≥{config.MIN_INVOICES_FOR_GAP} billing days in the last year whose days since last bill "
                    f"exceed {config.REORDER_GAP_TOLERANCE}× their usual (median) gap. Check overdue outstanding before pushing stock.",
            "rows": records(c[cols])}


def _segment(r, fm):
    if r >= 4 and fm >= 4:
        return "Champions"
    if r == 1 and fm >= 4.5:
        return "Can't lose them"
    if r <= 2 and fm >= 3:
        return "At risk"
    if r >= 3 and fm >= 3.5:
        return "Loyal"
    if r >= 4 and fm < 2:
        return "New / occasional"
    if r >= 4:
        return "Potential loyalist"
    if r <= 2:
        return "Hibernating / lost"
    return "Needs attention"


def rfm(months=12, as_of=None):
    """Recency-frequency-value segments. The sheet asks for two windows: last year (12)
    and last three years (36)."""
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    inv = _invoices(as_of)
    start = as_of - pd.DateOffset(months=months)
    w = inv[inv.date > start]
    years_available = (as_of - inv.date.min()).days / 365.25 if len(inv) else 0
    if w.empty:
        return {"as_of": as_of, "months": months, "segments": [], "rows": []}
    g = w.groupby("party").agg(last_date=("date", "max"), frequency=("date", "nunique"), value=("amount", "sum"),
                               route=("route", "last"), city=("city", "last")).reset_index()
    g["recency_days"] = (as_of - g.last_date).dt.days

    def score(s, reverse=False):
        r = s.rank(method="first", pct=True)
        sc = np.ceil(r * 5).clip(1, 5)
        return (6 - sc) if reverse else sc

    g["R"] = score(g.recency_days, reverse=True).astype(int)
    g["F"] = score(g.frequency).astype(int)
    g["M"] = score(g.value).astype(int)
    g["FM"] = (g.F + g.M) / 2
    g["segment"] = [_segment(r, fm) for r, fm in zip(g.R, g.FM)]
    seg = g.groupby("segment").agg(customers=("party", "size"), value=("value", "sum"),
                                   avg_recency_days=("recency_days", "mean")).reset_index()
    seg["value_share_pct"] = seg.value / seg.value.sum() * 100
    return {"as_of": as_of, "months": months, "years_of_history": round(years_available, 1),
            "window_note": None if years_available >= months / 12 - 0.05 else
            f"Only {years_available:.1f} years of history loaded, so the {months}-month window is shorter in practice.",
            "segments": records(seg.sort_values("value", ascending=False)),
            "rows": records(g.sort_values("value", ascending=False).drop(columns=["FM"]))}


def _features(inv, t):
    t = pd.Timestamp(t)
    h = inv[inv.date <= t]
    p = _profile(h, t)
    p = p[p.days_since_last <= 365]
    gap = p.usual_gap_days.fillna(p.usual_gap_days.median() if p.usual_gap_days.notna().any() else 30).clip(lower=1)
    X = pd.DataFrame({
        "log_recency": np.log1p(p.days_since_last),
        "recency_vs_gap": (p.days_since_last / gap).clip(upper=10),
        "log_frequency": np.log1p(p.billing_days_365),
        "log_value": np.log1p(p.sales_365d.fillna(0).clip(lower=0)),
        "trend": ((p.last_90d + 1) / (p.prev_90d + 1)).clip(upper=5).pipe(np.log),
        "tenure_days": ((t - p.first_date).dt.days.clip(upper=1500)) / 365,
    }, index=p.index)
    return p, X


def churn(as_of=None, horizon=None):
    """Probability that a customer active in the last year places no order in the next
    `horizon` days. Logistic regression trained on past snapshots of the same data."""
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    horizon = horizon or config.CHURN_HORIZON_DAYS
    inv = _invoices(as_of)
    if inv.empty:
        return {"as_of": as_of, "rows": []}
    first = inv.date.min()
    Xs, ys = [], []
    for k in range(0, 12):
        t = as_of - pd.Timedelta(days=horizon + 30 * k)
        if t - first < pd.Timedelta(days=120):
            break
        p, X = _features(inv, t)
        fut = inv[(inv.date > t) & (inv.date <= t + pd.Timedelta(days=horizon))].party.unique()
        y = (~p.party.isin(fut)).astype(int)
        Xs.append(X.assign(_snap=k))
        ys.append(y)
    method, auc = "heuristic", None
    p_now, X_now = _features(inv, as_of)
    if Xs and sum(len(x) for x in Xs) >= 60 and pd.concat(ys).nunique() == 2:
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import roc_auc_score
        Xall = pd.concat(Xs)
        yall = pd.concat(ys)
        cols = [c for c in Xall.columns if c != "_snap"]
        model = LogisticRegression(max_iter=1000)
        test = Xall._snap == 0
        if test.sum() >= 20 and (~test).sum() >= 40 and yall[~test].nunique() == 2 and yall[test].nunique() == 2:
            model.fit(Xall.loc[~test, cols], yall[~test])
            auc = float(roc_auc_score(yall[test], model.predict_proba(Xall.loc[test, cols])[:, 1]))
        model.fit(Xall[cols], yall)
        prob = model.predict_proba(X_now[cols])[:, 1]
        method = f"logistic regression on {len(Xs)} monthly snapshots ({len(Xall)} customer-snapshots)"
        coef = dict(zip(cols, model.coef_[0].round(3)))
    else:
        gap = p_now.usual_gap_days.fillna(30).clip(lower=1)
        prob = 1 - np.exp(-np.maximum(p_now.days_since_last / gap - 1, 0) / 2)
        coef = None
    p_now = p_now.assign(churn_probability=np.asarray(prob))
    p_now["risk_band"] = pd.cut(p_now.churn_probability, [-0.01, 0.3, 0.6, 1.01], labels=["Low", "Medium", "High"]).astype(str)
    p_now["value_at_risk_365d"] = p_now.sales_365d.fillna(0) * p_now.churn_probability
    cols = ["party", "route", "city", "churn_probability", "risk_band", "days_since_last", "usual_gap_days",
            "last_90d", "prev_90d", "sales_365d", "value_at_risk_365d", "mobile"]
    out = p_now.sort_values("value_at_risk_365d", ascending=False)
    return {"as_of": as_of, "horizon_days": horizon, "method": method, "holdout_auc": auc, "coefficients": coef,
            "bands": records(out.groupby("risk_band").agg(customers=("party", "size"),
                                                          value_at_risk=("value_at_risk_365d", "sum")).reset_index()),
            "rows": records(out[cols])}


def cross_sell(as_of=None, days=180, min_penetration=0.3):
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    s = loaders.sales()
    s = s[(~s.is_cash) & (~s.is_discount) & (s.date <= as_of) & (s.date > as_of - pd.Timedelta(days=days))]
    s = s[s.oil_family.isin(config.FORECAST_FAMILIES)]
    if s.empty:
        return {"rows": []}
    cf = s.groupby(["party", "oil_family"]).amount.sum().unstack(fill_value=0)
    route = s.groupby("party").route.last()
    total = cf.sum(axis=1)
    buys = cf > 0
    rows = []
    for fam in cf.columns:
        # penetration among customers on the same route, and typical share of wallet
        pen = buys[fam].groupby(route).mean()
        share = (cf[fam] / total).where(buys[fam]).groupby(route).median()
        for party in cf.index[~buys[fam]]:
            r = route.get(party)
            p_r = pen.get(r, np.nan)
            if pd.isna(p_r) or p_r < min_penetration or total[party] <= 0:
                continue
            sh = share.get(r, np.nan)
            rows.append({"party": party, "route": r, "missing_family": fam,
                         "buys": ", ".join(cf.columns[buys.loc[party]]),
                         "route_penetration_pct": p_r * 100, "current_sales": total[party],
                         "potential_value": total[party] * min(sh if pd.notna(sh) else 0.05, 0.5)})
    df = pd.DataFrame(rows)
    if df.empty:
        return {"as_of": as_of, "rows": []}
    df = df.sort_values("potential_value", ascending=False)
    summary = df.groupby("missing_family").agg(customers=("party", "nunique"), potential_value=("potential_value", "sum")).reset_index()
    return {"as_of": as_of, "days": days,
            "rule": f"Customer bought in the last {days} days but not this oil, while ≥{min_penetration:.0%} of customers on the same route do. "
                    "Potential = customer's purchases × the route's median share for that oil (capped at 50%).",
            "summary": records(summary.sort_values("potential_value", ascending=False)), "rows": records(df.head(200))}
