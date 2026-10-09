"""Local-only application. Mutable routes require a same-origin session token."""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
import secrets
import tempfile
import threading
import zipfile
import csv
from urllib.parse import urlparse
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.concurrency import run_in_threadpool
from .analytics import Scope, rankings, player_profile, coverage
from .selection import Preferences, select_eleven, sensitivity, why_not
from .sources import SOURCES, fetch_source, import_source_archive, MAX_DOWNLOAD_BYTES
from .store import connect
from .util import clean


def create_app(db_path: str | Path = "data/best-eleven.sqlite") -> FastAPI:
    app = FastAPI(title="Best Eleven Lab", version="0.1.0", docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])
    db_path = Path(db_path)
    assets = Path(__file__).parent / "web"
    token = secrets.token_urlsafe(32)
    writer = threading.Lock()
    app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @contextmanager
    def database():
        db = connect(db_path)
        try:
            yield db
        finally:
            db.close()

    @app.middleware("http")
    async def security(request: Request, call_next):
        if request.method == "POST":
            supplied = request.headers.get("x-best-eleven-token", "")
            if not secrets.compare_digest(supplied, token):
                return JSONResponse({"detail": "Reload the local application to obtain a valid session token."}, status_code=403)
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse({"detail": "Cross-origin writes are not allowed."}, status_code=403)
            if request.url.path not in {"/api/import", "/api/metadata"}:
                if int(request.headers.get("content-length", "0")) > 100_000:
                    return JSONResponse({"detail": "Request is too large."}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.exception_handler(ValueError)
    @app.exception_handler(TypeError)
    @app.exception_handler(zipfile.BadZipFile)
    @app.exception_handler(csv.Error)
    async def input_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/")
    def index():
        return FileResponse(assets / "index.html")

    @app.get("/api/status")
    def status():
        with database() as db:
            return clean({"coverage": coverage(db), "sources": [{**asdict(s), "url": s.url} for s in SOURCES.values()], "token": token, "local_only": True})

    def scope_and_pref(body):
        if set(body) - {"scope", "preferences", "locked", "excluded", "player_id"}:
            raise ValueError("Unknown request option")
        scope = Scope(**body.get("scope", {}))
        values = body.get("preferences", {})
        pref = Preferences(**({"min_bowling_options": 4 if scope.format == "Test" else 5} | values))
        return scope, pref

    @app.post("/api/analyse")
    def analyse(body: dict):
        scope, pref = scope_and_pref(body)
        with database() as db:
            rank = rankings(db, scope)
            result = select_eleven(rank, pref, locked=body.get("locked"), excluded=body.get("excluded"))
            return clean({"ranking": rank, "selection": result})

    @app.post("/api/profile")
    def profile(body: dict):
        scope, _ = scope_and_pref(body)
        if not isinstance(body.get("player_id"), str):
            raise ValueError("A player ID is required")
        with database() as db:
            return clean(player_profile(db, scope, body["player_id"]))

    @app.post("/api/sensitivity")
    def compare(body: dict):
        scope, pref = scope_and_pref(body)
        with database() as db:
            return clean(sensitivity(rankings(db, scope), pref))

    @app.post("/api/why-not")
    def alternative(body: dict):
        scope, pref = scope_and_pref(body)
        with database() as db:
            return clean(why_not(rankings(db, scope), body.get("player_id", ""), pref, locked=body.get("locked"), excluded=body.get("excluded")))

    @app.post("/api/evaluate")
    def evaluate(body: dict):
        from .evaluate import rolling_evaluate
        scope, _ = scope_and_pref(body)
        with database() as db:
            return clean(rolling_evaluate(db, scope))

    def mutate(fn):
        if not writer.acquire(blocking=False):
            raise HTTPException(409, "A data operation is already running in this local process.")
        try:
            with database() as db:
                return clean(fn(db))
        except (RuntimeError, OSError) as exc:
            raise HTTPException(502, str(exc)) from exc
        finally:
            writer.release()

    @app.post("/api/demo")
    def demo():
        from .demo import make_demo
        return mutate(lambda db: make_demo(db))

    @app.post("/api/fetch")
    def fetch(body: dict):
        if set(body) - {"source", "force"} or body.get("source") not in SOURCES:
            raise ValueError("Select a source from the published allowlist")
        return mutate(lambda db: fetch_source(db, body["source"], db_path.parent / "raw", force=bool(body.get("force", False))))

    async def uploaded_file(request, suffix, limit):
        temp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        path = Path(temp.name)
        try:
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, "Upload exceeds the size limit")
                temp.write(chunk)
            temp.close()
            if size == 0:
                raise ValueError("The uploaded file is empty")
            return path
        except BaseException:
            temp.close(); path.unlink(missing_ok=True)
            raise

    @app.post("/api/import")
    async def import_zip(request: Request, source: str):
        from .ingest import ingest_archive
        if source not in SOURCES:
            raise ValueError("Unknown source")
        path = await uploaded_file(request, ".zip", MAX_DOWNLOAD_BYTES)
        try:
            return await run_in_threadpool(mutate, lambda db: import_source_archive(db, path, source, SOURCES[source].url, db_path.parent / "raw"))
        finally:
            path.unlink(missing_ok=True)

    @app.post("/api/metadata")
    async def metadata(request: Request):
        from .metadata import import_metadata
        path = await uploaded_file(request, ".csv", 5_000_000)
        try:
            return await run_in_threadpool(mutate, lambda db: import_metadata(db, path))
        finally:
            path.unlink(missing_ok=True)

    return app
