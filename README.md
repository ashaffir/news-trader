# News Trader - Automated Trading System

A sophisticated, modular trading system that analyzes real-time news events using AI and executes trades automatically via the Alpaca API.

## 🎯 Overview

This Django-based system monitors multiple news sources, analyzes financial relevance using Large Language Models (LLMs), makes trade decisions, and executes them automatically. It features a real-time dashboard, comprehensive admin interface, and robust risk management.

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   News Sources  │───▶│  Data Ingestion │───▶│  LLM Analysis   │───▶│ Trade Execution │
│   • NewsAPI     │    │  • Web Scraping │    │  • OpenAI GPT   │    │  • Alpaca API   │
│   • Truth Social│    │  • API Polling  │    │  • Sentiment    │    │  • Risk Mgmt    │
│   • Reddit      │    │  • RSS Feeds    │    │  • Confidence   │    │  • P&L Tracking │
│   • Yahoo Finance│   │  • Real-time    │    │  • Symbol ID    │    │  • Stop/Limit   │
└─────────────────┘    └─────────────────┘    └─────────────────┘    └─────────────────┘
                                 │                        │                        │
                                 ▼                        ▼                        ▼
                       ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
                       │   PostgreSQL    │    │   Django Admin  │    │  WebSocket API  │
                       │   • Posts       │    │   • Config Mgmt │    │   • Real-time   │
                       │   • Analysis    │    │   • Monitoring  │    │   • Dashboard   │
                       │   • Trades      │    │   • Manual Ops  │    │   • Alerts      │
                       │   • Sources     │    │   • Audit Trail │    │   • Live Updates│
                       └─────────────────┘    └─────────────────┘    └─────────────────┘
```

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- Docker & Docker Compose
- OpenAI API Key
- Alpaca Trading API Keys

### Quick Access (Default Credentials)

| Service      | URL                              | Username | Password |
| ------------ | -------------------------------- | -------- | -------- |
| Dashboard    | http://localhost:8800/dashboard/ | -        | -        |
| Django Admin | http://localhost:8800/admin/     | `alfreds`  | `!Q2w3e4r%T`  |
| API          | http://localhost:8800/api/       | -        | -        |

### 1. Environment Setup

```bash
# Clone the repository
git clone <your-repo-url>
cd news-trader

# Create environment file
cp .env.example .env

# Edit .env with your API keys
nano .env
```

### 2. Docker Deployment

```bash
# Build and start all services (auto-migrates, bootstraps superuser, tasks, and CNBC Latest)
docker-compose up -d

# Important: Load tracked companies (required for opening any trades)
# This is NOT done automatically by docker-compose. Run once after services are up:
docker-compose exec web python manage.py import_tracked_companies /app/full_top_traded_companies_by_industry_expanded_with_financials.csv

