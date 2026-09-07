"""
API routes for all MJPDF PDF tools.
Every endpoint performs real conversion / operation and returns a downloadable file.
"""
import zipfile
from pathlib import Path


def _pdf_response(path: Path, filename: str, background=None, headers=None):
    if path.suffix.lower() == ".pdf":
        _mark_pdf_ownership(path)
    from fastapi.responses import FileResponse
    kw = {"path": str(path), "filename": filename, "media_type": "application/pdf"}
    if background is not None:
        kw["background"] = background
    if headers:
        kw["headers"] = headers
    return FileResponse(**kw)

def _mark_pdf_ownership(path: Path) -> None:
    """No visual watermark on outputs."""
    return


from typing import Optional, List

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse

from ..services import converters as cv
from ..utils.security import save_upload, cleanup_file, sanitize_filename
from ..config import TEMP_DIR

router = APIRouter(prefix="/api", tags=["tools"])


def _schedule_cleanup(background_tasks: BackgroundTasks, *paths):
    for p in paths:
        if p:
            background_tasks.add_task(cleanup_file, p)


# ---------------------------------------------------------------------------
# 2. Word → PDF
# ---------------------------------------------------------------------------
@router.post("/word-to-pdf")
async def word_to_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    path, original = await save_upload(file, "word")
    try:
        out = await cv.word_to_pdf(path)
        _schedule_cleanup(background_tasks, path, out)
        return FileResponse(
            path=out,
            filename=f"{Path(original).stem}.pdf",
            media_type="application/pdf",
            background=background_tasks,
        )
    except Exception as e:
        cleanup_file(path)
        raise HTTPException(status_code=500, detail=f"Conversion failed: {str(e)}")


# ---------------------------------------------------------------------------
# PPTX → PDF
# ---------------------------------------------------------------------------
@router.post("/pptx-to-pdf")
async def pptx_to_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    path, original = await save_upload(file, "pptx")
    try:
        out = await cv.pptx_to_pdf(path)
        _schedule_cleanup(background_tasks, path, out)
        return FileResponse(
            path=out,
            filename=f"{Path(original).stem}.pdf",
            media_type="application/pdf",
            background=background_tasks,
        )
    except Exception as e:
        cleanup_file(path)
        raise HTTPException(status_code=500, detail=f"Conversion failed: {str(e)}")


# ---------------------------------------------------------------------------
# 5. Compress PDF
# ---------------------------------------------------------------------------
@router.post("/compress-pdf")
async def compress_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    level: str = Form("medium"),
):
    if level not in ("low", "medium", "high"):
        raise HTTPException(status_code=400, detail="level must be low|medium|high")
    path, original = await save_upload(file, "pdf")
    try:
        out, stats = await cv.compress_pdf(path, level)
        _schedule_cleanup(background_tasks, path, out)
        # Return file + stats via headers
        headers = {
            "X-Original-Size": str(stats["original_size"]),
            "X-Compressed-Size": str(stats["compressed_size"]),
            "X-Reduction-Percent": str(stats["reduction_percent"]),
        }
        return FileResponse(
            path=out,
            filename=f"{Path(original).stem}_compressed.pdf",
            media_type="application/pdf",
            headers=headers,
            background=background_tasks,
        )
    except Exception as e:
        cleanup_file(path)
        raise HTTPException(status_code=500, detail=f"Compression failed: {str(e)}")


# ---------------------------------------------------------------------------
# 6. Merge PDF
# ---------------------------------------------------------------------------
@router.post("/merge-pdf")
async def merge_pdf(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
):
    if len(files) < 2:
        raise HTTPException(status_code=400, detail="At least 2 PDF files required")
    paths = []
    try:
        for f in files:
            p, _ = await save_upload(f, "pdf")
            paths.append(p)
        out = await cv.merge_pdfs(paths)
        _schedule_cleanup(background_tasks, *paths, out)
        return FileResponse(
            path=out,
            filename="merged.pdf",
            media_type="application/pdf",
            background=background_tasks,
        )
    except Exception as e:
        for p in paths:
            cleanup_file(p)
        raise HTTPException(status_code=500, detail=f"Merge failed: {str(e)}")


