# =============================================================================
# Plant Health Demo - Container Image
# =============================================================================

# Force AMD64 architecture for Cloud Run compatibility
# Required when building on ARM-based Macs (M1/M2/M3/M4)
FROM --platform=linux/amd64 python:3.12-slim

WORKDIR /app

# ... rest of file unchanged

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download spaCy model for Presidio
RUN python -m spacy download en_core_web_lg

# Copy application code
COPY . .

# Cloud Run injects PORT env var (default 8080)
ENV PORT=8080
EXPOSE 8080

# Run the application using shell form to expand $PORT
CMD chainlit run app.py --host 0.0.0.0 --port $PORT