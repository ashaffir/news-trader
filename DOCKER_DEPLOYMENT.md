# Docker Deployment Guide

## Overview

This News Trader application is well-configured for Docker deployment on any machine. The Docker setup includes all necessary services and proper isolation.

## ✅ What's Already Good

### 1. **Complete Service Architecture**
- **Web Service**: Django application on port 8800
- **Database**: PostgreSQL 15 with persistent data
- **Cache/Queue**: Redis for Celery tasks
- **Workers**: Celery worker and beat scheduler
- **Monitoring**: Optional Flower service for Celery monitoring

### 2. **Proper Volume Management**
- Named volumes for PostgreSQL data persistence
- Static files and media volumes for asset storage
- Application code mounted for development

### 3. **Health Checks**
- All services have proper health check configurations
- Web app has dedicated `/health/` endpoint
- Database and Redis have standard health checks
- Celery services have process-based health checks

### 4. **Security Features**
- Non-root user in containers
- Proper file permissions
- Environment variable isolation

### 5. **Cross-Platform Compatibility**
- Uses Playwright-managed Chromium for web scraping (ARM64 and AMD64)
- Python 3.11 base image
- No architecture-specific dependencies
- Browser binaries are downloaded at runtime by Playwright; no system Chrome install required

## 🔧 Required Setup for New Machine

### 1. **Environment Configuration**
Create a `.env` file with the following variables:

```bash
# Essential Django Settings
SECRET_KEY=your-secret-key-here
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0,your-domain.com

# Database (automatically configured for Docker)
DATABASE_URL=postgresql://news_trader:news_trader@db:5432/news_trader

# Redis (automatically configured for Docker)
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

# REQUIRED: Trading API Keys
ALPACA_API_KEY=your-alpaca-api-key
ALPACA_SECRET_KEY=your-alpaca-secret-key
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# REQUIRED: OpenAI API Key
OPENAI_API_KEY=your-openai-api-key

# OPTIONAL: News Source API Keys
NEWSAPI_KEY=your-newsapi-key
ALPHAVANTAGE_API_KEY=your-alphavantage-key
REDDIT_USER_AGENT=YourApp/1.0

# Telegram Bot (required to use the interactive Telegram features)
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
# One or more chat IDs allowed to interact with the bot (comma-separated)
TELEGRAM_AUTHORIZED_CHATS=123456789

# Note: When overriding ALLOWED_HOSTS for Docker, include 'web' as an internal host
# to allow container-to-container health checks, e.g.:
# ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0,web,your-domain.com
```

### 2. **Prerequisites**
- Docker Engine (v20.10+)
- Docker Compose (v2.0+)
- At least 2GB RAM available
- 10GB disk space for volumes

## 🚀 Deployment Steps

### Quick Start (Recommended)
```bash
# 1. Clone and navigate to project
git clone <repository-url>
cd news-trader

# 2. Create environment file
cp .env.example .env
# Edit .env with your API keys

# 3. First-time setup using the robust script
chmod +x docker_dev.sh
./docker_dev.sh setup

# If setup fails, clean and retry:
./docker_dev.sh clean && ./docker_dev.sh setup

# Optional: Ensure Playwright Chromium is installed in containers (first run only)
./docker_dev.sh pwinstall
```

### Manual Deployment
```bash
# 1. Build and start services
docker-compose up -d

# 2. Run database migrations
docker-compose exec web python manage.py migrate

# 3. Create superuser
docker-compose exec web python manage.py createsuperuser

# 4. Setup example data sources
docker-compose exec web python manage.py setup_example_sources

# 5. Collect static files
docker-compose exec web python manage.py collectstatic --noinput
```

## 🔍 Service Access

| Service | URL | Purpose |
|---------|-----|---------|
| Web Dashboard | http://localhost:8800/dashboard/ | Main application |
| Django Admin | http://localhost:8800/admin/ | Configuration |
| Health Check | http://localhost:8800/health/ | Service status |
| Flower Monitor | http://localhost:5555 | Celery monitoring (optional) |

### Telegram Bot
- The `telegram-bot` service starts automatically and polls for updates
- Ensure your `.env` has `TELEGRAM_BOT_TOKEN` and `TELEGRAM_AUTHORIZED_CHATS`
- Test by sending `/status`, `/pnl`, and `/trades` to the bot

## 📊 Management Scripts

