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
    missing = [k for k in ("host", "user", "password") if not kw.get(k)]
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


def clear_cache():
    with _lock:
        _cache.clear()


def ping():
    df = query_df("select current_database() as db, now() as server_time")
    return df.iloc[0].to_dict()
