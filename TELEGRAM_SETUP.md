# Telegram Bot Setup Guide

This guide explains how to set up the interactive Telegram bot for controlling your News Trading Bot.

## 🤖 Available Commands

Once configured, you can use these commands in your Telegram chat:

- `/start` or `/help` - Show welcome message and command list
- `/status` - Get bot status and trading overview
- `/enable` - Enable the trading bot
- `/disable` - Disable the trading bot  
- `/pnl` - Get detailed P&L summary (today, week, month, total)
- `/trades` - Show recent trades (last 10)
- `/alerts_on` - Enable Telegram notifications
- `/alerts_off` - Disable Telegram notifications

## 🔧 Setup Instructions

### 1. Create a Telegram Bot

1. Open Telegram and search for `@BotFather`
2. Send `/newbot` to create a new bot
3. Follow the instructions to choose a name and username
4. Copy the **Bot Token** (looks like `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)

### 2. Get Your Chat ID

1. Send a message to your new bot
2. Go to `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
3. Look for `"chat":{"id":` and copy the ID number

### 3. Configure Environment Variables

Add these to your `.env` file:

```bash
# Required: Your bot token from BotFather
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11

# Required: Authorized chat IDs (comma-separated for multiple users)
TELEGRAM_AUTHORIZED_CHATS=123456789,987654321

# Legacy support (fallback if TELEGRAM_AUTHORIZED_CHATS not set)
TELEGRAM_CHAT_ID=123456789
```

### 4. Install Dependencies

The required dependency `python-telegram-bot` is already added to `requirements.txt`.

If running locally:
```bash
pip install -r requirements.txt
```

If using Docker, rebuild the containers:
```bash
docker-compose down
docker-compose build
docker-compose up -d
```

### 5. Start the Telegram Bot

#### Option 1: Using Django Management Command (Recommended for Development)
```bash
python manage.py run_telegram_bot
```

#### Option 2: Using Celery Task (Recommended for Production)
```bash
# Start a Celery worker to handle the bot task
celery -A news_trader worker --loglevel=info

# In another terminal, start the bot task
python manage.py shell -c "from core.tasks import run_telegram_bot_task; run_telegram_bot_task.delay()"
```

#### Option 3: Using Docker
The bot can run as part of your Docker setup. Add this to your `docker-compose.yml`:

```yaml
telegram-bot:
  build: .
  command: python manage.py run_telegram_bot
  depends_on:
    - db
    - redis
  env_file:
    - .env
  restart: unless-stopped
```

## 🛡️ Security Features

- **Authorization**: Only authorized chat IDs can use the bot
- **Command validation**: All commands are validated and logged
- **Error handling**: Comprehensive error messages and logging
- **Rate limiting**: Built into the telegram library

## 🔍 Testing the Bot

1. Send `/start` to your bot - you should get a welcome message
2. Try `/status` to see your current bot status and trading summary
3. Use `/enable` or `/disable` to test bot control
4. Check `/pnl` to see your profit/loss summary

## 🚨 Troubleshooting

### Bot doesn't respond
- Check that `TELEGRAM_BOT_TOKEN` is correct
- Verify your chat ID is in `TELEGRAM_AUTHORIZED_CHATS`
- Check the logs for error messages

### Conflict: terminated by other getUpdates request
- Ensure only one bot instance is polling at a time
- This project now enforces a singleton bot using a Redis lock (uses `REDIS_URL` or `CELERY_BROKER_URL`)
- If you run multiple environments, use separate tokens or separate Redis instances

### "Unauthorized access" message
- Verify your chat ID is correctly added to `TELEGRAM_AUTHORIZED_CHATS`
- Make sure there are no extra spaces in the environment variable

### Commands fail with errors
- Check that the Django app is running and database is accessible
- Verify all required environment variables are set
- Check Celery is running if using the task-based approach

### Getting your Chat ID easily
Send this command to your bot and check the logs:
```bash
# In Django shell
from core.telegram_bot import TelegramBotService
bot = TelegramBotService()
print(f"Authorized chats: {bot.authorized_chat_ids}")
```

## 📱 Usage Tips

- Use inline keyboard buttons in `/status` for quick actions
- The bot remembers your preferences (alerts on/off)
- All actions are logged for audit purposes
- P&L calculations include both realized and unrealized gains/losses
- The bot works with your existing trading configuration

## 🔄 Integration with Existing Features

The Telegram bot integrates seamlessly with your existing system:

- Uses the same `TradingConfig.bot_enabled` field as the web interface
- Respects the same `AlertSettings` configuration
- Shows the same P&L data as your dashboard
- All actions are logged to `ActivityLog` for tracking

Now you can control your trading bot from anywhere using Telegram! 🚀
