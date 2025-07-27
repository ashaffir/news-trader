from django.shortcuts import render, redirect
from django.http import JsonResponse
from .models import Trade, Post, Analysis, Source, TradingConfig
from .tasks import close_trade_manually, scrape_posts, analyze_post, execute_trade
import logging
import json
import os
from django.utils import timezone
from datetime import datetime, timedelta
import requests
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

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
            "open_trades": Trade.objects.filter(status="open").count(),
            "trades_24h": Trade.objects.filter(created_at__gte=last_24h).count(),
        }

        # Trading Performance
        recent_trades = Trade.objects.filter(created_at__gte=last_24h)
        winning_trades = recent_trades.filter(realized_pnl__gt=0).count()
        total_recent_trades = recent_trades.count()
        win_rate = (
            (winning_trades / total_recent_trades * 100)
            if total_recent_trades > 0
            else 0
        )

        total_pnl = sum(trade.realized_pnl or 0 for trade in recent_trades)

        performance = {
            "win_rate": round(win_rate, 1),
            "total_pnl_24h": round(total_pnl, 2),
            "avg_confidence": get_avg_confidence(),
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
        error_msg = str(e).lower()
        if "unauthorized" in error_msg or "authentication" in error_msg:
            return {"status": "error", "message": "Invalid API credentials"}
        elif "forbidden" in error_msg or "access" in error_msg:
            return {
                "status": "error",
                "message": "Access forbidden - check permissions",
            }
        elif "timeout" in error_msg or "connection" in error_msg:
            return {"status": "warning", "message": "Connection timeout"}
        else:
            return {"status": "error", "message": f"Connection error: {str(e)}"}


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
    open_trades = Trade.objects.filter(status="open")

    if request.method == "POST":
        trade_id = request.POST.get("trade_id")
        if trade_id:
            logger.info(f"Attempting to close trade with ID: {trade_id}")
            try:
                trade = Trade.objects.get(id=trade_id, status="open")
                close_trade_manually.delay(trade.id)
                logger.info(f"Initiated manual close for trade {trade.id}.")
                return redirect("manual_close_trade")  # Redirect to refresh the page
            except Trade.DoesNotExist:
                logger.warning(
                    f"Attempted to close non-existent or already closed trade with ID: {trade_id}"
                )
                # Handle error: trade not found or not open
                pass
            except Exception as e:
                logger.error(
                    f"An unexpected error occurred while processing manual close for trade {trade_id}: {e}"
                )

    return render(request, "core/manual_close_trade.html", {"open_trades": open_trades})


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
