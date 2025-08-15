FROM python:3.11-slim-bookworm

# Prevent Python from writing pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

# Set work directory
WORKDIR /app

# Install system dependencies including Chromium for headless scraping
RUN apt-get update && apt-get install -y \
    # Basic tools
    curl \
    wget \
    gnupg2 \
    ca-certificates \
    # Chromium dependencies
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libfontconfig1 \
    libgbm1 \
    libgdk-pixbuf-2.0-0 \
    libgdk-pixbuf-xlib-2.0-0 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libxss1 \
    libxtst6 \
    lsb-release \
    xdg-utils \
    # Build tools for some Python packages
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Optional system Chromium install (disabled to improve build reliability and rely on Playwright-managed browser)
# If needed later, re-enable and add network retries
# RUN apt-get update \
#     && apt-get install -y chromium chromium-driver \
#     && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers as root before creating non-root user
ENV PLAYWRIGHT_BROWSERS_PATH=/app/.cache/ms-playwright
RUN mkdir -p /app/.cache/ms-playwright \
    && python -m playwright install --with-deps chromium \
    && echo "Playwright Chromium installed successfully"

# Create a non-root user for security (using UID 1000 for consistency)
RUN groupadd -r appuser -g 1000 && useradd -r -g appuser -u 1000 appuser

# Copy project files
COPY . /app/

# Ensure entrypoint is executable
RUN chmod 755 /app/entrypoint.sh

# Create directories for logs, media, and caches with proper permissions
RUN mkdir -p /app/logs /app/staticfiles /app/media \
    && chown -R appuser:appuser /app \
    && chmod -R 755 /app/logs /app/staticfiles /app/media /app/.cache

# Selenium not used; Playwright manages Chromium

# Switch to non-root user
USER appuser

# Health check (curl is available from base install)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -fsS http://localhost:8000/health/ || exit 1

# Default command (will be overridden by docker-compose)
CMD ["/app/entrypoint.sh"]