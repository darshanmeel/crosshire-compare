"""The FastAPI app. Every request passes the guard first: the Host must be this machine (a page
on another site cannot reach us by rebinding a name to 127.0.0.1), and every write must carry
X-Compare: 1 - a cross-site form or fetch cannot set it without a CORS preflight, and none is
allowed."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import sql

from . import jobs
from .workspace import Workspace, Workspaces, workspace


class EngineIn(BaseModel):
    memory: str
    disk: str

DIST = Path(__file__).resolve().parent.parent / "web_dist"

WRITE_HEADER = "X-Compare"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "testserver", "::1"}
SAFE_METHODS = {"GET", "HEAD"}


def allowed_hosts() -> set[str]:
    extra = os.environ.get("COMPARE_ALLOWED_HOSTS", "")
    return LOCAL_HOSTS | {h.strip().lower() for h in extra.split(",") if h.strip()}


def host_name(header: str) -> str:
    """'localhost:8501' -> 'localhost'; '[::1]:8501' -> '::1'."""
    h = header.strip().lower()
    if h.startswith("["):
        return h[1:h.find("]")] if "]" in h else h
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


def create_app() -> FastAPI:
    app = FastAPI(title="CrossHire Compare", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if host_name(request.headers.get("host", "")) not in allowed_hosts():
            return JSONResponse({"detail": "This server answers on this machine only."}, status_code=400)
        if request.method not in SAFE_METHODS and request.headers.get(WRITE_HEADER) != "1":
            return JSONResponse({"detail": f"A write needs the {WRITE_HEADER}: 1 header."}, status_code=403)
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        """Where and what is wrong - never the input, which may hold a password."""
        errors = [{"loc": [str(x) for x in e.get("loc", ())], "msg": str(e.get("msg", ""))} for e in exc.errors()]
        said = "; ".join(f"{'.'.join(e['loc'])}: {e['msg']}" for e in errors)
        return JSONResponse({"detail": f"The request was not understood - {said}.", "errors": errors}, status_code=422)

    app.state.workspaces = Workspaces()

    @app.get("/api/workspace")
    def get_workspace(ws: Workspace = Depends(workspace)) -> dict:
        return {"id": ws.id}

    def log_body(ws: Workspace) -> dict:
        return {"entries": [jobs.public(e) for e in reversed(ws.log)],
                "last": {p: jobs.public(e) for p, e in list(ws.last_run.items())}}

    @app.get("/api/log")
    def get_log(ws: Workspace = Depends(workspace)) -> dict:
        return log_body(ws)

    @app.delete("/api/log")
    def clear_log(ws: Workspace = Depends(workspace)) -> dict:
        with jobs._starting:                                           # not while a job is being added
            ws.log[:] = [e for e in ws.log if e["state"] == "running"]     # a running job stays, to be followed
            ws.last_run = {p: e for p, e in ws.last_run.items() if e["state"] == "running"}
        return log_body(ws)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str, ws: Workspace = Depends(workspace)) -> dict:
        e = jobs.find(ws, job_id)
        if e is None:
            raise HTTPException(404, "No such job in this workspace.")
        return jobs.public(e)

    from fastapi.responses import Response as RawResponse

    from .. import connforms, filepick, theme
    from ..connections import KINDS

    @app.get("/theme.css", include_in_schema=False)
    def theme_css() -> RawResponse:
        css = f"@import url('{theme.FONTS}');\n" + theme.tokens_css(light_when=':root[data-fs-mode="light"]', dark_when=':root[data-fs-mode="dark"]')
        return RawResponse(css, media_type="text/css")

    examples = Path(__file__).resolve().parents[2] / "examples"
    pair = {"A": examples / "hr_employees.csv", "B": examples / "payroll_employees.csv"}

    @app.get("/api/meta")
    def meta() -> dict:
        """The name, the look, the connection kinds and form - and the sample pair's paths when it is
        installed beside the app, for the page's "Try the HR vs Payroll example"."""
        return {"app_name": theme.APP_NAME, "tagline": theme.APP_TAGLINE, "theme": theme.THEME_NAME, "mode": theme.MODE,
                "kinds": KINDS, "form": connforms.form_spec(), "filepick": filepick.available(),
                "examples": {t: str(f) for t, f in pair.items()} if all(f.exists() for f in pair.values()) else None}

    def engine_view() -> dict:
        lim = sql.engine_limits()
        return {**lim, "machine_memory": sql.machine_memory_bytes(),
                "default_memory": sql.DEFAULT_MEMORY, "default_disk": sql.DEFAULT_DISK}

    @app.get("/api/engine")
    def engine() -> dict:
        """DuckDB's memory and spill-to-disk limits, where each comes from, and the machine's memory."""
        return engine_view()

    @app.put("/api/engine")
    def set_engine(body: EngineIn) -> dict:
        """Keep new limits for every DuckDB connection opened from now on. A limit fixed by
        COMPARE_DUCKDB_MEMORY / COMPARE_DUCKDB_DISK stays fixed: the page cannot change it."""
        try:
            sql.save_engine_limits(body.memory, body.disk)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        return engine_view()

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    from . import routes_connections
    app.include_router(routes_connections.router)
    from . import routes_sources
    app.include_router(routes_sources.router)
    from . import routes_setup
    app.include_router(routes_setup.router)
    from . import routes_profiling
    app.include_router(routes_profiling.router)
    from . import routes_col_flag, routes_col_key, routes_col_number, routes_col_when
    for r in (routes_col_when, routes_col_number, routes_col_flag, routes_col_key):
        app.include_router(r.router)          # one column's page, a module per kind of column
    from . import routes_compare
    app.include_router(routes_compare.router)
    from . import routes_results
    app.include_router(routes_results.router)
    from . import routes_downloads
    app.include_router(routes_downloads.router)

    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles

    class Page(StaticFiles):
        """index.html names the hashed assets, so a browser must ask again after an upgrade."""
        async def get_response(self, path, scope):
            r = await super().get_response(path, scope)
            if r.headers.get("content-type", "").startswith("text/html"):
                r.headers["Cache-Control"] = "no-cache"
            return r

    if (DIST / "index.html").exists():
        app.mount("/", Page(directory=DIST, html=True), name="page")
    else:
        @app.get("/", include_in_schema=False)
        def no_build() -> HTMLResponse:
            return HTMLResponse("<p>The page is not built yet: run <code>npm install</code> and "
                                "<code>npm run build</code> in the <code>web</code> folder.</p>", status_code=503)

    return app


app = create_app()
