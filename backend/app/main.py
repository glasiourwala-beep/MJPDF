"""
MJPDF – Professional PDF Tools Platform
"""
import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .routers import tools
from .config import BASE_DIR, TEMP_DIR, OUTPUT_DIR


def _cleanup_old_files(max_age_seconds: int = 3600):
    """Delete temp/output files older than max_age_seconds."""
    now = time.time()
    for folder in (TEMP_DIR, OUTPUT_DIR):
        try:
            if not folder.exists():
                continue
            for p in folder.iterdir():
                try:
                    if p.is_file() and (now - p.stat().st_mtime) > max_age_seconds:
                        p.unlink(missing_ok=True)
                    elif p.is_dir() and (now - p.stat().st_mtime) > max_age_seconds:
                        import shutil
                        shutil.rmtree(p, ignore_errors=True)
                except Exception:
                    pass
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: clean leftovers
    _cleanup_old_files()
    # Background periodic cleanup every 15 min
    stop = asyncio.Event()

    async def _periodic():
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=900)
            except asyncio.TimeoutError:
                await asyncio.get_running_loop().run_in_executor(None, _cleanup_old_files)

    task = asyncio.create_task(_periodic())
    yield
    stop.set()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="MJPDF",
    description="Professional online PDF tools – real conversions, high quality output",
    version="1.1.0",
    lifespan=lifespan,
    docs_url=None,      # disable public Swagger UI
    redoc_url=None,     # disable ReDoc
    openapi_url=None,   # disable OpenAPI schema exposure
)

# Security headers on every response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse, PlainTextResponse, HTMLResponse


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Block obvious path traversal / null bytes in URL path
        path = request.url.path or ""
        if ".." in path or "\x00" in path or "%00" in path.lower() or "%2e%2e" in path.lower():
            return JSONResponse({"detail": "Invalid request path."}, status_code=400)

        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        # CSP: allow self + google fonts used by frontend
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "img-src 'self' data: blob:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        # Do not cache API responses by default
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response


app.add_middleware(SecurityHeadersMiddleware)

# CORS: allow browser clients; credentials off with wildcard is safer pattern for public API tools
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Original-Size", "X-Compressed-Size", "X-Reduction-Percent", "Content-Disposition"],
    max_age=600,
)

# API routes FIRST (before catch-all frontend routes)
app.include_router(tools.router)
for route in tools.router.routes:
    if route not in app.routes:
        app.routes.append(route)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "MJPDF", "version": "1.1.0"}




# Frontend static + SPA — allowlist only (unknown URLs → 404)
FRONTEND_DIR = BASE_DIR / "frontend"

# Only these HTML pages are public
ALLOWED_STATIC_PAGES = frozenset({
    "about.html",
    "contact.html",
    "download.html",
    "terms.html",
    "privacy.html",
    "privacy-policy.html",
    "cookie-policy.html",
    "404.html",
})

# Pretty paths → files
PRETTY_PATHS = {
    "privacy-policy": "privacy-policy.html",
    "cookie-policy": "cookie-policy.html",
    "about": "about.html",
    "contact": "contact.html",
    "download": "download.html",
    "terms": "terms.html",
}

# Only real tools may open the SPA shell
ALLOWED_TOOL_IDS = frozenset({
    "word-to-pdf",
    "pptx-to-pdf",
    "compress-pdf",
    "merge-pdf",
    "split-pdf",
    "extract-pages",
    "delete-pages",
    "images-to-pdf",
    "pdf-to-images",
    "rotate-pdf",
    "organize-pdf",
    "watermark-pdf",
    "protect-pdf",
    "unlock-pdf",
})


def _safe_public_name(name: str) -> bool:
    """Reject path traversal and unsafe characters in single-segment paths."""
    if not name or len(name) > 120:
        return False
    if name in (".", "..") or ".." in name:
        return False
    if "/" in name or "\\" in name or "\x00" in name:
        return False
    # allow letters, digits, dash, underscore, dot only
    for ch in name:
        if not (ch.isalnum() or ch in "-_."):
            return False
    return True


def _find_public_file(name: str) -> Path | None:
    if not _safe_public_name(name):
        return None
    for base in (FRONTEND_DIR, BASE_DIR):
        path = (base / name).resolve()
        try:
            path.relative_to(base.resolve())
        except ValueError:
            return None
        if path.is_file():
            return path
    return None


def _not_found_response():
    page = FRONTEND_DIR / "404.html"
    if page.is_file():
        return FileResponse(page, status_code=404, media_type="text/html")
    return PlainTextResponse("404 — Page not found", status_code=404)


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR / "static"), name="static")

    @app.get("/")
    async def index():
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.get("/robots.txt")
    async def robots():
        path = _find_public_file("robots.txt")
        if path:
            return FileResponse(path, media_type="text/plain")
        return _not_found_response()

    @app.get("/sitemap.xml")
    async def sitemap():
        path = _find_public_file("sitemap.xml")
        if path:
            return FileResponse(path, media_type="application/xml")
        return _not_found_response()

    @app.get("/{page_name}")
    async def frontend_page(page_name: str):
        # Hard deny unsafe names
        if not _safe_public_name(page_name):
            return JSONResponse({"detail": "Invalid path."}, status_code=400)

        if page_name == "api":
            return JSONResponse({"detail": "Not found"}, status_code=404)

        # Pretty legal/info paths
        if page_name in PRETTY_PATHS:
            path = FRONTEND_DIR / PRETTY_PATHS[page_name]
            if path.is_file():
                return FileResponse(path, media_type="text/html")
            return _not_found_response()

        # Explicit allowlisted static HTML only
        if page_name in ALLOWED_STATIC_PAGES:
            path = FRONTEND_DIR / page_name
            if path.is_file():
                return FileResponse(path, media_type="text/html")
            return _not_found_response()

        # Known tools → SPA index.html
        if page_name in ALLOWED_TOOL_IDS:
            index_path = FRONTEND_DIR / "index.html"
            if index_path.is_file():
                return FileResponse(index_path, media_type="text/html")
            return _not_found_response()

        # Anything else (URL tampering) → 404 error
        return _not_found_response()
