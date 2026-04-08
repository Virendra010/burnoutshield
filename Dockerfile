# ─────────────────────────────────────────────────────────────────────────────
# BurnoutShield — Dockerfile
# Optimized for Google Cloud Run deployment
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Cloud Run injects PORT; default to 8080
ENV PORT=8080
ENV FLASK_ENV=production

# Expose port
EXPOSE 8080

# Run with Gunicorn (production WSGI server)
# - 2 worker processes (Cloud Run single vCPU default)
# - 120s timeout (ADK pipeline can take 30–60s)
CMD exec gunicorn \
    --bind "0.0.0.0:$PORT" \
    --workers 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    app:app
