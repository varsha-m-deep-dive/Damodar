"""Sales forecast by oil family (two assumptions), festival effect, price elasticity,
and a small Holt forecaster reused for purchase prices."""
import json

import numpy as np
import pandas as pd

from .. import config, loaders
from ..util import records, week_start


# ------------------------------------------------------------------ weekly series
def weekly(measure="net_sales", as_of=None):
    """Complete weeks (Mon-Sun) of net sales or kg per oil family, zero-filled."""
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    s = loaders.sales()
    s = s[(s.date <= as_of) & s.oil_family.isin(config.FORECAST_FAMILIES)]
    col = "amount" if measure == "net_sales" else "kg"
    s = s.assign(week=week_start(s.date))
    last_complete = week_start(pd.Series([as_of + pd.Timedelta(days=1)])).iloc[0] - pd.Timedelta(days=7)
    w = s[s.week <= last_complete].pivot_table(index="week", columns="oil_family", values=col, aggfunc="sum", fill_value=0)
    if w.empty:
        return w
    idx = pd.date_range(w.index.min(), last_complete, freq="W-MON")
    return w.reindex(idx, fill_value=0).reindex(columns=config.FORECAST_FAMILIES, fill_value=0)


def _scenario(series: pd.Series, horizon: int, max_years: int, level_weeks: int):
    """Forecast = current level x seasonal ratio seen in past years.
    For each past year k, ratio_k(h) = sales in week (origin+h-52k) / average weekly
    sales in the `level_weeks` weeks before (origin-52k). The forecast uses the mean
    ratio across years; the range uses the spread across years (or, with one year,
    the volatility of recent ratios)."""
    s = series.astype(float)
    n = len(s)
    level = s.iloc[-level_weeks:].mean() if n >= level_weeks else s.mean()
    ratios, years = [], 0
    for k in range(1, max_years + 1):
        lag = 52 * k
        if n - lag - level_weeks < 0 or n - lag + horizon > n:
            break
        base = s.iloc[n - lag - level_weeks:n - lag].mean()
        if base <= 0:
            continue
        fut = s.iloc[n - lag:n - lag + horizon].values
        if len(fut) < horizon:
            break
        ratios.append(fut / base)
        years += 1
    if not ratios:
        f = np.repeat(level, horizon)
        sd = s.iloc[-26:].std() / level if level else 0.3
        return f, f * np.exp(-1.28 * sd), f * np.exp(1.28 * sd), 0
    R = np.vstack(ratios)
    mean = R.mean(axis=0)
    f = level * mean
    if years >= 3:
        lo, hi = level * np.percentile(R, 10, axis=0), level * np.percentile(R, 90, axis=0)
    else:
        # one or two years: band from how far weekly sales usually stray from the seasonal path
        recent = s.iloc[-26:]
        prev = s.iloc[-26 - 52:-52] if n >= 78 else None
        if prev is not None and (prev > 0).all():
            lr = np.log((recent.values + 1) / (prev.values + 1))
            sd = float(np.std(lr - lr.mean()))
        else:
            sd = float(recent.std() / recent.mean()) if recent.mean() else 0.3
        sd = max(sd, 0.05)
        lo, hi = f * np.exp(-1.28 * sd), f * np.exp(1.28 * sd)
    return f, np.minimum(lo, f), np.maximum(hi, f), years


SCENARIOS = {
    "last_year": {"label": "Last year's pattern", "max_years": 1, "level_weeks": 8},
    "five_year": {"label": "Average of up to 5 years", "max_years": 5, "level_weeks": 13},
}


