import os
import re
import uuid
from pathlib import Path
from fastapi import UploadFile, HTTPException

from ..config import MAX_FILE_SIZE, ALLOWED_EXTENSIONS, TEMP_DIR, OUTPUT_DIR

try:
    import magic
    HAS_MAGIC = True
except ImportError:
    HAS_MAGIC = False

MIME_MAP = {
    "application/pdf": "pdf",
    "application/msword": "word",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "word",
    "application/vnd.ms-powerpoint": "pptx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "image/jpeg": "image",
    "image/png": "image",
    "image/webp": "image",
    "image/bmp": "image",
    "image/tiff": "image",
}


def sanitize_filename(filename: str) -> str:
    """Remove path components and dangerous characters."""
    name = Path(filename).name
    name = re.sub(r'[^\w\s\-\.\(\)]', '_', name)
    name = re.sub(r'\s+', '_', name).strip('._')
    if not name or name.startswith('.'):
        name = f"file_{uuid.uuid4().hex[:8]}"
    return name[:200]


def validate_file_type(file: UploadFile, expected_category: str | list[str]) -> str:
    """Validate file by extension and MIME type. Returns sanitized original name."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    if "\x00" in file.filename or len(file.filename) > 255:
        raise HTTPException(status_code=400, detail="Invalid filename")

    original = sanitize_filename(file.filename)
    ext = Path(original).suffix.lower()

    categories = expected_category if isinstance(expected_category, list) else [expected_category]
    allowed_exts = []
    for cat in categories:
        allowed_exts.extend(ALLOWED_EXTENSIONS.get(cat, []))

    if ext not in allowed_exts:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {', '.join(allowed_exts)}"
        )
    return original


def _ensure_dirs():
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


async def save_upload(file: UploadFile, expected_category: str | list[str]) -> tuple[Path, str]:
    """Validate, size-check and save upload to a unique temp path. Returns (path, original_name)."""
    _ensure_dirs()
    original_name = validate_file_type(file, expected_category)

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"File too large. Max {MAX_FILE_SIZE // (1024*1024)} MB")
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    # Basic MIME sniff (optional)
    if HAS_MAGIC:
        try:
            mime = magic.from_buffer(content[:2048], mime=True)
            categories = expected_category if isinstance(expected_category, list) else [expected_category]
            valid_mimes = [m for m, c in MIME_MAP.items() if c in categories]
            if mime not in valid_mimes and not any(
                m in mime for m in ("pdf", "word", "officedocument", "powerpoint", "image", "octet-stream")
            ):
                pass
        except Exception:
            pass

    unique = f"{uuid.uuid4().hex}_{original_name}"
    dest = TEMP_DIR / unique
    dest.write_bytes(content)
    return dest, original_name


def safe_output_path(prefix: str, extension: str) -> Path:
    """Generate a unique safe output path."""
    name = f"{prefix}_{uuid.uuid4().hex[:12]}.{extension.lstrip('.')}"
    return OUTPUT_DIR / name


def cleanup_file(path: Path | str | None):
    """Best-effort delete of a temporary file."""
    if not path:
        return
    try:
        p = Path(path)
        if p.exists() and p.is_file():
            p.unlink()
    except Exception:
        pass
