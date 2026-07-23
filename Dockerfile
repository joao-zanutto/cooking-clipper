# Cooking Clipper — Video processing pipeline
# Build: docker build -t cooking-clipper .
# Run:   docker run --rm -v $(pwd)/.env:/app/.env cooking-clipper s3://bucket/video.mov

FROM python:3.12-slim

# System dependencies for OpenCV and ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY split.py .
COPY frontend/ ./frontend/

# Default command shows help
ENTRYPOINT ["python", "split.py"]
CMD ["--help"]