def sales_forecast(horizon=12, measure="net_sales", as_of=None):
    horizon = int(min(max(horizon, 4), 12))
    w = weekly(measure, as_of)
    if w.empty:
        return {"families": [], "note": "No sales history"}
    out = {"measure": measure, "horizon_weeks": horizon, "last_actual_week": w.index[-1], "families": []}
    future = pd.date_range(w.index[-1] + pd.Timedelta(days=7), periods=horizon, freq="W-MON")
    for fam in w.columns:
        s = w[fam]
        if s.sum() <= 0:
            continue
        fam_out = {"family": fam, "history": records(pd.DataFrame({"week": s.index[-26:], "actual": s.values[-26:]})),
                   "scenarios": {}}
        for key, cfg in SCENARIOS.items():
            f, lo, hi, yrs = _scenario(s, horizon, cfg["max_years"], cfg["level_weeks"])
            # backtest: same method from an origin `horizon` weeks ago
            bt = None
            if len(s) > 52 + 2 * horizon:
                bf, _, _, _ = _scenario(s.iloc[:-horizon], horizon, cfg["max_years"], cfg["level_weeks"])
                act = s.iloc[-horizon:].values
                if act.sum() > 0:
                    bt = float(np.abs(bf - act).sum() / act.sum() * 100)  # WAPE
            fam_out["scenarios"][key] = {
                "label": cfg["label"], "years_used": yrs, "backtest_error_pct": bt,
                "total": float(f.sum()), "total_low": float(lo.sum()), "total_high": float(hi.sum()),
                "weeks": records(pd.DataFrame({"week": future, "forecast": f, "low": lo, "high": hi}))}
        out["families"].append(fam_out)
    out["note"] = ("Range is an 80% band. 'Years used' shows how many past years had enough data; with fewer than "
                   "the scenario asks for, the forecast uses what exists. Backtest error = weighted % error when the "
                   "same method forecast the last weeks of actual data.")
    return out


# ------------------------------------------------------------------ festivals
def _festivals():
    p = config.DATA_DIR / "festivals.json"
    data = json.loads(p.read_text())
    return {k: [pd.Timestamp(d) for d in v] for k, v in data.items() if not k.startswith("_")}


def festival_effect(as_of=None, pre_days=14):
    """Uplift in daily sales in the `pre_days` before each festival vs a baseline of the
    surrounding weeks (D-56..D-15 and D+15..D+42), per oil family."""
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    s = loaders.sales()
    s = s[(s.date <= as_of) & s.oil_family.isin(config.FORECAST_FAMILIES) & ~s.is_discount]
    daily = s.pivot_table(index="date", columns="oil_family", values="kg", aggfunc="sum", fill_value=0)
    if daily.empty:
        return {"rows": []}
    daily = daily.reindex(pd.date_range(daily.index.min(), daily.index.max()), fill_value=0)
    daily["All oils"] = daily.sum(axis=1)
    lo, hi = daily.index.min(), daily.index.max()
    rows = []
    for fest, dates in _festivals().items():
        for d in dates:
            if d - pd.Timedelta(days=56) < lo or d + pd.Timedelta(days=42) > hi:
                continue
            win = daily.loc[d - pd.Timedelta(days=pre_days): d - pd.Timedelta(days=1)]
            base = pd.concat([daily.loc[d - pd.Timedelta(days=56): d - pd.Timedelta(days=15)],
                              daily.loc[d + pd.Timedelta(days=15): d + pd.Timedelta(days=42)]])
            for fam in daily.columns:
                b = base[fam].mean()
                if b <= 0:
                    continue
                rows.append({"festival": fest, "date": d, "family": fam, "uplift_pct": (win[fam].mean() / b - 1) * 100})
    df = pd.DataFrame(rows)
    if df.empty:
        return {"rows": [], "note": "Not enough history around festival dates yet."}
    last = df.sort_values("date").groupby(["festival", "family"]).tail(1).rename(
        columns={"uplift_pct": "uplift_last_year_pct", "date": "last_date"})
    avg = df[df.date >= as_of - pd.DateOffset(years=5)].groupby(["festival", "family"]).agg(
        uplift_5yr_avg_pct=("uplift_pct", "mean"), years=("date", "nunique")).reset_index()
    t = last.merge(avg, on=["festival", "family"], how="left")
    upcoming = [{"festival": f, "date": min(d for d in ds if d > as_of)} for f, ds in _festivals().items()
                if any(d > as_of for d in ds)]
    return {"as_of": as_of, "pre_days": pre_days, "rows": records(t.sort_values(["festival", "family"])),
            "upcoming": records(pd.DataFrame(upcoming).sort_values("date")) if upcoming else [],
            "note": f"Uplift = average daily kg in the {pre_days} days before the festival vs the surrounding 10 weeks. "
                    "Festival dates come from data/festivals.json; lunar dates should be checked each year."}


