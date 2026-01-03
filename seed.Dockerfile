FROM postgres:16-alpine

WORKDIR /app

COPY schema.sql seed.sh ./
RUN chmod +x ./seed.sh

# Runtime configuration for seeding.
#
# You can provide either:
# - DATABASE_URL (preferred when available)
#
# Or the split variables:
# - DATABASE_HOST
# - DATABASE_PORT (default 5432)
# - DATABASE_USER (or POSTGRES_USER)
# - DATABASE_PASSWORD (or DATABASE_PASS / POSTGRES_PASSWORD)
# - DATABASE_NAME (or POSTGRES_DB)
#
# Schema file:
# - SCHEMA_FILE (default /app/schema.sql)
ENV DATABASE_PORT=5432 \
    SCHEMA_FILE=/app/schema.sql \
    DATABASE_URL= \
    DATABASE_HOST= \
    DATABASE_USER= \
    DATABASE_PASSWORD= \
    DATABASE_PASS= \
    DATABASE_NAME= \
    POSTGRES_USER= \
    POSTGRES_PASSWORD= \
    POSTGRES_DB=

CMD ["sh", "-c", "./seed.sh"]
