"""FastAPI entry point.

    cd backend
    uvicorn app.main:app --reload --port 8000

Serves /api/* and, if the React app has been built (frontend/dist), the dashboard itself."""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .api import ROUTES, handle

app = FastAPI(title="Damodara Oil Mill – KPI dashboard API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])


def _make(path):
    async def endpoint(request: Request):
        status, body = await run_in_threadpool(handle, path, request.query_params)
        return JSONResponse(body, status_code=status)
    endpoint.__name__ = path.strip("/").replace("/", "_").replace("-", "_")
    return endpoint


for _p in ROUTES:
    app.add_api_route(_p, _make(_p), methods=["GET"])

_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="dashboard")
