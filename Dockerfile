FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DEBIAN_FRONTEND=noninteractive \
    SAL_USE_VCLPLUGIN=svp \
    HOME=/tmp

WORKDIR /app

# LibreOffice + fonts that match Microsoft metrics (Carlito≈Calibri, Caladea≈Cambria)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice \
    libreoffice-writer \
    libreoffice-impress \
    libreoffice-java-common \
    default-jre-headless \
    fontconfig \
    fonts-dejavu-core \
    fonts-liberation \
    fonts-noto-core \
    fonts-crosextra-carlito \
    fonts-crosextra-caladea \
    fonts-freefont-ttf \
    ghostscript \
    poppler-utils \
    libmagic1 \
    && mkdir -p /etc/fonts/conf.d \
    && printf '%s\n' \
'<?xml version="1.0"?>' \
'<!DOCTYPE fontconfig SYSTEM "fonts.dtd">' \
'<fontconfig>' \
'  <alias><family>Calibri</family><prefer><family>Carlito</family></prefer></alias>' \
'  <alias><family>Calibri Light</family><prefer><family>Carlito</family></prefer></alias>' \
'  <alias><family>Cambria</family><prefer><family>Caladea</family></prefer></alias>' \
'  <alias><family>Arial</family><prefer><family>Liberation Sans</family></prefer></alias>' \
'  <alias><family>Times New Roman</family><prefer><family>Liberation Serif</family></prefer></alias>' \
'  <alias><family>Courier New</family><prefer><family>Liberation Mono</family></prefer></alias>' \
'  <alias><family>Georgia</family><prefer><family>Gelasio</family></prefer></alias>' \
'</fontconfig>' \
      > /etc/fonts/conf.d/99-mjpdf-ms-aliases.conf \
    && fc-cache -f \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY frontend /app/frontend

RUN mkdir -p /app/temp /app/uploads /app/outputs \
    && chmod -R 777 /app/temp /app/uploads /app/outputs

ENV PORT=8000
EXPOSE 8000

RUN soffice --version || libreoffice --version

CMD uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT}
