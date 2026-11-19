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
    # keep long-running queries alive across networks that drop quiet connections
    kw.update(keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5)
    return psycopg.connect(**kw)


# At most DB_MAX_CONCURRENT queries run at once. A page asks for many KPIs together; without
# this, they all hit Neon in parallel and a small compute can drop connections
# ("SSL connection has been closed unexpectedly").
_db_slots = threading.BoundedSemaphore(max(1, config.DB_MAX_CONCURRENT))


def _query_once(sql, params):
    with _connect() as conn, conn.cursor() as cur:
        if config.PG_SCHEMA and config.PG_SCHEMA != "public":
            # set inside the same transaction: Neon's pooler does not accept startup options
            from psycopg import sql as psql
            cur.execute(psql.SQL("SET LOCAL search_path TO {}").format(psql.Identifier(config.PG_SCHEMA)))
        cur.execute(sql, params or {})
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols)


def query_df(sql: str, params=None) -> pd.DataFrame:
    """Run a read-only query. Dropped connections (Neon waking up, network blips) are retried."""
    import psycopg
    attempts = max(1, config.DB_RETRIES + 1)
    with _db_slots:
        for i in range(attempts):
            try:
                return _query_once(sql, params)
            except psycopg.OperationalError as e:
                if i == attempts - 1:
                    raise
                wait = 2 * (i + 1)
                print(f"database connection failed ({e}); retrying in {wait}s")
                time.sleep(wait)


_key_load_locks = {}
_warming = threading.local()
warm_status = {"running": False, "last_done": None, "seconds": None, "error": None}


def cached(key, fn, ttl=None):
    """Return fn() from cache if fresh. Concurrent requests for the same key wait for one load
    instead of each running the same query."""
    ttl = config.CACHE_TTL_SECONDS if ttl is None else ttl
    if getattr(_warming, "on", False):  # background refresh renews entries before users see them expire
        ttl = max(60, ttl - config.WARM_INTERVAL_SECONDS - 60)
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        klock = _key_load_locks.setdefault(key, threading.Lock())
    with klock:
        with _lock:  # another request may have loaded it while we waited
            hit = _cache.get(key)
            if hit and time.time() - hit[0] < ttl:
                return hit[1]
        now = time.time()
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


def start_warmer(loaders_list):
    """Load the data right after start-up and refresh it in the background, so dashboard
    requests are answered from memory instead of waiting on the database (which can take
    longer than the hosting platform's request timeout on the first load)."""
    interval = config.WARM_INTERVAL_SECONDS
    if interval <= 0:
        return

    def loop():
        _warming.on = True
        while True:
            t0 = time.time()
            warm_status.update(running=True, error=None)
            for fn in loaders_list:
                try:
                    fn()
                except Exception as e:  # keep going; the error shows on the page that needs it
                    warm_status["error"] = f"{getattr(fn, '__name__', fn)}: {type(e).__name__}: {e}"
                    print(f"background load failed: {warm_status['error']}")
            warm_status.update(running=False, last_done=time.strftime("%Y-%m-%dT%H:%M:%S"),
                               seconds=round(time.time() - t0, 1))
            time.sleep(interval)

    threading.Thread(target=loop, name="data-warmer", daemon=True).start()
