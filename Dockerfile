FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PDF_INPUT_DIR=/app/data/inbox \
    PDF_STATE_DIR=/app/data/state \
    OCR_LANGUAGES=spa+eng

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-spa \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# The server runs as this user; docker-entrypoint.sh starts as root only to fix the
# ownership of /app/data and then drops to it.
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --home-dir /nonexistent \
        --shell /usr/sbin/nologin app

WORKDIR /app
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt
COPY app ./app
COPY --chmod=0755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN mkdir -p /app/data/inbox /app/data/state && chown -R app:app /app/data

EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
