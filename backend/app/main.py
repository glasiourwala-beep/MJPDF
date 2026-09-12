"""
MJPDF – Professional PDF Tools Platform
"""
import asyncio
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, Response

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
        # CSP: self + Google Fonts + AdSense
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' "
            "https://pagead2.googlesyndication.com "
            "https://www.googletagservices.com "
            "https://www.google.com "
            "https://partner.googleadservices.com "
            "https://tpc.googlesyndication.com "
            "https://adservice.google.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "img-src 'self' data: blob: https:; "
            "connect-src 'self' "
            "https://pagead2.googlesyndication.com "
            "https://www.google.com "
            "https://googleads.g.doubleclick.net "
            "https://tpc.googlesyndication.com "
            "https://fundingchoicesmessages.google.com "
            "https://ep1.adtrafficquality.google "
            "https://ep2.adtrafficquality.google; "
            "frame-src "
            "https://googleads.g.doubleclick.net "
            "https://tpc.googlesyndication.com "
            "https://www.google.com "
            "https://pagead2.googlesyndication.com "
            "https://ep2.adtrafficquality.google "
            "https://www.google.com; "
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
    from .config import LIBREOFFICE_CMD
    import shutil
    lo = Path(LIBREOFFICE_CMD)
    lo_ok = lo.is_file() or bool(shutil.which(str(LIBREOFFICE_CMD))) or bool(shutil.which("soffice"))
    return {
        "status": "ok",
        "service": "MJPDF",
        "version": "1.1.1",
        "libreoffice": bool(lo_ok),
        "libreoffice_cmd": str(LIBREOFFICE_CMD),
    }




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


SITE_ORIGIN = "https://mjpdf.onrender.com"

# Unique SEO per tool (server-rendered so Google sees real titles/canonicals)
TOOL_SEO = {
    "word-to-pdf": {
        "title": "Word to PDF Converter Online — Free | MJPDF",
        "description": "Convert Word DOC or DOCX files to PDF online with MJPDF. Fast, simple, and free Word to PDF conversion.",
    },
    "pptx-to-pdf": {
        "title": "PowerPoint to PDF Converter Online | MJPDF",
        "description": "Convert PowerPoint PPT and PPTX files to PDF online. Preserve slides for easy sharing with MJPDF.",
    },
    "compress-pdf": {
        "title": "Compress PDF Online — Reduce PDF File Size | MJPDF",
        "description": "Compress PDF files online with MJPDF. Reduce PDF size quickly while maintaining quality.",
    },
    "merge-pdf": {
        "title": "Merge PDF Online — Combine PDF Files | MJPDF",
        "description": "Merge multiple PDF files into one document online. Fast and free PDF combiner by MJPDF.",
    },
    "split-pdf": {
        "title": "Split PDF Online — Separate PDF Pages | MJPDF",
        "description": "Split a PDF into individual pages online. Download pages as a ZIP with MJPDF.",
    },
    "extract-pages": {
        "title": "Extract PDF Pages Online | MJPDF",
        "description": "Extract selected pages from a PDF online. Create a new PDF with only the pages you need.",
    },
    "delete-pages": {
        "title": "Delete PDF Pages Online | MJPDF",
        "description": "Remove pages from a PDF online. Delete unwanted pages and download the updated file.",
    },
    "images-to-pdf": {
        "title": "Images to PDF Converter Online | MJPDF",
        "description": "Convert JPG and PNG images to PDF online. Combine multiple images into one PDF with MJPDF.",
    },
    "pdf-to-images": {
        "title": "PDF to JPG / PNG Converter Online | MJPDF",
        "description": "Convert PDF pages to JPG or PNG images online. Export high-quality images with MJPDF.",
    },
    "rotate-pdf": {
        "title": "Rotate PDF Pages Online | MJPDF",
        "description": "Rotate PDF pages online by 90, 180, or 270 degrees. Fix page orientation with MJPDF.",
    },
    "organize-pdf": {
        "title": "Organize PDF Pages Online — Reorder | MJPDF",
        "description": "Reorder PDF pages online. Rearrange your document and download the new order with MJPDF.",
    },
    "watermark-pdf": {
        "title": "Add Watermark to PDF Online | MJPDF",
        "description": "Add a text watermark to PDF files online. Customize opacity, rotation, and size with MJPDF.",
    },
    "protect-pdf": {
        "title": "Password Protect PDF Online | MJPDF",
        "description": "Protect PDF files with a password online. Encrypt documents securely with MJPDF.",
    },
    "unlock-pdf": {
        "title": "Unlock PDF Online — Remove Password | MJPDF",
        "description": "Unlock password-protected PDFs online when you know the password. Simple PDF unlock by MJPDF.",
    },
}


