# Multi-stage Dockerfile for Enterprise Banking RAG Assistant
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    LLM_PROFILE=mock \
    PYTHONPATH=/app

WORKDIR /app

# Install minimal OS dependencies for sentence-transformers and sqlite
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install pinned Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application codebase
COPY . .

# Pre-create data directories
RUN mkdir -p data/qdrant data/cache reports/mock reports/real

# Default port for FastAPI (8000)
EXPOSE 8000

# Healthcheck targeting FastAPI ping endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

