import math
import uuid
from datetime import date, datetime
from decimal import Decimal

import numpy as np
import pandas as pd


def fy_start(d) -> pd.Timestamp:
    d = pd.Timestamp(d)
    return pd.Timestamp(d.year if d.month >= 4 else d.year - 1, 4, 1)


def same_day_last_year(d) -> pd.Timestamp:
    d = pd.Timestamp(d)
    try:
        return d.replace(year=d.year - 1)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year - 1, day=28)


def safe_div(a, b):
    try:
        if b is None or b == 0 or (isinstance(b, float) and math.isnan(b)):
            return None
        return a / b
    except Exception:
        return None


def pct_change(cur, prev):
    r = safe_div(cur, prev)
    return None if r is None else (r - 1) * 100


def _clean_value(v):
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        if math.isnan(v) or math.isinf(v):
            return None
        return round(float(v), 4)
    if isinstance(v, (pd.Timestamp, datetime)):
        if pd.isna(v):
            return None
        return v.strftime("%Y-%m-%d")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, uuid.UUID):  # Postgres uuid columns (e.g. GUIDs) come back as UUID objects
        return str(v)
    if isinstance(v, Decimal):  # Postgres numeric columns
        return None if v.is_nan() else round(float(v), 4)
    if v is pd.NaT:
        return None
    return v


def records(df: pd.DataFrame, limit=None):
    """DataFrame -> list of JSON-safe dicts."""
    if df is None or len(df) == 0:
        return []
    if limit:
        df = df.head(limit)
    cols = list(df.columns)
    return [{c: _clean_value(v) for c, v in zip(cols, row)} for row in df.itertuples(index=False, name=None)]


def clean(obj):
    """Recursively make a structure JSON-safe."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, pd.DataFrame):
        return records(obj)
    if isinstance(obj, pd.Series):
        return clean(obj.to_dict())
    return _clean_value(obj)


def week_start(s: pd.Series) -> pd.Series:
    """Monday of each date."""
    s = pd.to_datetime(s)
    return (s - pd.to_timedelta(s.dt.weekday, unit="D")).dt.normalize()
