# Jarvis API. Built from the repo root (see render.yaml), so the Trading Lab in tradinglab/ is included.
#   docker build -f apps/api/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ffmpeg turns Jarvis's spoken report into a Telegram voice note (OGG/Opus)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

# dependencies first, so code changes don't reinstall them
COPY apps/api/requirements.txt .
RUN pip install -r requirements.txt

COPY apps/api/app ./app
COPY tradinglab ./tradinglab

# run as a non-root user
RUN useradd --create-home jarvis
USER jarvis

# Render passes PORT; 8000 for local `docker run`
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
