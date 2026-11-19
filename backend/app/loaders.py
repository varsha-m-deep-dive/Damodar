"""Load and clean data from the views. Every KPI module works on the DataFrames returned
here, so the business logic is the same whether data comes from Postgres or (demo mode)
from the Excel extract."""
import re
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import config, sql, sku
from .db import cached, delta_query, query_df

NULL_TOKENS = {"[NULL]", "NULL", "None", "nan", "NaN", ""}


# ------------------------------------------------------------------ helpers
def clean_frame(df: pd.DataFrame, date_cols=(), num_cols=()) -> pd.DataFrame:
    df = df.copy()
    for c in df.columns:
        if df[c].dtype == object or pd.api.types.is_string_dtype(df[c]):
            col = df[c].astype(object)
            df[c] = col.where(~col.isin(NULL_TOKENS) & col.notna(), None)
    for c in date_cols:
        if c in df:
            df[c] = pd.to_datetime(df[c].astype(str).str[:10], errors="coerce")
    for c in num_cols:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


def fix_due_dates(df):
    """Tally leaves 1-Jan-2000 (or blank) as the due date on some bills: use the bill date."""
    if "duedate" in df and "billdate" in df:
        bad = df.duedate.isna() | (df.duedate < df.billdate)
        df.loc[bad, "duedate"] = df.loc[bad, "billdate"]
        if "daysfromduedate" in df and "daysfrombilldate" in df:
            df.loc[bad, "daysfromduedate"] = df.loc[bad, "daysfrombilldate"]
    return df


def history_start(years=None):
    years = years or config.HISTORY_YEARS
    today = date.today()
    fy_start_year = today.year if today.month >= 4 else today.year - 1
    return date(fy_start_year - years, 4, 1)


def _dim(col):
    if col not in sql.ALLOWED_DIM_COLUMNS:
        raise ValueError(f"Dimension column '{col}' is not allowed")
    return col


def _params(**kw):
    p = {"company_re": config.COMPANY_INCLUDE_REGEX}
    p.update(kw)
    return p


# ------------------------------------------------------------------ demo (Excel) source
_demo_cache = {}


def _demo_sheets():
    if "sheets" not in _demo_cache:
        import os
        import pickle
        pkl = str(config.DEMO_EXCEL) + ".cache.pkl"
        if os.path.exists(pkl) and os.path.getmtime(pkl) >= os.path.getmtime(config.DEMO_EXCEL):
            with open(pkl, "rb") as f:
                _demo_cache["sheets"] = pickle.load(f)
        else:
            _demo_cache["sheets"] = pd.read_excel(config.DEMO_EXCEL, sheet_name=None)
            try:
                with open(pkl, "wb") as f:
                    pickle.dump(_demo_cache["sheets"], f)
            except OSError:
                pass
    return _demo_cache["sheets"]


def _demo_sheet(prefix):
    for name, df in _demo_sheets().items():
        if name.lower().startswith(prefix.lower()):
            return df.copy()
    return pd.DataFrame()


# ------------------------------------------------------------------ companies
def companies() -> pd.DataFrame:
    def load():
        if config.DEMO_EXCEL:
            s = _demo_sheet("SalesAnalysis")
            s["date"] = pd.to_datetime(s["date"])
            df = s.groupby("companyname").agg(first_date=("date", "min"), last_date=("date", "max"),
                                              line_count=("date", "size")).reset_index()
        else:
            df = query_df(sql.COMPANIES)
        df = clean_frame(df, date_cols=["first_date", "last_date"])
        df["included"] = df.companyname.str.contains(config.COMPANY_INCLUDE_REGEX, regex=True, na=False)
        return df.sort_values("first_date")
    return cached("companies", load)


def current_company() -> str:
    if config.CURRENT_COMPANY:
        return config.CURRENT_COMPANY
    c = companies()
    c = c[c.included]
    if c.empty:
        raise RuntimeError("No company matches COMPANY_INCLUDE_REGEX")
    return c.sort_values(["last_date", "first_date"]).iloc[-1].companyname


def dedupe_companies(df, date_col="date"):
    """Tally opens one company per financial year. Keep each row only from the company
    that 'owns' its date (the latest company whose first transaction is on/before it), so
    overlapping books are never double-counted."""
    if df.empty or "companyname" not in df:
        return df
    c = companies()
    c = c[c.included][["companyname", "first_date"]].dropna().sort_values("first_date")
    if c.empty:
        return df
    starts = c.first_date.values
    names = c.companyname.values
    d = pd.to_datetime(df[date_col]).values
    idx = np.searchsorted(starts, d, side="right") - 1
    owner = np.where(idx >= 0, names[np.clip(idx, 0, len(names) - 1)], names[0])
    return df[df.companyname.values == owner]


