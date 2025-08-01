import os
import openai
import alpaca_trade_api as tradeapi
import json
import requests
from bs4 import BeautifulSoup
from celery import shared_task

from .models import Source, ApiResponse, Post, Analysis, Trade, TradingConfig, ActivityLog
from django.utils import timezone
from django.db.models import Q
import logging
import hashlib
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def format_activity_message(message_type, data):
    """Format activity message for consistent display."""
    messages = {
        'new_post': f"📰 New post from {data.get('source', 'Unknown')}: {data.get('content_preview', '')[:100]}...",
        'analysis_complete': f"🧠 Analysis: {data.get('symbol', 'N/A')} {data.get('direction', '').upper()} ({round(data.get('confidence', 0) * 100)}% confidence)",
        'trade_executed': f"💰 Trade: {data.get('direction', '').upper()} {data.get('quantity', 0)} {data.get('symbol', 'N/A')} @ ${data.get('price', 0)}",
        'trade_closed': f"🎯 Trade closed: {data.get('symbol', 'N/A')} P&L: ${data.get('pnl', 0):.2f}",
        'trade_close_requested': f"🚨 Close request: {data.get('symbol', 'N/A')} order submitted (ID: {data.get('order_id', 'N/A')})",
        'scraper_error': f"⚠️ Scraping error from {data.get('source', 'Unknown')}: {data.get('error', 'Unknown error')}",
        'trade_status': f"📊 {data.get('status', 'Status update')}",
    }
    return messages.get(message_type, f"🔄 Update: {data}")


def send_dashboard_update(message_type, data):
    """Save activity update to database for polling-based UI updates."""
    try:
        # Format the message for display
        message = format_activity_message(message_type, data)
        
        # Save to database - this is now the primary method
        ActivityLog.objects.create(
            activity_type=message_type,
            message=message,
            data=data
        )
        logger.debug(f"Activity logged to database: {message_type}")
        
    except Exception as e:
        logger.error(f"Failed to save activity update ({message_type}): {e}")
        # Continue execution even if database save fails


def _create_simulated_post(source, error_message, method):
    # Make simulated URLs clearly distinct and non-browsable
    simulated_url = f"simulated://{source.name.replace(' ', '_')}/{method}/{hashlib.md5(error_message.encode()).hexdigest()}/{os.urandom(5).hex()}"
    simulated_content = f"Simulated post from {source.name} via {method} due to error: {error_message}. This is a placeholder for testing downstream processes."

    post = Post.objects.create(
        source=source, content=simulated_content, url=simulated_url
    )
    logger.info(f"Simulated post created: {post.url}")
    send_dashboard_update(
        "new_post",
        {
            "source": source.name,
            "content_preview": simulated_content[:100] + "...",
            "url": simulated_url,
            "post_id": post.id,
            "simulated": True,
        },
    )
    analyze_post.delay(post.id)


def _scrape_web(source):
    try:
        logger.info(f"Attempting to web scrape from {source.url}")
        response = requests.get(source.url)
        response.raise_for_status()  # Raise an exception for HTTP errors
        soup = BeautifulSoup(response.text, "html.parser")

        # Extract text content (a generic approach, can be refined)
        paragraphs = soup.find_all("p")
        scraped_content = "\n".join([p.get_text() for p in paragraphs])

        # Generate a unique URL for the post
        unique_id = hashlib.md5(scraped_content.encode()).hexdigest()
        post_url = f"{source.url}#{unique_id}"

        # Check if a post with this URL already exists to prevent duplicates
        if not Post.objects.filter(url=post_url).exists():
            post = Post.objects.create(
                source=source, content=scraped_content, url=post_url
            )
            logger.info(f"New post scraped from {source.name} (Web): {post.url}")
            send_dashboard_update(
                "new_post",
                {
                    "source": source.name,
                    "content_preview": scraped_content[:100] + "...",
                    "url": post_url,
                    "post_id": post.id,
                },
            )
            analyze_post.delay(post.id)
        else:
            logger.info(f"Post with URL {post_url} already exists. Skipping (Web).")
            send_dashboard_update(
                "scraper_skipped",
                {"source": source.name, "url": post_url, "method": "web"},
            )

    except requests.exceptions.RequestException as e:
        logger.error(f"Error web scraping {source.url}: {e}")
        send_dashboard_update(
            "scraper_error", {"source": source.name, "error": str(e), "method": "web"}
        )
        _create_simulated_post(source, str(e), "web")
    except Exception as e:
        logger.error(
            f"An unexpected error occurred while web scraping {source.url}: {e}"
        )
        send_dashboard_update(
            "scraper_error", {"source": source.name, "error": str(e), "method": "web"}
        )
        _create_simulated_post(source, str(e), "web")


