import os
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
TEMP_DIR = BASE_DIR / "temp"
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"

for d in (TEMP_DIR, UPLOAD_DIR, OUTPUT_DIR):
    d.mkdir(parents=True, exist_ok=True)

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB
ALLOWED_EXTENSIONS = {
    "pdf": [".pdf"],
    "word": [".doc", ".docx"],
    "pptx": [".ppt", ".pptx"],
    "image": [".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"],
}

# Cleanup after processing (seconds)
CLEANUP_DELAY = 3600  # 1 hour


def find_libreoffice() -> str:
    """
    Find LibreOffice executable on Windows / Linux / macOS.
    Returns the full path or 'soffice' if found in PATH.
    """
    # 1. Already in PATH?
    for name in ("soffice", "soffice.exe", "libreoffice", "libreoffice.exe"):
        found = shutil.which(name)
        if found:
            return found

    # 2. Common Windows install locations
    if os.name == "nt":
        candidates = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
            r"C:\Program Files\LibreOffice 24\program\soffice.exe",
            r"C:\Program Files\LibreOffice 25\program\soffice.exe",
            r"C:\Program Files\LibreOffice 7\program\soffice.exe",
            str(Path.home() / "AppData/Local/Programs/LibreOffice/program/soffice.exe"),
        ]
        for path in candidates:
            if Path(path).is_file():
                return path

    # 3. Common Linux / macOS locations
    for path in (
        "/usr/bin/soffice",
        "/usr/bin/libreoffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ):
        if Path(path).is_file():
            return path

    # Not found – return default (will raise clear error later)
    return "soffice"


LIBREOFFICE_CMD = find_libreoffice()

# Self-hosted download package: place empty file ".selfhost" in project root
# or set env MJPDF_OWNER_WATERMARK=1 to stamp outputs.
import os as _os
OWNER_WATERMARK = (
    _os.environ.get("MJPDF_OWNER_WATERMARK", "").strip() in ("1", "true", "yes")
    or (BASE_DIR / ".selfhost").is_file()
)
