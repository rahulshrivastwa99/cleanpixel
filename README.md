# CleanPixel 🛡️

**Lossless Image Metadata & C2PA Scrubber**

Strip all EXIF, XMP, IPTC, and C2PA (LinkedIn "(cr)" AI stamp) metadata from PNG, JPG, and WEBP images — without losing a single pixel of quality.

---

## Features

- 🔬 **Lossless JPEG stripping** — Raw byte-level surgery. Zero re-compression. Identical DCT coefficients.
- 🧩 **Lossless PNG stripping** — Chunk-level rebuild. Only IHDR/IDAT/IEND survive.
- 🤖 **C2PA / JUMBF removal** — Kills LinkedIn's "(cr)" AI-generation badge (APP11/c2pa chunks).
- 📦 **Batch support** — Up to 10 files at once, with ZIP download.
- 📋 **Copy to Clipboard** — Paste directly into LinkedIn / Canva without saving to disk.
- 🔒 **100% ephemeral** — Nothing written to disk. All in-memory. Files gone after response.

---

## Project Structure

```
cleanPixel/
├── backend/
│   ├── main.py           # FastAPI application
│   ├── cleaner.py        # Core stripping engine
│   └── requirements.txt
├── frontend/
│   └── index.html        # Single-page app (Tailwind CDN + Vanilla JS)
├── render.yaml           # Render.com deploy config
└── README.md
```

---

## Run Locally

### Requirements
- Python 3.10+

### Steps

```bash
# 1. Clone or open the folder
cd cleanPixel

# 2. Install dependencies
pip install -r backend/requirements.txt

# 3. Start the server
cd backend
python main.py
```

Open **http://localhost:8000** in your browser.

---

## Deploy on Render (Free Tier — 1 Click)

### Step 1: Push to GitHub
```bash
# From d:\cleanPixel
git init
git add .
git commit -m "Initial commit: CleanPixel"
git remote add origin https://github.com/YOUR_USERNAME/cleanpixel.git
git push -u origin main
```

### Step 2: Deploy on Render
1. Go to **https://render.com** → Sign up / Log in
2. Click **"New +"** → **"Web Service"**
3. Connect your GitHub repo
4. Render will auto-detect `render.yaml` — hit **"Create Web Service"**

That's it. Your app will be live at `https://cleanpixel.onrender.com` (or similar).

**Render Settings (if configuring manually):**
| Setting | Value |
|---|---|
| Environment | Python |
| Build Command | `pip install -r backend/requirements.txt` |
| Start Command | `cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT` |
| Health Check Path | `/health` |

> **Note:** Free tier sleeps after 15 min of inactivity. Upgrade to Starter ($7/mo) for always-on.

---

## Day-to-Day Usage

### LinkedIn "(cr)" Badge Removal

1. Generate your image with ChatGPT / DALL-E
2. Download the image (it has C2PA metadata embedded)
3. Open CleanPixel → Drop the image → Download cleaned version
4. Upload the cleaned image to LinkedIn — no "(cr)" badge appears ✅

### Privacy (removing GPS / camera data before posting)

1. Drop any photo taken on your phone/camera
2. CleanPixel strips GPS coordinates, device model, serial number
3. Download and post safely

### Batch workflow

1. Drop up to 10 images at once
2. All process in parallel
3. Click **"Download All as ZIP"** — one download, all clean

---

## How C2PA Stripping Works

| Format | C2PA Location | How We Strip |
|---|---|---|
| JPEG | `APP11 (0xFF 0xEB)` marker — JUMBF box | Skip the entire APP11 segment in raw byte pass |
| PNG | `c2pa`, `JUMB`, `caBX` chunks | Whitelist-only chunk reconstruction |
| WEBP | Embedded in EXIF/XMP chunks | Pillow re-save without metadata |

**JPEG is truly lossless** — we never decode or re-encode the image. We copy the raw DCT entropy-coded scan data byte-for-byte.

---

## Verify with ExifTool

```bash
# Install: https://exiftool.org
exiftool your_original.jpg      # Shows all metadata
exiftool your_cleaned.jpg       # Should show nothing (or minimal)
```

Expected output after cleaning:
```
ExifTool Version Number         : 12.x
File Name                       : cleaned.jpg
File Size                       : 245 kB
File Type                       : JPEG
MIME Type                       : image/jpeg
Image Width                     : 1024
Image Height                    : 1024
(nothing else)
```
