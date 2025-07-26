import os
import openai
import alpaca_trade_api as tradeapi
import json
import requests
from bs4 import BeautifulSoup
from celery import shared_task
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from .models import Source, ApiResponse, Post, Analysis, Trade
import logging
import hashlib

logger = logging.getLogger(__name__)

def send_dashboard_update(message_type, data):
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        "dashboard_updates",
        {
            "type": "send_update",
            "message_type": message_type,
            "data": data,
        }
    )

def _create_simulated_post(source, error_message, method):
    # Make simulated URLs clearly distinct and non-browsable
    simulated_url = f"simulated://{source.name.replace(' ', '_')}/{method}/{hashlib.md5(error_message.encode()).hexdigest()}/{os.urandom(5).hex()}"
    simulated_content = f"Simulated post from {source.name} via {method} due to error: {error_message}. This is a placeholder for testing downstream processes."
    
    post = Post.objects.create(source=source, content=simulated_content, url=simulated_url)
    logger.info(f"Simulated post created: {post.url}")
    send_dashboard_update("new_post", {"source": source.name, "content_preview": simulated_content[:100] + "...", "url": simulated_url, "post_id": post.id, "simulated": True})
    analyze_post.delay(post.id)

def _scrape_web(source):
    try:
        logger.info(f"Attempting to web scrape from {source.url}")
        response = requests.get(source.url)
        response.raise_for_status()  # Raise an exception for HTTP errors
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract text content (a generic approach, can be refined)
        paragraphs = soup.find_all('p')
        scraped_content = '\n'.join([p.get_text() for p in paragraphs])
        
        # Generate a unique URL for the post
        unique_id = hashlib.md5(scraped_content.encode()).hexdigest()
        post_url = f"{source.url}#{unique_id}"

        # Check if a post with this URL already exists to prevent duplicates
        if not Post.objects.filter(url=post_url).exists():
            post = Post.objects.create(source=source, content=scraped_content, url=post_url)
            logger.info(f"New post scraped from {source.name} (Web): {post.url}")
            send_dashboard_update("new_post", {"source": source.name, "content_preview": scraped_content[:100] + "...", "url": post_url, "post_id": post.id})
            analyze_post.delay(post.id)
        else:
            logger.info(f"Post with URL {post_url} already exists. Skipping (Web).")
            send_dashboard_update("scraper_skipped", {"source": source.name, "url": post_url, "method": "web"})

    except requests.exceptions.RequestException as e:
        logger.error(f"Error web scraping {source.url}: {e}")
        send_dashboard_update("scraper_error", {"source": source.name, "error": str(e), "method": "web"})
        _create_simulated_post(source, str(e), "web")
    except Exception as e:
        logger.error(f"An unexpected error occurred while web scraping {source.url}: {e}")
        send_dashboard_update("scraper_error", {"source": source.name, "error": str(e), "method": "web"})
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
        send_dashboard_update("scraper_skipped", {"source": source.name, "reason": "API config missing", "method": "api"})
        _create_simulated_post(source, "API config missing", "api")
        return

    api_key = os.getenv(key_field)
    if not api_key:
        error_msg = f"API key '{key_field}' not found in environment variables. Cannot fetch from API for {source.name}."
        logger.error(error_msg)
        send_dashboard_update("scraper_error", {"source": source.name, "error": error_msg, "method": "api"})
        _create_simulated_post(source, f"API key {key_field} missing", "api")
        return

    headers = {'Authorization': f'Bearer {api_key}'}
    data = None
    params = None

    if req_params:
        try:
            # req_params is already a JSON object from models.JSONField
            if req_type == 'GET':
                params = req_params
            elif req_type == 'POST':
                data = json.dumps(req_params) # Send as JSON body
                headers['Content-Type'] = 'application/json'
        except Exception as e:
            error_msg = f"Error processing request_params for {source.name}: {e}. Params: {req_params}"
            logger.error(error_msg)
            send_dashboard_update("scraper_error", {"source": source.name, "error": error_msg, "method": "api"})
            _create_simulated_post(source, error_msg, "api")
            return

    try:
        logger.info(f"API Request: Type={req_type}, URL={endpoint}, Headers={headers}, Params={params}, Data={data}")
        if req_type == 'POST':
            response = requests.post(endpoint, headers=headers, data=data)
        else: # Default to GET
            response = requests.get(endpoint, headers=headers, params=params)

        response.raise_for_status()
        api_data = response.json()
        logger.info(f"API Response for {source.name}: {json.dumps(api_data)[:200]}...")

        # Create an ApiResponse object
        api_response_url = f"{endpoint}/{hashlib.md5(json.dumps(api_data).encode()).hexdigest()}"
        if not ApiResponse.objects.filter(url=api_response_url).exists():
            api_response = ApiResponse.objects.create(source=source, raw_content=api_data, url=api_response_url)
            logger.info(f"New API Response recorded for {source.name}: {api_response.url}")
            send_dashboard_update("new_api_response", {"source": source.name, "url": api_response.url, "api_response_id": api_response.id})
            
            # Parse the API response into individual posts
            _parse_api_response_to_posts(api_response)
        else:
            logger.info(f"API Response with URL {api_response_url} already exists. Skipping (API).")
            send_dashboard_update("scraper_skipped", {"source": source.name, "url": api_response_url, "method": "api"})

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching from API for {source.name}: {e}")
        send_dashboard_update("scraper_error", {"source": source.name, "error": str(e), "method": "api"})
        _create_simulated_post(source, str(e), "api")
    except json.JSONDecodeError as e:
        error_msg = f"API response for {source.name} was not valid JSON: {e}. Raw response: {response.text[:200]}..."
        logger.error(error_msg)
        send_dashboard_update("scraper_error", {"source": source.name, "error": error_msg, "method": "api"})
        _create_simulated_post(source, error_msg, "api")
    except Exception as e:
        logger.error(f"An unexpected error occurred while fetching from API for {source.name}: {e}")
        send_dashboard_update("scraper_error", {"source": source.name, "error": str(e), "method": "api"})
        _create_simulated_post(source, str(e), "api")

