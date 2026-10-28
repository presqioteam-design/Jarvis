# Jarvis API. Render builds this from apps/api (see render.yaml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# dependencies first, so code changes don't reinstall them
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

# run as a non-root user
RUN useradd --create-home jarvis
USER jarvis

# Render passes PORT; 8000 for local `docker run`
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