def _fetch_api_posts(source):
    logger.info(f"Attempting to fetch posts from API for {source.name}")

    endpoint = source.api_endpoint
    key_field = source.api_key_field
    req_type = source.request_type
    req_params = source.request_params

    if not endpoint or not key_field:
        error_msg = f"API fetching for {source.name} skipped: API endpoint or key field missing in Source configuration."
        logger.warning(error_msg)
        send_dashboard_update(
            "scraper_skipped",
            {"source": source.name, "reason": "API config missing", "method": "api"},
        )
        _create_simulated_post(source, "API config missing", "api")
        return

    api_key = os.getenv(key_field)
    if not api_key:
        error_msg = f"API key '{key_field}' not found in environment variables. Cannot fetch from API for {source.name}."
        logger.error(error_msg)
        send_dashboard_update(
            "scraper_error",
            {"source": source.name, "error": error_msg, "method": "api"},
        )
        _create_simulated_post(source, f"API key {key_field} missing", "api")
        return

    headers = {"Authorization": f"Bearer {api_key}"}
    data = None
    params = None

    if req_params:
        try:
            # req_params is already a JSON object from models.JSONField
            if req_type == "GET":
                params = req_params
            elif req_type == "POST":
                data = json.dumps(req_params)  # Send as JSON body
                headers["Content-Type"] = "application/json"
        except Exception as e:
            error_msg = f"Error processing request_params for {source.name}: {e}. Params: {req_params}"
            logger.error(error_msg)
            send_dashboard_update(
                "scraper_error",
                {"source": source.name, "error": error_msg, "method": "api"},
            )
            _create_simulated_post(source, error_msg, "api")
            return

    try:
        logger.info(
            f"API Request: Type={req_type}, URL={endpoint}, Headers={headers}, Params={params}, Data={data}"
        )
        if req_type == "POST":
            response = requests.post(endpoint, headers=headers, data=data)
        else:  # Default to GET
            response = requests.get(endpoint, headers=headers, params=params)

        response.raise_for_status()
        api_data = response.json()
        logger.info(f"API Response for {source.name}: {json.dumps(api_data)[:200]}...")

        # Create an ApiResponse object
        api_response_url = (
            f"{endpoint}/{hashlib.md5(json.dumps(api_data).encode()).hexdigest()}"
        )
        if not ApiResponse.objects.filter(url=api_response_url).exists():
            api_response = ApiResponse.objects.create(
                source=source, raw_content=api_data, url=api_response_url
            )
            logger.info(
                f"New API Response recorded for {source.name}: {api_response.url}"
            )
            send_dashboard_update(
                "new_api_response",
                {
                    "source": source.name,
                    "url": api_response.url,
                    "api_response_id": api_response.id,
                },
            )

            # Parse the API response into individual posts
            _parse_api_response_to_posts(api_response)
        else:
            logger.info(
                f"API Response with URL {api_response_url} already exists. Skipping (API)."
            )
            send_dashboard_update(
                "scraper_skipped",
                {"source": source.name, "url": api_response_url, "method": "api"},
            )

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching from API for {source.name}: {e}")
        send_dashboard_update(
            "scraper_error", {"source": source.name, "error": str(e), "method": "api"}
        )
        _create_simulated_post(source, str(e), "api")
    except json.JSONDecodeError as e:
        error_msg = f"API response for {source.name} was not valid JSON: {e}. Raw response: {response.text[:200]}..."
        logger.error(error_msg)
        send_dashboard_update(
            "scraper_error",
            {"source": source.name, "error": error_msg, "method": "api"},
        )
        _create_simulated_post(source, error_msg, "api")
    except Exception as e:
        logger.error(
            f"An unexpected error occurred while fetching from API for {source.name}: {e}"
        )
        send_dashboard_update(
            "scraper_error", {"source": source.name, "error": str(e), "method": "api"}
        )
        _create_simulated_post(source, str(e), "api")


def _parse_api_response_to_posts(api_response):
    """Parses a raw API response and creates individual Post objects."""
    logger.info(
        f"Parsing API response {api_response.id} from {api_response.source.name}"
    )
    data = api_response.raw_content
    source = api_response.source

    # This is a placeholder. The actual parsing logic will depend on the API's response structure.
    # You will need to customize this based on the specific API you are integrating with.
    # For demonstration, let's assume the API returns a list of dictionaries, where each dictionary is a post.
    if isinstance(data, list):
        for item in data:
            # Assuming each item has a 'content' and 'url' field
            content = item.get(
                "content", json.dumps(item)
            )  # Fallback to full item if no 'content'
            post_url = item.get(
                "url",
                f"{api_response.url}/post/{hashlib.md5(content.encode()).hexdigest()}",
            )

            if not Post.objects.filter(url=post_url).exists():
                post = Post.objects.create(
                    api_response=api_response,
                    source=source,
                    content=content,
                    url=post_url,
                )
                logger.info(f"New post extracted from API response: {post.url}")
                send_dashboard_update(
                    "new_post",
                    {
                        "source": source.name,
                        "content_preview": content[:100] + "...",
                        "url": post_url,
                        "post_id": post.id,
                        "method": "api",
                    },
                )
                analyze_post.delay(post.id)
            else:
                logger.info(
                    f"Post with URL {post_url} already exists. Skipping (API Response Parsing)."
                )
                send_dashboard_update(
                    "scraper_skipped",
                    {"source": source.name, "url": post_url, "method": "api_parse"},
                )
    elif isinstance(data, dict):
        # Handle single post API response or other structures
        content = data.get("content", json.dumps(data))
        post_url = data.get(
            "url",
            f"{api_response.url}/post/{hashlib.md5(content.encode()).hexdigest()}",
        )
        if not Post.objects.filter(url=post_url).exists():
            post = Post.objects.create(
                api_response=api_response, source=source, content=content, url=post_url
            )
            logger.info(f"New post extracted from API response: {post.url}")
            send_dashboard_update(
                "new_post",
                {
                    "source": source.name,
                    "content_preview": content[:100] + "...",
                    "url": post_url,
                    "post_id": post.id,
                    "method": "api",
                },
            )
            analyze_post.delay(post.id)
        else:
            logger.info(
                f"Post with URL {post_url} already exists. Skipping (API Response Parsing)."
            )
            send_dashboard_update(
                "scraper_skipped",
                {"source": source.name, "url": post_url, "method": "api_parse"},
            )
    else:
        logger.warning(
            f"Unknown API response data format for {api_response.id}. Skipping parsing."
        )
        send_dashboard_update(
            "scraper_error",
            {
                "source": source.name,
                "error": "Unknown API response format",
                "method": "api_parse",
            },
        )


