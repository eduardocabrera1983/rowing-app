# ── Production Dockerfile ──
FROM python:3.11-slim

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r rowing && useradd -r -g rowing -d /app -s /sbin/nologin rowing

WORKDIR /app

# Install dependencies first (cache-friendly)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY rowing_app/ rowing_app/

# Create data directory for SQLite (owned by app user)
RUN mkdir -p /app/data && chown -R rowing:rowing /app

# Switch to non-root user
USER rowing

# Expose port
EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# Run with uvicorn (production settings)
CMD ["uvicorn", "rowing_app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
