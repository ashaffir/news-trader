from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib import messages
from .models import Trade, Post, Analysis, Source, TradingConfig, ActivityLog
from .tasks import (
    close_trade_manually,
    close_all_trades_manually,
    scrape_posts,
    analyze_post,
    execute_trade,
    send_dashboard_update,
)
import logging
import json
import os
from django.utils import timezone
from datetime import datetime, timedelta
import requests
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST
from django.contrib import messages

logger = logging.getLogger(__name__)


def dashboard_view(request):
    logger.info("Dashboard view accessed.")
    # Get bot status for the dashboard
    trading_config = TradingConfig.objects.filter(is_active=True).first()
    bot_enabled = trading_config.bot_enabled if trading_config else False

    context = {"bot_enabled": bot_enabled}
    return render(request, "core/dashboard.html", context)


@csrf_exempt
def trigger_scrape_ajax(request):
    """AJAX endpoint to trigger scraping for a specific source."""
    try:
        source_id = request.POST.get("source_id")
        if not source_id:
            return JsonResponse({
                "success": False,
                "error": "No source ID provided"
            }, status=400)

        try:
            source = Source.objects.get(id=source_id)
        except Source.DoesNotExist:
            return JsonResponse({
                "success": False,
                "error": f"Source with ID {source_id} not found"
            }, status=404)

        # Trigger the scraping task (manual test mode)
        scrape_posts.delay(source_id=source_id, manual_test=True)
        logger.info(f"AJAX triggered manual test scrape_posts task for Source ID: {source_id}")

        return JsonResponse({
            "success": True,
            "message": f"Scraping started for {source.name}",
            "source_id": source_id,
            "source_name": source.name,
            "results_url": f"/api/posts/?source={source_id}"
        })

    except Exception as e:
        logger.error(f"Error in trigger_scrape_ajax: {e}")
        return JsonResponse({
            "success": False,
            "error": str(e)
        }, status=500)


@csrf_exempt
@require_POST
def trigger_analysis_ajax(request):
    """AJAX endpoint to trigger analysis for a specific post."""
    try:
        post_id = request.POST.get("post_id")
        if not post_id:
            return JsonResponse({
                "success": False,
                "error": "No post ID provided"
            }, status=400)

        try:
            post = Post.objects.get(id=post_id)
        except Post.DoesNotExist:
            return JsonResponse({
                "success": False,
                "error": f"Post with ID {post_id} not found"
            }, status=404)

        # Check if post already has analysis
        if hasattr(post, 'analysis'):
            return JsonResponse({
                "success": False,
                "error": f"Post #{post_id} already has analysis"
            }, status=400)

        # Trigger the analysis task with manual_test=True
        analyze_post.delay(post.id, manual_test=True)
        logger.info(f"AJAX triggered analyze_post task for Post ID: {post_id} (manual_test=True)")

        return JsonResponse({
            "success": True,
            "message": f"Analysis started for Post #{post_id}",
            "post_id": post_id,
            "post_source": post.source.name,
            "results_url": f"/api/analyses/?post={post_id}"
        })

    except Exception as e:
        logger.error(f"Error in trigger_analysis_ajax: {e}")
        return JsonResponse({
            "success": False,
            "error": str(e)
        }, status=500)


@csrf_exempt
def get_post_analysis_ajax(request, post_id):
    """AJAX endpoint to get analysis data for a specific post."""
    try:
        try:
            post = Post.objects.get(id=post_id)
        except Post.DoesNotExist:
            return JsonResponse({
                "success": False,
                "error": f"Post with ID {post_id} not found"
            }, status=404)
        
        # Check if post has analysis
        if not hasattr(post, 'analysis'):
            return JsonResponse({
                "success": False,
                "error": f"Post #{post_id} does not have an analysis yet"
            }, status=404)
        
        analysis = post.analysis
        
        # Format the analysis data
        analysis_data = {
            "post_id": post.id,
            "post_title": f"Post #{post.id} from {post.source.name}",
            "post_content": post.content[:200] + "..." if len(post.content) > 200 else post.content,
            "post_source": post.source.name,
            "post_url": post.url,
            "post_created_at": post.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": analysis.symbol,
            "direction": analysis.direction,
            "confidence": round(analysis.confidence, 3),
            "confidence_percentage": round(analysis.confidence * 100, 1),
            "reason": analysis.reason,
            "sentiment_score": round(analysis.sentiment_score, 3) if analysis.sentiment_score else None,
            "market_impact_score": round(analysis.market_impact_score, 3) if analysis.market_impact_score else None,
            "trading_config_used": analysis.trading_config_used.name if analysis.trading_config_used else "Default",
            "analysis_created_at": analysis.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "raw_llm_response": analysis.raw_llm_response
        }
        
        return JsonResponse({
            "success": True,
            "analysis": analysis_data
        })
        
    except Exception as e:
        logger.error(f"Error in get_post_analysis_ajax for post {post_id}: {e}")
        return JsonResponse({
            "success": False,
            "error": str(e)
        }, status=500)


@csrf_exempt
@require_POST
def toggle_bot_status(request):
    """Toggle the bot enabled/disabled status."""
    try:
        trading_config = TradingConfig.objects.filter(is_active=True).first()
        if not trading_config:
            # Create default config if none exists
            trading_config = TradingConfig.objects.create(
                name="Default Trading Configuration",
                is_active=True,
                bot_enabled=True,
                trading_enabled=True,
                default_position_size=100.0,
                max_position_size=1000.0,
                stop_loss_percentage=5.0,
                take_profit_percentage=10.0,
                min_confidence_threshold=0.7,
                max_daily_trades=10,
                llm_model="gpt-3.5-turbo",
                market_hours_only=True,
            )

        # Toggle the bot status
        trading_config.bot_enabled = not trading_config.bot_enabled
        trading_config.save()

        status = "enabled" if trading_config.bot_enabled else "disabled"
        logger.info(f"Bot status toggled to: {status}")

        return JsonResponse(
            {
                "success": True,
                "bot_enabled": trading_config.bot_enabled,
                "message": f"Bot {status} successfully",
            }
        )

    except Exception as e:
        logger.error(f"Error toggling bot status: {e}")
        return JsonResponse({"success": False, "error": str(e)}, status=500)