def get_active_trading_config():
    """Get the active trading configuration or create a default one."""
    try:
        return TradingConfig.objects.filter(is_active=True).first()
    except TradingConfig.DoesNotExist:
        # Create default config if none exists
        return TradingConfig.objects.create(
            name="Default Configuration", is_active=True
        )


def is_trading_allowed():
    """Check if trading is currently allowed based on configuration."""
    config = get_active_trading_config()
    if not config or not config.trading_enabled:
        return False, "Trading is disabled in configuration"

    if config.market_hours_only:
        # Add market hours check here if needed
        # For now, allow trading 24/7 unless specifically configured
        pass

    return True, "Trading allowed"


def check_daily_trade_limit():
    """Check if daily trade limit has been reached."""
    config = get_active_trading_config()
    if not config:
        return True, "No configuration found"

    today = timezone.now().date()
    today_trades = Trade.objects.filter(
        created_at__date=today, status__in=["open", "closed"]
    ).count()

    if today_trades >= config.max_daily_trades:
        return (
            False,
            f"Daily trade limit reached ({today_trades}/{config.max_daily_trades})",
        )

    return True, f"Trade limit OK ({today_trades}/{config.max_daily_trades})"


@shared_task
def scrape_posts(source_id=None):
    """Scrape posts from all configured sources or a specific source."""
    logger.info(f"Scrape posts task initiated. Source ID: {source_id}")

    # Check if bot is enabled
    trading_config = get_active_trading_config()
    if trading_config and not trading_config.bot_enabled:
        logger.info("Bot is disabled. Skipping scraping task.")
        return

    if source_id:
        try:
            sources = Source.objects.filter(id=source_id)
            if not sources.exists():
                logger.error(f"Source with ID {source_id} not found.")
                send_dashboard_update(
                    "scraper_error",
                    {"source": "N/A", "error": f"Source ID {source_id} not found"},
                )
                return
        except Exception as e:
            logger.error(f"Error getting source {source_id}: {e}")
            send_dashboard_update(
                "scraper_error",
                {"source": "N/A", "error": f"Error getting source {source_id}: {e}"},
            )
            return
    else:
        sources = Source.objects.all()

    send_dashboard_update(
        "scraper_status",
        {"status": "Scraping started", "total_sources": sources.count()},
    )

    for source in sources:
        if source.scraping_method == "web":
            _scrape_web(source)
        elif source.scraping_method == "api":
            _fetch_api_posts(source)
        elif source.scraping_method == "both":
            _scrape_web(source)
            _fetch_api_posts(source)
        else:
            logger.warning(
                f"Unknown scraping method for source {source.name}: {source.scraping_method}. Skipping."
            )
            send_dashboard_update(
                "scraper_skipped",
                {
                    "source": source.name,
                    "reason": f"Unknown scraping method: {source.scraping_method}",
                },
            )

    send_dashboard_update("scraper_status", {"status": "Scraping finished"})
    logger.info("Scraping finished.")


