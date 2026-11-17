# Backend image. Build from the repository root:  docker build -f backend/Dockerfile -t vidhi-backend .
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# Exact tested versions (requirements.lock) - the image is reproducible.
# GnuPG encrypts the database backups made by the backup container (tools/db_backup.py).
RUN apt-get update && apt-get install -y --no-install-recommends gnupg && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements.lock ./
RUN pip install -r requirements.txt -c requirements.lock

COPY backend/ ./
# Never ship tests, local env files or caches in the image.
RUN rm -rf tests .env .env.* __pycache__ \
    && useradd --system --uid 10001 --no-create-home appuser \
    && chown -R appuser /app
USER appuser

EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8001/api/health', timeout=4).status == 200 else 1)"

# WEB_CONCURRENCY sets the worker count (rate limits and job locks live in MongoDB, so several workers are safe).
# Trust the proxy headers only because this container is reachable solely through the web container / load balancer.
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-access-log"]
