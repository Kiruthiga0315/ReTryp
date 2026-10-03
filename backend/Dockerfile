FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# psycopg2 needs libpq at build time; curl is used for the container health check.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY tests ./tests

# Non-root runtime user.
RUN useradd --create-home --uid 10001 retryp \
    && mkdir -p /app/data \
    && chown -R retryp:retryp /app
USER retryp

ENV DATABASE_URL=sqlite:////app/data/retryp.db \
    HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

# Migrate, create the sign-in accounts, then serve. The entrypoint is
# idempotent so restarts are safe. No trips are seeded.
CMD ["sh", "-c", "alembic upgrade head && python -m app.bootstrap || true && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