@shared_task
def analyze_post(post_id):
    """Analyze a post with an LLM."""
    logger.info(f"Analyzing post {post_id} with LLM.")

    # Check if bot is enabled
    trading_config = get_active_trading_config()
    if trading_config and not trading_config.bot_enabled:
        logger.info("Bot is disabled. Skipping analysis task.")
        return

    post = Post.objects.get(id=post_id)
    send_dashboard_update(
        "analysis_status", {"post_id": post.id, "status": "Analysis started"}
    )

    # Get active trading configuration
    config = get_active_trading_config()

    openai.api_key = os.getenv("OPENAI_API_KEY")
    if not openai.api_key:
        logger.error(
            "OPENAI_API_KEY not found in environment variables. Cannot analyze post."
        )
        send_dashboard_update(
            "analysis_error",
            {"post_id": post.id, "error": "OPENAI_API_KEY not configured"},
        )
        return

    llm_output = {}
    raw_response_content = None
    trade_executed_flag = False

    try:
        # Use configurable LLM model and prompt
        model = config.llm_model if config else "gpt-3.5-turbo"
        prompt = (
            config.llm_prompt_template
            if config
            else """You are a financial analyst. Analyze the given text for potential financial impact on a stock. 
Respond with a JSON object: { "symbol": "STOCK_SYMBOL", "direction": "buy", "confidence": 0.87, "reason": "Explanation" }. 
Direction can be 'buy', 'sell', or 'hold'. Confidence is a float between 0 and 1."""
        )

        response = openai.OpenAI().chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": post.content},
            ],
            response_format={"type": "json_object"},
            temperature=getattr(config, "llm_temperature", 0.1) if config else 0.1,
            max_tokens=getattr(config, "llm_max_tokens", 1000) if config else 1000,
        )

        raw_response_content = response.choices[0].message.content
        llm_output = json.loads(raw_response_content)

        analysis = Analysis.objects.create(
            post=post,
            symbol=llm_output.get("symbol", "UNKNOWN"),
            direction=llm_output.get("direction", "hold"),
            confidence=llm_output.get("confidence", 0.0),
            reason=llm_output.get("reason", "No reason provided by LLM."),
            raw_llm_response=raw_response_content,
            trading_config_used=config,
        )
        logger.info(
            f"Analysis complete for post {post.id}: Symbol={analysis.symbol}, Direction={analysis.direction}, Confidence={analysis.confidence}"
        )

        # Check if trade should be executed based on configuration
        confidence_threshold = config.min_confidence_threshold if config else 0.7
        if (
            analysis.direction in ["buy", "sell"]
            and analysis.confidence >= confidence_threshold
        ):
            # Check trading limits
            trading_allowed, reason = is_trading_allowed()
            daily_limit_ok, daily_reason = check_daily_trade_limit()

            if trading_allowed and daily_limit_ok:
                trade_executed_flag = True
                execute_trade.delay(analysis.id)
            else:
                logger.info(
                    f"Trade not executed for analysis {analysis.id}: Trading={reason}, Daily={daily_reason}"
                )
                send_dashboard_update(
                    "trade_skipped",
                    {
                        "analysis_id": analysis.id,
                        "reason": f"Trading: {reason}, Daily: {daily_reason}",
                    },
                )

        send_dashboard_update(
            "new_analysis",
            {
                "post_id": post.id,
                "symbol": analysis.symbol,
                "direction": analysis.direction,
                "confidence": analysis.confidence,
                "reason": analysis.reason[:100] + "...",
                "trade_executed": trade_executed_flag,
            },
        )

    except json.JSONDecodeError as e:
        error_msg = f"LLM response for post {post.id} was not valid JSON: {e}. Raw response: {raw_response_content}"
        logger.error(error_msg)
        Analysis.objects.create(
            post=post,
            symbol="ERROR",
            direction="hold",
            confidence=0.0,
            reason=f"LLM returned invalid JSON: {e}",
            raw_llm_response=raw_response_content,
            trading_config_used=config,
        )
        send_dashboard_update(
            "analysis_error", {"post_id": post.id, "error": error_msg}
        )
    except Exception as e:
        error_msg = f"Error analyzing post {post.id} with LLM: {e}"
        logger.error(error_msg)
        Analysis.objects.create(
            post=post,
            symbol="ERROR",
            direction="hold",
            confidence=0.0,
            reason=f"LLM analysis failed: {e}",
            raw_llm_response=raw_response_content,
            trading_config_used=config,
        )
        send_dashboard_update(
            "analysis_error", {"post_id": post.id, "error": error_msg}
        )


@shared_task
def execute_trade(analysis_id):
    """Execute a trade based on an analysis with enhanced position management."""
    logger.info(f"Processing trade analysis {analysis_id}.")

    # Check if bot is enabled
    trading_config = get_active_trading_config()
    if trading_config and not trading_config.bot_enabled:
        logger.info("Bot is disabled. Skipping trade execution.")
        return

    analysis = Analysis.objects.get(id=analysis_id)
    send_dashboard_update(
        "trade_status",
        {"analysis_id": analysis.id, "status": "Analyzing position management"},
    )

    # Check for existing open position in the same symbol
    existing_trade = Trade.objects.filter(
        symbol=analysis.symbol,
        status="open"
    ).first()

    if existing_trade:
        logger.info(f"Found existing open position for {analysis.symbol}: {existing_trade.direction}")
        
        if analysis.direction != existing_trade.direction:
            # Conflicting direction → Close position (market consensus lost)
            logger.info(f"Conflicting analysis for {analysis.symbol}: existing {existing_trade.direction}, new {analysis.direction}. Closing position.")
            close_trade_due_to_conflict.delay(existing_trade.id, analysis.id)
        else:
            # Supporting direction → Adjust TP/SL if conditions are met
            logger.info(f"Supporting analysis for {analysis.symbol}: {analysis.direction}. Checking for adjustment.")
            adjust_position_risk.delay(existing_trade.id, analysis.id)
    else:
        # No existing position → Create new trade
        logger.info(f"No existing position for {analysis.symbol}. Creating new trade.")
        create_new_trade.delay(analysis.id)