def _inject_tool_seo(html: str, tool_id: str) -> str:
    """Rewrite title, description, canonical, and OG tags for a tool URL."""
    seo = TOOL_SEO.get(tool_id)
    if not seo:
        return html
    title = seo["title"]
    desc = seo["description"]
    url = f"{SITE_ORIGIN}/{tool_id}"
    # title
    html = re.sub(r"<title>[^<]*</title>", f"<title>{title}</title>", html, count=1)
    # meta description
    html = re.sub(
        r'<meta\s+name="description"\s+content="[^"]*"\s*/?>',
        f'<meta name="description" content="{desc}" />',
        html,
        count=1,
        flags=re.I,
    )
    # canonical — force absolute tool URL (critical for indexing)
    if re.search(r'rel="canonical"', html, re.I):
        html = re.sub(
            r'<link\s+rel="canonical"\s+href="[^"]*"\s*/?>',
            f'<link rel="canonical" href="{url}" />',
            html,
            count=1,
            flags=re.I,
        )
    else:
        html = html.replace("</head>", f'  <link rel="canonical" href="{url}" />\n</head>', 1)
    # og:title / og:description / og:url
    html = re.sub(
        r'<meta\s+property="og:title"\s+content="[^"]*"\s*/?>',
        f'<meta property="og:title" content="{title}" />',
        html,
        count=1,
        flags=re.I,
    )
    html = re.sub(
        r'<meta\s+property="og:description"\s+content="[^"]*"\s*/?>',
        f'<meta property="og:description" content="{desc}" />',
        html,
        count=1,
        flags=re.I,
    )
    if re.search(r'property="og:url"', html, re.I):
        html = re.sub(
            r'<meta\s+property="og:url"\s+content="[^"]*"\s*/?>',
            f'<meta property="og:url" content="{url}" />',
            html,
            count=1,
            flags=re.I,
        )
    else:
        html = html.replace("</head>", f'  <meta property="og:url" content="{url}" />\n</head>', 1)
    # twitter
    html = re.sub(
        r'<meta\s+name="twitter:title"\s+content="[^"]*"\s*/?>',
        f'<meta name="twitter:title" content="{title}" />',
        html,
        count=1,
        flags=re.I,
    )
    html = re.sub(
        r'<meta\s+name="twitter:description"\s+content="[^"]*"\s*/?>',
        f'<meta name="twitter:description" content="{desc}" />',
        html,
        count=1,
        flags=re.I,
    )
    # visible noscript fallback H1 for crawlers that skip JS
    noscript = (
        f'<noscript><main style="max-width:720px;margin:2rem auto;padding:1rem;font-family:sans-serif">'
        f'<h1>{title.split("|")[0].strip()}</h1>'
        f'<p>{desc}</p>'
        f'<p><a href="{SITE_ORIGIN}/">All MJPDF tools</a></p>'
        f'</main></noscript>'
    )
    if "<noscript>" not in html.lower():
        html = html.replace("<body>", f"<body>\n{noscript}", 1)
    return html


def _read_index_html() -> str:
    return (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")



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

    @app.api_route("/", methods=["GET", "HEAD"])
    async def index():
        # Absolute canonical for homepage
        html = _read_index_html()
        html = re.sub(
            r'<link\s+rel="canonical"\s+href="[^"]*"\s*/?>',
            f'<link rel="canonical" href="{SITE_ORIGIN}/" />',
            html,
            count=1,
            flags=re.I,
        )
        return HTMLResponse(html)

    @app.api_route("/robots.txt", methods=["GET", "HEAD"])
    async def robots():
        path = _find_public_file("robots.txt")
        if path:
            return FileResponse(path, media_type="text/plain")
        return _not_found_response()

    @app.api_route("/sitemap.xml", methods=["GET", "HEAD"])
    async def sitemap():
        path = _find_public_file("sitemap.xml")
        if path:
            return FileResponse(path, media_type="application/xml")
        return _not_found_response()

    @app.api_route("/{page_name}", methods=["GET", "HEAD"])
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

        # Known tools → index.html with UNIQUE server-side SEO (title + canonical)
        if page_name in ALLOWED_TOOL_IDS:
            index_path = FRONTEND_DIR / "index.html"
            if index_path.is_file():
                html = _inject_tool_seo(_read_index_html(), page_name)
                return HTMLResponse(html)
            return _not_found_response()

        # Anything else (URL tampering) → 404 error
        return _not_found_response()