def system_status_api(request):
    """API endpoint to provide comprehensive system status for the dashboard."""
    try:
        # Get current time
        now = timezone.now()
        last_24h = now - timedelta(hours=24)
        last_hour = now - timedelta(hours=1)

        # API Status Checks
        api_status = {
            "openai": check_openai_api(),
            "news_sources": check_news_sources_status(),
            "alpaca": check_alpaca_api(),
        }

        # Get real Alpaca trading data and sync with database
        alpaca_data = get_alpaca_trading_data()
        alpaca_positions = alpaca_data.get("positions", [])
        sync_alpaca_positions_to_database(alpaca_positions)

        # System Statistics
        stats = {
            "total_sources": Source.objects.count(),
            "active_sources": Source.objects.filter(scraping_enabled=True).count(),
            "total_posts": Post.objects.count(),
            "posts_24h": Post.objects.filter(created_at__gte=last_24h).count(),
            "posts_1h": Post.objects.filter(created_at__gte=last_hour).count(),
            "total_analyses": Analysis.objects.count(),
            "analyses_24h": Analysis.objects.filter(created_at__gte=last_24h).count(),
            "total_trades": Trade.objects.count(),
            "open_trades": Trade.objects.filter(status__in=["open", "pending_close"]).count(),  # Synced database count
            "trades_24h": Trade.objects.filter(created_at__gte=last_24h).count(),
        }

        # Trading Performance from Alpaca
        recent_trades = Trade.objects.filter(created_at__gte=last_24h)
        winning_trades = recent_trades.filter(realized_pnl__gt=0).count()
        total_recent_trades = recent_trades.count()
        win_rate = (
            (winning_trades / total_recent_trades * 100)
            if total_recent_trades > 0
            else 0
        )

        performance = {
            "win_rate": round(win_rate, 1),
            "total_pnl_24h": round(alpaca_data["total_pnl"], 2),  # Real Alpaca P&L
            "day_pnl": round(alpaca_data["day_pnl"], 2),  # Real day P&L
            "avg_confidence": get_avg_confidence(),
            "account_value": round(
                alpaca_data["account_value"], 2
            ),  # Real account value
            "buying_power": round(alpaca_data.get("buying_power", 0), 2),
            "alpaca_positions": alpaca_data.get("positions", []),
        }

        # Source Status
        sources_status = []
        for source in Source.objects.all():
            sources_status.append(
                {
                    "id": source.id,
                    "name": source.name,
                    "enabled": source.scraping_enabled,
                    "status": source.scraping_status,
                    "last_scraped": (
                        source.last_scraped_at.isoformat()
                        if source.last_scraped_at
                        else None
                    ),
                    "error_count": source.error_count,
                    "posts_count": source.individual_posts.count(),
                }
            )

        # Recent Activity
        recent_posts = Post.objects.order_by("-created_at")[:5]
        recent_activity = []
        for post in recent_posts:
            activity = {
                "type": "post",
                "timestamp": post.created_at.isoformat(),
                "source": post.source.name,
                "content_preview": (
                    post.content[:100] + "..."
                    if len(post.content) > 100
                    else post.content
                ),
                "has_analysis": hasattr(post, "analysis"),
            }
            if hasattr(post, "analysis"):
                activity["analysis"] = {
                    "symbol": post.analysis.symbol,
                    "direction": post.analysis.direction,
                    "confidence": post.analysis.confidence,
                }
            recent_activity.append(activity)

        # Trading Configuration
        active_config = TradingConfig.objects.filter(is_active=True).first()
        config_info = None
        if active_config:
            config_info = {
                "name": active_config.name,
                "trading_enabled": active_config.trading_enabled,
                "bot_enabled": active_config.bot_enabled,
                "min_confidence": active_config.min_confidence_threshold,
                "max_daily_trades": active_config.max_daily_trades,
                "position_size": active_config.default_position_size,
            }

        return JsonResponse(
            {
                "timestamp": now.isoformat(),
                "api_status": api_status,
                "statistics": stats,
                "performance": performance,
                "sources": sources_status,
                "recent_activity": recent_activity,
                "trading_config": config_info,
            }
        )

    except Exception as e:
        logger.error(f"Error getting system status: {e}")
        return JsonResponse({"error": str(e)}, status=500)


