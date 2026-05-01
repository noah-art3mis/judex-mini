# Tesseract OCR HTTP service for Fly.io Machines.
#
# Mirrors the image config in judex/scraping/ocr/modal_app.py
# (Tesseract + Portuguese language pack + poppler) so OCR output
# is byte-identical between the Modal and Fly variants.
#
# Build size target: ~250 MB. The bulk is tesseract-ocr-por's
# language pack (~110 MB). Don't try to slim it further — losing
# the language pack regresses CER from 1% to ~15% on Portuguese.

FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-por \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