# ------------------------------------------------------------------ sales
def sales() -> pd.DataFrame:
    def load():
        if config.DEMO_EXCEL:
            df = _demo_sheet("SalesAnalysis")
            df = df.rename(columns={config.DIM_ROUTE: "route", config.DIM_CITY: "city",
                                    config.DIM_AGENT: "agent", config.DIM_ZONE: "zone"})
            keep = df.ledgergroupl1.eq(config.SALES_LEDGER_GROUP) | df.ledgername.isin(config.DISCOUNT_LEDGERS)
            df = df[keep]
        else:
            q = sql.SALES.format(route=_dim(config.DIM_ROUTE), city=_dim(config.DIM_CITY),
                                 agent=_dim(config.DIM_AGENT), zone=_dim(config.DIM_ZONE))
            df = delta_query("sales", q, _params(start=history_start(), discount_ledgers=list(config.DISCOUNT_LEDGERS)), "date")
        df = clean_frame(df, date_cols=["date"], num_cols=["quantity", "altquantity", "amount"])
        df = df[df.companyname.str.contains(config.COMPANY_INCLUDE_REGEX, regex=True, na=False)]
        df = dedupe_companies(df)
        excl_l = "|".join(config.EXCLUDE_SALES_LEDGER_PATTERNS)
        excl_v = "|".join(config.EXCLUDE_VOUCHER_TYPE_PATTERNS)
        bad = df.ledgername.fillna("").str.upper().str.contains(excl_l) | \
            df.vouchertypename.fillna("").str.upper().str.contains(excl_v)
        df = df[~bad]
        df["is_discount"] = df.ledgername.isin(config.DISCOUNT_LEDGERS)
        if not config.INCLUDE_DISCOUNTS_IN_NET_SALES:
            df = df[~df.is_discount]
        df["is_credit_note"] = df.vouchertype.eq("Credit Note")
        df["party"] = df.partyledgername.fillna("(no party)")
        df["is_cash"] = df.partygroupl2.isin(config.CASH_PARTY_GROUPS) | \
            df.party.str.upper().str.contains(config.CASH_PARTY_NAME_PATTERN, regex=True, na=False)
        for c in ("route", "city", "agent", "zone"):
            df[c] = df[c].fillna("(not set)")
        df = sku.enrich(df)
        df.loc[df.is_discount, ["kg", "quantity"]] = 0.0
        return df.reset_index(drop=True)
    return cached("sales", load)


# ------------------------------------------------------------------ receivables / payables
def outstanding() -> pd.DataFrame:
    def load():
        if config.DEMO_EXCEL:
            df = _demo_sheet("CustomerOutstanding")
            df = df[df.companyname == current_company()]
        else:
            df = query_df(sql.OUTSTANDING, {"company": current_company()})
        df = clean_frame(df, date_cols=["billdate", "duedate", "lastagnstdate"],
                         num_cols=["originalamount", "adjustedamount", "pendingamount",
                                   "daysfrombilldate", "daysfromduedate"])
        df["billname"] = df.billname.astype(str)
        return fix_due_dates(df)
    return cached("outstanding", load)


def payables() -> pd.DataFrame:
    def load():
        if config.DEMO_EXCEL:
            df = _demo_sheet("SupplierPayable")
            df = df[df.companyname == current_company()]
        else:
            df = query_df(sql.PAYABLES, {"company": current_company()})
        df = clean_frame(df, date_cols=["billdate", "duedate", "lastagnstdate"],
                         num_cols=["originalamount", "adjustedamount", "pendingamount",
                                   "daysfrombilldate", "daysfromduedate"])
        df["billname"] = df.billname.astype(str)
        return fix_due_dates(df)
    return cached("payables", load)