### Interactive Management
```bash
# Use the comprehensive management script
./docker_dev.sh

# Options available:
# - Setup (first time)
# - Start/Stop/Restart services
# - View logs
# - Open Django shell
# - Monitor services
```

### Command Line Operations
```bash
# Quick commands
./docker_dev.sh setup     # First-time setup
./docker_dev.sh start     # Start all services
./docker_dev.sh stop      # Stop all services
./docker_dev.sh status    # Show service status
./docker_dev.sh logs      # View all logs
```

## 🔧 Production Considerations

### Security
```bash
# Set production environment variables
DEBUG=False
SECRET_KEY=generate-strong-secret-key
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
```

### Performance
```bash
# Adjust worker concurrency based on CPU cores
# In docker-compose.yml, modify:
command: celery -A news_trader worker -l info --concurrency=4
```

### Monitoring
```bash
# Enable Flower monitoring
docker-compose --profile monitoring up -d flower

# View service logs
docker-compose logs -f web
docker-compose logs -f celery
```

## 🐛 Troubleshooting

### Setup Failures (NEW: Robust Recovery)

**🚀 Failed Setup? No Problem!** The setup script now has automatic error recovery:

```bash
# If setup fails at any point, simply run:
./docker_dev.sh clean && ./docker_dev.sh setup

# Or use the interactive menu:
./docker_dev.sh
# Choose option 12 (Clean up Docker), then option 1 (Setup)
```

The setup script now:
- ✅ **Detects failures** at each step
- ✅ **Provides clear error messages** with next steps
- ✅ **Can be safely re-run** multiple times
- ✅ **Automatically cleans up** after failures

### Common Issues and Solutions

1. **Setup fails partway through**
   ```bash
   # NEW: Simple recovery process
   ./docker_dev.sh clean && ./docker_dev.sh setup
   
   # Check what failed in the logs
   ./docker_dev.sh logs
   ```

2. **Services won't start**
   ```bash
   # Check if .env file exists and has required variables
   ls -la .env
   
   # Check Docker daemon is running
   docker info
   
   # Reset everything and retry
   ./docker_dev.sh clean && ./docker_dev.sh setup
   ```

3. **Database connection errors**
   ```bash
   # NEW: Robust cleanup and retry
   ./docker_dev.sh clean && ./docker_dev.sh setup
   
   # OR manual reset:
   docker-compose down -v
   docker-compose up -d db
   # Wait 30 seconds, then restart other services
   ```

4. **Celery tasks not processing**
   ```bash
   # Check Celery worker logs
   docker-compose logs celery
   
   # Restart Celery services
   docker-compose restart celery celery-beat
   ```

5. **Health check failures**
   ```bash
   # Check service status
   docker-compose ps
   
   # Test health endpoint directly
   curl http://localhost:8800/health/
   
   # If still failing, clean restart:
   ./docker_dev.sh clean && ./docker_dev.sh setup
   ```

6. **Telegram bot issues**
   - 409 Conflict ("terminated by other getUpdates request")
     ```bash
     # Make sure only one bot instance is polling
     docker-compose restart telegram-bot
     # Also ensure you are not running `python manage.py run_telegram_bot` on your host
     ```
   - Messages fail to send due to Markdown entity errors
     - Bot replies are formatted as plain text by default to avoid parse errors
     - If you customize formatting, either escape Markdown or avoid `parse_mode`

## 📈 Monitoring

### Health Checks
All services include comprehensive health checks:
- **Web**: HTTP endpoint at `/health/`
- **Database**: PostgreSQL ready check
- **Redis**: Ping command
- **Celery**: Process inspection
- **Celery Beat**: Process grep check

### Log Monitoring
```bash
# Real-time logs for all services
docker-compose logs -f

# Specific service logs
docker-compose logs -f web
docker-compose logs -f celery
```

## ✅ Deployment Checklist

- [ ] Docker and Docker Compose installed
- [ ] `.env` file created with all required API keys
- [ ] API keys tested and valid
- [ ] Sufficient system resources (2GB+ RAM)
- [ ] Firewall configured (if remote access needed)
- [ ] SSL certificates configured (for production)
- [ ] Backup strategy in place for volumes
- [ ] Monitoring solution configured

## 📞 Support

If you encounter issues:
1. Check service logs: `docker-compose logs [service_name]`
2. Verify environment variables: `docker-compose config`
3. Check service health: `./docker_dev.sh status`
4. Review this documentation

The Docker setup is production-ready and should work consistently across different machines and architectures.