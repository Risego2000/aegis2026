# AEGIS en un solo contenedor: cliente estático compilado + API Python.
#
# Un proceso, un puerto, sin servicios externos. La base vive en /data para que
# sobreviva al contenedor (volumen). Imagen final ~180 MB.

# ---- 1. cliente ----------------------------------------------------------
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# Si se sirve bajo un subpath (GitHub Pages), pásalo como build-arg.
ARG NEXT_BASE_PATH=""
ENV NEXT_BASE_PATH=$NEXT_BASE_PATH
RUN npm run build

# ---- 2. API + cliente ----------------------------------------------------
FROM python:3.12-slim AS api
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=web /web/out ./frontend/out

ENV HOST=0.0.0.0 \
    PORT=8000 \
    SQLITE_PATH=/data/aegis.sqlite \
    FRONTEND_DIR=/app/frontend/out \
    RETENTION_DAYS=7 \
    PLAYBACK_ENABLED=true

RUN mkdir -p /data && useradd --system --uid 10001 aegis && chown -R aegis:aegis /data /app
USER aegis
VOLUME ["/data"]
EXPOSE 8000

# Sin curl en la imagen: el healthcheck usa el propio Python.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
