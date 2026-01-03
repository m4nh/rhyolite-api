FROM python:3.12-slim

WORKDIR /app

# Install system deps (kept minimal; psycopg[binary] doesn't require libpq-dev)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

# Runtime configuration
# NOTE: Intentionally NOT declaring DATABASE_URL.
#
# Required (split DB config; no DATABASE_URL):
# - DATABASE_HOST
# - DATABASE_PORT (default 5432)
# - DATABASE_USER (or POSTGRES_USER)
# - DATABASE_PASSWORD (or DATABASE_PASS / POSTGRES_PASSWORD)
# - DATABASE_NAME (or POSTGRES_DB)
#
# Optional:
# - DATABASE_DRIVER (default postgresql+psycopg)
# - ATTACHMENTS_DIR (default /data/attachments)
# - HOST (default 0.0.0.0)
# - PORT (default 8000)
ENV HOST=0.0.0.0 \
    PORT=8000 \
    ATTACHMENTS_DIR=/data/attachments \
    DATABASE_PORT=5432 \
    DATABASE_DRIVER=postgresql+psycopg

RUN mkdir -p "$ATTACHMENTS_DIR"

EXPOSE 8000

CMD ["sh", "-c", "uvicorn server:app --host ${HOST:-0.0.0.0} --port ${PORT:-8000}"]
