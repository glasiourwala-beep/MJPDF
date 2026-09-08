"""
High-quality document conversion services for MJPDF.
Uses LibreOffice for Office formats and pdf2docx / PyMuPDF for PDF operations.
Designed for concurrent requests (unique LO profiles + unique temp paths).
"""
import asyncio
import subprocess
import shutil
import tempfile
import uuid
import os
from pathlib import Path


def apply_owner_page_watermark(pdf_path: Path, text: str = "") -> None:
    """Disabled — no visual owner watermark on outputs."""
    return

from typing import Optional

import pymupdf
from pdf2docx import Converter
from pypdf import PdfReader, PdfWriter
from docx import Document
from pptx import Presentation
from PIL import Image
import pdf2image

from ..config import LIBREOFFICE_CMD, TEMP_DIR, OUTPUT_DIR
from ..utils.security import safe_output_path, cleanup_file
from concurrent.futures import ThreadPoolExecutor
import threading

# Bounded thread pool for CPU / subprocess work (multi-user friendly)
_MAX_WORKERS = min(32, max(4, (os.cpu_count() or 4) * 2))
_EXECUTOR = ThreadPoolExecutor(max_workers=_MAX_WORKERS)

# Limit concurrent LibreOffice processes (each is heavy)
_LO_LIMIT = 1  # one LO at a time — shared profile is much faster than per-job profiles
_lo_semaphore: Optional[asyncio.Semaphore] = None
_lo_thread_lock = threading.Lock()
_LO_SHARED_PROFILE = TEMP_DIR / "lo_profile_shared"


def _lo_sem() -> asyncio.Semaphore:
    global _lo_semaphore
    if _lo_semaphore is None:
        _lo_semaphore = asyncio.Semaphore(_LO_LIMIT)
    return _lo_semaphore


async def _run_sync(fn, *args, **kwargs):
    """Run blocking function in shared thread pool."""
    loop = asyncio.get_running_loop()
    if kwargs:
        return await loop.run_in_executor(_EXECUTOR, lambda: fn(*args, **kwargs))
    return await loop.run_in_executor(_EXECUTOR, fn, *args)


