# MJPDF — All-in-One PDF Tools

Professional online PDF tools: convert, compress, merge, split, protect, and more.

**Tagline:** Simple PDF Tools. Powerful Results.

---

## What you need

| Requirement | Required? | Notes |
|-------------|-----------|--------|
| **Python 3.10+** | Yes | 3.11 or 3.12 recommended |
| **pip** | Yes | Comes with Python |
| **LibreOffice** | Yes (for Word/PPT ↔ PDF) | Word → PDF, PDF → Word fallback, PowerPoint → PDF |
| **Ghostscript** | Optional | Better PDF compression if installed |
| **Poppler** | Optional | Only if pdf2image path is used; PyMuPDF works without it |
| Modern browser | Yes | Chrome, Edge, Firefox, Safari |

---

## 1. Install Python

### Windows
1. Download: https://www.python.org/downloads/
2. Run installer
3. **Check** “Add python.exe to PATH”
4. Open PowerShell and verify:

```powershell
python --version
pip --version
```

### macOS
```bash
# Option A: official installer from python.org
# Option B: Homebrew
brew install python
python3 --version
```

### Linux (Ubuntu/Debian)
```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv
python3 --version
```

---

## 2. Install LibreOffice (required for Office conversions)

### Windows
1. Download: https://www.libreoffice.org/download/download/
2. Install with default path  
   Typical path: `C:\Program Files\LibreOffice\program\soffice.exe`
3. Restart the terminal after install

### macOS
```bash
brew install --cask libreoffice
```

### Linux
```bash
sudo apt install libreoffice
# or
sudo dnf install libreoffice
```

---

## 3. Optional software (better quality / extras)

### Ghostscript (better Compress PDF)
- Windows: https://ghostscript.com/releases/gsdnld.html  
  Install, then ensure `gswin64c` is on PATH or under `C:\Program Files\gs\...`
- macOS: `brew install ghostscript`
- Linux: `sudo apt install ghostscript`

If Ghostscript is missing, MJPDF still compresses using PyMuPDF.

### Poppler (optional image pipeline)
- Windows: often not needed (PyMuPDF is used)
- macOS: `brew install poppler`
- Linux: `sudo apt install poppler-utils`

---

## 4. Download / open the project

1. Unzip `mjpdf.zip` (or clone the project)
2. Open a terminal **inside** the `mjpdf` folder

Example (Windows):

```powershell
cd C:\Users\YOUR_NAME\Desktop\fileora
```

Example (macOS/Linux):

```bash
cd ~/Desktop/fileora
```

---

## 5. Create virtual environment & install Python packages

### Windows (PowerShell)

```powershell
cd path\to\fileora
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
```

If activation is blocked:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\venv\Scripts\Activate.ps1
```

### macOS / Linux

```bash
cd path/to/fileora
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
```

---

## 6. Run the server

### Windows (PowerShell)

```powershell
.\venv\Scripts\Activate.ps1
$env:PYTHONPATH = $PWD
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

### macOS / Linux

```bash
source venv/bin/activate
export PYTHONPATH=$PWD
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

### Open in browser

```
http://localhost:8000
```

Same Wi‑Fi par phone se test:

```
http://YOUR_PC_IP:8000
```

(Example: `http://192.168.1.10:8000`)

Stop server: `Ctrl + C`

---

## 7. Typical Windows full setup (copy-paste)

```powershell
cd C:\Users\YOUR_NAME\Desktop\fileora
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
$env:PYTHONPATH = $PWD
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

Then open: http://localhost:8000  
Hard refresh if UI looks old: **Ctrl + F5**

---

## Project structure

```
mjpdf/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app + frontend routes
│   │   ├── config.py            # Paths, limits, LibreOffice detect
│   │   ├── routers/tools.py     # API endpoints
│   │   ├── services/converters.py
│   │   └── utils/security.py
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── about.html, contact.html, terms.html
│   ├── privacy-policy.html, cookie-policy.html
│   ├── robots.txt, sitemap.xml
│   └── static/                  # CSS, JS, logo
├── temp/ uploads/ outputs/      # Created at runtime
└── README.md
```

---

## Available tools (current)

| Tool | Route / API |
|------|-------------|
| Word to PDF | `/word-to-pdf` |
| PowerPoint to PDF | `/pptx-to-pdf` |
| Compress PDF | `/compress-pdf` |
| Merge PDF | `/merge-pdf` |
| Split PDF | `/split-pdf` |
| Extract Pages | `/extract-pages` |
| Delete Pages | `/delete-pages` |
| Images to PDF | `/images-to-pdf` |
| PDF to Images | `/pdf-to-images` |
| Rotate PDF | `/rotate-pdf` |
| Organize PDF | `/organize-pdf` |
| Watermark PDF | `/watermark-pdf` |
| Protect PDF | `/protect-pdf` |
| Unlock PDF | `/unlock-pdf` |

Max upload size: **100 MB** (see `backend/app/config.py`).

---

## Common problems

### `uvicorn` not recognized
Virtual environment active nahi hai, ya packages install nahi hue.

```powershell
.\venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
```

### Word → PDF / PPT → PDF fails (`WinError 2` / LibreOffice not found)
LibreOffice install karo, phir terminal **restart** karke server dubara chalao.

### Compress PDF fails without Ghostscript
Update lene ke baad PyMuPDF fallback use hota hai. Optional: Ghostscript install karo.

### `source` / `export` not recognized (Windows)
Linux commands mat use karo. PowerShell ke liye:

```powershell
.\venv\Scripts\Activate.ps1
$env:PYTHONPATH = $PWD
```

### UI / logo purana dikhe
Hard refresh: **Ctrl + F5** (Mac: **Cmd + Shift + R**)

### Port 8000 already in use
```powershell
uvicorn backend.app.main:app --host 0.0.0.0 --port 8001
```
Then open `http://localhost:8001`

---

## API health check

```
http://localhost:8000/api/health
```

Should return JSON like: `{"status":"ok","service":"MJPDF",...}`

---

## Privacy note

Uploaded files are processed temporarily on the server. Automatic cleanup removes old temp/output files periodically (about 1 hour, depending on config). MJPDF is not long-term cloud storage.

Contact: **glasiourwala@gmail.com**

---

## License / use

For personal or project use as provided. Review Terms and Privacy pages on the site before public deployment.
