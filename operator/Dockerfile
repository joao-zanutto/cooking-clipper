# Cooking Clipper Operator — watches S3 bucket, spawns K8s Jobs
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy operator requirements separately for caching
COPY operator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY operator/controller.py .
COPY operator/frontend/ ./frontend/

ENTRYPOINT ["python", "controller.py"]