@shared_task
def create_new_trade(analysis_id):
    """Create a new trade for the given analysis."""
    analysis = Analysis.objects.get(id=analysis_id)
    config = get_active_trading_config()

    logger.info(f"Creating new trade for analysis {analysis_id}: {analysis.symbol} {analysis.direction}")

    ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
    ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
    ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        logger.error("Alpaca API keys not found in environment variables. Cannot execute trade.")
        send_dashboard_update(
            "trade_error",
            {"analysis_id": analysis.id, "error": "Alpaca API keys not configured"},
        )
        return

    api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, base_url=ALPACA_BASE_URL)

    try:
        # Determine position size
        position_size = config.default_position_size if config else 100.0

        # Get current stock price for quantity calculation
        try:
            ticker = api.get_latest_trade(analysis.symbol)
            current_price = ticker.price
            quantity = int(position_size / current_price)
            if quantity < 1:
                quantity = 1
        except Exception as e:
            logger.warning(
                f"Could not get current price for {analysis.symbol}: {e}. Using quantity 1."
            )
            quantity = 1
            current_price = 0.0

        # Submit order to Alpaca
        order = api.submit_order(
            symbol=analysis.symbol,
            qty=quantity,
            side=analysis.direction,  # "buy" or "sell"
            type="market",
            time_in_force="gtc",
        )

        # Calculate stop loss and take profit prices
        stop_loss_price = None
        take_profit_price = None
        if config and current_price > 0:
            if analysis.direction == "buy":
                stop_loss_price = current_price * (1 - config.stop_loss_percentage / 100)
                take_profit_price = current_price * (1 + config.take_profit_percentage / 100)
            else:  # sell
                stop_loss_price = current_price * (1 + config.stop_loss_percentage / 100)
                take_profit_price = current_price * (1 - config.take_profit_percentage / 100)

        # Create trade record
        trade = Trade.objects.create(
            analysis=analysis,
            symbol=analysis.symbol,
            direction=analysis.direction,
            quantity=quantity,
            entry_price=current_price,
            status="pending",
            alpaca_order_id=order.id,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            original_stop_loss_price=stop_loss_price,  # Store original values
            original_take_profit_price=take_profit_price,
        )

        logger.info(
            f"Submitted {analysis.direction.upper()} order for {analysis.symbol}. Trade ID: {trade.id}, Order ID: {order.id}"
        )

        send_dashboard_update(
            "new_trade",
            {
                "trade_id": trade.id,
                "symbol": trade.symbol,
                "direction": trade.direction,
                "quantity": trade.quantity,
                "status": trade.status,
                "entry_price": trade.entry_price,
                "stop_loss_price": trade.stop_loss_price,
                "take_profit_price": trade.take_profit_price,
            },
        )

    except Exception as e:
        error_msg = f"Error creating new trade for analysis {analysis.id}: {e}"
        logger.error(error_msg)
        send_dashboard_update(
            "trade_error", {"analysis_id": analysis.id, "error": error_msg}
        )


@shared_task
def adjust_position_risk(trade_id, analysis_id):
    """Adjust TP/SL for existing position based on supporting analysis."""
    trade = Trade.objects.get(id=trade_id)
    analysis = Analysis.objects.get(id=analysis_id)
    config = get_active_trading_config()

    logger.info(f"Evaluating position adjustment for trade {trade_id} based on analysis {analysis_id}")

    # Check if adjustments are allowed and not already done
    if not config or not config.allow_position_adjustments:
        logger.info(f"Position adjustments disabled in config for trade {trade_id}")
        return

    if trade.has_been_adjusted:
        logger.info(f"Trade {trade_id} has already been adjusted. Skipping.")
        return

    # Check confidence threshold
    if analysis.confidence < config.min_confidence_for_adjustment:
        logger.info(
            f"Analysis confidence {analysis.confidence} below adjustment threshold "
            f"{config.min_confidence_for_adjustment} for trade {trade_id}"
        )
        return

    try:
        # Calculate conservative adjustment based on analysis confidence
        adjustment_factor = analysis.confidence * config.conservative_adjustment_factor

        logger.info(
            f"Applying conservative adjustment (factor: {adjustment_factor:.2f}) to trade {trade_id}"
        )

        # Adjust take profit (move further out for supporting news)
        if trade.take_profit_price and trade.entry_price:
            current_tp_distance = abs(trade.take_profit_price - trade.entry_price)
            additional_distance = current_tp_distance * adjustment_factor * 0.1  # 10% max extension

            if trade.direction == "buy":
                new_tp = trade.take_profit_price + additional_distance
            else:  # sell
                new_tp = trade.take_profit_price - additional_distance

            trade.take_profit_price = new_tp
            logger.info(f"Adjusted TP for trade {trade_id}: {trade.take_profit_price:.2f}")

        # Adjust stop loss (tighten to lock in profits)
        if trade.stop_loss_price and trade.entry_price:
            current_sl_distance = abs(trade.stop_loss_price - trade.entry_price)
            tighter_distance = current_sl_distance * (1 - adjustment_factor * 0.3)  # Up to 30% tighter

            if trade.direction == "buy":
                new_sl = trade.entry_price - tighter_distance
            else:  # sell
                new_sl = trade.entry_price + tighter_distance

            trade.stop_loss_price = new_sl
            logger.info(f"Adjusted SL for trade {trade_id}: {trade.stop_loss_price:.2f}")

        # Mark as adjusted (one-time only)
        trade.has_been_adjusted = True
        trade.save()

        send_dashboard_update(
            "position_adjusted",
            {
                "trade_id": trade.id,
                "symbol": trade.symbol,
                "new_take_profit": trade.take_profit_price,
                "new_stop_loss": trade.stop_loss_price,
                "adjustment_factor": adjustment_factor,
                "analysis_confidence": analysis.confidence,
            },
        )

        logger.info(f"Successfully adjusted position for trade {trade_id}")

    except Exception as e:
        error_msg = f"Error adjusting position for trade {trade_id}: {e}"
        logger.error(error_msg)
        send_dashboard_update(
            "trade_error", {"trade_id": trade_id, "error": error_msg}
        )


