"""Export every KPI endpoint's result to a Google Sheet (KPI_SHEET_ID): one tab per endpoint plus
an "Index" tab. Each tab holds the endpoint's headline figures (key / value) followed by each of
its tables. The whole export uses a few batched API calls, well inside the Sheets quota."""
import json
import threading
import time
from datetime import datetime

from . import config, gsheets

MAX_ROWS_PER_TABLE = 5000
MAX_CELLS_PER_CALL = 200_000
SKIP = {"/api/meta", "/api/health", "/api/cache/clear"}
# Endpoints exported more than once with different settings: (tab suffix, params)
VARIANTS = {
    "/api/sales/dimension": [("route", {"dim": "route"}), ("city", {"dim": "city"}),
                             ("zone", {"dim": "zone"}), ("agent", {"dim": "agent"})],
    "/api/sales/rfm": [("12m", {"months": "12"}), ("36m", {"months": "36"})],
    "/api/sales/forecast": [("net_sales", {}), ("kg", {"measure": "kg"})],
}

_lock = threading.Lock()
status = {"running": False, "last_run": None, "ok": None, "error": None, "seconds": None,
          "tabs": 0, "failed": [], "url": None}


def jobs():
    from .api import ROUTES
    out = []
    for path in ROUTES:
        if path in SKIP:
            continue
        base = path[len("/api/"):].replace("/", "_")
        for suffix, params in VARIANTS.get(path, [("", {})]):
            out.append((f"{base}_{suffix}" if suffix else base, path, params))
    return out


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)[:5000]
    if isinstance(v, str):
        return v[:5000]
    return v


def flatten(result):
    """Split an endpoint's JSON into (key/value pairs, [(table name, columns, rows)])."""
    pairs, tables = [], []

    def walk(obj, prefix):
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{prefix}.{k}" if prefix else str(k))
        elif isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj):
            cols = []
            for r in obj:
                for c in r:
                    if c not in cols:
                        cols.append(c)
            tables.append((prefix or "rows", cols, [[_cell(r.get(c)) for c in cols] for r in obj]))
        elif isinstance(obj, list) and any(isinstance(x, (dict, list)) for x in obj):
            pairs.append((prefix, _cell(obj)))
        elif isinstance(obj, list):
            pairs.append((prefix, ", ".join("" if x is None else str(x) for x in obj)))
        else:
            pairs.append((prefix or "value", _cell(obj)))

    walk(result, "")
    return pairs, tables


def build_tab(title, path, params, result, stamp):
    rows = [[title, f"{path}{'?' + '&'.join(f'{k}={v}' for k, v in params.items()) if params else ''}",
             f"updated {stamp}"], []]
    pairs, tables = flatten(result)
    if pairs:
        rows += [["Summary"], ["field", "value"]] + [[k, v] for k, v in pairs] + [[]]
    for name, cols, data in tables:
        note = f" (first {MAX_ROWS_PER_TABLE} of {len(data)} rows)" if len(data) > MAX_ROWS_PER_TABLE else ""
        rows += [[f"{name}{note}"], cols] + data[:MAX_ROWS_PER_TABLE] + [[]]
    return rows


def _q(title):
    return "'" + title.replace("'", "''") + "'"


def run_export():
    from .api import handle
    if not _lock.acquire(blocking=False):
        return {"ok": False, "error": "An export is already running.", **status}
    t0 = time.time()
    status.update(running=True, error=None)
    try:
        sh = gsheets.open_sheet(config.KPI_SHEET_ID, "KPI export")
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        tabs, index, failed = {}, [["tab", "endpoint", "status", "rows", "updated"]], []
        for title, path, params in jobs():
            code, body = handle(path, params)
            if code != 200:
                failed.append({"tab": title, "error": body.get("error")})
                tabs[title] = [[title, path, f"ERROR {stamp}"], [], [body.get("error", "error")]]
                index.append([title, path, f"error: {body.get('error', '')}"[:500], 0, stamp])
                continue
            tabs[title] = build_tab(title, path, params, body, stamp)
            index.append([title, path, "ok", len(tabs[title]), stamp])
        tabs = {"Index": index, **tabs}

        existing = {ws.title: ws for ws in sh.worksheets()}
        add = [{"addSheet": {"properties": {"title": t}}} for t in tabs if t not in existing]
        if add:
            sh.batch_update({"requests": add})
            existing = {ws.title: ws for ws in sh.worksheets()}
        resize = []
        for t, rows in tabs.items():
            ncols = max((len(r) for r in rows), default=1)
            resize.append({"updateSheetProperties": {
                "properties": {"sheetId": existing[t].id, "index": list(tabs).index(t),
                               "gridProperties": {"rowCount": max(len(rows), 1) + 5, "columnCount": max(ncols, 1),
                                                  "frozenRowCount": 1}},
                "fields": "index,gridProperties.rowCount,gridProperties.columnCount,gridProperties.frozenRowCount"}})
        sh.batch_update({"requests": resize})
        sh.values_batch_clear(body={"ranges": [_q(t) for t in tabs]})

        batch, cells = [], 0
        for t, rows in tabs.items():
            n = sum(len(r) for r in rows)
            if batch and cells + n > MAX_CELLS_PER_CALL:
                sh.values_batch_update({"valueInputOption": "RAW", "data": batch})
                batch, cells = [], 0
            batch.append({"range": f"{_q(t)}!A1", "values": rows})
            cells += n
        if batch:
            sh.values_batch_update({"valueInputOption": "RAW", "data": batch})

        status.update(ok=not failed, failed=failed, tabs=len(tabs),
                      url=f"https://docs.google.com/spreadsheets/d/{config.KPI_SHEET_ID}")
        return {"ok": True, **status}
    except Exception as e:
        status.update(ok=False, error=f"{type(e).__name__}: {e}")
        raise
    finally:
        status.update(running=False, last_run=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                      seconds=round(time.time() - t0, 1))
        _lock.release()


def start_scheduler():
    """Background export every SHEETS_EXPORT_INTERVAL_MINUTES (single-container deployments)."""
    minutes = config.SHEETS_EXPORT_INTERVAL_MINUTES
    if minutes <= 0 or not config.KPI_SHEET_ID or not gsheets.configured():
        return

    def loop():
        time.sleep(60)  # let the app start first
        while True:
            try:
                run_export()
            except Exception as e:
                print(f"scheduled Sheets export failed: {e}")
            time.sleep(minutes * 60)

    threading.Thread(target=loop, name="sheets-export", daemon=True).start()