def billwise() -> pd.DataFrame:
    """araptransbillwise with a normalised sign: amount > 0 increases what the party owes
    us (debtor) or what we owe them (creditor)."""
    def load():
        if config.DEMO_EXCEL:
            df = _demo_billwise()
        else:
            df = delta_query("billwise", sql.BILLWISE, _params(start=history_start()), "voucherdate")
        df = clean_frame(df, date_cols=["voucherdate", "billdate", "duedate"], num_cols=["billlineamount"])
        df["billname"] = df.billname.astype(str)
        df = fix_due_dates(df)
        df = dedupe_companies(df, "voucherdate")
        df["credit_days"] = pd.to_numeric(df.creditperiod.astype(str).str.extract(r"(\d+)")[0], errors="coerce")
        out = []
        for side, grp, inc_vt in (("debtor", "Sundry Debtors", "Sales"), ("creditor", "Sundry Creditors", "Purchase")):
            d = df[df.typeofledger == grp].copy()
            if d.empty:
                continue
            # auto-detect sign: billing vouchers (Sales / Purchase) must come out positive
            base = d.loc[d.vouchertype == inc_vt, "billlineamount"].sum()
            sign = -1.0 if base < 0 else 1.0
            d["amount"] = d.billlineamount * sign
            d["side"] = side
            out.append(d)
        return pd.concat(out, ignore_index=True) if out else df.assign(amount=[], side=[])
    return cached("billwise", load)


def _demo_billwise():
    """Demo only: rebuild bill lines from the outstanding/payable extracts plus the 5-week
    ledger extract. Fully paid bills are missing, so demo payment-behaviour figures are
    indicative only."""
    rows = []
    co = _demo_sheet("CustomerOutstanding")
    sp = _demo_sheet("SupplierPayable")
    for df, typ, guid, name, inc, pay in ((co, "Sundry Debtors", "customerguid", "customer", "Sales", "Receipt"),
                                          (sp, "Sundry Creditors", "supplierguid", "supplier", "Purchase", "Payment")):
        if df.empty:
            continue
        df = clean_frame(df, date_cols=["billdate", "duedate", "lastagnstdate"],
                         num_cols=["originalamount", "adjustedamount"])
        df = df[df.companyname.str.contains(config.COMPANY_INCLUDE_REGEX, na=False)]
        base = pd.DataFrame({"companyname": df.companyname, "ledgerguid": df[guid], "ledgername": df[name],
                             "typeofledger": typ, "billname": df.billname, "billdate": df.billdate,
                             "duedate": df.duedate, "creditperiod": df.creditperiod})
        new = base.assign(vouchertype=inc, voucherdate=df.billdate, billtype="New Ref",
                          billlineamount=df.originalamount)
        paid = df.adjustedamount.abs() > 0
        agst = base[paid].assign(vouchertype=pay, voucherdate=df.lastagnstdate[paid].fillna(df.billdate[paid]),
                                 billtype="Agst Ref", billlineamount=-df.adjustedamount[paid].abs())
        rows += [new, agst]
    led = _demo_sheet("ledgerinvtrans")
    if not led.empty:
        led = led[led.typeofledger.isin(["Sundry Debtors", "Sundry Creditors"])]
        led = led.drop_duplicates("acclineid")
        sign = np.where(led.typeofledger.eq("Sundry Debtors"), -1.0, 1.0)  # Tally: debit < 0
        rows.append(pd.DataFrame({
            "companyname": led.companyname, "ledgerguid": led.ledgerguid, "ledgername": led.ledgername,
            "typeofledger": led.typeofledger, "billname": "On Account", "billdate": led.date,
            "duedate": led.date, "creditperiod": None, "vouchertype": led.vouchertype,
            "voucherdate": led.date, "billtype": "On Account", "billlineamount": led.amount.values * sign}))
        rows[-1] = rows[-1][rows[-1].vouchertype.isin(["Receipt", "Payment"])]
    out = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    out["voucherid"] = None
    out["voucherno"] = None
    return out


def customer_master() -> pd.DataFrame:
    def load():
        if config.DEMO_EXCEL:
            df = _demo_sheet("CoA")
            df = df[(df.companyname == current_company()) & (df.typeofledger == "Sundry Debtors")]
            cols = [c for c in ("ledgerguid", "ledgername", "creditlimit", "creditperiod") if c in df]
            df = df[cols]
        else:
            df = query_df(sql.CUSTOMER_MASTER, {"company": current_company()})
        df = clean_frame(df)
        if "creditlimit" in df:
            df["creditlimit"] = pd.to_numeric(df.creditlimit.astype(str).str.replace(r"[^\d.\-]", "", regex=True),
                                              errors="coerce").abs()
        else:
            df["creditlimit"] = np.nan
        df["credit_days"] = pd.to_numeric(df.get("creditperiod", pd.Series(dtype=str)).astype(str)
                                          .str.extract(r"(\d+)")[0], errors="coerce")
        return df
    return cached("customer_master", load)