@shared_task
def close_trade_due_to_conflict(trade_id, conflicting_analysis_id):
    """Close a trade due to conflicting market analysis (no consensus)."""
    trade = Trade.objects.get(id=trade_id)
    analysis = Analysis.objects.get(id=conflicting_analysis_id)

    logger.info(
        f"Closing trade {trade_id} ({trade.symbol} {trade.direction}) due to conflicting analysis "
        f"{conflicting_analysis_id} ({analysis.direction})"
    )

    try:
        # Set close reason
        trade.close_reason = "market_consensus_lost"
        trade.save()

        # Use existing manual close logic
        close_trade_manually.delay(trade_id)

        send_dashboard_update(
            "trade_closed_conflict",
            {
                "trade_id": trade.id,
                "symbol": trade.symbol,
                "original_direction": trade.direction,
                "conflicting_direction": analysis.direction,
                "reason": "Market consensus lost",
            },
        )

        logger.info(f"Initiated close for conflicting trade {trade_id}")

    except Exception as e:
        error_msg = f"Error closing conflicting trade {trade_id}: {e}"
        logger.error(error_msg)
        send_dashboard_update(
            "trade_error", {"trade_id": trade_id, "error": error_msg}
        )


@shared_task
def close_expired_positions():
    """Close positions that have exceeded the maximum hold time."""
    config = get_active_trading_config()
    if not config:
        logger.warning("No active trading config found. Skipping expired position cleanup.")
        return

    # Calculate cutoff time
    cutoff_time = timezone.now() - timedelta(hours=config.max_position_hold_time_hours)
    
    # Find expired trades
    expired_trades = Trade.objects.filter(
        status="open",
        opened_at__lt=cutoff_time
    )

    expired_count = expired_trades.count()
    if expired_count == 0:
        logger.info("No expired positions found.")
        return

    logger.info(f"Found {expired_count} expired positions to close (older than {config.max_position_hold_time_hours} hours)")

    closed_count = 0
    failed_count = 0

    for trade in expired_trades:
        try:
            # Set close reason and initiate close
            trade.close_reason = "time_limit"
            trade.save()

            close_trade_manually.delay(trade.id)
            closed_count += 1
            
            logger.info(f"Initiated time-based close for trade {trade.id} ({trade.symbol})")

        except Exception as e:
            failed_count += 1
            logger.error(f"Error closing expired trade {trade.id}: {e}")

    # Send dashboard update
    send_dashboard_update(
        "expired_positions_closed",
        {
            "total_expired": expired_count,
            "closed_count": closed_count,
            "failed_count": failed_count,
            "max_hold_hours": config.max_position_hold_time_hours,
        },
    )

    logger.info(f"Expired position cleanup completed: {closed_count} initiated, {failed_count} failed")


@shared_task
def monitor_local_stop_take_levels():
    """Monitor open positions for local TP/SL triggers without sending to Alpaca."""
    config = get_active_trading_config()
    if not config:
        logger.warning("No active trading config found. Skipping TP/SL monitoring.")
        return

    # Get all open trades
    open_trades = Trade.objects.filter(status="open")
    
    if not open_trades.exists():
        logger.debug("No open trades to monitor.")
        return

    logger.info(f"Monitoring {open_trades.count()} open positions for TP/SL triggers")

    ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
    ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
    ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        logger.warning("Alpaca API keys not configured. Skipping TP/SL monitoring.")
        return

    api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, base_url=ALPACA_BASE_URL)

    triggered_count = 0

    for trade in open_trades:
        try:
            # Get current price
            ticker = api.get_latest_trade(trade.symbol)
            current_price = float(ticker.price)

            # Check stop loss trigger
            if should_trigger_stop_loss(trade, current_price):
                logger.info(f"Stop loss triggered for trade {trade.id} ({trade.symbol}): {current_price} vs SL {trade.stop_loss_price}")
                trade.close_reason = "stop_loss"
                trade.save()
                close_trade_manually.delay(trade.id)
                triggered_count += 1

            # Check take profit trigger
            elif should_trigger_take_profit(trade, current_price):
                logger.info(f"Take profit triggered for trade {trade.id} ({trade.symbol}): {current_price} vs TP {trade.take_profit_price}")
                trade.close_reason = "take_profit"
                trade.save()
                close_trade_manually.delay(trade.id)
                triggered_count += 1

        except Exception as e:
            logger.error(f"Error monitoring trade {trade.id} ({trade.symbol}): {e}")

    if triggered_count > 0:
        logger.info(f"TP/SL monitoring completed: {triggered_count} positions triggered")


