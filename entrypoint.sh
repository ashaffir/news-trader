#!/bin/bash
set -euo pipefail

# Ensure proper permissions for cache directories
echo "Setting up directories and permissions..."

# Create directories if they don't exist (in case volumes override them)
mkdir -p /app/.cache/ms-playwright /app/staticfiles /app/media /app/logs

# Ensure all directories are writable by current user
# This handles both Docker volume mounts and direct execution
if [ -w /app ]; then
    chmod 755 /app/.cache/ms-playwright /app/staticfiles /app/media /app/logs 2>/dev/null || true
    # Ensure Playwright cache is writable
    [ -d /app/.cache/ms-playwright ] && chmod -R 755 /app/.cache/ms-playwright 2>/dev/null || true
else
    echo "Warning: Cannot write to /app directory. Some features may not work properly."
fi

# Verify logs directory is accessible
if [ ! -w /app/logs ]; then
    echo "Error: Cannot write to /app/logs directory. Attempting to fix..."
    mkdir -p /app/logs 2>/dev/null || echo "Failed to create logs directory"
    chmod 755 /app/logs 2>/dev/null || echo "Failed to set permissions on logs directory"
fi

# Wait for Postgres if DATABASE_URL is configured for postgres
if [[ -n "${DATABASE_URL:-}" ]] && [[ "$DATABASE_URL" == postgres* ]]; then
  echo "Waiting for Postgres to be ready..."
  ATTEMPTS=0
  until python - <<'PY'
import sys, os
import psycopg2
from urllib.parse import urlparse
url = os.environ.get('DATABASE_URL')
if not url:
    sys.exit(0)
u = urlparse(url)
try:
    conn = psycopg2.connect(
        dbname=u.path.lstrip('/'), user=u.username, password=u.password,
        host=u.hostname, port=u.port or 5432, connect_timeout=3
    )
    conn.close()
    sys.exit(0)
except Exception:
    sys.exit(1)
PY
  do
    ATTEMPTS=$((ATTEMPTS+1))
    if [[ $ATTEMPTS -gt 50 ]]; then
      echo "Postgres not ready after waiting. Exiting." >&2
      exit 1
    fi
    sleep 2
  done
fi

export DJANGO_SETTINGS_MODULE=news_trader.settings

ROLE="${SERVICE_ROLE:-web}"
echo "Starting service role: $ROLE"

case "$ROLE" in
  web)
    echo "Running migrations..."
    python manage.py migrate --noinput

    echo "Collecting static files..."
    python manage.py collectstatic --noinput || true

    # Playwright browsers are pre-installed during Docker build
    export PLAYWRIGHT_BROWSERS_PATH=/app/.cache/ms-playwright

    echo "Bootstrapping full setup..."
    python manage.py bootstrap_full_setup --with-cnbc-latest || true

    exec python manage.py runserver 0.0.0.0:8000
    ;;
  worker)
    # Wait for web health endpoint before starting
    echo "Waiting for web service to be healthy..."
    until curl -sf http://web:8000/health/ >/dev/null 2>&1; do
      sleep 2
    done
    exec celery -A news_trader worker -l info --concurrency=4 -P threads
    ;;
  beat)
    # Wait for web health endpoint before starting
    echo "Waiting for web service to be healthy..."
    until curl -sf http://web:8000/health/ >/dev/null 2>&1; do
      sleep 2
    done
    exec celery -A news_trader beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
    ;;
  *)
    echo "Unknown SERVICE_ROLE: $ROLE" >&2
    exit 1
    ;;
esac


