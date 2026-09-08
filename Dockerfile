FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DEBIAN_FRONTEND=noninteractive \
    SAL_USE_VCLPLUGIN=svp \
    HOME=/tmp \
    FONTCONFIG_PATH=/etc/fonts

WORKDIR /app

# Full Writer stack + MS-metric fonts (Carlito≈Calibri, Caladea≈Cambria, Liberation≈Arial/Times)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice \
    libreoffice-writer \
    libreoffice-impress \
    libreoffice-java-common \
    default-jre-headless \
    fontconfig \
    fonts-dejavu-core \
    fonts-liberation \
    fonts-liberation-sans-narrow \
    fonts-noto-core \
    fonts-crosextra-carlito \
    fonts-crosextra-caladea \
    fonts-freefont-ttf \
    fonts-open-sans \
    ghostscript \
    poppler-utils \
    libmagic1 \
    && mkdir -p /etc/fonts/conf.d \
    && printf '%s\n' \
'<?xml version="1.0"?>' \
'<!DOCTYPE fontconfig SYSTEM "fonts.dtd">' \
'<fontconfig>' \
'  <alias binding="same"><family>Calibri</family><prefer><family>Carlito</family></prefer></alias>' \
'  <alias binding="same"><family>Calibri Light</family><prefer><family>Carlito</family></prefer></alias>' \
'  <alias binding="same"><family>Cambria</family><prefer><family>Caladea</family></prefer></alias>' \
'  <alias binding="same"><family>Arial</family><prefer><family>Liberation Sans</family></prefer></alias>' \
'  <alias binding="same"><family>Helvetica</family><prefer><family>Liberation Sans</family></prefer></alias>' \
'  <alias binding="same"><family>Times New Roman</family><prefer><family>Liberation Serif</family></prefer></alias>' \
'  <alias binding="same"><family>Times</family><prefer><family>Liberation Serif</family></prefer></alias>' \
'  <alias binding="same"><family>Courier New</family><prefer><family>Liberation Mono</family></prefer></alias>' \
'  <alias binding="same"><family>Georgia</family><prefer><family>Liberation Serif</family></prefer></alias>' \
'  <alias binding="same"><family>Segoe UI</family><prefer><family>Carlito</family></prefer></alias>' \
'</fontconfig>' \
      > /etc/fonts/conf.d/99-mjpdf-ms-aliases.conf \
    && mkdir -p /usr/lib/libreoffice/share/fonts/truetype/mjpdf \
    && find /usr/share/fonts -type f \( -iname "Carlito*.ttf" -o -iname "Caladea*.ttf" -o -iname "Liberation*.ttf" \) \
         -exec cp -n {} /usr/lib/libreoffice/share/fonts/truetype/mjpdf/ \; \
    && fc-cache -f -v \
    && (fc-list | grep -i carlito | head -3 || true) \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Seed LibreOffice user profile with font replacement hints (Calibri -> Carlito)
RUN mkdir -p /app/lo-profile-template/user/registry/data/org/openoffice/Office \
    && printf '%s\n' \
'<?xml version="1.0" encoding="UTF-8"?>' \
'<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">' \
' <item oor:path="/org.openoffice.VCL/DefaultFonts">' \
'  <prop oor:name="Replacement" oor:op="fuse"><value>true</value></prop>' \
' </item>' \
'</oor:items>' \
      > /app/lo-profile-template/user/registrymodifications.xcu

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY frontend /app/frontend

RUN mkdir -p /app/temp /app/uploads /app/outputs \
    && chmod -R 777 /app/temp /app/uploads /app/outputs /app/lo-profile-template

ENV PORT=8000
EXPOSE 8000

RUN soffice --version || libreoffice --version

CMD uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT}
