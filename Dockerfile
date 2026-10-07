# SusMob – Produktionsimage (FastAPI + SQLite + statisches Frontend)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data \
    PORT=8080

WORKDIR /app

# Abhängigkeiten zuerst (bessere Layer-Caches)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY index.html ./
COPY server ./server
COPY static ./static
COPY docs ./docs

# Uploads, Artefakte und SQLite liegen im Volume (Bestand zwischen Neustarts)
RUN mkdir -p /app/data
VOLUME ["/app/data"]

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4).status==200 else 1)"

# Nur eine Prozess-/Worker-Instanz: SQLite + In-Memory-Admin-Tokens
CMD ["sh", "-c", "uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers"]