# You can re-run the import any time to update names/metadata
```

### 3. Access the System

- **Dashboard**: http://localhost:8800/dashboard/
- **Admin Panel**: http://localhost:8800/admin/ (admin/admin)
- **API**: http://localhost:8800/api/

#### Default Admin Credentials
- **Username**: `admin`
- **Password**: `admin`

> ⚠️ **Security Note**: Change the default admin password in production environments!

## 📋 Core Components

### 1. Source Connector
Handles data ingestion from multiple sources:

- **API Sources**: NewsAPI, Truth Social, Reddit, AlphaVantage
- **Web Scraping**: RSS feeds, HTML parsing
- **Configuration**: Flexible JSON-based extraction rules

### 2. Post Analyzer
AI-powered financial analysis:

- **LLM Integration**: OpenAI GPT models
- **Configurable Prompts**: Custom analysis templates
- **Output**: Symbol, direction (buy/sell/hold), confidence, reasoning

### 3. Trading Engine
Automated trade execution:

- **Alpaca Integration**: Paper & live trading
- **Risk Management**: Stop-loss, take-profit, position sizing
- **Trade Tracking**: Real-time P&L, status updates

### 4. Admin Interface
Comprehensive management system:

- **Source Configuration**: API endpoints, scraping rules
- **Trading Parameters**: Risk settings, LLM configuration
- **Monitoring**: Trade history, error logs, performance metrics

### 5. Real-Time Dashboard
Live monitoring interface:

- **Live Updates**: Real-time trade alerts via polling
- **Activity Log**: Scraping, analysis, trade events
- **Manual Controls**: Close trades, trigger actions

## 🔧 Configuration

### Trading Configuration

```python
# Available via Django Admin
{
    "name": "Default Config",
    "default_position_size": 100.0,      # USD per trade
    "max_position_size": 1000.0,         # Maximum USD per trade
    "stop_loss_percentage": 5.0,         # 5% stop loss
    "take_profit_percentage": 10.0,      # 10% take profit
    "min_confidence_threshold": 0.7,     # Minimum LLM confidence
    "max_daily_trades": 10,              # Daily trade limit
    "trading_enabled": true,             # Master trading switch
    "market_hours_only": true           # Trade only during market hours
}
```

### Source Configuration Examples

#### NewsAPI Source
```python
{
    "name": "NewsAPI - Financial News",
    "api_endpoint": "https://newsapi.org/v2/everything",
    "api_key_field": "NEWSAPI_KEY",
    "request_params": {
        "q": "stock market OR NYSE OR earnings",
        "sortBy": "publishedAt",
        "language": "en",
        "pageSize": 20
    },
    "data_extraction_config": {
        "response_path": "articles",
        "content_field": "title",
        "url_field": "url"
    }
}
```

#### Reddit Source
```python
{
    "name": "Reddit - r/stocks",
    "api_endpoint": "https://www.reddit.com/r/stocks/hot.json",
    "data_extraction_config": {
        "response_path": "data.children",
        "content_field": "data.title",
        "min_score": 10
    }
}
```

## 🛠️ Development

### Local Development Setup

#### Using dev_manager.sh (Recommended)

```bash
# Make script executable
chmod +x dev_manager.sh

# Set up everything automatically
./dev_manager.sh setup

# Start all services
./dev_manager.sh start

# Access the system
# Dashboard: http://localhost:8800/dashboard/
# Admin: http://localhost:8800/admin/ (admin/admin)
```

#### Manual Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Set up database (SQLite for dev)
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Start development server
python manage.py runserver

# In separate terminals:
# Start Celery worker
celery -A news_trader worker -l info

# Start Celery beat (scheduler)
celery -A news_trader beat -l info
```

### Running Tests

```bash
# Run all tests
python manage.py test

# Run specific app tests
python manage.py test core

# Run with coverage
coverage run --source='.' manage.py test
coverage report
```

## 📊 API Usage

### REST API Endpoints

```bash
# Get trading summary
curl http://localhost:8800/api/trades/summary/

# Trigger manual scraping
curl -X POST http://localhost:8800/api/sources/1/trigger_scrape/

# Close a trade manually
curl -X POST http://localhost:8800/api/trades/123/close/

# Get recent analyses
curl http://localhost:8800/api/analyses/?direction=buy&min_confidence=0.8
```

### Live Updates

Real-time updates are delivered via simple polling every 3 seconds - much more reliable than WebSockets!
socket.onmessage = function(event) {
    const data = JSON.parse(event.data);
    console.log('Update:', data);
};
```

## 🔐 Security & Production

### Environment Variables

```bash
# Essential API Keys
OPENAI_API_KEY=your-openai-key
ALPACA_API_KEY=your-alpaca-key
ALPACA_SECRET_KEY=your-alpaca-secret

# Source-specific keys
NEWSAPI_KEY=your-newsapi-key
REDDIT_USER_AGENT=YourApp/1.0

# Security settings
DJANGO_SECRET_KEY=your-secret-key
DJANGO_DEBUG=False
SECURE_SSL_REDIRECT=True
```

### Production Checklist

- [ ] Set `DEBUG=False`
- [ ] Configure SSL certificates
- [ ] Set up monitoring (logs, metrics)
- [ ] Configure backup strategy
- [ ] Set proper CORS origins
- [ ] Enable rate limiting
- [ ] Review API key permissions

## 💾 Database Backups (Celery Beat)

- **What it does**: A daily PostgreSQL backup runs via Celery Beat and saves a compressed dump to the local machine.
- **Default schedule**: 02:30 daily. You can change the exact time in Django Admin.
- **Task name**: `Daily Database Backup (Local)` (under Admin → django_celery_beat → Periodic tasks)
- **Default location**: `<project_root>/backups` on the host where Django runs.

### Configure the schedule
1. Go to Admin → `django_celery_beat` → `Periodic tasks`.
2. Find `Daily Database Backup (Local)`.
3. Edit the `Crontab` to set your desired time, then Save.

Tip (Docker): If running in Docker, bind-mount the backups folder to persist on the host.
```yaml
services:
  web:
    volumes:
      - ./:/app
      - ./backups:/app/backups  # ensure backups are written to host
