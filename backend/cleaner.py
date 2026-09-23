import struct
import zlib
import io
from typing import Tuple

# ──────────────────────────────────────────────────────────────────────────────
#  JPEG  ─  Raw-byte surgical strip (zero re-compression, zero quality loss)
# ──────────────────────────────────────────────────────────────────────────────

# Markers whose segments we STRIP (metadata containers)
_JPEG_STRIP_MARKERS = {
    0xE0,  # APP0  – JFIF
    0xE1,  # APP1  – EXIF / XMP
    0xE2,  # APP2  – ICC profile / FlashPix
    0xE3,  # APP3
    0xE4,  # APP4
    0xE5,  # APP5
    0xE6,  # APP6
    0xE7,  # APP7
    0xE8,  # APP8
    0xE9,  # APP9
    0xEA,  # APP10
    0xEB,  # APP11 – C2PA / JUMBF Content Credentials  ← LinkedIn "(cr)"
    0xEC,  # APP12
    0xED,  # APP13 – IPTC / Photoshop
    0xEE,  # APP14 – Adobe
    0xEF,  # APP15
    0xFE,  # COM   – Comment
}

# Markers that have NO length field (standalone / entropy coded)
_JPEG_STANDALONE = {0xD8, 0xD9, 0x01}  # SOI, EOI, TEM
_JPEG_RST = set(range(0xD0, 0xD8))     # RST0–RST7


def clean_jpeg(data: bytes) -> Tuple[bytes, dict]:
    """
    Surgically remove all metadata segments from a JPEG file.
    Returns (cleaned_bytes, info_dict).
    The DCT image data is copied byte-for-byte – zero re-encoding.
    """
    if len(data) < 2 or data[0:2] != b"\xff\xd8":
        raise ValueError("Not a valid JPEG file")

    out = io.BytesIO()
    out.write(b"\xff\xd8")  # SOI – always first

    pos = 2
    info = {"exif_found": False, "c2pa_found": False, "iptc_found": False,
            "strips": []}
    length = len(data)

    while pos < length:
        # Find next 0xFF marker byte
        if data[pos] != 0xFF:
            pos += 1
            continue

        # Skip padding 0xFF bytes
        while pos < length and data[pos] == 0xFF:
            pos += 1

        if pos >= length:
            break

        marker = data[pos]
        pos += 1

        # ── Standalone markers (no length field) ──────────────────────────
        if marker in _JPEG_STANDALONE or marker in _JPEG_RST:
            if marker == 0xD9:  # EOI
                out.write(b"\xff\xd9")
            # RST markers inside scan data are handled below
            continue

        # ── SOS – start of scan: copy everything from here to EOI ─────────
        if marker == 0xDA:
            sos_len = struct.unpack(">H", data[pos:pos+2])[0]
            out.write(b"\xff\xda")
            out.write(data[pos:pos + sos_len])
            pos += sos_len
            # Copy raw entropy-coded segment until EOI
            eoi_pos = data.rfind(b"\xff\xd9")
            if eoi_pos == -1:
                out.write(data[pos:])
            else:
                out.write(data[pos:eoi_pos])
                out.write(b"\xff\xd9")
            break  # Done

        # ── Segments with a 2-byte length field ───────────────────────────
        if pos + 2 > length:
            break
        seg_len = struct.unpack(">H", data[pos:pos+2])[0]
        seg_end = pos + seg_len  # length includes itself (2 bytes)

        if marker in _JPEG_STRIP_MARKERS:
            # Record what we stripped
            label = {
                0xE1: "EXIF/XMP (APP1)",
                0xEB: "C2PA/JUMBF (APP11)",
                0xED: "IPTC/Photoshop (APP13)",
            }.get(marker, f"APP{marker - 0xE0} (0xFF{marker:02X})")
            info["strips"].append(label)
            if marker == 0xE1:
                info["exif_found"] = True
            if marker == 0xEB:
                info["c2pa_found"] = True
            if marker == 0xED:
                info["iptc_found"] = True
            # Skip this segment entirely
            pos = seg_end
        else:
            # Keep segment verbatim (DQT, DHT, SOF, DRI, etc.)
            out.write(b"\xff")
            out.write(bytes([marker]))
            out.write(data[pos:seg_end])
            pos = seg_end

    return out.getvalue(), info


# ──────────────────────────────────────────────────────────────────────────────
#  PNG  ─  Chunk-level surgery (100% pixel-identical output)
# ──────────────────────────────────────────────────────────────────────────────

PNG_SIG = b"\x89PNG\r\n\x1a\n"