def check_openai_api():
    """Check if OpenAI API is accessible with real connection test."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {"status": "error", "message": "API key not configured"}

    try:
        # Real API test - make a simple request to verify connectivity
        import requests

        headers = {"Authorization": f"Bearer {api_key}"}
        response = requests.get(
            "https://api.openai.com/v1/models", headers=headers, timeout=10
        )

        if response.status_code == 200:
            return {"status": "ok", "message": "API connected and responding"}
        elif response.status_code == 401:
            return {"status": "error", "message": "Invalid API key"}
        elif response.status_code == 429:
            return {"status": "warning", "message": "Rate limit exceeded"}
        else:
            return {"status": "error", "message": f"API error: {response.status_code}"}

    except requests.exceptions.Timeout:
        return {"status": "warning", "message": "Connection timeout"}
    except requests.exceptions.ConnectionError:
        return {"status": "error", "message": "Cannot reach OpenAI servers"}
    except Exception as e:
        return {"status": "error", "message": f"Connection error: {str(e)}"}


def check_newsapi_api():
    """Check if NewsAPI is accessible."""
    api_key = os.getenv("NEWSAPI_KEY")
    if not api_key:
        return {"status": "error", "message": "API key not configured"}

    try:
        # Quick API test
        response = requests.get(
            "https://newsapi.org/v2/top-headlines",
            params={"apiKey": api_key, "pageSize": 1, "country": "us"},
            timeout=5,
        )
        if response.status_code == 200:
            return {"status": "ok", "message": "API responding"}
        else:
            return {"status": "error", "message": f"API error: {response.status_code}"}
    except Exception as e:
        return {"status": "warning", "message": f"Connection error: {str(e)}"}


def check_alpaca_api():
    """Check if Alpaca API is accessible with real connection test using alpaca-py."""
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    if not api_key or not secret_key:
        return {"status": "error", "message": "API keys not configured"}

    try:
        # Real API test using alpaca-trade-api
        import alpaca_trade_api as tradeapi

        # Create TradingClient instance
        trading_client = tradeapi.REST(
            api_key,
            secret_key,
            base_url=base_url
        )

        # Test connection by getting account information
        account = trading_client.get_account()

        if account and hasattr(account, "status"):
            return {
                "status": "ok",
                "message": f"Trading account connected ({account.status})",
                "account_status": account.status,
                "buying_power": (
                    str(account.buying_power)
                    if hasattr(account, "buying_power")
                    else None
                ),
            }
        else:
            return {"status": "warning", "message": "Account data incomplete"}

    except ImportError:
        return {"status": "error", "message": "alpaca-trade-api package not installed"}
    except Exception as e:
        return {"status": "error", "message": f"Connection failed: {str(e)}"}


def get_alpaca_trading_data():
    """Get real trading data from Alpaca API."""
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    if not api_key or not secret_key:
        return {
            "open_positions": 0,
            "account_value": 10000,
            "total_pnl": 0.0,
            "day_pnl": 0.0,
            "error": "API keys not configured",
        }

    try:
        import alpaca_trade_api as tradeapi

        trading_client = tradeapi.REST(
            api_key, secret_key, base_url=base_url
        )

        # Get account info
        account = trading_client.get_account()

        # Get positions
        positions = trading_client.list_positions()

        # Calculate metrics
        open_positions = len(positions)
        account_value = (
            float(account.portfolio_value) if account.portfolio_value else 10000
        )
        total_pnl = (
            float(account.total_profit_loss)
            if hasattr(account, "total_profit_loss") and account.total_profit_loss
            else 0.0
        )
        day_pnl = (
            float(account.day_profit_loss)
            if hasattr(account, "day_profit_loss") and account.day_profit_loss
            else 0.0
        )

        return {
            "open_positions": open_positions,
            "account_value": account_value,
            "total_pnl": total_pnl,
            "day_pnl": day_pnl,
            "buying_power": (
                float(account.buying_power) if account.buying_power else 0.0
            ),
            "positions": [
                {
                    "symbol": pos.symbol,
                    "qty": float(pos.qty),
                    "market_value": (
                        float(pos.market_value) if pos.market_value else 0.0
                    ),
                    "unrealized_pl": (
                        float(pos.unrealized_pl) if pos.unrealized_pl else 0.0
                    ),
                }
                for pos in positions
            ],
        }

    except Exception as e:
        logger.error(f"Error getting Alpaca trading data: {e}")
        return {
            "open_positions": 0,
            "account_value": 10000,
            "total_pnl": 0.0,
            "day_pnl": 0.0,
            "error": str(e),
        }


def check_news_sources_status():
    """Check the overall status of all news sources."""
    try:
        total_sources = Source.objects.count()
        if total_sources == 0:
            return {
                "status": "warning",
                "message": "No sources configured",
                "count": 0,
                "active_count": 0,
            }

        active_sources = Source.objects.filter(scraping_enabled=True).count()
        error_sources = Source.objects.filter(scraping_status="error").count()
        running_sources = Source.objects.filter(scraping_status="running").count()

        # Determine overall status
        if error_sources > 0:
            status = "error"
            message = f"{error_sources} source(s) have errors"
        elif active_sources == 0:
            status = "warning"
            message = "No active sources"
        elif running_sources > 0:
            status = "ok"
            message = f"{running_sources} source(s) running"
        else:
            status = "ok"
            message = f"{active_sources} source(s) ready"

        return {
            "status": status,
            "message": message,
            "count": total_sources,
            "active_count": active_sources,
            "error_count": error_sources,
            "running_count": running_sources,
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "count": 0, "active_count": 0}


def get_avg_confidence():
    """Get average confidence from recent analyses."""
    last_24h = timezone.now() - timedelta(hours=24)
    recent_analyses = Analysis.objects.filter(created_at__gte=last_24h)
    if recent_analyses.exists():
        total_confidence = sum(a.confidence for a in recent_analyses)
        return round(total_confidence / recent_analyses.count(), 2)
    return 0


def check_single_connection(request, service):
    """API endpoint to check connection to a specific service."""
    try:
        if service == "openai":
            result = check_openai_api()
        elif service == "alpaca":
            result = check_alpaca_api()
        else:
            return JsonResponse(
                {"status": "error", "message": f"Unknown service: {service}"},
                status=400,
            )

        return JsonResponse(result)

    except Exception as e:
        logger.error(f"Error checking {service} connection: {e}")
        return JsonResponse(
            {"status": "error", "message": f"Failed to check {service}: {str(e)}"},
            status=500,
        )


def sync_alpaca_positions_to_database(alpaca_positions):
    """Sync Alpaca positions with database Trade records."""
    from .models import Trade, Analysis

    logger.info(f"Syncing {len(alpaca_positions)} Alpaca positions to database...")

    # Get all symbols from Alpaca
    alpaca_symbols = {pos["symbol"] for pos in alpaca_positions}

    # Create or update database records for each Alpaca position
    for position in alpaca_positions:
        symbol = position["symbol"]
        direction = "buy" if float(position["qty"]) > 0 else "sell"
        quantity = abs(float(position["qty"]))

        # Calculate entry price from market value and quantity
        qty = float(position["qty"])
        market_value = float(position["market_value"])
        entry_price = abs(market_value) / abs(qty) if qty != 0 else 0

        unrealized_pnl = float(position.get("unrealized_pl", 0))

        # Check if trade record already exists
        existing_trade = Trade.objects.filter(symbol=symbol, status="open").first()

        if not existing_trade:
            # Create new trade record
            # Try to find recent analysis for this symbol
            analysis = Analysis.objects.filter(symbol=symbol).order_by('-created_at').first()

            trade = Trade.objects.create(
                analysis=analysis,
                symbol=symbol,
                direction=direction,
                quantity=quantity,
                entry_price=entry_price,
                status="open",
                alpaca_order_id=f"sync_{symbol}_{int(timezone.now().timestamp())}",
                opened_at=timezone.now(),
                unrealized_pnl=unrealized_pnl,
            )
            logger.debug(f"Created new trade record for {symbol}")
        else:
            # Update existing trade with current Alpaca data
            existing_trade.quantity = quantity
            existing_trade.unrealized_pnl = unrealized_pnl
            existing_trade.updated_at = timezone.now()
            existing_trade.save()
            logger.debug(f"Updated trade record for {symbol}")

    # Close database trades that no longer exist in Alpaca
    db_open_trades = Trade.objects.filter(status="open")
    for db_trade in db_open_trades:
        if db_trade.symbol not in alpaca_symbols:
            # Position no longer exists in Alpaca, mark as closed
            db_trade.status = "closed"
            db_trade.close_reason = "position_closed_externally"
            db_trade.closed_at = timezone.now()
            db_trade.save()
            logger.info(f"Marked {db_trade.symbol} as closed (no longer in Alpaca)")


def manual_close_trade_view(request):
    logger.info("Manual close trade view accessed.")

    # Get real Alpaca positions
    alpaca_data = get_alpaca_trading_data()
    alpaca_positions = alpaca_data.get("positions", [])

    # Sync Alpaca positions with database
    sync_alpaca_positions_to_database(alpaca_positions)

    # Get trades with pending_close status first
    pending_close_trades = Trade.objects.filter(status="pending_close")
    pending_symbols = {trade.symbol for trade in pending_close_trades}

    # Convert Alpaca positions to trade-like objects for the template
    open_trades = []

    # Add pending_close trades first
    for trade in pending_close_trades:
        # Use the database trade object directly, but enhance with Alpaca data if available
        alpaca_pos = next((pos for pos in alpaca_positions if pos["symbol"] == trade.symbol), None)
        if alpaca_pos:
            trade.unrealized_pnl = float(alpaca_pos["unrealized_pl"])
            trade.alpaca_position = True
        else:
            trade.alpaca_position = False
        open_trades.append(trade)

    # Then add Alpaca positions that aren't pending close
    for pos in alpaca_positions:
        if pos["symbol"] in pending_symbols:
            continue  # Skip this position as it's already added as pending_close
        # Create a proper object with all necessary attributes
        class AlpacaTrade:
            def __init__(self, position_data):
                self.id = f"alpaca_{position_data['symbol']}"
                self.symbol = position_data["symbol"]
                self.direction = "buy" if float(position_data["qty"]) > 0 else "sell"
                self.quantity = abs(float(position_data["qty"]))
                qty = float(position_data["qty"])
                market_value = float(position_data["market_value"])
                # For short positions, market_value is negative, so we need absolute value
                self.entry_price = abs(market_value) / abs(qty) if qty != 0 else 0
                self.status = "open"
                self.unrealized_pnl = float(position_data["unrealized_pl"])
                self.created_at = timezone.now()
                self.alpaca_position = True

                # Get TP/SL from database if available
                try:
                    db_trade = Trade.objects.filter(symbol=self.symbol, status="open").first()
                    if db_trade:
                        self.take_profit_price = db_trade.take_profit_price
                        self.stop_loss_price = db_trade.stop_loss_price
                        self.created_at = db_trade.created_at or timezone.now()
                    else:
                        self.take_profit_price = None
                        self.stop_loss_price = None
                except:
                    self.take_profit_price = None
                    self.stop_loss_price = None

                # Calculate P&L percentage based on cost basis
                cost_basis = self.entry_price * self.quantity
                if cost_basis > 0:
                    self.pnl_percentage = (self.unrealized_pnl / cost_basis) * 100
                else:
                    self.pnl_percentage = 0.0

                # Check if we have stored TP/SL settings for this symbol
                try:
                    stored_trade = Trade.objects.get(
                        symbol=self.symbol,
                        status="open",
                        alpaca_order_id=f"position_{self.symbol}",
                    )
                    self.take_profit_price = stored_trade.take_profit_price
                    self.stop_loss_price = stored_trade.stop_loss_price
                    self.take_profit_price_percentage = stored_trade.take_profit_price_percentage
                    self.stop_loss_price_percentage = stored_trade.stop_loss_price_percentage
                except Trade.DoesNotExist:
                    pass

                # If we only have prices but no percentages, calculate them
                if self.take_profit_price and not hasattr(self, 'take_profit_price_percentage'):
                    if self.entry_price and self.entry_price > 0:
                        self.take_profit_price_percentage = ((self.take_profit_price - self.entry_price) / self.entry_price) * 100
                    else:
                        self.take_profit_price_percentage = None

                if self.stop_loss_price and not hasattr(self, 'stop_loss_price_percentage'):
                    if self.entry_price and self.entry_price > 0:
                        self.stop_loss_price_percentage = abs(((self.stop_loss_price - self.entry_price) / self.entry_price) * 100)
                    else:
                        self.stop_loss_price_percentage = None

                # Initialize percentage fields if they don't exist
                if not hasattr(self, 'take_profit_price_percentage'):
                    self.take_profit_price_percentage = None
                if not hasattr(self, 'stop_loss_price_percentage'):
                    self.stop_loss_price_percentage = None  # No stored settings

        trade_obj = AlpacaTrade(pos)
        open_trades.append(trade_obj)

    # Also include local database trades that might have Alpaca order IDs
    local_trades = Trade.objects.filter(status__in=["open", "pending"])
    for trade in local_trades:
        # Only add if not already represented by Alpaca position
        if not any(pos["symbol"] == trade.symbol for pos in alpaca_positions):
            trade.alpaca_position = False
            # Calculate P&L percentage for local trades too
            if trade.entry_price and trade.quantity and trade.entry_price > 0:
                cost_basis = trade.entry_price * trade.quantity
                trade.pnl_percentage = ((trade.unrealized_pnl or 0) / cost_basis) * 100
            else:
                trade.pnl_percentage = 0.0
            open_trades.append(trade)

    if request.method == "POST":
        # Handle both form data and JSON requests
        if request.content_type == 'application/json':
            import json
            try:
                data = json.loads(request.body)
                action = data.get("action")
                trade_id = data.get("trade_id")
                request_data = data
            except json.JSONDecodeError:
                return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
        else:
            action = request.POST.get("action")
            trade_id = request.POST.get("trade_id")
            request_data = request.POST

        if action == "close_all":
            logger.info("Initiating close all trades request.")
            try:
                # Execute the close all task
                close_all_trades_manually.delay()
                logger.info("Close all trades task initiated successfully.")
                messages.success(
                    request,
                    "Close all trades request has been initiated. Please wait for processing to complete.",
                )
            except Exception as e:
                logger.error(f"Error initiating close all trades: {e}")
                messages.error(
                    request, f"Failed to initiate close all trades: {str(e)}"
                )
            return redirect("close_trade")

        elif action == "close_trade" and trade_id:
            logger.info(f"Attempting to close trade with ID: {trade_id}")

            # Check if this is an Alpaca position (ID starts with "alpaca_")
            if trade_id.startswith("alpaca_"):
                symbol = trade_id.replace("alpaca_", "")
                logger.info(f"Closing Alpaca position for symbol: {symbol}")

                try:
                    # Import necessary modules for Alpaca API
                    import os
                    import alpaca_trade_api as tradeapi

                    # Get Alpaca credentials
                    ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
                    ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
                    ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

                    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
                        logger.error("Alpaca API credentials not found")
                        messages.error(request, "Alpaca API credentials not configured")
                        return redirect("close_trade")

                    # Initialize Alpaca API
                    api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, base_url=ALPACA_BASE_URL)

                    # Get current position to determine quantity and side
                    position = api.get_position(symbol)
                    qty = abs(float(position.qty))
                    current_side = "long" if float(position.qty) > 0 else "short"
                    close_side = "sell" if current_side == "long" else "buy"

                    # Submit close order
                    close_order = api.submit_order(
                        symbol=symbol,
                        qty=qty,
                        side=close_side,
                        type="market",
                        time_in_force="gtc",
                    )

                    logger.info(f"Successfully submitted close order for {symbol}: Order ID {close_order.id}")

                    # Get current price for exit price
                    try:
                        ticker = api.get_latest_trade(symbol)
                        exit_price = ticker.price
                    except:
                        # Use current market price or fallback to average entry price
                        exit_price = float(position.avg_entry_price)

                    # Find or create Trade record for this position
                    trade_record = None

                    # First try to find existing trade record with this Alpaca position
                    try:
                        trade_record = Trade.objects.get(
                            symbol=symbol,
                            status="open",
                            alpaca_order_id=f"position_{symbol}"
                        )
                    except Trade.DoesNotExist:
                        # Try to find any open trade for this symbol
                        try:
                            trade_record = Trade.objects.filter(
                                symbol=symbol,
                                status="open"
                            ).first()
                        except:
                            pass

                    # If no trade record found, create a new one
                    if not trade_record:
                        # Try to get most recent analysis for this symbol
                        analysis = Analysis.objects.filter(symbol=symbol).order_by('-created_at').first()

                        trade_record = Trade.objects.create(
                            analysis=analysis,  # May be None
                            symbol=symbol,
                            direction="buy" if current_side == "long" else "sell",
                            quantity=qty,
                            entry_price=float(position.avg_entry_price),
                            status="open",
                            alpaca_order_id=f"position_{symbol}",
                            opened_at=timezone.now()
                        )
                        logger.info(f"Created new trade record for Alpaca position {symbol}")

                    # Calculate P&L
                    if trade_record.direction == "buy" or current_side == "long":
                        pnl = (exit_price - trade_record.entry_price) * trade_record.quantity
                    else:
                        pnl = (trade_record.entry_price - exit_price) * trade_record.quantity

                    # Update trade record with closure information
                    trade_record.status = "closed"
                    trade_record.exit_price = exit_price
                    trade_record.realized_pnl = pnl
                    trade_record.close_reason = "manual"
                    trade_record.closed_at = timezone.now()
                    trade_record.save()

                    logger.info(f"Updated trade record {trade_record.id} for {symbol} closure with P&L: ${pnl:.2f}")

                    messages.success(
                        request,
                        f"Close order for {symbol} has been submitted to Alpaca (Order ID: {close_order.id}). P&L: ${pnl:.2f}"
                    )

                    # Send update to dashboard activity log
                    send_dashboard_update(
                        "trade_close_requested",
                        {
                            "symbol": symbol,
                            "order_id": close_order.id,
                            "message": f"Close order submitted for {symbol} via Alpaca API",
                            "status": "submitted",
                            "pnl": pnl
                        }
                    )

                    # Send trade closed update
                    send_dashboard_update(
                        "trade_closed",
                        {
                            "trade_id": trade_record.id,
                            "symbol": symbol,
                            "status": "closed",
                            "exit_price": exit_price,
                            "realized_pnl": pnl,
                            "message": f"Alpaca position {symbol} manually closed",
                            "pnl": pnl
                        }
                    )

                except Exception as e:
                    logger.error(f"Failed to close Alpaca position {symbol}: {str(e)}")
                    messages.error(
                        request,
                        f"Failed to close position for {symbol}: {str(e)}"
                    )

                return redirect("close_trade")

            # Handle regular database trades
            try:
                trade = Trade.objects.get(id=trade_id, status="open")
                # Update status to pending_close first
                trade.status = "pending_close"
                trade.save()

                close_trade_manually.delay(trade.id)
                logger.info(f"Initiated manual close for trade {trade.id} - Status updated to pending_close.")
                messages.success(
                    request,
                    f"Close order for {trade.symbol} has been submitted"
                )

                # Send update to dashboard activity log
                send_dashboard_update(
                    "trade_close_requested",
                    {
                        "symbol": trade.symbol,
                        "trade_id": trade.id,
                        "message": f"Manual close initiated for {trade.symbol}",
                        "status": "initiated"
                    }
                )
                return redirect("close_trade")  # Redirect to refresh the page
            except Trade.DoesNotExist:
                logger.warning(
                    f"Attempted to close non-existent or already closed trade with ID: {trade_id}"
                )
                messages.error(
                    request,
                    f"Trade not found or already closed"
                )
            except Exception as e:
                logger.error(
                    f"An unexpected error occurred while processing manual close for trade {trade_id}: {e}"
                )
                messages.error(
                    request,
                    f"Error closing trade: {str(e)}"
                )

        elif action == "edit_trade" and trade_id:
            logger.info(f"Attempting to edit trade settings for ID: {trade_id}")
            try:
                take_profit_percent = request_data.get("take_profit_percent")
                stop_loss_percent = request_data.get("stop_loss_percent")

                # Handle Alpaca positions (they have alpaca_ prefix)
                if trade_id.startswith("alpaca_"):
                    symbol = trade_id.replace("alpaca_", "")
                    logger.info(
                        f"Updating take profit/stop loss for Alpaca position: {symbol}"
                    )

                    # Get current position data to calculate entry price
                    alpaca_data = get_alpaca_trading_data()
                    alpaca_positions = alpaca_data.get("positions", [])
                    position = next(
                        (p for p in alpaca_positions if p["symbol"] == symbol), None
                    )

                    if position:
                        entry_price = (
                            float(position["market_value"])
                            / abs(float(position["qty"]))
                            if float(position["qty"]) != 0
                            else 0
                        )

                        # Calculate actual prices from percentages
                        take_profit_price = None
                        stop_loss_price = None

                        if take_profit_percent:
                            take_profit_price = entry_price * (
                                1 + float(take_profit_percent) / 100
                            )

                        if stop_loss_percent:
                            stop_loss_price = entry_price * (
                                1 - float(stop_loss_percent) / 100
                            )

                        # Find existing trade for this symbol, don't create duplicates
                        trade = Trade.objects.filter(
                            symbol=symbol,
                            status="open"
                        ).first()

                        if not trade:
                            # Only create if no existing trade found
                            trade = Trade.objects.create(
                                symbol=symbol,
                                status="open",
                                alpaca_order_id=f"position_{symbol}",
                                analysis=None,  # Manual TP/SL doesn't need analysis
                                direction="buy" if float(position["qty"]) > 0 else "sell",
                                quantity=abs(float(position["qty"])),
                                entry_price=entry_price,
                            )

                        # Update the take profit and stop loss prices
                        if take_profit_price:
                            trade.take_profit_price = take_profit_price
                            trade.take_profit_price_percentage = take_profit_percent
                        if stop_loss_price:
                            trade.stop_loss_price = stop_loss_price
                            trade.stop_loss_price_percentage = stop_loss_percent
                        trade.save()

                        tp_display = f"${take_profit_price:.2f}" if take_profit_price else "None"
                        sl_display = f"${stop_loss_price:.2f}" if stop_loss_price else "None"
                        logger.info(
                            f"Updated trade settings for {symbol}: TP={tp_display}, SL={sl_display}"
                        )

                        # Add success message for Alpaca positions
                        tp_msg = f"TP: {take_profit_percent}%" if take_profit_percent else "TP: None"
                        sl_msg = f"SL: {stop_loss_percent}%" if stop_loss_percent else "SL: None"
                        messages.success(
                            request,
                            f"Trade settings updated successfully for {symbol} - {tp_msg}, {sl_msg}"
                        )

                        # Log activity for TP/SL change
                        send_dashboard_update(
                            "trade_status",
                            {
                                "trade_id": trade_id,
                                "symbol": symbol,
                                "status": f"TP/SL updated: {tp_msg}, {sl_msg}",
                                "take_profit_price": take_profit_price,
                                "stop_loss_price": stop_loss_price,
                                "take_profit_percent": take_profit_percent,
                                "stop_loss_percent": stop_loss_percent,
                            }
                        )

                        # TODO: Implement actual Alpaca bracket order creation here
                        # This would involve canceling existing position and creating new bracket order

                else:
                    # Handle local database trades
                    trade = Trade.objects.get(id=trade_id, status="open")

                    # Calculate actual prices from percentages and store percentages
                    if take_profit_percent:
                        trade.take_profit_price = trade.entry_price * (
                            1 + float(take_profit_percent) / 100
                        )
                        trade.take_profit_price_percentage = float(take_profit_percent)
                    else:
                        trade.take_profit_price = None
                        trade.take_profit_price_percentage = None

                    if stop_loss_percent:
                        trade.stop_loss_price = trade.entry_price * (
                            1 - float(stop_loss_percent) / 100
                        )
                        trade.stop_loss_price_percentage = float(stop_loss_percent)
                    else:
                        trade.stop_loss_price = None
                        trade.stop_loss_price_percentage = None

                    trade.save()
                    logger.info(f"Updated trade settings for trade {trade.id}")

                    # Add success message
                    tp_msg = f"TP: {take_profit_percent}%" if take_profit_percent else "TP: None"
                    sl_msg = f"SL: {stop_loss_percent}%" if stop_loss_percent else "SL: None"
                    messages.success(
                        request,
                        f"Trade settings updated successfully for {trade.symbol} - {tp_msg}, {sl_msg}"
                    )

                    # Log activity for TP/SL change
                    send_dashboard_update(
                        "trade_status",
                        {
                            "trade_id": trade.id,
                            "symbol": trade.symbol,
                            "status": f"TP/SL updated: {tp_msg}, {sl_msg}",
                            "take_profit_price": trade.take_profit_price,
                            "stop_loss_price": trade.stop_loss_price,
                            "take_profit_percent": take_profit_percent,
                            "stop_loss_percent": stop_loss_percent,
                        }
                    )

                # Return JSON response for AJAX requests
                if request.content_type == 'application/json':
                    # Determine symbol name for response
                    response_symbol = symbol if "alpaca_" in trade_id else (trade.symbol if 'trade' in locals() else 'Unknown')
                    
                    logger.info(f"Returning JSON success response for {response_symbol}")
                    return JsonResponse({
                        'success': True,
                        'message': f'Trade settings updated successfully for {response_symbol}',
                        'take_profit_percent': take_profit_percent,
                        'stop_loss_percent': stop_loss_percent
                    })
                else:
                    return redirect("close_trade")

            except Exception as e:
                logger.error(f"Error updating trade settings for {trade_id}: {e}")
                messages.error(request, f"Error updating trade settings: {str(e)}")
                
                # Return JSON error for AJAX requests
                if request.content_type == 'application/json':
                    return JsonResponse({
                        'success': False,
                        'error': f'Error updating trade settings: {str(e)}'
                    })
                else:
                    return redirect("close_trade")

        elif action == "cancel_trade" and trade_id:
            logger.info(f"Attempting to cancel pending trade with ID: {trade_id}")
            try:
                trade = Trade.objects.get(id=trade_id, status="pending")
                
                # Cancel the order via Alpaca API if it has an order ID
                if trade.alpaca_order_id:
                    import os
                    import alpaca_trade_api as tradeapi
                    
                    api_key = os.getenv("ALPACA_API_KEY")
                    secret_key = os.getenv("ALPACA_SECRET_KEY")
                    base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
                    
                    if api_key and secret_key:
                        api = tradeapi.REST(api_key, secret_key, base_url=base_url)
                        api.cancel_order(trade.alpaca_order_id)
                        logger.info(f"Cancelled Alpaca order {trade.alpaca_order_id} for trade {trade_id}")
                
                # Update trade status to cancelled
                trade.status = "cancelled"
                trade.save()
                
                messages.success(
                    request,
                    f"Pending order for {trade.symbol} has been cancelled successfully"
                )
                
                # Send update to dashboard activity log
                send_dashboard_update(
                    "trade_cancelled", 
                    {
                        "trade_id": trade.id,
                        "symbol": trade.symbol,
                        "message": f"Pending order for {trade.symbol} cancelled by user",
                        "status": "cancelled"
                    }
                )
                
            except Trade.DoesNotExist:
                logger.warning(f"Attempted to cancel non-existent or non-pending trade with ID: {trade_id}")
                messages.error(request, "Trade not found or not in pending status")
            except Exception as e:
                logger.error(f"Error cancelling trade {trade_id}: {e}")
                messages.error(request, f"Error cancelling trade: {str(e)}")
            
            return redirect("close_trade")

    # Calculate total unrealized P&L for summary
    total_unrealized_pnl = sum(
        getattr(trade, "unrealized_pnl", 0) for trade in open_trades
    )

    # Get bot status for navbar
    trading_config = TradingConfig.objects.filter(is_active=True).first()
    bot_enabled = trading_config.bot_enabled if trading_config else False

    return render(
        request,
        "core/close_trade.html",
        {
            "open_trades": open_trades,
            "total_unrealized_pnl": total_unrealized_pnl,
            "bot_enabled": bot_enabled,
        },
    )


def test_page_view(request):
    logger.info("Test page accessed.")
    if request.method == "POST":
        action = request.POST.get("action")

        if action == "trigger_scrape":
            source_id = request.POST.get("source_id")
            if source_id:
                try:
                    # Pass the source_id to the scrape_posts task as manual test
                    scrape_posts.delay(source_id=source_id, manual_test=True)
                    logger.info(
                        f"Manually triggered test scrape_posts task for Source ID: {source_id}."
                    )
                except Source.DoesNotExist:
                    logger.warning(
                        f"Source with ID {source_id} not found for scraping."
                    )
            else:
                logger.warning("No Source ID provided for manual scrape trigger.")
        elif action == "trigger_analysis":
            post_id = request.POST.get("post_id")
            if post_id:
                try:
                    post = Post.objects.get(id=post_id)
                    analyze_post.delay(post.id)
                    logger.info(
                        f"Manually triggered analyze_post task for Post ID: {post_id}."
                    )
                except Post.DoesNotExist:
                    logger.warning(f"Post with ID {post_id} not found for analysis.")
            else:
                logger.warning("No Post ID provided for manual analysis trigger.")
        elif action == "trigger_trade":
            analysis_id = request.POST.get("analysis_id")
            if analysis_id:
                try:
                    analysis = Analysis.objects.get(id=analysis_id)
                    execute_trade.delay(analysis.id)
                    logger.info(
                        f"Manually triggered execute_trade task for Analysis ID: {analysis_id}."
                    )
                except Analysis.DoesNotExist:
                    logger.warning(
                        f"Analysis with ID {analysis_id} not found for trade execution."
                    )
            else:
                logger.warning("No Analysis ID provided for manual trade trigger.")
        elif action == "manual_test_trade":
            symbol = request.POST.get("symbol", "").upper().strip()
            direction = request.POST.get("direction", "").lower().strip()
            quantity = request.POST.get("quantity", "").strip()
            position_size = request.POST.get("position_size", "").strip()

            if symbol and direction in ["buy", "sell"]:
                try:
                    from .tasks import create_manual_test_trade

                    # Convert inputs to appropriate types
                    quantity_int = int(quantity) if quantity else None
                    position_size_float = float(position_size) if position_size else None

                    # Validate at least one of quantity or position_size is provided
                    if not quantity_int and not position_size_float:
                        quantity_int = 1  # Default to 1 share

                    create_manual_test_trade.delay(
                        symbol=symbol,
                        direction=direction,
                        quantity=quantity_int,
                        position_size=position_size_float
                    )
                    logger.info(
                        f"Manually triggered test trade: {symbol} {direction} qty={quantity_int} pos_size={position_size_float}"
                    )
                    messages.success(
                        request,
                        f"Test trade submitted: {symbol} {direction.upper()}"
                    )
                except ValueError as e:
                    logger.warning(f"Invalid input for manual test trade: {e}")
                    messages.error(request, "Invalid quantity or position size. Please enter valid numbers.")
                except Exception as e:
                    logger.error(f"Error creating manual test trade: {e}")
                    messages.error(request, f"Error creating test trade: {str(e)}")
            else:
                logger.warning(f"Invalid manual test trade parameters: symbol={symbol}, direction={direction}")
                messages.error(request, "Please provide a valid symbol and direction (buy/sell).")

        return redirect(
            "test_page"
        )  # Redirect to refresh the page and prevent form resubmission

    # Fetch some recent posts and analyses to display for manual triggering
    recent_posts = Post.objects.order_by("-created_at")[:10]
    recent_analyses = Analysis.objects.order_by("-created_at")[:10]
    sources = Source.objects.all()  # Fetch all sources

    # Get bot status for display in menu
    trading_config = TradingConfig.objects.filter(is_active=True).first()
    bot_enabled = trading_config.bot_enabled if trading_config else False

    return render(
        request,
        "core/test_page.html",
        {
            "recent_posts": recent_posts,
            "recent_analyses": recent_analyses,
            "sources": sources,  # Pass sources to the template
            "bot_enabled": bot_enabled,  # Pass bot status to template
        },
    )


def recent_activities_api(request):
    """API endpoint to get recent activity logs from database."""
    try:
        # Get recent activities from the last 24 hours
        last_24h = timezone.now() - timedelta(hours=24)
        activities = ActivityLog.objects.filter(
            created_at__gte=last_24h
        ).order_by('-created_at')[:20]

        activity_list = []
        for activity in activities:
            # Calculate time ago properly
            time_diff = timezone.now() - activity.created_at
            total_seconds = int(time_diff.total_seconds())

            if total_seconds < 60:
                time_ago = "Just now"
            elif total_seconds < 3600:
                time_ago = f"{total_seconds // 60} min ago"
            elif total_seconds < 86400:
                time_ago = f"{total_seconds // 3600}h ago"
            else:
                time_ago = f"{total_seconds // 86400}d ago"

            activity_list.append({
                'id': activity.id,
                'type': activity.activity_type,
                'message': activity.message,
                'data': activity.data,
                'created_at': activity.created_at.isoformat(),
                'time_ago': time_ago
            })

        return JsonResponse({
            'success': True,
            'activities': activity_list,
            'count': len(activity_list)
        })
    except Exception as e:
        logger.error(f"Error fetching recent activities: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e),
            'activities': [],
            'count': 0
        })


# OLD close_trade_view function removed - now using unified manual_close_trade_view


def close_trade_api(request):
    """API endpoint for closing trades."""
    if request.method == 'POST':
        try:
            import json
            from .models import Trade
            from .tasks import close_trade_manually
            
            data = json.loads(request.body)
            trade_id = data.get('trade_id')
            
            if not trade_id:
                return JsonResponse({'error': 'Trade ID is required'}, status=400)
            
            # Verify trade exists and is open
            try:
                trade = Trade.objects.get(id=trade_id, status__in=['open', 'pending_close'])
            except Trade.DoesNotExist:
                return JsonResponse({'error': 'Trade not found or already closed'}, status=404)
            
            # Close the trade
            close_trade_manually.delay(trade_id)
            
            return JsonResponse({
                'success': True,
                'message': f'Trade {trade_id} closure initiated',
                'trade_id': trade_id
            })
            
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    elif request.method == 'GET':
        # Return list of open trades
        from .models import Trade
        
        open_trades = Trade.objects.filter(status__in=['pending', 'open', 'pending_close']).values(
            'id', 'symbol', 'direction', 'quantity', 'entry_price', 'created_at', 'status'
        ).order_by('-created_at')
        
        return JsonResponse({
            'success': True,
            'trades': list(open_trades),
            'count': len(open_trades)
        })
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)


def cancel_trade_api(request):
    """API endpoint for canceling pending trades."""
    if request.method == 'POST':
        try:
            import json
            from .models import Trade
            
            data = json.loads(request.body)
            trade_id = data.get('trade_id')
            
            if not trade_id:
                return JsonResponse({'error': 'Trade ID is required'}, status=400)
            
            # Verify trade exists and is pending
            try:
                trade = Trade.objects.get(id=trade_id, status='pending')
            except Trade.DoesNotExist:
                return JsonResponse({'error': 'Trade not found or not cancelable'}, status=404)
            
            # Cancel the trade via Alpaca API
            try:
                import alpaca_trade_api as tradeapi
                import os
                
                api_key = os.getenv("ALPACA_API_KEY")
                secret_key = os.getenv("ALPACA_SECRET_KEY")
                base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
                
                if not api_key or not secret_key:
                    return JsonResponse({'error': 'Alpaca API keys not configured'}, status=500)
                
                api = tradeapi.REST(api_key, secret_key, base_url=base_url)
                
                # Cancel the order
                if trade.alpaca_order_id:
                    api.cancel_order(trade.alpaca_order_id)
                    trade.status = 'cancelled'
                    trade.save()
                    
                    return JsonResponse({
                        'success': True,
                        'message': f'Order cancelled for {trade.symbol}',
                        'trade_id': trade_id
                    })
                else:
                    return JsonResponse({'error': 'No Alpaca order ID found for this trade'}, status=400)
                    
            except Exception as e:
                logger.error(f"Error canceling trade {trade_id}: {e}")
                return JsonResponse({'error': f'Failed to cancel order: {str(e)}'}, status=500)
            
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)


def trade_status_api(request, trade_id):
    """API endpoint for refreshing trade status from Alpaca."""
    if request.method == 'GET':
        try:
            from .models import Trade
            
            # Verify trade exists
            try:
                trade = Trade.objects.get(id=trade_id)
            except Trade.DoesNotExist:
                return JsonResponse({'error': 'Trade not found'}, status=404)
            
            # Get status from Alpaca API
            try:
                import alpaca_trade_api as tradeapi
                import os
                
                api_key = os.getenv("ALPACA_API_KEY")
                secret_key = os.getenv("ALPACA_SECRET_KEY")
                base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
                
                if not api_key or not secret_key:
                    return JsonResponse({'error': 'Alpaca API keys not configured'}, status=500)
                
                api = tradeapi.REST(api_key, secret_key, base_url=base_url)
                
                if trade.alpaca_order_id:
                    # Get order status from Alpaca
                    order = api.get_order(trade.alpaca_order_id)
                    
                    # Update trade status based on Alpaca order status
                    old_status = trade.status
                    if order.status == 'filled':
                        trade.status = 'open'
                        if hasattr(order, 'filled_avg_price') and order.filled_avg_price:
                            trade.entry_price = float(order.filled_avg_price)
                    elif order.status == 'cancelled':
                        trade.status = 'cancelled'
                    elif order.status in ['pending_new', 'new', 'partially_filled']:
                        trade.status = 'pending'
                    elif order.status == 'rejected':
                        trade.status = 'rejected'
                    
                    trade.save()
                    
                    status_changed = old_status != trade.status
                    
                    return JsonResponse({
                        'success': True,
                        'status': trade.status,
                        'alpaca_status': order.status,
                        'status_changed': status_changed,
                        'message': f'Status updated: {trade.status}' if status_changed else f'Status unchanged: {trade.status}'
                    })
                else:
                    return JsonResponse({'error': 'No Alpaca order ID found for this trade'}, status=400)
                    
            except Exception as e:
                logger.error(f"Error refreshing trade status for {trade_id}: {e}")
                return JsonResponse({'error': f'Failed to refresh status: {str(e)}'}, status=500)
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@csrf_exempt
def trigger_scrape_api(request):
    """CSRF-exempt API endpoint for triggering scraping."""
    if request.method == 'POST':
        try:
            import json
            from .models import Source
            from .tasks import scrape_posts
            
            # Parse request data
            if request.content_type == 'application/json':
                data = json.loads(request.body)
                source_id = data.get('source_id')
            else:
                source_id = request.POST.get('source_id')
            
            if source_id:
                # Scrape specific source
                try:
                    source = Source.objects.get(id=source_id, scraping_enabled=True)
                    result = scrape_posts.delay(source_id=source_id, manual_test=True)
                    return JsonResponse({
                        'success': True,
                        'message': f'Scraping started for {source.name}',
                        'task_id': result.id,
                        'source': source.name
                    })
                except Source.DoesNotExist:
                    return JsonResponse({'error': 'Source not found or disabled'}, status=404)
            else:
                # Scrape all enabled sources
                sources = Source.objects.filter(scraping_enabled=True)
                tasks = []
                for source in sources:
                    result = scrape_posts.delay(source_id=source.id, manual_test=True)
                    tasks.append({'source': source.name, 'task_id': result.id})
                
                return JsonResponse({
                    'success': True,
                    'message': f'Scraping started for {len(tasks)} sources',
                    'tasks': tasks
                })
                
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    elif request.method == 'GET':
        # Return scraping status
        from .models import Source
        sources = Source.objects.filter(scraping_enabled=True)
        return JsonResponse({
            'success': True,
            'enabled_sources': sources.count(),
            'sources': [{'id': s.id, 'name': s.name} for s in sources]
        })
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)


def public_posts_api(request):
    """Public API endpoint for posts (no auth required)."""
    try:
        from .models import Post
        from django.core.paginator import Paginator
        
        # Get query parameters
        source_id = request.GET.get("source_id")
        page = request.GET.get("page", 1)
        page_size = min(int(request.GET.get("page_size", 20)), 100)
        
        # Filter posts
        posts_queryset = Post.objects.select_related("source").order_by("-created_at")
        if source_id:
            posts_queryset = posts_queryset.filter(source_id=source_id)
        
        # Paginate
        paginator = Paginator(posts_queryset, page_size)
        page_obj = paginator.get_page(page)
        
        # Serialize posts
        posts_data = []
        for post in page_obj:
            posts_data.append({
                "id": post.id,
                "content": post.content,
                "url": post.url,
                "source": {
                    "id": post.source.id,
                    "name": post.source.name
                },
                "created_at": post.created_at.isoformat(),
            })
        
        return JsonResponse({
            "count": paginator.count,
            "total_pages": paginator.num_pages,
            "current_page": page_obj.number,
            "next": page_obj.has_next(),
            "previous": page_obj.has_previous(),
            "results": posts_data
        })
        
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

