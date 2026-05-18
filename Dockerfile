# ── Stage 1: build dependencies ──────────────────────────────────────────────
FROM python:3.12-alpine AS builder

WORKDIR /app

RUN apk add --no-cache \
    gcc \
    musl-dev \
    libffi-dev \
    jpeg-dev \
    zlib-dev \
    freetype-dev

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock* ./
COPY src/ src/

RUN uv sync --no-dev

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-alpine AS runtime

WORKDIR /app

RUN apk add --no-cache \
    jpeg \
    zlib \
    freetype \
    libstdc++

# Create non-root user
RUN addgroup -S fire && adduser -S -G fire fire

COPY --from=builder /app/.venv /app/.venv
COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini .

# Create /data as root and give fire user ownership
# This runs at BUILD time so the directory exists with correct permissions.
# The volume mounts OVER /data at runtime — but Docker preserves ownership
# of the mount point, so fire user can write into the volume.
RUN mkdir -p /data/db /data/files \
    && chown -R fire:fire /data /app

USER fire

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"

EXPOSE 8000

# mkdir at startup too — in case the named volume is brand new and empty
CMD ["sh", "-c", \
    "mkdir -p /data/db /data/files && \
    alembic upgrade head && \
    uvicorn fire.main:app --host 0.0.0.0 --port 8000 --workers 1"]