def _parse_api_response_to_posts(api_response):
    """Parses a raw API response and creates individual Post objects."""
    logger.info(f"Parsing API response {api_response.id} from {api_response.source.name}")
    data = api_response.raw_content
    source = api_response.source

    # This is a placeholder. The actual parsing logic will depend on the API's response structure.
    # You will need to customize this based on the specific API you are integrating with.
    # For demonstration, let's assume the API returns a list of dictionaries, where each dictionary is a post.
    if isinstance(data, list):
        for item in data:
            # Assuming each item has a 'content' and 'url' field
            content = item.get('content', json.dumps(item)) # Fallback to full item if no 'content'
            post_url = item.get('url', f"{api_response.url}/post/{hashlib.md5(content.encode()).hexdigest()}")
            
            if not Post.objects.filter(url=post_url).exists():
                post = Post.objects.create(api_response=api_response, source=source, content=content, url=post_url)
                logger.info(f"New post extracted from API response: {post.url}")
                send_dashboard_update("new_post", {"source": source.name, "content_preview": content[:100] + "...", "url": post_url, "post_id": post.id, "method": "api"})
                analyze_post.delay(post.id)
            else:
                logger.info(f"Post with URL {post_url} already exists. Skipping (API Response Parsing).")
                send_dashboard_update("scraper_skipped", {"source": source.name, "url": post_url, "method": "api_parse"})
    elif isinstance(data, dict):
        # Handle single post API response or other structures
        content = data.get('content', json.dumps(data))
        post_url = data.get('url', f"{api_response.url}/post/{hashlib.md5(content.encode()).hexdigest()}")
        if not Post.objects.filter(url=post_url).exists():
            post = Post.objects.create(api_response=api_response, source=source, content=content, url=post_url)
            logger.info(f"New post extracted from API response: {post.url}")
            send_dashboard_update("new_post", {"source": source.name, "content_preview": content[:100] + "...", "url": post_url, "post_id": post.id, "method": "api"})
            analyze_post.delay(post.id)
        else:
            logger.info(f"Post with URL {post_url} already exists. Skipping (API Response Parsing).")
            send_dashboard_update("scraper_skipped", {"source": source.name, "url": post_url, "method": "api_parse"})
    else:
        logger.warning(f"Unknown API response data format for {api_response.id}. Skipping parsing.")
        send_dashboard_update("scraper_error", {"source": source.name, "error": "Unknown API response format", "method": "api_parse"})

