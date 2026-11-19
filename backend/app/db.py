"""Database access: one short-lived connection per query (Neon's pooler handles
pooling), results returned as pandas DataFrames, with a small in-process TTL cache."""
import threading
import time

import pandas as pd

from . import config

_cache = {}
_lock = threading.Lock()


def _connect():
    import psycopg  # psycopg 3
    kw = {k: v for k, v in config.PG.items() if v}
    missing = [k for k in ("host", "dbname", "user", "password") if not kw.get(k)]
    if missing:
        raise RuntimeError(f"Database settings missing: {', '.join('PG' + m.upper() for m in missing)}. "
                           "Copy backend/.env.example to backend/.env and fill it in.")
    kw.setdefault("connect_timeout", 20)
    return psycopg.connect(**kw)


def query_df(sql: str, params=None) -> pd.DataFrame:
    with _connect() as conn, conn.cursor() as cur:
        if config.PG_SCHEMA and config.PG_SCHEMA != "public":
            # set inside the same transaction: Neon's pooler does not accept startup options
            from psycopg import sql as psql
            cur.execute(psql.SQL("SET LOCAL search_path TO {}").format(psql.Identifier(config.PG_SCHEMA)))
        cur.execute(sql, params or {})
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols)


def cached(key, fn, ttl=None):
    """Return fn() from cache if fresh."""
    ttl = config.CACHE_TTL_SECONDS if ttl is None else ttl
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    val = fn()
    with _lock:
        _cache[key] = (now, val)
    return val


def clear_cache(full=False):
    """Drop processed results. The next request re-reads the database: only recent rows
    (delta) for the large history tables, unless full=True."""
    with _lock:
        _cache.clear()
    if full:
        with _raw_lock:
            _raw.clear()


# ------------------------------------------------------------------ delta refresh
# The history tables (sales, bill-wise, purchases, ...) hold up to 5 years of rows. After the
# first full load, each refresh only re-reads rows dated on/after (last cutoff - overlap) and
# swaps them in. The overlap re-reads recent days so edits, cancellations and deletions of
# recent vouchers are picked up; a full reload every DELTA_FULL_RELOAD_HOURS catches edits to
# older vouchers.
_raw = {}
_raw_lock = threading.Lock()
_key_locks = {}
refresh_log = {}


def _key_lock(key):
    with _raw_lock:
        return _key_locks.setdefault(key, threading.Lock())


def delta_query(key: str, sql: str, params: dict, date_col: str) -> pd.DataFrame:
    """Run `sql` (which must filter `<date> >= %(start)s`) incrementally. Returns the full raw
    frame from params['start'] onwards, fetching only the recent part when possible."""
    start = pd.Timestamp(params["start"])
    with _key_lock(key):
        with _raw_lock:
            prev = _raw.get(key)
        now = time.time()
        full = (prev is None or not config.DELTA_ENABLED or prev["sql"] != sql
                or now - prev["full_at"] > config.DELTA_FULL_RELOAD_HOURS * 3600)
        t0 = time.time()
        if full:
            df = query_df(sql, params)
            full_at, fetched = now, len(df)
        else:
            cutoff = max(start, prev["cutoff"] - pd.Timedelta(days=config.DELTA_OVERLAP_DAYS))
            new = query_df(sql, {**params, "start": cutoff.date()})
            old = prev["df"]
            old = old[(pd.to_datetime(old[date_col]) < cutoff) & (pd.to_datetime(old[date_col]) >= start)]
            df = pd.concat([old, new], ignore_index=True) if len(new) else old.reset_index(drop=True)
            full_at, fetched = prev["full_at"], len(new)
        dates = pd.to_datetime(df[date_col], errors="coerce") if len(df) else pd.Series(dtype="datetime64[ns]")
        max_date = dates.max() if len(dates) else pd.NaT
        today = pd.Timestamp.today().normalize()
        cutoff = min(max_date, today) if pd.notna(max_date) else start
        with _raw_lock:
            _raw[key] = {"df": df, "cutoff": cutoff, "full_at": full_at, "sql": sql}
            refresh_log[key] = {"mode": "full" if full else "delta", "rows_fetched": fetched,
                                "rows_total": len(df), "seconds": round(time.time() - t0, 2),
                                "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                "cutoff": None if pd.isna(cutoff) else str(cutoff.date())}
        return df.copy()


def ping():
    df = query_df("select current_database() as db, now() as server_time")
    return df.iloc[0].to_dict()