def should_trigger_stop_loss(trade, current_price):
    """Check if stop loss should be triggered for a trade."""
    if not trade.stop_loss_price:
        return False

    if trade.direction == "buy":
        # For long positions, stop loss triggers when price falls below SL
        return current_price <= trade.stop_loss_price
    else:  # sell
        # For short positions, stop loss triggers when price rises above SL
        return current_price >= trade.stop_loss_price


def should_trigger_take_profit(trade, current_price):
    """Check if take profit should be triggered for a trade."""
    if not trade.take_profit_price:
        return False

    if trade.direction == "buy":
        # For long positions, take profit triggers when price rises above TP
        return current_price >= trade.take_profit_price
    else:  # sell
        # For short positions, take profit triggers when price falls below TP
        return current_price <= trade.take_profit_price


@shared_task
def close_trade_manually(trade_id):
    """Manually close an open trade."""
    logger.info(f"Attempting to manually close trade {trade_id}.")
    try:
        trade = Trade.objects.get(id=trade_id, status="open")

        # Try to close via Alpaca API if we have order ID
        if trade.alpaca_order_id:
            ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
            ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
            ALPACA_BASE_URL = os.getenv(
                "ALPACA_BASE_URL", "https://paper-api.alpaca.markets"
            )

            if ALPACA_API_KEY and ALPACA_SECRET_KEY:
                try:
                    api = tradeapi.REST(
                        ALPACA_API_KEY, ALPACA_SECRET_KEY, base_url=ALPACA_BASE_URL
                    )

                    # Submit opposite order to close position
                    close_side = "sell" if trade.direction == "buy" else "buy"
                    close_order = api.submit_order(
                        symbol=trade.symbol,
                        qty=trade.quantity,
                        side=close_side,
                        type="market",
                        time_in_force="gtc",
                    )

                    # Get current price for exit price
                    try:
                        ticker = api.get_latest_trade(trade.symbol)
                        exit_price = ticker.price
                    except:
                        exit_price = trade.entry_price  # Fallback

                    # Calculate P&L
                    if trade.direction == "buy":
                        pnl = (exit_price - trade.entry_price) * trade.quantity
                    else:
                        pnl = (trade.entry_price - exit_price) * trade.quantity

                    trade.status = "closed"
                    trade.exit_price = exit_price
                    trade.realized_pnl = pnl
                    trade.close_reason = "manual"
                    trade.closed_at = timezone.now()
                    trade.save()

                    logger.info(
                        f"Trade {trade.id} closed via Alpaca API with P&L: ${pnl:.2f}"
                    )

                except Exception as api_error:
                    logger.warning(
                        f"Could not close trade via Alpaca API: {api_error}. Closing locally."
                    )
                    trade.status = "closed"
                    trade.exit_price = trade.entry_price  # Neutral exit
                    trade.realized_pnl = 0.0
                    trade.close_reason = "manual"
                    trade.closed_at = timezone.now()
                    trade.save()
            else:
                # Close locally without API
                trade.status = "closed"
                trade.exit_price = trade.entry_price  # Neutral exit
                trade.realized_pnl = 0.0
                trade.close_reason = "manual"
                trade.closed_at = timezone.now()
                trade.save()
        else:
            # Close locally without API
            trade.status = "closed"
            trade.exit_price = trade.entry_price  # Neutral exit
            trade.realized_pnl = 0.0
            trade.close_reason = "manual"
            trade.closed_at = timezone.now()
            trade.save()

        logger.info(f"Trade {trade.id} for {trade.symbol} manually closed.")
        send_dashboard_update(
            "trade_closed",
            {
                "trade_id": trade.id,
                "symbol": trade.symbol,
                "status": trade.status,
                "exit_price": trade.exit_price,
                "realized_pnl": trade.realized_pnl,
                "message": "Trade manually closed.",
            },
        )

    except Trade.DoesNotExist:
        error_msg = f"Trade {trade_id} not found or not open."
        logger.warning(error_msg)
        send_dashboard_update("trade_error", {"trade_id": trade_id, "error": error_msg})
    except Exception as e:
        error_msg = f"Error closing trade {trade_id} manually: {e}"
        logger.error(error_msg)
        send_dashboard_update("trade_error", {"trade_id": trade_id, "error": error_msg})