# ---------------------------------------------------------------------------
# 7. Split / Extract / Delete
# ---------------------------------------------------------------------------
@router.post("/extract-pages")
async def extract_pages(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    pages: str = Form(...),
):
    path, original = await save_upload(file, "pdf")
    try:
        out = await cv.extract_pages(path, pages)
        _schedule_cleanup(background_tasks, path, out)
        return FileResponse(
            path=out,
            filename=f"{Path(original).stem}_extracted.pdf",
            media_type="application/pdf",
            background=background_tasks,
        )
    except Exception as e:
        cleanup_file(path)
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/delete-pages")
async def delete_pages(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    pages: str = Form(...),
):
    path, original = await save_upload(file, "pdf")
    try:
        out = await cv.delete_pages(path, pages)
        _schedule_cleanup(background_tasks, path, out)
        return FileResponse(
            path=out,
            filename=f"{Path(original).stem}_deleted.pdf",
            media_type="application/pdf",
            background=background_tasks,
        )
    except Exception as e:
        cleanup_file(path)
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/split-pdf")
async def split_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    path, original = await save_upload(file, "pdf")
    try:
        outs = await cv.split_every_page(path)
        # Zip them
        zip_path = TEMP_DIR / f"split_{Path(original).stem}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, p in enumerate(outs):
                zf.write(p, f"page_{i+1}.pdf")
                cleanup_file(p)
        cleanup_file(path)
        _schedule_cleanup(background_tasks, zip_path)
        return FileResponse(
            path=zip_path,
            filename=f"{Path(original).stem}_pages.zip",
            media_type="application/zip",
            background=background_tasks,
        )
    except Exception as e:
        cleanup_file(path)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# 8 / 9. Images → PDF / PDF → Images
# ---------------------------------------------------------------------------
@router.post("/images-to-pdf")
async def images_to_pdf(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    page_size: str = Form("A4"),
    orientation: str = Form("portrait"),
):
    paths = []
    try:
        for f in files:
            p, _ = await save_upload(f, "image")
            paths.append(p)
        out = await cv.images_to_pdf(paths, page_size, orientation)
        _schedule_cleanup(background_tasks, *paths, out)
        return FileResponse(
            path=out,
            filename="images.pdf",
            media_type="application/pdf",
            background=background_tasks,
        )
    except Exception as e:
        for p in paths:
            cleanup_file(p)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pdf-to-images")
async def pdf_to_images(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    format: str = Form("jpg"),
    dpi: int = Form(150),
    pages: Optional[str] = Form(None),
):
    if format not in ("jpg", "png"):
        raise HTTPException(status_code=400, detail="format must be jpg or png")
    path, original = await save_upload(file, "pdf")
    try:
        outs = await cv.pdf_to_images(path, format, dpi, pages)
        zip_path = TEMP_DIR / f"images_{Path(original).stem}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, p in enumerate(outs):
                zf.write(p, f"page_{i+1}.{format}")
                cleanup_file(p)
        cleanup_file(path)
        _schedule_cleanup(background_tasks, zip_path)
        return FileResponse(
            path=zip_path,
            filename=f"{Path(original).stem}_images.zip",
            media_type="application/zip",
            background=background_tasks,
        )
    except Exception as e:
        cleanup_file(path)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# 10. Rotate
