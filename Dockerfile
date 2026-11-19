# StreamClips AI Studio Dockerfile (Optimized for Hugging Face Spaces & Cloud)
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV STREAMCLIPS_HOME=/app/data
ENV HF_HOME=/app/models
ENV PORT=7860

# Install system dependencies: FFmpeg with libass support, Node.js, fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libass9 \
    nodejs \
    npm \
    curl \
    fonts-dejavu-core \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python packages
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -U pip setuptools wheel \
    && pip install --no-cache-dir -r /app/requirements.txt

# Copy application source code
COPY . /app

# Ensure directories exist
RUN mkdir -p /app/data /app/models /app/web/uploads

# Pre-download face detection model & Whisper tiny model to speed up cold starts
RUN python -c "from pathlib import Path; import urllib.request; \
    p = Path('/app/models/face_yunet.onnx'); p.parent.mkdir(parents=True, exist_ok=True); \
    urllib.request.urlretrieve('https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx', p); \
    from faster_whisper import WhisperModel; WhisperModel('tiny', device='cpu', compute_type='int8', download_root='/app/models/whisper')"

EXPOSE 7860 10000 8000

# Start Uvicorn bound to Hugging Face Spaces port 7860 (or $PORT)
CMD ["sh", "-c", "uvicorn web.server:app --host 0.0.0.0 --port ${PORT:-7860}"]