@shared_task
def scrape_posts(source_id=None):
    """Scrape posts from all configured sources or a specific source."""
    logger.info(f"Scrape posts task initiated. Source ID: {source_id}")
    
    sources = []
    if source_id:
        try:
            sources.append(Source.objects.get(id=source_id))
        except Source.DoesNotExist:
            logger.error(f"Source with ID {source_id} not found.")
            send_dashboard_update("scraper_error", {"source": "N/A", "error": f"Source ID {source_id} not found"})
            return
    else:
        sources = Source.objects.all()

    send_dashboard_update("scraper_status", {"status": "Scraping started", "total_sources": sources.count()})
    
    for source in sources:
        if source.scraping_method == 'web':
            _scrape_web(source)
        elif source.scraping_method == 'api':
            _fetch_api_posts(source)
        elif source.scraping_method == 'both':
            _scrape_web(source)
            _fetch_api_posts(source)
        else:
            logger.warning(f"Unknown scraping method for source {source.name}: {source.scraping_method}. Skipping.")
            send_dashboard_update("scraper_skipped", {"source": source.name, "reason": f"Unknown scraping method: {source.scraping_method}"})

    send_dashboard_update("scraper_status", {"status": "Scraping finished"})
    logger.info("Scraping finished.")

@shared_task
def analyze_post(post_id):
    """Analyze a post with an LLM."""
    logger.info(f"Analyzing post {post_id} with LLM.")
    post = Post.objects.get(id=post_id)
    send_dashboard_update("analysis_status", {"post_id": post.id, "status": "Analysis started"})
    
    openai.api_key = os.getenv("OPENAI_API_KEY")
    if not openai.api_key:
        logger.error("OPENAI_API_KEY not found in environment variables. Cannot analyze post.")
        send_dashboard_update("analysis_error", {"post_id": post.id, "error": "OPENAI_API_KEY not configured"})
        return

    llm_output = {}
    raw_response_content = None
    trade_executed_flag = False

    try:
        # Initialize OpenAI client without the 'proxies' argument
        response = openai.OpenAI().chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a financial analyst. Analyze the given text for potential financial impact on a stock. Respond with a JSON object: { \"symbol\": \"STOCK_SYMBOL\", \"direction\": \"buy\", \"confidence\": 0.87, \"reason\": \"Explanation\" }. Direction can be 'buy', 'sell', or 'hold'. Confidence is a float between 0 and 1."},
                {"role": "user", "content": post.content}
            ],
            response_format={"type": "json_object"}
        )
        
        raw_response_content = response.choices[0].message.content
        llm_output = json.loads(raw_response_content)
        
        analysis = Analysis.objects.create(
            post=post,
            symbol=llm_output.get("symbol", "UNKNOWN"),
            direction=llm_output.get("direction", "hold"),
            confidence=llm_output.get("confidence", 0.0),
            reason=llm_output.get("reason", "No reason provided by LLM."),
            raw_llm_response=raw_response_content # Store the raw JSON string
        )
        logger.info(f"Analysis complete for post {post.id}: Symbol={analysis.symbol}, Direction={analysis.direction}, Confidence={analysis.confidence}")
        
        # Check if a trade will be executed based on analysis
        if analysis.direction in ['buy', 'sell']:
            trade_executed_flag = True
            execute_trade.delay(analysis.id)

        send_dashboard_update("new_analysis", {
            "post_id": post.id,
            "symbol": analysis.symbol,
            "direction": analysis.direction,
            "confidence": analysis.confidence,
            "reason": analysis.reason[:100] + "...",
            "trade_executed": trade_executed_flag
        })

    except json.JSONDecodeError as e:
        error_msg = f"LLM response for post {post.id} was not valid JSON: {e}. Raw response: {raw_response_content}"
        logger.error(error_msg)
        Analysis.objects.create(
            post=post,
            symbol="ERROR",
            direction="hold",
            confidence=0.0,
            reason=f"LLM returned invalid JSON: {e}",
            raw_llm_response=raw_response_content
        )
        send_dashboard_update("analysis_error", {"post_id": post.id, "error": error_msg})
    except Exception as e:
        error_msg = f"Error analyzing post {post.id} with LLM: {e}"
        logger.error(error_msg)
        Analysis.objects.create(
            post=post,
            symbol="ERROR",
            direction="hold",
            confidence=0.0,
            reason=f"LLM analysis failed: {e}",
            raw_llm_response=raw_response_content
        )
        send_dashboard_update("analysis_error", {"post_id": post.id, "error": error_msg})

