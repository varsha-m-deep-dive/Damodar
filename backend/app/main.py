"""FastAPI entry point.

    cd backend
    uvicorn app.main:app --reload --port 8000

Serves /api/* and, if the React app has been built (frontend/dist), the dashboard itself.
Every /api route except health and the sign-in/reset routes needs `Authorization: Bearer <token>`."""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import auth, config, gsheets, sheets_export
from .api import ROUTES, handle

app = FastAPI(title="Damodara Oil Mill – KPI dashboard API", version="1.1")

PUBLIC = {"/api/health", "/api/auth/login", "/api/auth/forgot", "/api/auth/reset", "/api/auth/config"}
ADMIN_PREFIXES = ("/api/admin/",)


@app.middleware("http")
async def require_login(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or not path.startswith("/api/") or path in PUBLIC:
        return await call_next(request)
    if not config.AUTH_REQUIRED:
        request.state.user = {"email": "local", "name": "Local", "role": "admin"}
        return await call_next(request)
    header = request.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else ""
    user = await run_in_threadpool(auth.user_from_token, token) if token else None
    if not user:
        return JSONResponse({"error": "Please sign in.", "auth": True}, status_code=401)
    if path.startswith(ADMIN_PREFIXES) and user["role"] != "admin":
        return JSONResponse({"error": "Admins only."}, status_code=403)
    request.state.user = user
    return await call_next(request)


# Added after the auth middleware so it wraps it: 401s still carry CORS headers.
app.add_middleware(CORSMiddleware, allow_origins=config.ALLOWED_ORIGINS, allow_methods=["GET", "POST"],
                   allow_headers=["Authorization", "Content-Type"], max_age=600)


async def _body(request: Request) -> dict:
    try:
        b = await request.json()
        return b if isinstance(b, dict) else {}
    except Exception:
        return {}


def _own_url(request: Request) -> str:
    """This server's public address (DigitalOcean passes the original scheme in x-forwarded-proto)."""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    return f"{proto}://{request.headers.get('host', request.url.netloc)}"


def _admin_base(request: Request) -> str:
    """Where the signed-in admin is using the dashboard (e.g. the Vercel site), for links they copy."""
    origin = request.headers.get("origin", "").rstrip("/")
    return origin if origin.startswith(("https://", "http://")) else _own_url(request)


async def _run(fn, *args, **kw):
    try:
        return JSONResponse(await run_in_threadpool(fn, *args, **kw))
    except auth.AuthError as e:
        return JSONResponse({"error": str(e)}, status_code=e.status)
    except gsheets.SheetsNotConfigured as e:
        return JSONResponse({"error": str(e)}, status_code=503)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)


# ------------------------------------------------------------------ auth
@app.get("/api/auth/config")
async def auth_config():
    from . import emailer
    from . import db
    return {"auth_required": config.AUTH_REQUIRED, "email_enabled": emailer.enabled(), "data_loading": db.warm_status}


@app.post("/api/auth/login")
async def login(request: Request):
    b = await _body(request)
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0]
    return await _run(auth.login, b.get("email"), b.get("password"), ip)


@app.post("/api/auth/forgot")
async def forgot(request: Request):
    b = await _body(request)
    # never trust the Origin header here: anyone can call this, and the link carries a reset token
    return await _run(auth.forgot_password, b.get("email"), base_url=_own_url(request))


@app.post("/api/auth/reset")
async def reset(request: Request):
    b = await _body(request)
    return await _run(auth.reset_password, b.get("email"), b.get("token"), b.get("password"))


@app.get("/api/auth/me")
async def me(request: Request):
    return {"user": request.state.user}


@app.post("/api/auth/change-password")
async def change_password(request: Request):
    b = await _body(request)
    return await _run(auth.change_password, request.state.user["email"], b.get("current"), b.get("password"))


# ------------------------------------------------------------------ admin: users
@app.get("/api/admin/users")
async def users(request: Request):
    return await _run(auth.list_users)


@app.post("/api/admin/users")
async def create_user(request: Request):
    b = await _body(request)
    return await _run(auth.create_user, b.get("email"), b.get("name"), b.get("role", "viewer"),
                      b.get("password") or None, bool(b.get("send_invite", True)), base_url=_admin_base(request))


@app.post("/api/admin/users/update")
async def update_user(request: Request):
    b = await _body(request)
    return await _run(auth.update_user, b.get("email"), request.state.user["email"], b.get("name"),
                      b.get("role"), b.get("active"))


@app.post("/api/admin/users/reset-link")
async def reset_link(request: Request):
    b = await _body(request)
    return await _run(auth.admin_reset_link, b.get("email"), bool(b.get("send_email")), base_url=_admin_base(request))


# ------------------------------------------------------------------ admin: Google Sheets export
@app.get("/api/admin/sheets/status")
async def sheets_status(request: Request):
    return {**sheets_export.status, "configured": bool(config.KPI_SHEET_ID and gsheets.configured()),
            "service_account": gsheets.service_account_email(),
            "interval_minutes": config.SHEETS_EXPORT_INTERVAL_MINUTES,
            "url": f"https://docs.google.com/spreadsheets/d/{config.KPI_SHEET_ID}" if config.KPI_SHEET_ID else None}


@app.post("/api/admin/sheets/export")
async def sheets_run(request: Request):
    return await _run(sheets_export.run_export)


# ------------------------------------------------------------------ KPI routes
def _make(path):
    async def endpoint(request: Request):
        status, body = await run_in_threadpool(handle, path, request.query_params)
        return JSONResponse(body, status_code=status)
    endpoint.__name__ = path.strip("/").replace("/", "_").replace("-", "_")
    return endpoint


for _p in ROUTES:
    app.add_api_route(_p, _make(_p), methods=["GET"])


@app.on_event("startup")
async def _startup():
    if config.AUTH_REQUIRED:
        try:
            await run_in_threadpool(auth.store)  # creates the first admin if needed
        except Exception as e:
            print(f"WARNING: user store not ready: {e}")
    sheets_export.start_scheduler()
    from . import db, loaders
    db.start_warmer([loaders.companies, loaders.sales, loaders.outstanding, loaders.payables,
                     loaders.customer_master, loaders.billwise, loaders.purchases, loaders.production,
                     loaders.bom, loaders.closing_stock, loaders.orders, loaders.voucher_headers])


_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="dashboard")