@shared_task
def create_manual_test_trade(symbol, direction, quantity=None, position_size=None):
    """Create a manual test trade directly to Alpaca API for testing purposes."""
    logger.info(f"Creating manual test trade: {symbol} {direction}")

    ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
    ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
    ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        logger.error("Alpaca API keys not found in environment variables. Cannot execute test trade.")
        send_dashboard_update(
            "trade_error",
            {"error": "Alpaca API keys not configured"},
        )
        return

    api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, base_url=ALPACA_BASE_URL)

    try:
        # Get current stock price for quantity calculation if needed
        try:
            ticker = api.get_latest_trade(symbol)
            current_price = ticker.price
            
            # Calculate quantity if position_size is provided, otherwise use quantity directly
            if position_size and not quantity:
                quantity = max(1, int(position_size / current_price))
            elif not quantity:
                quantity = 1  # Default to 1 share
                
        except Exception as e:
            logger.warning(f"Could not get current price for {symbol}: {e}. Using quantity 1.")
            quantity = quantity or 1
            current_price = 0.0

        # Submit order to Alpaca
        logger.info(f"Submitting test order: {symbol}, qty={quantity}, side={direction}")
        order = api.submit_order(
            symbol=symbol,
            qty=quantity,
            side=direction,  # "buy" or "sell"
            type="market",
            time_in_force="gtc",
        )

        # Create minimal trade record for tracking (without analysis)
        trade = Trade.objects.create(
            analysis=None,  # No analysis for manual test trades
            symbol=symbol,
            direction=direction,
            quantity=quantity,
            entry_price=current_price,
            status="pending",
            alpaca_order_id=order.id,
            opened_at=timezone.now(),
            # Note: Manual test trade - Order ID stored in alpaca_order_id
        )

        logger.info(f"Manual test trade created successfully: Trade #{trade.id}, Alpaca Order #{order.id}")
        
        send_dashboard_update(
            "manual_trade_success",
            {
                "trade_id": trade.id,
                "symbol": symbol,
                "direction": direction,
                "quantity": quantity,
                "alpaca_order_id": order.id,
                "current_price": current_price,
            },
        )

        return {
            "success": True,
            "trade_id": trade.id,
            "alpaca_order_id": order.id,
            "message": f"Test trade created: {symbol} {direction} {quantity} shares"
        }

    except Exception as e:
        error_msg = f"Failed to create manual test trade: {str(e)}"
        logger.error(error_msg)
        send_dashboard_update("trade_error", {"error": error_msg})
        return {"success": False, "error": error_msg}


@shared_task
def update_trade_status():
    """Periodic task to update trade statuses from Alpaca API."""
    logger.info("Updating trade statuses from Alpaca API.")

    ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
    ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
    ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        logger.warning("Alpaca API keys not configured. Skipping trade status update.")
        return

    try:
        api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, base_url=ALPACA_BASE_URL)

        # Get pending trades
        pending_trades = Trade.objects.filter(
            status="pending", alpaca_order_id__isnull=False
        )

        for trade in pending_trades:
            try:
                order = api.get_order(trade.alpaca_order_id)

                if order.status == "filled":
                    trade.status = "open"
                    trade.entry_price = float(
                        order.filled_avg_price or order.limit_price or trade.entry_price
                    )
                    trade.opened_at = timezone.now()
                    trade.save()

                    logger.info(
                        f"Trade {trade.id} status updated to open with entry price {trade.entry_price}"
                    )
                    send_dashboard_update(
                        "trade_status_updated",
                        {
                            "trade_id": trade.id,
                            "status": "open",
                            "entry_price": trade.entry_price,
                        },
                    )

                elif order.status in ["cancelled", "rejected"]:
                    trade.status = "failed"
                    trade.save()

                    logger.info(f"Trade {trade.id} failed: {order.status}")
                    send_dashboard_update(
                        "trade_status_updated",
                        {
                            "trade_id": trade.id,
                            "status": "failed",
                            "reason": order.status,
                        },
                    )

            except Exception as e:
                logger.error(f"Error updating status for trade {trade.id}: {e}")

    except Exception as e:
        logger.error(f"Error updating trade statuses: {e}")


@shared_task
def close_all_trades_manually():
    """Close all open trades manually."""
    logger.info("Attempting to close all open trades manually.")
    try:
        # First sync database with Alpaca to ensure consistency
        from .views import get_alpaca_trading_data, sync_alpaca_positions_to_database
        
        alpaca_data = get_alpaca_trading_data()
        alpaca_positions = alpaca_data.get("positions", [])
        sync_alpaca_positions_to_database(alpaca_positions)
        
        # Get all open trades from database (now synced)
        open_trades = Trade.objects.filter(status="open")
        trade_count = open_trades.count()

        if trade_count == 0:
            logger.info("No open trades to close.")
            return {
                "status": "success",
                "message": "No open trades to close",
                "closed_count": 0,
            }

        logger.info(f"Found {trade_count} open trades to close.")

        # Close each trade individually
        closed_count = 0
        failed_count = 0
        errors = []

        for trade in open_trades:
            try:
                # Use the existing close trade logic
                close_trade_manually.delay(trade.id)
                closed_count += 1
                logger.info(f"Initiated close for trade {trade.id} ({trade.symbol})")
            except Exception as e:
                failed_count += 1
                error_msg = (
                    f"Failed to close trade {trade.id} ({trade.symbol}): {str(e)}"
                )
                errors.append(error_msg)
                logger.error(error_msg)

        result_message = (
            f"Close all initiated: {closed_count} successful, {failed_count} failed"
        )
        if errors:
            result_message += (
                f". Errors: {'; '.join(errors[:3])}"  # Limit error messages
            )

        logger.info(result_message)

        # Send dashboard update
        send_dashboard_update(
            "trades_closed_all",
            {
                "closed_count": closed_count,
                "failed_count": failed_count,
                "total_count": trade_count,
                "message": result_message,
            },
        )

        return {
            "status": "success" if failed_count == 0 else "partial",
            "message": result_message,
            "closed_count": closed_count,
            "failed_count": failed_count,
            "errors": errors,
        }

    except Exception as e:
        error_msg = f"Error in close_all_trades_manually: {e}"
        logger.error(error_msg)
        send_dashboard_update("trades_error", {"error": error_msg})
        return {"status": "error", "message": error_msg, "closed_count": 0}