async def run_cmd(cmd: list[str], timeout: int = 120) -> tuple[int, str, str]:
    """Run a subprocess with timeout (non-blocking)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(TEMP_DIR),
        )
    except FileNotFoundError as e:
        return 127, "", str(e)
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        raise RuntimeError("Conversion timed out")


def _libreoffice_convert(input_path: Path, out_dir: Path, target_format: str, timeout: int = 180) -> Path:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    """
    LibreOffice headless convert.
    Copies input to a simple ASCII filename (special chars break soffice),
    uses a writable profile under TEMP_DIR.
    """
    lo = str(LIBREOFFICE_CMD)
    if not Path(lo).is_file() and shutil.which(lo) is None:
        # try common linux names
        for cand in ("soffice", "libreoffice", "/usr/bin/soffice", "/usr/bin/libreoffice"):
            if Path(cand).is_file() or shutil.which(cand):
                lo = shutil.which(cand) or cand
                break
        else:
            raise RuntimeError(
                "LibreOffice is not installed on the server. Word/PPT to PDF needs LibreOffice."
            )

    out_dir.mkdir(parents=True, exist_ok=True)

    # Simple path — LO fails on many unicode/space names
    safe_in = out_dir / f"input_{uuid.uuid4().hex[:10]}{input_path.suffix.lower()}"
    shutil.copy2(str(input_path), str(safe_in))

    profile_dir = TEMP_DIR / f"lo_prof_{uuid.uuid4().hex[:12]}"
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_uri = profile_dir.resolve().as_uri()

    # Prefer Writer PDF export with font embedding (better alignment vs layout-only pdf)
    fmt = target_format
    if fmt == "pdf" or fmt.startswith("pdf:"):
        # Embed fonts so tab/column alignment stays closer to Word
        fmt = 'pdf:writer_pdf_Export'

    cmd = [
        lo,
        "--headless",
        "--norestore",
        "--nofirststartwizard",
        "--nologo",
        "--nodefault",
        "--nolockcheck",
        f"-env:UserInstallation={profile_uri}",
        "--convert-to", fmt,
        "--outdir", str(out_dir.resolve()),
        str(safe_in.resolve()),
    ]

    env = {
        **os.environ,
        "HOME": str(profile_dir),
        "SAL_USE_VCLPLUGIN": "svp",
    }

    try:
        with _lo_thread_lock:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(out_dir),
                env=env,
            )
    except subprocess.TimeoutExpired:
        shutil.rmtree(profile_dir, ignore_errors=True)
        raise RuntimeError("Conversion timed out. Try a smaller file or retry.")
    except FileNotFoundError:
        shutil.rmtree(profile_dir, ignore_errors=True)
        raise RuntimeError("LibreOffice binary not found on server.")
    finally:
        try:
            safe_in.unlink(missing_ok=True)
        except Exception:
            pass
        shutil.rmtree(profile_dir, ignore_errors=True)

    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        # Common OOM / crash
        low = err.lower()
        if "memory" in low or "killed" in low:
            raise RuntimeError("Server ran out of memory during conversion. Try a smaller file.")
        raise RuntimeError(f"LibreOffice failed: {err[:300] or 'unknown error'}")

    # Output named after safe_in stem
    stem = safe_in.stem
    candidates = sorted(out_dir.glob(f"{stem}.*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for c in candidates:
        if c.suffix.lower() == ".pdf" or c.suffix.lower().lstrip(".") in fmt.split(":")[0].lower():
            return c
    # any new non-input file
    for c in candidates:
        if c.resolve() != safe_in.resolve():
            return c
    raise RuntimeError("LibreOffice produced no output file. The document may be corrupted or unsupported.")


async def _libreoffice_convert_async(input_path: Path, out_dir: Path, target_format: str, timeout: int = 120) -> Path:
    """Async LO convert with concurrency limit (max 2 parallel)."""
    async with _lo_sem():
        return await _run_sync(_libreoffice_convert, input_path, out_dir, target_format, timeout)



# ---------------------------------------------------------------------------
# 1. PDF → Word (DOCX)  — editable text + tables
# ---------------------------------------------------------------------------
async def pdf_to_docx(pdf_path: Path) -> Path:
    """
    PDF → editable DOCX.
    Runs pdf2docx + LibreOffice, picks the better structured result,
    then light post-process (clean text / empty paras / table borders).
    """
    import re
    from docx import Document
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    def _score_docx(p: Path) -> tuple:
        """Higher = better structured document."""
        try:
            doc = Document(str(p))
            paras = sum(1 for x in doc.paragraphs if x.text.strip())
            tables = len(doc.tables)
            cells = sum(len(r.cells) for t in doc.tables for r in t.rows)
            images = 0
            for rel in doc.part.rels.values():
                if "image" in getattr(rel, "reltype", ""):
                    images += 1
            size = p.stat().st_size
            # Prefer more structure, then size
            return (tables * 50 + cells * 2 + paras + images * 20, size)
        except Exception:
            return (0, p.stat().st_size if p.exists() else 0)

    def _convert_pdf2docx():
        out = safe_output_path("pdf2word_p2d", "docx")
        cv = Converter(str(pdf_path))
        try:
            # layout-aware conversion of all pages
            cv.convert(str(out), start=0, end=None)
        finally:
            cv.close()
        if not out.exists() or out.stat().st_size < 800:
            raise RuntimeError("pdf2docx empty")
        return out

    def _convert_libreoffice():
        work = TEMP_DIR / f"lo_pdf2docx_{uuid.uuid4().hex}"
        work.mkdir(exist_ok=True)
        try:
            # Explicit Word 2007 XML filter when available
            try:
                converted = _libreoffice_convert(pdf_path, work, "docx:MS Word 2007 XML")
            except Exception:
                converted = _libreoffice_convert(pdf_path, work, "docx")
            final = safe_output_path("pdf2word_lo", "docx")
            shutil.move(str(converted), str(final))
            return final
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _clean_text(s: str) -> str:
        if not s:
            return s
        s = s.replace(r"\text{", "").replace("}", "")
        s = s.replace(r"\mathrm{", "").replace(r"\mathbf{", "").replace(r"\mathit{", "")
        s = re.sub(r"\$([^$]*)\$", r"\1", s)
        s = re.sub(r"\\\((.*?)\\\)", r"\1", s)
        s = re.sub(r"\\\[(.*?)\\\]", r"\1", s)
        s = re.sub(r"\s+", " ", s)
        return s.strip()

    def _post_process(docx_path: Path) -> Path:
        doc = Document(str(docx_path))
        for p in doc.paragraphs:
            for run in p.runs:
                if run.text:
                    cleaned = _clean_text(run.text)
                    if cleaned != run.text:
                        run.text = cleaned
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        for run in p.runs:
                            if run.text:
                                cleaned = _clean_text(run.text)
                                if cleaned != run.text:
                                    run.text = cleaned
                    try:
                        tc = cell._tc
                        tcPr = tc.get_or_add_tcPr()
                        borders = tcPr.find(qn("w:tcBorders"))
                        if borders is None:
                            borders = OxmlElement("w:tcBorders")
                            for edge in ("top", "left", "bottom", "right"):
                                tag = OxmlElement(f"w:{edge}")
                                tag.set(qn("w:val"), "single")
                                tag.set(qn("w:sz"), "4")
                                tag.set(qn("w:space"), "0")
                                tag.set(qn("w:color"), "000000")
                                borders.append(tag)
                            tcPr.append(borders)
                    except Exception:
                        pass

        body = doc.element.body
        # trailing empty paragraphs
        for child in reversed(list(body)):
            if child.tag != qn("w:p"):
                break
            text = "".join(node.text or "" for node in child.iter(qn("w:t")))
            if text.strip():
                break
            body.remove(child)
        # consecutive empty
        prev_empty = False
        for child in list(body):
            if child.tag != qn("w:p"):
                prev_empty = False
                continue
            text = "".join(node.text or "" for node in child.iter(qn("w:t")))
            has_drawing = (
                child.find(".//" + qn("w:drawing")) is not None
                or child.find(".//" + qn("w:pict")) is not None
            )
            is_empty = (not text.strip()) and not has_drawing
            if is_empty and prev_empty:
                body.remove(child)
            prev_empty = is_empty

        out = safe_output_path("pdf2word", "docx")
        doc.save(str(out))
        return out

    candidates = []

    # Engine A: pdf2docx
    try:
        a = await _run_sync(_convert_pdf2docx)
        if a and a.exists():
            candidates.append(a)
    except Exception:
        pass

    # Engine B: LibreOffice
    try:
        b = await _run_sync(_convert_libreoffice)
        if b and b.exists():
            candidates.append(b)
    except Exception:
        pass

    if not candidates:
        raise RuntimeError("PDF to Word failed with all engines")

    # Pick best structured result
    best = max(candidates, key=_score_docx)

    try:
        cleaned = await _run_sync(_post_process, best)
        if cleaned.exists() and cleaned.stat().st_size > 500:
            return cleaned
    except Exception:
        pass
    return best


# ---------------------------------------------------------------------------
# 2. Word → PDF
# ---------------------------------------------------------------------------


def _normalize_docx_lists(docx_path: Path) -> Path:
    """
    Free-stack quality boost before LibreOffice PDF export:
    - Map MS fonts to metric-compatible fonts (Calibri→Carlito, etc.)
    - Expand tabs (tab stops break columns in LO)
    - Cap oversized bullet/number glyphs
    - Soften heavy paragraph shading that becomes ugly gray bars
    - Normalize heading run sizes slightly for consistency
    """
    try:
        from docx import Document
        from docx.shared import Pt, Twips
        from docx.oxml.ns import qn

        FONT_MAP = {
            "calibri": "Carlito",
            "calibri light": "Carlito",
            "cambria": "Caladea",
            "arial": "Liberation Sans",
            "times new roman": "Liberation Serif",
            "courier new": "Liberation Mono",
            "segoe ui": "Carlito",
            "tahoma": "Liberation Sans",
            "verdana": "Liberation Sans",
            "georgia": "Liberation Serif",
        }

        doc = Document(str(docx_path))
        changed = False

        def map_font(run) -> None:
            nonlocal changed
            try:
                name = (run.font.name or "").strip()
                if not name and run._element.rPr is not None:
                    rFonts = run._element.rPr.rFonts
                    if rFonts is not None:
                        name = (
                            rFonts.get(qn("w:ascii"))
                            or rFonts.get(qn("w:hAnsi"))
                            or ""
                        )
                key = name.lower().strip()
                if key in FONT_MAP:
                    run.font.name = FONT_MAP[key]
                    r = run._element
                    rPr = r.get_or_add_rPr()
                    rFonts = rPr.find(qn("w:rFonts"))
                    if rFonts is None:
                        from docx.oxml import OxmlElement
                        rFonts = OxmlElement("w:rFonts")
                        rPr.insert(0, rFonts)
                    for attr in (
                        qn("w:ascii"),
                        qn("w:hAnsi"),
                        qn("w:cs"),
                        qn("w:eastAsia"),
                    ):
                        rFonts.set(attr, FONT_MAP[key])
                    changed = True
            except Exception:
                pass

        def strip_heavy_shading(paragraph) -> None:
            nonlocal changed
            try:
                pPr = paragraph._p.pPr
                if pPr is None:
                    return
                shd = pPr.find(qn("w:shd"))
                if shd is not None:
                    fill = (shd.get(qn("w:fill")) or "").upper()
                    # Remove light gray fills that LO renders as ugly bars
                    if fill in ("", "AUTO", "FFFFFF"):
                        return
                    # light grays common in student templates
                    if fill in (
                        "F2F2F2",
                        "F5F5F5",
                        "EEEEEE",
                        "E7E6E6",
                        "D9D9D9",
                        "F0F0F0",
                        "FAFAFA",
                        "EDEDED",
                    ):
                        pPr.remove(shd)
                        changed = True
            except Exception:
                pass

        def fix_runs(paragraph, is_list: bool, is_heading: bool) -> None:
            nonlocal changed
            for run in paragraph.runs:
                map_font(run)
                text = run.text or ""
                if "\t" in text:
                    run.text = text.replace("\t", "    ")
                    changed = True
                    text = run.text
                # Bullet / symbol glyphs
                if len(text.strip()) <= 2 and text.strip() in {
                    "•", "●", "○", "■", "□", "▪", "▫", "–", "-", "*", "·", "◦",
                    "►", "▸", "‣", "◆", "◇", "➢", "➤",
                }:
                    try:
                        run.font.size = Pt(11 if not is_heading else 12)
                        changed = True
                    except Exception:
                        pass
                try:
                    if run.font.size and run.font.size.pt > 36:
                        run.font.size = Pt(18 if is_heading else 12)
                        changed = True
                    elif is_list and run.font.size and run.font.size.pt > 14:
                        run.font.size = Pt(11)
                        changed = True
                except Exception:
                    pass

        for p in doc.paragraphs:
            style_name = (p.style.name or "") if p.style else ""
            style_l = style_name.lower()
            is_heading = style_l.startswith("heading") or style_l in {
                "title",
                "subtitle",
            }
            is_list = "list" in style_l
            try:
                pPr = p._p.pPr
                if pPr is not None and pPr.numPr is not None:
                    is_list = True
            except Exception:
                pass
            strip_heavy_shading(p)
            fix_runs(p, is_list, is_heading)

        # Tables: same font/tab fixes
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        style_l = ((p.style.name or "") if p.style else "").lower()
                        is_list = "list" in style_l
                        try:
                            if p._p.pPr is not None and p._p.pPr.numPr is not None:
                                is_list = True
                        except Exception:
                            pass
                        strip_heavy_shading(p)
                        fix_runs(p, is_list, False)

        out = safe_output_path("word_norm", "docx")
        doc.save(str(out))
        return out
    except Exception:
        return docx_path



async def word_to_pdf(docx_path: Path) -> Path:
    """
    Word DOC/DOCX → PDF via LibreOffice.
    Pre-normalizes fonts/tabs/bullets/shading, then exports with Writer PDF filter.
    """
    try:
        src = await _run_sync(_normalize_docx_lists, docx_path)
    except Exception:
        src = docx_path
    work = TEMP_DIR / f"lo_word_{uuid.uuid4().hex}"
    work.mkdir(exist_ok=True)
    try:
        try:
            converted = await _libreoffice_convert_async(
                src, work, "pdf:writer_pdf_Export", timeout=180
            )
        except Exception:
            converted = await _libreoffice_convert_async(src, work, "pdf", timeout=180)
        if not converted.exists() or converted.stat().st_size < 50:
            raise RuntimeError("PDF output was empty")
        final = safe_output_path("word2pdf", "pdf")
        shutil.move(str(converted), str(final))
        return final
    except Exception as e:
        msg = str(e)
        if "LibreOffice" in msg or "soffice" in msg:
            raise
        raise RuntimeError(f"Word to PDF failed: {msg}") from e
    finally:
        shutil.rmtree(work, ignore_errors=True)
        if src != docx_path:
            try:
                src.unlink(missing_ok=True)
            except Exception:
                pass




# ---------------------------------------------------------------------------
# 3. PDF → PPTX
# ---------------------------------------------------------------------------
async def pdf_to_pptx(pdf_path: Path) -> Path:
    """
    Convert each PDF page into a slide.
    Renders pages at high DPI and places them as full-slide images.
    """
    from pptx.util import Inches

    out = safe_output_path("pdf2pptx", "pptx")
    loop = asyncio.get_running_loop()

    def _render_pages():
        """Return list of PIL Images for each PDF page."""
        # Try pdf2image (needs poppler)
        try:
            return pdf2image.convert_from_path(
                str(pdf_path),
                dpi=120,
                fmt="png",
                thread_count=max(1, (os.cpu_count() or 2)),
            )
        except Exception:
            pass
        # Fallback: PyMuPDF (no poppler needed)
        doc = pymupdf.open(str(pdf_path))
        images = []
        for page in doc:
            pix = page.get_pixmap(matrix=pymupdf.Matrix(120 / 72, 120 / 72), alpha=False)
            tmp = TEMP_DIR / f"pptx_page_{page.number}.png"
            pix.save(str(tmp))
            images.append(Image.open(tmp).copy())
            tmp.unlink(missing_ok=True)
        doc.close()
        return images

    def _convert():
        images = _render_pages()
        if not images:
            raise RuntimeError("No pages found in PDF")

        prs = Presentation()
        first = images[0]
        width_in = first.width / 120
        height_in = first.height / 120
        # Reasonable limits
        width_in = min(max(width_in, 5), 20)
        height_in = min(max(height_in, 5), 20)
        prs.slide_width = Inches(width_in)
        prs.slide_height = Inches(height_in)

        blank_layout = prs.slide_layouts[6]  # blank

        for img in images:
            slide = prs.slides.add_slide(blank_layout)
            tmp_img = TEMP_DIR / f"slide_{id(img)}.png"
            img.save(tmp_img, "PNG")
            try:
                slide.shapes.add_picture(
                    str(tmp_img),
                    Inches(0),
                    Inches(0),
                    width=prs.slide_width,
                    height=prs.slide_height,
                )
            finally:
                tmp_img.unlink(missing_ok=True)

        prs.save(str(out))
        return out

    result = await loop.run_in_executor(None, _convert)
    if not result.exists():
        raise RuntimeError("PDF to PPTX failed")
    return result


# ---------------------------------------------------------------------------
# 4. PPTX / PPT → PDF
# ---------------------------------------------------------------------------
async def pptx_to_pdf(pptx_path: Path) -> Path:
    """High-fidelity PowerPoint to PDF via LibreOffice."""
    work = TEMP_DIR / f"lo_ppt_{uuid.uuid4().hex}"
    work.mkdir(exist_ok=True)
    try:
        loop = asyncio.get_running_loop()
        converted = await _libreoffice_convert_async(pptx_path, work, "pdf")
        final = safe_output_path("pptx2pdf", "pdf")
        shutil.move(str(converted), str(final))
        return final
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------------------
# 5. Compress PDF
# ---------------------------------------------------------------------------
def _find_ghostscript() -> Optional[str]:
    """Locate Ghostscript binary on Windows / Linux / macOS."""
    for name in ("gswin64c", "gswin32c", "gs", "gswin64c.exe", "gswin32c.exe"):
        found = shutil.which(name)
        if found:
            return found
    if os.name == "nt":
        candidates = [
            r"C:\Program Files\gs\gs10.04.0\bin\gswin64c.exe",
            r"C:\Program Files\gs\gs10.03.1\bin\gswin64c.exe",
            r"C:\Program Files\gs\gs10.02.1\bin\gswin64c.exe",
            r"C:\Program Files\gs\gs10.01.2\bin\gswin64c.exe",
            r"C:\Program Files\gs\gs10.00.0\bin\gswin64c.exe",
            r"C:\Program Files\gs\gs9.56.1\bin\gswin64c.exe",
            r"C:\Program Files (x86)\gs\gs10.04.0\bin\gswin32c.exe",
            r"C:\Program Files (x86)\gs\gs9.56.1\bin\gswin32c.exe",
        ]
        # Also scan C:\Program Files\gs\* dynamically
        gs_root = Path(r"C:\Program Files\gs")
        if gs_root.is_dir():
            for d in sorted(gs_root.iterdir(), reverse=True):
                exe = d / "bin" / "gswin64c.exe"
                if exe.is_file():
                    candidates.insert(0, str(exe))
        for path in candidates:
            if Path(path).is_file():
                return path
    return None


async def compress_pdf(pdf_path: Path, level: str = "medium") -> tuple[Path, dict]:
    """
    Compress PDF.
    Primary: Ghostscript (if installed)
    Fallback: PyMuPDF (always available) — works without Ghostscript
    levels: low (high quality), medium, high (smaller)
    """
    settings = {
        "low": "/prepress",
        "medium": "/ebook",
        "high": "/screen",
    }
    gs_setting = settings.get(level, "/ebook")
    out = safe_output_path(f"compress_{level}", "pdf")
    loop = asyncio.get_running_loop()
    used_gs = False

    gs_bin = _find_ghostscript()
    if gs_bin:
        cmd = [
            gs_bin,
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.4",
            f"-dPDFSETTINGS={gs_setting}",
            "-dNOPAUSE",
            "-dQUIET",
            "-dBATCH",
            f"-sOutputFile={out}",
            str(pdf_path),
        ]
        try:
            code, stdout, stderr = await run_cmd(cmd, timeout=90)
            if code == 0 and out.exists() and out.stat().st_size > 0:
                used_gs = True
        except Exception:
            used_gs = False

    if not used_gs:
        # PyMuPDF fallback — no Ghostscript required
        def _fallback():
            src = pymupdf.open(str(pdf_path))
            try:
                if level == "high":
                    # Stronger: rasterize pages at lower DPI + JPEG
                    doc = pymupdf.open()
                    try:
                        for page in src:
                            mat = pymupdf.Matrix(100 / 72, 100 / 72)
                            pix = page.get_pixmap(matrix=mat, alpha=False)
                            new_page = doc.new_page(width=page.rect.width, height=page.rect.height)
                            img_bytes = pix.tobytes("jpeg", jpg_quality=45)
                            new_page.insert_image(page.rect, stream=img_bytes)
                        doc.save(str(out), garbage=4, deflate=True, clean=True)
                    finally:
                        doc.close()
                else:
                    # Lossless-ish cleanup (medium / low)
                    src.save(str(out), garbage=4, deflate=True, clean=True)
            finally:
                src.close()
            return out

        out = await loop.run_in_executor(None, _fallback)

    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError("Compression produced empty output")

    original_size = pdf_path.stat().st_size
    new_size = out.stat().st_size
    reduction = max(0, (1 - new_size / original_size) * 100) if original_size else 0

    stats = {
        "original_size": original_size,
        "compressed_size": new_size,
        "reduction_percent": round(reduction, 1),
        "level": level,
    }
    return out, stats


# ---------------------------------------------------------------------------
# 6. Merge PDFs
# ---------------------------------------------------------------------------
async def merge_pdfs(pdf_paths: list[Path]) -> Path:
    """Merge multiple PDFs preserving page order and content."""
    if not pdf_paths:
        raise ValueError("No PDFs provided")
    out = safe_output_path("merged", "pdf")
    loop = asyncio.get_running_loop()

    def _merge():
        writer = PdfWriter()
        for p in pdf_paths:
            reader = PdfReader(str(p))
            for page in reader.pages:
                writer.add_page(page)
        with open(out, "wb") as f:
            writer.write(f)
        return out

    return await loop.run_in_executor(None, _merge)


# ---------------------------------------------------------------------------
# 7. Split / Extract / Delete pages
# ---------------------------------------------------------------------------
def _parse_page_ranges(ranges: str, total_pages: int) -> list[int]:
    """Parse '1-3,5,8-10' into 0-based page indices. Validates bounds."""
    pages = set()
    for part in ranges.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start = int(a)
            end = int(b)
            if start > end:
                start, end = end, start
            for i in range(start, end + 1):
                if 1 <= i <= total_pages:
                    pages.add(i - 1)
        else:
            i = int(part)
            if 1 <= i <= total_pages:
                pages.add(i - 1)
    return sorted(pages)


async def extract_pages(pdf_path: Path, ranges: str) -> Path:
    """Extract selected pages into a new PDF."""
    out = safe_output_path("extract", "pdf")
    loop = asyncio.get_running_loop()

    def _extract():
        reader = PdfReader(str(pdf_path))
        total = len(reader.pages)
        indices = _parse_page_ranges(ranges, total)
        if not indices:
            raise ValueError("No valid pages selected")
        writer = PdfWriter()
        for i in indices:
            writer.add_page(reader.pages[i])
        with open(out, "wb") as f:
            writer.write(f)
        return out

    return await loop.run_in_executor(None, _extract)


async def delete_pages(pdf_path: Path, ranges: str) -> Path:
    """Delete selected pages and return remaining PDF."""
    out = safe_output_path("delete_pages", "pdf")
    loop = asyncio.get_running_loop()

    def _delete():
        reader = PdfReader(str(pdf_path))
        total = len(reader.pages)
        to_delete = set(_parse_page_ranges(ranges, total))
        if not to_delete:
            raise ValueError("No valid pages to delete")
        if len(to_delete) >= total:
            raise ValueError("Cannot delete all pages")
        writer = PdfWriter()
        for i in range(total):
            if i not in to_delete:
                writer.add_page(reader.pages[i])
        with open(out, "wb") as f:
            writer.write(f)
        return out

    return await loop.run_in_executor(None, _delete)


async def split_every_page(pdf_path: Path) -> list[Path]:
    """Split PDF into one file per page."""
    loop = asyncio.get_running_loop()

    def _split():
        reader = PdfReader(str(pdf_path))
        results = []
        for i, page in enumerate(reader.pages):
            writer = PdfWriter()
            writer.add_page(page)
            out = safe_output_path(f"page_{i+1}", "pdf")
            with open(out, "wb") as f:
                writer.write(f)
            results.append(out)
        return results

    return await loop.run_in_executor(None, _split)


# ---------------------------------------------------------------------------
# 8 / 9. Images ↔ PDF
# ---------------------------------------------------------------------------
async def images_to_pdf(image_paths: list[Path], page_size: str = "A4", orientation: str = "portrait") -> Path:
    """Combine images into a multi-page PDF. page_size: A4, Letter, fit."""
    from reportlab.lib.pagesizes import A4, letter, landscape
    from reportlab.pdfgen import canvas

    out = safe_output_path("images2pdf", "pdf")
    loop = asyncio.get_running_loop()

    def _convert():
        if page_size.upper() == "LETTER":
            base = letter
        else:
            base = A4
        if orientation.lower() == "landscape":
            page = landscape(base)
        else:
            page = base

        c = canvas.Canvas(str(out), pagesize=page)
        pw, ph = page

        for img_path in image_paths:
            with Image.open(img_path) as im:
                im = im.convert("RGB")
                iw, ih = im.size
                # Fit image into page with small margin
                margin = 20
                max_w = pw - 2 * margin
                max_h = ph - 2 * margin
                scale = min(max_w / iw, max_h / ih)
                w = iw * scale
                h = ih * scale
                x = (pw - w) / 2
                y = (ph - h) / 2
                tmp = TEMP_DIR / f"img_{id(im)}.jpg"
                im.save(tmp, "JPEG", quality=92)
                c.drawImage(str(tmp), x, y, width=w, height=h, preserveAspectRatio=True)
                tmp.unlink(missing_ok=True)
            c.showPage()
        c.save()
        return out

    return await loop.run_in_executor(None, _convert)


async def pdf_to_images(pdf_path: Path, fmt: str = "jpg", dpi: int = 150, pages: Optional[str] = None) -> list[Path]:
    """
    Convert PDF pages to images. fmt: jpg|png.
    Primary: PyMuPDF (no poppler needed — works on Windows)
    Fallback: pdf2image if available
    """
    loop = asyncio.get_running_loop()

    def _convert_pymupdf():
        doc = pymupdf.open(str(pdf_path))
        total = doc.page_count
        if pages:
            indices = _parse_page_ranges(pages, total)
        else:
            indices = list(range(total))
        if not indices:
            doc.close()
            raise ValueError("No valid pages selected")

        zoom = dpi / 72.0
        mat = pymupdf.Matrix(zoom, zoom)
        results = []
        for n, i in enumerate(indices):
            if i < 0 or i >= total:
                continue
            page = doc[i]
            pix = page.get_pixmap(matrix=mat, alpha=False)
            out = safe_output_path(f"page_{n+1}", fmt)
            if fmt == "png":
                pix.save(str(out))
            else:
                # JPEG via PIL for quality control
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                img.save(str(out), "JPEG", quality=92)
            results.append(out)
        doc.close()
        return results

    def _convert_pdf2image():
        kwargs = {"dpi": dpi, "fmt": fmt, "thread_count": 2}
        if pages:
            reader = PdfReader(str(pdf_path))
            total = len(reader.pages)
            indices = _parse_page_ranges(pages, total)
            images = pdf2image.convert_from_path(str(pdf_path), **kwargs)
            selected = [images[i] for i in indices if i < len(images)]
        else:
            selected = pdf2image.convert_from_path(str(pdf_path), **kwargs)

        results = []
        for i, img in enumerate(selected):
            out = safe_output_path(f"page_{i+1}", fmt)
            img.save(str(out), "PNG" if fmt == "png" else "JPEG", quality=92)
            results.append(out)
        return results

    def _convert():
        try:
            return _convert_pymupdf()
        except Exception:
            return _convert_pdf2image()

    return await loop.run_in_executor(None, _convert)


# ---------------------------------------------------------------------------
# 10. Rotate PDF
# ---------------------------------------------------------------------------
async def rotate_pdf(pdf_path: Path, angle: int = 90, pages: Optional[str] = None) -> Path:
    """Rotate pages by 90/180/270. pages=None means all."""
    if angle not in (90, 180, 270):
        raise ValueError("Angle must be 90, 180 or 270")
    out = safe_output_path(f"rotate_{angle}", "pdf")
    loop = asyncio.get_running_loop()

    def _rotate():
        reader = PdfReader(str(pdf_path))
        total = len(reader.pages)
        indices = set(_parse_page_ranges(pages, total)) if pages else set(range(total))
        writer = PdfWriter()
        for i, page in enumerate(reader.pages):
            if i in indices:
                page.rotate(angle)
            writer.add_page(page)
        with open(out, "wb") as f:
            writer.write(f)
        return out

    return await loop.run_in_executor(None, _rotate)


# ---------------------------------------------------------------------------
# 11. Organize PDF (reorder + optional rotate/delete/duplicate)
# ---------------------------------------------------------------------------
async def organize_pdf(pdf_path: Path, page_order: list[int], rotations: Optional[dict[int, int]] = None) -> Path:
    """
    Rebuild PDF according to new 0-based page order.
    rotations: {page_index_in_new_order: angle}
    """
    out = safe_output_path("organize", "pdf")
    loop = asyncio.get_running_loop()

    def _organize():
        reader = PdfReader(str(pdf_path))
        total = len(reader.pages)
        writer = PdfWriter()
        for new_idx, old_idx in enumerate(page_order):
            if not (0 <= old_idx < total):
                continue
            page = reader.pages[old_idx]
            if rotations and new_idx in rotations:
                page.rotate(rotations[new_idx])
            writer.add_page(page)
        with open(out, "wb") as f:
            writer.write(f)
        return out

    return await loop.run_in_executor(None, _organize)


# ---------------------------------------------------------------------------
# 14. Watermark
# ---------------------------------------------------------------------------
async def watermark_pdf(
    pdf_path: Path,
    text: Optional[str] = None,
    image_path: Optional[Path] = None,
    opacity: float = 0.3,
    rotation: int = 45,
    font_size: int = 40,
    position: str = "center",
) -> Path:
    """
    Add text or image watermark.
    Uses PIL-rendered stamp image so it works on all PyMuPDF versions
    (no Shape.finish opacity / insert_text rotate issues).
    """
    out = safe_output_path("watermark", "pdf")
    loop = asyncio.get_running_loop()

    try:
        opacity = max(0.05, min(1.0, float(opacity)))
    except (TypeError, ValueError):
        opacity = 0.3
    try:
        rot = int(float(rotation))
    except (TypeError, ValueError):
        rot = 45
    try:
        fsize = int(float(font_size))
    except (TypeError, ValueError):
        fsize = 40
    fsize = max(12, min(120, fsize))

    def _make_text_stamp(page_w: float, page_h: float) -> Path:
        """Render rotated semi-transparent text to a PNG stamp."""
        from PIL import ImageDraw, ImageFont

        # High-res stamp roughly page-sized
        scale = 2
        w, h = max(200, int(page_w * scale)), max(200, int(page_h * scale))
        img = Image.new("RGBA", (w, h), (255, 255, 255, 0))
        draw = ImageDraw.Draw(img)

        # Try a common font; fallback to default
        font = None
        for name in (
            "arial.ttf",
            "Arial.ttf",
            "DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
        ):
            try:
                font = ImageFont.truetype(name, size=max(16, int(fsize * scale * 0.8)))
                break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()

        alpha = int(255 * opacity)
        color = (80, 80, 80, alpha)
        msg = str(text)

        # Draw text in center then rotate
        tw, th = draw.textbbox((0, 0), msg, font=font)[2:]
        tmp = Image.new("RGBA", (max(tw + 40, 100), max(th + 40, 50)), (255, 255, 255, 0))
        d2 = ImageDraw.Draw(tmp)
        d2.text((20, 10), msg, font=font, fill=color)
        tmp = tmp.rotate(-rot, expand=True, resample=Image.BICUBIC)

        # Paste centered
        px = (w - tmp.width) // 2
        py = (h - tmp.height) // 2
        img.paste(tmp, (px, py), tmp)

        stamp = TEMP_DIR / f"wm_stamp_{uuid.uuid4().hex}.png"
        img.save(stamp, "PNG")
        return stamp

    def _watermark():
        doc = pymupdf.open(str(pdf_path))
        stamp_path = None
        try:
            for page in doc:
                rect = page.rect
                if text:
                    if stamp_path is None or not stamp_path.exists():
                        stamp_path = _make_text_stamp(rect.width, rect.height)
                    # Full-page stamp (transparent outside text)
                    try:
                        page.insert_image(rect, filename=str(stamp_path), keep_proportion=False)
                    except TypeError:
                        page.insert_image(rect, filename=str(stamp_path))

                if image_path and Path(image_path).exists():
                    # Apply opacity by blending watermark image with alpha
                    try:
                        wm = Image.open(image_path).convert("RGBA")
                        a = wm.split()[3]
                        a = a.point(lambda p: int(p * opacity))
                        wm.putalpha(a)
                        tmp_img = TEMP_DIR / f"wm_img_{uuid.uuid4().hex}.png"
                        wm.save(tmp_img, "PNG")
                        img_rect = pymupdf.Rect(
                            rect.width * 0.25,
                            rect.height * 0.25,
                            rect.width * 0.75,
                            rect.height * 0.75,
                        )
                        page.insert_image(img_rect, filename=str(tmp_img))
                        tmp_img.unlink(missing_ok=True)
                    except Exception:
                        img_rect = pymupdf.Rect(
                            rect.width * 0.25,
                            rect.height * 0.25,
                            rect.width * 0.75,
                            rect.height * 0.75,
                        )
                        page.insert_image(img_rect, filename=str(image_path))

            doc.save(str(out), garbage=3, deflate=True)
        finally:
            doc.close()
            if stamp_path:
                stamp_path.unlink(missing_ok=True)
        return out

    return await loop.run_in_executor(None, _watermark)


# ---------------------------------------------------------------------------
# 15. Protect (password)
# ---------------------------------------------------------------------------
async def protect_pdf(pdf_path: Path, user_password: str, owner_password: Optional[str] = None) -> Path:
    """Encrypt PDF with password. Requires password to open."""
    out = safe_output_path("protected", "pdf")
    loop = asyncio.get_running_loop()
    owner = owner_password or user_password

    def _protect():
        reader = PdfReader(str(pdf_path))
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        writer.encrypt(user_password=user_password, owner_password=owner, algorithm="AES-256")
        with open(out, "wb") as f:
            writer.write(f)
        return out

    return await loop.run_in_executor(None, _protect)


# ---------------------------------------------------------------------------
# 16. Unlock
# ---------------------------------------------------------------------------
async def unlock_pdf(pdf_path: Path, password: str) -> Path:
    """Decrypt PDF when correct password is provided."""
    out = safe_output_path("unlocked", "pdf")
    loop = asyncio.get_running_loop()

    def _unlock():
        reader = PdfReader(str(pdf_path))
        if reader.is_encrypted:
            if not reader.decrypt(password):
                raise ValueError("Incorrect password")
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        with open(out, "wb") as f:
            writer.write(f)
        return out

    return await loop.run_in_executor(None, _unlock)


# ---------------------------------------------------------------------------
# 17. Repair
# ---------------------------------------------------------------------------
async def repair_pdf(pdf_path: Path) -> Path:
    """Attempt to repair a damaged PDF using PyMuPDF + pikepdf."""
    out = safe_output_path("repaired", "pdf")
    loop = asyncio.get_running_loop()

    def _repair():
        # First try PyMuPDF
        try:
            doc = pymupdf.open(str(pdf_path))
            doc.save(str(out), garbage=4, deflate=True, clean=True)
            doc.close()
            # Validate
            test = pymupdf.open(str(out))
            if test.page_count == 0:
                raise RuntimeError("Empty after repair")
            test.close()
            return out
        except Exception:
            pass
        # Fallback pikepdf
        import pikepdf
        with pikepdf.open(str(pdf_path), allow_overwriting_input=False) as pdf:
            pdf.save(str(out))
        return out

    return await loop.run_in_executor(None, _repair)


# ---------------------------------------------------------------------------
# 18. Metadata
# ---------------------------------------------------------------------------
async def get_metadata(pdf_path: Path) -> dict:
    loop = asyncio.get_running_loop()

    def _get():
        reader = PdfReader(str(pdf_path))
        meta = reader.metadata or {}
        return {
            "title": meta.get("/Title", ""),
            "author": meta.get("/Author", ""),
            "subject": meta.get("/Subject", ""),
            "keywords": meta.get("/Keywords", ""),
            "creator": meta.get("/Creator", ""),
            "producer": meta.get("/Producer", ""),
            "pages": len(reader.pages),
        }

    return await loop.run_in_executor(None, _get)


async def set_metadata(pdf_path: Path, meta: dict) -> Path:
    out = safe_output_path("metadata", "pdf")
    loop = asyncio.get_running_loop()

    def _set():
        reader = PdfReader(str(pdf_path))
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        writer.add_metadata({
            "/Title": meta.get("title", ""),
            "/Author": meta.get("author", ""),
            "/Subject": meta.get("subject", ""),
            "/Keywords": meta.get("keywords", ""),
            "/Creator": meta.get("creator", "MJPDF"),
        })
        with open(out, "wb") as f:
            writer.write(f)
        return out

    return await loop.run_in_executor(None, _set)
