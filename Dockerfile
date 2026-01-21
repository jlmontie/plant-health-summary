# =============================================================================
# Plant Health Demo - Container Image
# =============================================================================

# Force AMD64 architecture for Cloud Run compatibility
# Required when building on ARM-based Macs (M1/M2/M3/M4)
FROM --platform=linux/amd64 python:3.12-slim

WORKDIR /app

# Install system dependencies (minimal - no spaCy/Presidio needed in production)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# NOTE: spaCy model NOT installed in production image
# Production uses Cloud DLP for PII redaction (USE_CLOUD_DLP=true)
# For local development with Presidio, run: python -m spacy download en_core_web_lg

# Copy application code
COPY . .

# Cloud Run injects PORT env var (default 8080)
ENV PORT=8080
EXPOSE 8080

# Default to Cloud DLP in production (set USE_CLOUD_DLP=false for local Presidio)
ENV USE_CLOUD_DLP=true

# Run the application using shell form to expand $PORT
CMD chainlit run app.py --host 0.0.0.0 --port $PORT