@shared_task
def execute_trade(analysis_id):
    """Execute a trade based on an analysis."""
    logger.info(f"Executing trade for analysis {analysis_id}.")
    analysis = Analysis.objects.get(id=analysis_id)
    send_dashboard_update("trade_status", {"analysis_id": analysis.id, "status": "Trade execution started"})

    ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
    ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
    
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        logger.error("Alpaca API keys not found in environment variables. Cannot execute trade.")
        send_dashboard_update("trade_error", {"analysis_id": analysis.id, "error": "Alpaca API keys not configured"})
        return

    api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, base_url='https://paper-api.alpaca.markets') # Use paper trading for development

    try:
        if analysis.direction == 'buy':
            api.submit_order(
                symbol=analysis.symbol,
                qty=1, # Example quantity
                side='buy',
                type='market',
                time_in_force='gtc'
            )
            trade = Trade.objects.create(
                analysis=analysis,
                symbol=analysis.symbol,
                direction=analysis.direction,
                quantity=1,
                entry_price=0.0, # Will be updated by Alpaca webhook or later logic
                status='open'
            )
            logger.info(f"Submitted BUY order for {analysis.symbol}. Trade ID: {trade.id}")
            send_dashboard_update("new_trade", {
                "trade_id": trade.id,
                "symbol": trade.symbol,
                "direction": trade.direction,
                "quantity": trade.quantity,
                "status": trade.status
            })
        elif analysis.direction == 'sell':
            api.submit_order(
                symbol=analysis.symbol,
                qty=1, # Example quantity
                side='sell',
                type='market',
                time_in_force='gtc'
            )
            trade = Trade.objects.create(
                analysis=analysis,
                symbol=analysis.symbol,
                direction=analysis.direction,
                quantity=1,
                entry_price=0.0, # Will be updated by Alpaca webhook or later logic
                status='open'
            )
            logger.info(f"Submitted SELL order for {analysis.symbol}. Trade ID: {trade.id}")
            send_dashboard_update("new_trade", {
                "trade_id": trade.id,
                "symbol": trade.symbol,
                "direction": trade.direction,
                "quantity": trade.quantity,
                "status": trade.status
            })
        else:
            logger.info(f"No trade executed for {analysis.symbol} with direction {analysis.direction}")
            send_dashboard_update("trade_skipped", {"analysis_id": analysis.id, "reason": f"Direction was {analysis.direction}"})

    except Exception as e:
        error_msg = f"Error executing trade for analysis {analysis.id}: {e}"
        logger.error(error_msg)
        send_dashboard_update("trade_error", {"analysis_id": analysis.id, "error": error_msg})

@shared_task
def close_trade_manually(trade_id):
    """Manually close an open trade."""
    logger.info(f"Attempting to manually close trade {trade_id}.")
    try:
        trade = Trade.objects.get(id=trade_id, status='open')
        trade.status = 'closed'
        trade.exit_price = 0.0 # In a real scenario, this would be the actual exit price from Alpaca
        trade.save()
        logger.info(f"Trade {trade.id} for {trade.symbol} manually closed.")
        send_dashboard_update("trade_closed", {
            "trade_id": trade.id,
            "symbol": trade.symbol,
            "status": trade.status,
            "message": "Trade manually closed."
        })
    except Trade.DoesNotExist:
        error_msg = f"Trade {trade_id} not found or not open."
        logger.warning(error_msg)
        send_dashboard_update("trade_error", {"trade_id": trade_id, "error": error_msg})
    except Exception as e:
        error_msg = f"Error closing trade {trade_id} manually: {e}"
        logger.error(error_msg)
        send_dashboard_update("trade_error", {"trade_id": trade_id, "error": error_msg})