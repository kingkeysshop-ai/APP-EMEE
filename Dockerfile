FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates tzdata && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data

ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8
ENV DATABASE_PATH=/data/subscribers.db
ENV TZ_NAME=America/Bogota

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/health || exit 1

CMD gunicorn app:app --bind 0.0.0.0:${PORT:-8080} --workers 2 --timeout 60 --access-logfile - --error-logfile -