# ------------------------------------------------------------------ purchases / orders
def purchases() -> pd.DataFrame:
    def load():
        if config.DEMO_EXCEL:
            df = _demo_sheet("ledgerinvtrans")
            df = df[df.vouchertype.isin(["Purchase", "Debit Note"]) & ~df.ispartyledger.astype(bool)
                    & df.ledgergroupl1.eq("Purchase Accounts")]
        else:
            df = delta_query("purchases", sql.PURCHASES, _params(start=history_start()), "date")
        df = clean_frame(df, date_cols=["date"], num_cols=["quantity", "amount"])
        df = dedupe_companies(df)
        # Purchase lines are debits (negative in Tally): make value and quantity positive
        sgn = np.where(df.vouchertype.eq("Debit Note"), -1.0, 1.0)
        df["value"] = df.amount.abs() * sgn
        df["qty"] = df.quantity.abs() * sgn
        df["supplier"] = df.partyledgername.fillna("(unknown)")
        df = sku.enrich(df, qty_col="qty", altqty_col="__none__")
        return df.reset_index(drop=True)
    return cached("purchases", load)


def orders() -> pd.DataFrame:
    def load():
        if config.DEMO_EXCEL:
            df = _demo_sheet("ledgerinvtrans")
            df = df[df.invlineid.notna()]
            bl = df.batchlineorderno.fillna("").astype(str)
            df = df[df.vouchertype.eq("Sales Order") |
                    (df.vouchertype.eq("Sales") & ~bl.isin(["", "Not Applicable", "[NULL]"]))]
        else:
            df = delta_query("orders", sql.ORDERS, _params(start=history_start(1)), "date")
        df = clean_frame(df, date_cols=["date", "orderduedate", "preclosuredate"], num_cols=["quantity", "amount"])
        df = dedupe_companies(df)
        df["qty"] = df.quantity.abs()
        df["value"] = df.amount.abs()
        return df.reset_index(drop=True)
    return cached("orders", load)


# ------------------------------------------------------------------ production / stock
def production() -> pd.DataFrame:
    def load():
        if config.DEMO_EXCEL:
            df = _demo_sheet("Production")
        else:
            df = delta_query("production", sql.PRODUCTION, _params(start=history_start(2)), "date")
        df = clean_frame(df, date_cols=["date"], num_cols=["quantity"])
        df = dedupe_companies(df)
        df["quantity"] = df.quantity.abs()
        df = sku.enrich(df, group_col="__none__", altqty_col="__none__")
        return df.reset_index(drop=True)
    return cached("production", load)


def bom() -> pd.DataFrame:
    def load():
        if config.DEMO_EXCEL:
            df = _demo_sheet("itembom")
            df = df[df.companyname == current_company()]
            df = df.sort_values("componentstockitemname").drop_duplicates(
                ["stockitemguid", "bomname", "componentserial"])
        else:
            df = query_df(sql.BOM, {"company": current_company()})
        return clean_frame(df, num_cols=["qty", "headeritemqty", "headeritemaltqty"])
    return cached("bom", load)


def closing_stock() -> pd.DataFrame:
    def load():
        if config.DEMO_EXCEL:
            df = _demo_sheet("ClosingStock")
            df = df[df.companyname == current_company()]
        else:
            df = query_df(sql.CLOSING_STOCK, {"company": current_company()})
        return clean_frame(df, num_cols=["closingqty"])
    return cached("closing_stock", load)


def voucher_headers() -> pd.DataFrame:
    def load():
        if config.DEMO_EXCEL:
            df = _demo_sheet("ledgerinvtrans")
            cols = ["companyname", "voucherid", "vouchermasterid", "voucheralterid", "date", "vouchertype",
                    "vouchertypename", "voucherno", "enteredby", "partyledgername"]
            df = df[[c for c in cols if c in df]].drop_duplicates("voucherid")
        else:
            df = delta_query("voucher_headers", sql.VOUCHER_HEADERS, _params(start=history_start(1)), "date")
        df = clean_frame(df, date_cols=["date"])
        df["vouchermasterid"] = pd.to_numeric(df.vouchermasterid, errors="coerce")
        return df
    return cached("voucher_headers", load)


def data_as_of() -> pd.Timestamp:
    """Reference 'today'. Live: the calendar date. Demo: last sales date in the extract."""
    if config.DEMO_EXCEL:
        return pd.Timestamp(sales().date.max()).normalize()
    return pd.Timestamp(date.today())
