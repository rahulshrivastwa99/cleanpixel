import io
import zipfile
import mimetypes
from pathlib import Path
from typing import List

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from cleaner import clean_image

# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(
    title="CleanPixel API",
    description="Losslessly strip EXIF, IPTC, XMP, and C2PA metadata from images",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Serve frontend ─────────────────────────────────────────────────────────────
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    index = FRONTEND_DIR / "index.html"
    if not index.exists():
        return HTMLResponse("<h1>Frontend not found</h1>", status_code=404)
    return HTMLResponse(index.read_text(encoding="utf-8"))


@app.get("/health")
async def health():
    return {"status": "ok", "service": "CleanPixel"}


# ── Single image clean ─────────────────────────────────────────────────────────
@app.post("/api/clean")
async def clean_single(file: UploadFile = File(...)):
    """
    Accept a single image upload, strip all metadata, return the cleaned image.
    Processing is 100% in-memory — nothing is written to disk.
    """
    _validate_file(file)
    raw = await file.read()

    if len(raw) > 25 * 1024 * 1024:  # 25 MB limit
        raise HTTPException(status_code=413, detail="File exceeds 25 MB limit")

    try:
        cleaned, info = clean_image(raw, file.content_type or "")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    original_size = len(raw)
    cleaned_size = len(cleaned)

    # Determine output MIME / extension
    out_mime = _out_mime(file.content_type or "", raw)
    ext = _ext(out_mime)
    stem = Path(file.filename or "image").stem
    out_name = f"{stem}_cleaned{ext}"

    # RFC 5987 — encode filename as UTF-8 percent-encoded for header safety
    safe_name = out_name.encode("utf-8").decode("ascii", errors="replace")
    utf8_name = out_name.encode("utf-8").hex()
    # Use ascii fallback for filename*, proper RFC 5987 quoting
    import urllib.parse
    quoted_name = urllib.parse.quote(out_name, safe="")
    content_disp = f"attachment; filename*=UTF-8''{quoted_name}"

    # Strip labels — ensure all ascii for headers
    strips_safe = ", ".join(
        s.encode("ascii", errors="replace").decode("ascii")
        for s in info.get("strips", [])
    )

    headers = {
        "X-Original-Size": str(original_size),
        "X-Cleaned-Size": str(cleaned_size),
        "X-EXIF-Found": str(info.get("exif_found", False)).lower(),
        "X-C2PA-Found": str(info.get("c2pa_found", False)).lower(),
        "X-IPTC-Found": str(info.get("iptc_found", False)).lower(),
        "X-Strips": strips_safe,
        "Content-Disposition": content_disp,
        "Access-Control-Expose-Headers": (
            "X-Original-Size, X-Cleaned-Size, X-EXIF-Found, "
            "X-C2PA-Found, X-IPTC-Found, X-Strips, Content-Disposition"
        ),
    }

    return StreamingResponse(
        io.BytesIO(cleaned),
        media_type=out_mime,
        headers=headers,
    )


# ── Batch clean (up to 10 files → ZIP) ────────────────────────────────────────
@app.post("/api/clean-batch")
async def clean_batch(files: List[UploadFile] = File(...)):
    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 files per batch")

    zip_buf = io.BytesIO()
    results = []

    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            _validate_file(f)
            raw = await f.read()
            if len(raw) > 25 * 1024 * 1024:
                results.append({"name": f.filename, "error": "exceeds 25 MB"})
                continue
            try:
                cleaned, info = clean_image(raw, f.content_type or "")
                out_mime = _out_mime(f.content_type or "", raw)
                ext = _ext(out_mime)
                stem = Path(f.filename or "image").stem
                out_name = f"{stem}_cleaned{ext}"
                zf.writestr(out_name, cleaned)
                results.append({
                    "name": f.filename,
                    "out_name": out_name,
                    "original_size": len(raw),
                    "cleaned_size": len(cleaned),
                    "exif_found": info.get("exif_found", False),
                    "c2pa_found": info.get("c2pa_found", False),
                    "strips": info.get("strips", []),
                })
            except Exception as e:
                results.append({"name": f.filename, "error": str(e)})

    zip_buf.seek(0)
    headers = {
        "Content-Disposition": 'attachment; filename="cleanpixel_batch.zip"',
        "Access-Control-Expose-Headers": "Content-Disposition",
    }
    return StreamingResponse(zip_buf, media_type="application/zip", headers=headers)


# ── Helpers ────────────────────────────────────────────────────────────────────
_ALLOWED_TYPES = {
    "image/jpeg", "image/jpg", "image/png", "image/webp",
}
_ALLOWED_MAGIC = [
    (b"\xff\xd8", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
]


def _validate_file(f: UploadFile):
    ct = (f.content_type or "").lower()
    if ct and ct not in _ALLOWED_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported type '{ct}'. Use JPEG, PNG, or WEBP.",
        )


def _out_mime(content_type: str, data: bytes) -> str:
    ct = content_type.lower()
    if "png" in ct or data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if "webp" in ct or (data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
        return "image/webp"
    return "image/jpeg"


def _ext(mime: str) -> str:
    return {
        "image/png": ".png",
        "image/webp": ".webp",
    }.get(mime, ".jpg")


# ── Dev entry point ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