# Chunks that carry metadata – strip all of these
_PNG_STRIP_TYPES = {
    b"tEXt",  # Plain text metadata
    b"zTXt",  # Compressed text metadata
    b"iTXt",  # International UTF-8 text (XMP lives here)
    b"eXIf",  # EXIF data
    b"c2pa",  # C2PA / Content Credentials
    b"JUMB",  # JUMBF box (wraps C2PA)
    b"caBX",  # C2PA box variant
    b"uuid",  # UUID-based metadata (XMP)
    b"sCAL",  # Physical scale (minor, strip for cleanliness)
    b"oFFs",  # Image offset
    b"pCAL",  # Calibration
    b"hIST",  # Histogram
    b"tIME",  # Timestamp
    b"sPLT",  # Suggested palette
}

# Chunks we always keep
_PNG_KEEP_TYPES = {
    b"IHDR",  # Image header — MUST keep
    b"IDAT",  # Image data — MUST keep
    b"IEND",  # Image end — MUST keep
    b"PLTE",  # Palette (required for indexed PNGs)
    b"tRNS",  # Transparency
    b"gAMA",  # Gamma (affects rendering)
    b"cHRM",  # Chromaticity
    b"sRGB",  # sRGB colorspace
    b"bKGD",  # Background colour
    b"sBIT",  # Significant bits
    b"pHYs",  # Physical pixel dimensions (DPI)
    b"ICCN",  # ICC profile name
    b"iCCP",  # Embedded ICC profile (keep for color accuracy)
}


def _png_chunk_crc(chunk_type: bytes, data: bytes) -> bytes:
    return struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)


def clean_png(data: bytes) -> Tuple[bytes, dict]:
    """
    Parse PNG chunk structure and rebuild with only essential chunks.
    Returns (cleaned_bytes, info_dict).
    """
    if data[:8] != PNG_SIG:
        raise ValueError("Not a valid PNG file")

    out = io.BytesIO()
    out.write(PNG_SIG)

    pos = 8
    length = len(data)
    info = {"exif_found": False, "c2pa_found": False, "strips": []}

    while pos + 12 <= length:
        chunk_len = struct.unpack(">I", data[pos:pos+4])[0]
        chunk_type = data[pos+4:pos+8]
        chunk_data = data[pos+8:pos+8+chunk_len]
        # CRC is 4 bytes after chunk data
        pos += 12 + chunk_len  # 4 (len) + 4 (type) + chunk_len + 4 (crc)

        if chunk_type in _PNG_STRIP_TYPES:
            info["strips"].append(chunk_type.decode("latin-1", errors="replace"))
            if chunk_type == b"eXIf":
                info["exif_found"] = True
            if chunk_type in (b"c2pa", b"JUMB", b"caBX"):
                info["c2pa_found"] = True
            continue  # Drop this chunk

        # Keep this chunk — re-emit with correct CRC
        crc = _png_chunk_crc(chunk_type, chunk_data)
        out.write(struct.pack(">I", chunk_len))
        out.write(chunk_type)
        out.write(chunk_data)
        out.write(crc)

        if chunk_type == b"IEND":
            break

    return out.getvalue(), info


# ──────────────────────────────────────────────────────────────────────────────
#  WEBP  ─  Pillow re-save (lossless for lossless WEBP; near-lossless for lossy)
# ──────────────────────────────────────────────────────────────────────────────

def clean_webp(data: bytes) -> Tuple[bytes, dict]:
    """
    Re-save WEBP using Pillow without EXIF/metadata.
    For lossless WEBP this is pixel-identical.
    For lossy WEBP we use quality=100 to minimise any re-encode loss.
    """
    from PIL import Image
    img = Image.open(io.BytesIO(data))

    info = {
        "exif_found": bool(img.info.get("exif")),
        "c2pa_found": False,
        "strips": ["EXIF", "XMP"] if img.info.get("exif") else [],
    }

    buf = io.BytesIO()
    # Detect if source is lossless
    is_lossless = img.info.get("lossless", False)
    if is_lossless:
        img.save(buf, format="WEBP", lossless=True, exif=b"", xmp=b"")
    else:
        img.save(buf, format="WEBP", quality=100, method=6, exif=b"", xmp=b"")

    return buf.getvalue(), info


# ──────────────────────────────────────────────────────────────────────────────
#  Dispatcher
# ──────────────────────────────────────────────────────────────────────────────

def clean_image(data: bytes, content_type: str) -> Tuple[bytes, dict]:
    """
    Route to the correct cleaner based on MIME type or magic bytes.
    Returns (cleaned_bytes, info_dict).
    """
    ct = content_type.lower()

    # Detect by magic bytes (more reliable than Content-Type header)
    if data[:2] == b"\xff\xd8":
        return clean_jpeg(data)
    if data[:8] == PNG_SIG:
        return clean_png(data)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return clean_webp(data)

    # Fallback: trust MIME
    if "jpeg" in ct or "jpg" in ct:
        return clean_jpeg(data)
    if "png" in ct:
        return clean_png(data)
    if "webp" in ct:
        return clean_webp(data)

    raise ValueError(f"Unsupported file type: {content_type}")
