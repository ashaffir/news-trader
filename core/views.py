from django.shortcuts import render, redirect
from django.http import JsonResponse
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

        # Get real Alpaca trading data
        alpaca_data = get_alpaca_trading_data()

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
            "open_trades": alpaca_data["open_positions"],  # Real Alpaca positions
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
    base_url = os.getenv("ALPACA_API_URL", "https://paper-api.alpaca.markets")

    if not api_key or not secret_key:
        return {"status": "error", "message": "API keys not configured"}

    try:
        # Real API test using the new alpaca-py TradingClient
        from alpaca.trading.client import TradingClient

        # Create TradingClient instance
        trading_client = TradingClient(
            api_key=api_key,
            secret_key=secret_key,
            paper=True,  # Using paper trading as configured in .env
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
        return {"status": "error", "message": "alpaca-py package not installed"}
    except Exception as e:
        return {"status": "error", "message": f"Connection failed: {str(e)}"}


def get_alpaca_trading_data():
    """Get real trading data from Alpaca API."""
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")

    if not api_key or not secret_key:
        return {
            "open_positions": 0,
            "account_value": 10000,
            "total_pnl": 0.0,
            "day_pnl": 0.0,
            "error": "API keys not configured",
        }

    try:
        from alpaca.trading.client import TradingClient

        trading_client = TradingClient(
            api_key=api_key, secret_key=secret_key, paper=True
        )

        # Get account info
        account = trading_client.get_account()

        # Get positions
        positions = trading_client.get_all_positions()

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


def manual_close_trade_view(request):
    logger.info("Manual close trade view accessed.")

    # Get real Alpaca positions instead of just local database
    alpaca_data = get_alpaca_trading_data()
    alpaca_positions = alpaca_data.get("positions", [])

    # Convert Alpaca positions to trade-like objects for the template
    open_trades = []
    for pos in alpaca_positions:
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
                # Initialize TP/SL as None for new positions
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
                except Trade.DoesNotExist:
                    pass  # No stored settings

        trade_obj = AlpacaTrade(pos)
        open_trades.append(trade_obj)

    # Also include local database trades that might have Alpaca order IDs
    local_trades = Trade.objects.filter(status="open")
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
        action = request.POST.get("action")
        trade_id = request.POST.get("trade_id")

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
            return redirect("manual_close_trade")

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
                    from django.contrib import messages
                    
                    # Get Alpaca credentials
                    ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
                    ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
                    ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
                    
                    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
                        logger.error("Alpaca API credentials not found")
                        messages.error(request, "Alpaca API credentials not configured")
                        return redirect("manual_close_trade")
                    
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
                
                return redirect("manual_close_trade")
            
            # Handle regular database trades
            try:
                trade = Trade.objects.get(id=trade_id, status="open")
                close_trade_manually.delay(trade.id)
                logger.info(f"Initiated manual close for trade {trade.id}.")
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
                return redirect("manual_close_trade")  # Redirect to refresh the page
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
                take_profit_percent = request.POST.get("take_profit_percent")
                stop_loss_percent = request.POST.get("stop_loss_percent")

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

                        # Find or create a basic analysis for this Alpaca position
                        from .models import Analysis

                        analysis, _ = Analysis.objects.get_or_create(
                            symbol=symbol,
                            defaults={
                                "post_id": 1,  # We'll use the first post as placeholder
                                "direction": (
                                    "buy" if float(position["qty"]) > 0 else "sell"
                                ),
                                "confidence": 0.8,  # Default confidence for manual settings
                                "reason": f"Manual take profit/stop loss settings for {symbol} position",
                            },
                        )

                        # Create or update a local trade record to store the settings
                        trade, created = Trade.objects.get_or_create(
                            symbol=symbol,
                            status="open",
                            alpaca_order_id=f"position_{symbol}",
                            defaults={
                                "analysis": analysis,
                                "direction": (
                                    "buy" if float(position["qty"]) > 0 else "sell"
                                ),
                                "quantity": abs(float(position["qty"])),
                                "entry_price": entry_price,
                            },
                        )

                        # Update the take profit and stop loss prices
                        if take_profit_price:
                            trade.take_profit_price = take_profit_price
                        if stop_loss_price:
                            trade.stop_loss_price = stop_loss_price
                        trade.save()

                        logger.info(
                            f"Updated trade settings for {symbol}: TP=${take_profit_price:.2f if take_profit_price else 'None'}, SL=${stop_loss_price:.2f if stop_loss_price else 'None'}"
                        )

                        # TODO: Implement actual Alpaca bracket order creation here
                        # This would involve canceling existing position and creating new bracket order

                else:
                    # Handle local database trades
                    trade = Trade.objects.get(id=trade_id, status="open")

                    # Calculate actual prices from percentages
                    if take_profit_percent:
                        trade.take_profit_price = trade.entry_price * (
                            1 + float(take_profit_percent) / 100
                        )

                    if stop_loss_percent:
                        trade.stop_loss_price = trade.entry_price * (
                            1 - float(stop_loss_percent) / 100
                        )

                    trade.save()
                    logger.info(f"Updated trade settings for trade {trade.id}")

                return redirect("manual_close_trade")

            except Exception as e:
                logger.error(f"Error updating trade settings for {trade_id}: {e}")
                # Could add error message to be displayed to user

    # Calculate total unrealized P&L for summary
    total_unrealized_pnl = sum(
        getattr(trade, "unrealized_pnl", 0) for trade in open_trades
    )

    return render(
        request,
        "core/manual_close_trade.html",
        {"open_trades": open_trades, "total_unrealized_pnl": total_unrealized_pnl},
    )


def test_page_view(request):
    logger.info("Test page accessed.")
    if request.method == "POST":
        action = request.POST.get("action")

        if action == "trigger_scrape":
            source_id = request.POST.get("source_id")
            if source_id:
                try:
                    # Pass only the source_id to the scrape_posts task
                    scrape_posts.delay(source_id=source_id)
                    logger.info(
                        f"Manually triggered scrape_posts task for Source ID: {source_id}."
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

        return redirect(
            "test_page"
        )  # Redirect to refresh the page and prevent form resubmission

    # Fetch some recent posts and analyses to display for manual triggering
    recent_posts = Post.objects.order_by("-created_at")[:10]
    recent_analyses = Analysis.objects.order_by("-created_at")[:10]
    sources = Source.objects.all()  # Fetch all sources

    return render(
        request,
        "core/test_page.html",
        {
            "recent_posts": recent_posts,
            "recent_analyses": recent_analyses,
            "sources": sources,  # Pass sources to the template
        },
    )


def recent_activities_api(request):
    """API endpoint to get recent activity logs from database."""
    try:
        # Get the last 50 activities
        recent_activities = ActivityLog.objects.order_by('-created_at')[:50]
        
        activities_data = []
        for activity in recent_activities:
            activities_data.append({
                'id': activity.id,
                'type': activity.activity_type,
                'message': activity.message,
                'data': activity.data,
                'timestamp': activity.created_at.isoformat(),
                'created_at': activity.created_at.strftime('%H:%M:%S')  # Formatted time
            })
        
        return JsonResponse({
            'success': True,
            'activities': activities_data,
            'count': len(activities_data)
        })
        
    except Exception as e:
        logger.error(f"Error fetching recent activities: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
