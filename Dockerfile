# SusMob – schlankes Produktions-Image (FastAPI + SQLite, keine Systembibliotheken nötig)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ ./server/
COPY static/ ./static/
COPY index.html .

# Datenverzeichnis (SQLite + Uploads + Artefakte) – bei Hosting als Volume/Disk mounten
RUN mkdir -p /app/data
VOLUME ["/app/data"]

# Der Port kommt aus $PORT: lokal 8080, bei Render 10000 (Render setzt PORT selbst).
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD python -c "import os,sys,urllib.request; p=os.environ.get('PORT','8080'); sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+p+'/healthz', timeout=4).status==200 else 1)"

CMD ["sh", "-c", "uvicorn server.main:app --host 0.0.0.0 --port ${PORT}"]