# ------------------------------------------------------------------ elasticity
def elasticity(as_of=None, years=3):
    """log(weekly kg) = a + b·log(₹/kg) + month effects, per oil family."""
    as_of = pd.Timestamp(as_of) if as_of else loaders.data_as_of()
    s = loaders.sales()
    s = s[(s.date <= as_of) & (s.date > as_of - pd.DateOffset(years=years)) & s.oil_family.isin(config.FORECAST_FAMILIES)
          & ~s.is_discount & ~s.is_credit_note & (s.kg > 0)]
    s = s.assign(week=week_start(s.date))
    rows, points = [], []
    for fam, g in s.groupby("oil_family"):
        # Fixed-weight price index: each SKU's ₹/kg weighted by its overall kg share, so a
        # shift towards cheap loose oil is not mistaken for a price cut.
        sk = g.groupby(["week", "stockitemname"]).agg(kg=("kg", "sum"), value=("amount", "sum")).reset_index()
        sk = sk[(sk.kg > 0) & (sk.value > 0)]
        sk["p"] = sk.value / sk.kg
        wts = sk.groupby("stockitemname").kg.sum()
        sk["wt"] = sk.stockitemname.map(wts / wts.sum())
        idx = sk.groupby("week").apply(lambda x: (x.p * x.wt).sum() / x.wt.sum(), include_groups=False).rename("price")
        w = g.groupby("week").agg(kg=("kg", "sum"), value=("amount", "sum")).join(idx).reset_index()
        w = w[(w.kg > 0) & (w.value > 0) & w.price.notna()]
        n = len(w)
        if n < 20:
            rows.append({"family": fam, "weeks": n, "elasticity": None, "confidence": "Too little data"})
            continue
        y = np.log(w.kg.values)
        X = [np.ones(n), np.log(w.price.values)]
        months = w.week.dt.month.values
        for m in range(2, 13):
            if (months == m).any():
                X.append((months == m).astype(float))
        X = np.column_stack(X)
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = y - X @ beta
        dof = max(n - X.shape[1], 1)
        sigma2 = resid @ resid / dof
        try:
            se = float(np.sqrt(np.diag(sigma2 * np.linalg.pinv(X.T @ X)))[1])
        except Exception:
            se = None
        r2 = 1 - resid.var() / y.var() if y.var() else None
        b = float(beta[1])
        t = abs(b / se) if se else 0
        conf = "Strong" if t >= 3 else "Moderate" if t >= 2 else "Weak – treat as indicative"
        if b > 0.3 or b < -3:
            conf = "Not reliable – volume and price both moved with the market"
        if n < 104:
            conf += f" (only {n} weeks; 2+ years recommended)"
        rows.append({"family": fam, "weeks": n, "elasticity": b, "std_error": se, "r_squared": r2,
                     "avg_price_per_kg": float(w.price.mean()), "confidence": conf,
                     "meaning": f"A 1% price rise goes with a {b:+.2f}% change in weekly volume"})
        points += [{"family": fam, "week": wk, "price": p, "kg": k} for wk, p, k in zip(w.week, w.price, w.kg)]
    return {"as_of": as_of, "rows": rows, "points": records(pd.DataFrame(points)),
            "note": "Estimated from Damodara's own weekly volumes and a fixed-weight SKU price index, with month effects removed. "
                    "Prices mostly follow raw-material costs, so the estimate mixes demand response with market moves. "
                    "Values above +0.3 or below -3 are flagged as not reliable."}


# ------------------------------------------------------------------ Holt (used for prices)
def holt(series: pd.Series, horizon=4, alpha=0.5, beta=0.2):
    y = series.dropna().astype(float).values
    if len(y) == 0:
        return np.array([]), 0.0
    if len(y) == 1:
        return np.repeat(y[0], horizon), 0.0
    level, trend = y[0], y[1] - y[0]
    for v in y[1:]:
        prev = level
        level = alpha * v + (1 - alpha) * (level + trend)
        trend = beta * (level - prev) + (1 - beta) * trend
    return np.array([level + (h + 1) * trend for h in range(horizon)]), trend