# ---------------------------------------------------------------------------
@router.post("/rotate-pdf")
async def rotate_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    angle: int = Form(90),
    pages: Optional[str] = Form(None),
):
    path, original = await save_upload(file, "pdf")
    try:
        out = await cv.rotate_pdf(path, angle, pages)
        _schedule_cleanup(background_tasks, path, out)
        return FileResponse(
            path=out,
            filename=f"{Path(original).stem}_rotated.pdf",
            media_type="application/pdf",
            background=background_tasks,
        )
    except Exception as e:
        cleanup_file(path)
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# 11. Organize (simplified: reorder via page list)
# ---------------------------------------------------------------------------
@router.post("/organize-pdf")
async def organize_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    page_order: str = Form(...),  # comma-separated 1-based pages, e.g. "3,1,2,4"
):
    path, original = await save_upload(file, "pdf")
    try:
        order = [int(x.strip()) - 1 for x in page_order.split(",") if x.strip()]
        out = await cv.organize_pdf(path, order)
        _schedule_cleanup(background_tasks, path, out)
        return FileResponse(
            path=out,
            filename=f"{Path(original).stem}_organized.pdf",
            media_type="application/pdf",
            background=background_tasks,
        )
    except Exception as e:
        cleanup_file(path)
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# 14. Watermark
# ---------------------------------------------------------------------------
@router.post("/watermark-pdf")
async def watermark_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    text: Optional[str] = Form(None),
    opacity: Optional[str] = Form("0.3"),
    rotation: Optional[str] = Form("45"),
    font_size: Optional[str] = Form("40"),
    image: Optional[UploadFile] = File(None),
):
    path, original = await save_upload(file, "pdf")
    img_path = None
    try:
        if image and image.filename:
            img_path, _ = await save_upload(image, "image")

        wm_text = (text or "").strip() or None
        if not wm_text and not img_path:
            raise HTTPException(status_code=400, detail="Provide watermark text (e.g. CONFIDENTIAL)")

        try:
            op = float(opacity) if opacity not in (None, "") else 0.3
        except ValueError:
            op = 0.3
        try:
            rot = int(float(rotation)) if rotation not in (None, "") else 45
        except ValueError:
            rot = 45
        try:
            fsz = int(float(font_size)) if font_size not in (None, "") else 40
        except ValueError:
            fsz = 40

        out = await cv.watermark_pdf(
            path,
            text=wm_text,
            image_path=img_path,
            opacity=op,
            rotation=rot,
            font_size=fsz,
        )
        _schedule_cleanup(background_tasks, path, img_path, out)
        return FileResponse(
            path=out,
            filename=f"{Path(original).stem}_watermarked.pdf",
            media_type="application/pdf",
            background=background_tasks,
        )
    except HTTPException:
        cleanup_file(path)
        cleanup_file(img_path)
        raise
    except Exception as e:
        cleanup_file(path)
        cleanup_file(img_path)
        raise HTTPException(status_code=500, detail=f"Watermark failed: {e}")


# ---------------------------------------------------------------------------
# 15. Protect
# ---------------------------------------------------------------------------
@router.post("/protect-pdf")
async def protect_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    password: str = Form(...),
):
    if len(password) < 1:
        raise HTTPException(status_code=400, detail="Password required")
    path, original = await save_upload(file, "pdf")
    try:
        out = await cv.protect_pdf(path, password)
        _schedule_cleanup(background_tasks, path, out)
        return FileResponse(
            path=out,
            filename=f"{Path(original).stem}_protected.pdf",
            media_type="application/pdf",
            background=background_tasks,
        )
    except Exception as e:
        cleanup_file(path)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# 16. Unlock
# ---------------------------------------------------------------------------
@router.post("/unlock-pdf")
async def unlock_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    password: str = Form(...),
):
    path, original = await save_upload(file, "pdf")
    try:
        out = await cv.unlock_pdf(path, password)
        _schedule_cleanup(background_tasks, path, out)
        return FileResponse(
            path=out,
            filename=f"{Path(original).stem}_unlocked.pdf",
            media_type="application/pdf",
            background=background_tasks,
        )
    except ValueError as e:
        cleanup_file(path)
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        cleanup_file(path)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# 17. Repair

