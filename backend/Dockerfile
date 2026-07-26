# syntax=docker/dockerfile:1

FROM python:3.14-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# lxml (via python-pptx) needs a compiler only if no wheel is available.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Dependency layer: changes rarely, so it stays cached across code edits.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[postgres]"

COPY tests ./tests

RUN useradd --create-home --uid 10001 deckforge \
    && mkdir -p /app/data \
    && chown -R deckforge:deckforge /app
USER deckforge

ENV DECKFORGE_DATA_DIR=/app/data \
    DECKFORGE_DATABASE_URL=sqlite+aiosqlite:////app/data/deckforge.db

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "deckforge.main:app", "--host", "0.0.0.0", "--port", "8000"]