```

### Run a backup on demand
```bash
# Uses default location: <project_root>/backups
python manage.py backup_database

# Or specify a custom absolute directory on the host
python manage.py backup_database --output-dir /absolute/path/to/backups
```

### Notes
- Requires `pg_dump` to be available on the machine executing the task.
  - The app will look for `PG_DUMP_PATH` first (e.g., `/usr/local/bin/pg_dump`),
    otherwise it falls back to your `PATH` using `which pg_dump`.
  - macOS (Homebrew): `brew install libpq && echo 'export PATH="/opt/homebrew/opt/libpq/bin:$PATH"' >> ~/.zshrc`
  - Ubuntu/Debian: `sudo apt-get install -y postgresql-client`
- Database connection details are taken from `settings.DATABASES['default']`.
- Each successful run logs an entry in `ActivityLog` (type `system_event`).
- If you need to (re)create the periodic tasks programmatically:
```bash
python manage.py setup_periodic_tasks
```

## 📈 Monitoring & Observability

### Key Metrics

1. **Trading Performance**
   - Win rate percentage
   - Average P&L per trade
   - Sharpe ratio
   - Maximum drawdown

2. **System Health**
   - Scraping success rate
   - LLM analysis latency
   - Trade execution time
   - Error rates by component

3. **Data Quality**
   - Posts analyzed per hour
   - Confidence score distribution
   - Symbol identification accuracy

### Logging

```python
# View logs
docker-compose logs -f web
docker-compose logs -f celery
docker-compose logs -f celery-beat

# Log files location
./logs/django.log (rotated nightly)
```

#### Log rotation and automatic cleanup
- The application writes logs to `logs/django.log` and rotates them nightly (UTC) using a timed rotating handler.
- Retention is controlled by the `LOG_RETENTION_DAYS` environment variable. Default: `14`.
- A daily Celery Beat task named `Daily Log Maintenance` removes old log files exceeding the retention window.
- You can adjust the schedule from Admin → `django_celery_beat` → `Periodic tasks`.

## 🎛️ Management Commands

```bash
# Set up example sources and configuration
python manage.py setup_example_sources

# Test Alpaca API connection
python manage.py test_alpaca_connection

# Analyze specific post
python manage.py analyze_post <post_id>

# Generate performance report
python manage.py trading_report --days 7

# Clean old data
python manage.py cleanup_old_data --days 30
```

## 🐛 Troubleshooting

### Common Issues

1. **Database Connection Errors**
   ```bash
   # Check PostgreSQL is running
   docker-compose ps db
   
   # Reset database
   docker-compose down -v
   docker-compose up -d db
   ```

2. **Celery Tasks Not Running**
   ```bash
   # Check Celery workers
   docker-compose logs celery
   
   # Restart Celery
   docker-compose restart celery celery-beat
   ```

3. **API Rate Limits**
   ```bash
   # Check source error logs
   # Adjust scraping intervals
   # Enable/disable sources via admin
   ```

### Debug Mode

```bash
# Enable debug logging
export DJANGO_DEBUG=True
export LOG_LEVEL=DEBUG

# Monitor task execution
celery -A news_trader flower  # Celery monitoring UI
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

### Code Style

```bash
# Format code
black .
isort .

# Lint code
flake8 .
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## ⚠️ Disclaimer

This software is for educational and research purposes only. Trading involves financial risk. Always:

- Use paper trading for testing
- Never invest more than you can afford to lose
- Understand the risks of automated trading
- Comply with all applicable regulations
- Monitor your trades actively

The developers are not responsible for any financial losses incurred through the use of this software.