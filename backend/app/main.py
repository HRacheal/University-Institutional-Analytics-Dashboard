"""FastAPI application.  From the backend folder:

    uvicorn app.main:app --port 8000            # API (and the built frontend from frontend/dist, if present)

First start creates backend/var/uiad.db, the system roles, an administrator and a demo management user. Their one-time
initial passwords are written to backend/var/initial_credentials.txt (git-ignored) unless UIAD_BOOTSTRAP_ADMIN_PASSWORD is set.
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .core.config import get_settings

log = logging.getLogger("uiad")

# The built frontend has no inline scripts; Ant Design injects <style> elements, hence 'unsafe-inline' for styles only.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
       "frame-ancestors 'none'")


def _configure_logging():
    s = get_settings()
    if logging.getLogger().handlers and any(isinstance(h, logging.FileHandler) for h in logging.getLogger().handlers):
        return
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    fh = logging.FileHandler(s.var_dir / "uiad.log", encoding="utf-8")
    fh.setFormatter(fmt)
    root = logging.getLogger()
    root.addHandler(fh)
    root.setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    from .core.bootstrap import bootstrap
    info = bootstrap()
    if info["created_users"]:
        log.warning("bootstrap created users %s; initial passwords in backend/var/initial_credentials.txt", info["created_users"])
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="University Institutional Analytics Dashboard API", version="1.0.0", lifespan=lifespan,
                  docs_url="/api/docs" if s.api_docs else None, openapi_url="/api/openapi.json" if s.api_docs else None,
                  redoc_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=list(s.cors_origins), allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])

    @app.middleware("http")
    async def request_log(request: Request, call_next):
        t0 = time.time()
        rid = uuid.uuid4().hex[:8]
        try:
            resp = await call_next(request)
        except Exception:                               # unexpected: logged with traceback, generic message to the client
            log.exception("request %s %s %s failed", rid, request.method, request.url.path)
            return JSONResponse({"detail": "internal error", "request_id": rid}, status_code=500)
        if request.url.path.startswith("/api/"):
            log.info("%s %s %s %s %.0fms", rid, request.method, request.url.path, resp.status_code, 1000 * (time.time() - t0))
        resp.headers["X-Request-ID"] = rid
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if not request.url.path.startswith("/api/docs"):        # Swagger UI loads its own CDN assets
            resp.headers["Content-Security-Policy"] = CSP
        if request.url.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        if s.is_production:
            resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return resp

    from .ml.service import ArtifactError, InputValidationError

    @app.exception_handler(InputValidationError)
    async def _invalid(request: Request, exc: InputValidationError):
        return JSONResponse({"detail": str(exc), "details": getattr(exc, "details", None)}, status_code=422)

    @app.exception_handler(ArtifactError)
    async def _artifact(request: Request, exc: ArtifactError):
        msg = str(exc)
        unavailable = any(k in msg for k in ("not restored", "could not load", "SHA-256 mismatch", "manifest not found"))
        log.warning("artifact error on %s: %s", request.url.path, msg)
        # 503: a registered artifact is missing/unloadable on this server; 404: unknown task, run or unsupported operation
        return JSONResponse({"detail": msg}, status_code=503 if unavailable else 404)

    from .api import admin, analytics, ml
    from .auth import router as auth
    for r in (auth.router, analytics.router, ml.router, admin.router):
        app.include_router(r)

    @app.get("/api/health")
    def health():
        from .ml.service import registry
        reg = registry()
        st = reg.status()
        return {"status": "ok", "models_registered": len(st), "artifacts_present": sum(1 for x in st if x["artifact_present"]),
                "environment": reg.env}

    dist = s.frontend_dist
    if dist.exists():                                   # built SPA: static assets + index.html fallback for client routes
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            f = (dist / path).resolve()
            if path and not path.startswith("api/") and dist.resolve() in f.parents and f.is_file():
                return FileResponse(f)
            if path.startswith("api/"):
                return JSONResponse({"detail": "not found"}, status_code=404)
            return FileResponse(dist / "index.html")
    return app


app = create_app()
