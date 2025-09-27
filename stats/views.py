from django.shortcuts import render
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth.decorators import login_required

# Import TradingConfig to reflect bot status in navbar on Stats page
from core.models import TradingConfig


@login_required
def stats_page(request):
    """Render Stats page shell; data loaded via JS."""
    # Default date range: last 30 days
    end = timezone.now()
    start = end - timedelta(days=30)
    # Provide bot status for navbar indicator consistency with other pages
    trading_config = TradingConfig.objects.filter(is_active=True).first()
    bot_enabled = trading_config.bot_enabled if trading_config else False
    context = {
        "default_start": start.isoformat(),
        "default_end": end.isoformat(),
        "bot_enabled": bot_enabled,
    }
    return render(request, "stats/stats.html", context)

# Create your views here.


@login_required
def analysis_page(request):
    """Render Analysis page shell; data loaded via JS."""
    end = timezone.now()
    start = end - timedelta(days=30)
    trading_config = TradingConfig.objects.filter(is_active=True).first()
    bot_enabled = trading_config.bot_enabled if trading_config else False
    context = {
        "default_start": start.isoformat(),
        "default_end": end.isoformat(),
        "bot_enabled": bot_enabled,
    }
    return render(request, "stats/analysis.html", context)


@login_required
def trades_log_page(request):
    """Render Trades Log page; data loaded via JS."""
    end = timezone.now()
    start = end - timedelta(days=30)
    trading_config = TradingConfig.objects.filter(is_active=True).first()
    bot_enabled = trading_config.bot_enabled if trading_config else False
    context = {
        "default_start": start.isoformat(),
        "default_end": end.isoformat(),
        "bot_enabled": bot_enabled,
    }
    return render(request, "stats/trades_log.html", context)


@login_required
def asset_view_page(request, symbol: str, date: str):
    """Render Asset View page for a given symbol and date (YYYY-MM-DD)."""
    trading_config = TradingConfig.objects.filter(is_active=True).first()
    bot_enabled = trading_config.bot_enabled if trading_config else False
    # Optional trade details for annotations/metrics
    trade = None
    try:
        from core.models import Trade
        trade_id = request.GET.get('trade_id')
        if trade_id:
            trade = Trade.objects.select_related('analysis').filter(id=trade_id).first()
    except Exception:
        trade = None
    context = {
        "symbol": symbol.upper(),
        "date": date,
        "bot_enabled": bot_enabled,
        "trade_id": getattr(trade, 'id', None),
        "direction": getattr(trade, 'direction', None),
        "confidence": getattr(getattr(trade, 'analysis', None), 'confidence', None) if trade else None,
        "max_hold_hours": getattr(trade, 'max_holding_time_hours', None) or (getattr(getattr(trade, 'analysis', None), 'max_holding_time_hours', None) if trade else None),
        "opened_at": trade.opened_at.isoformat() if getattr(trade, 'opened_at', None) else None,
        "closed_at": trade.closed_at.isoformat() if getattr(trade, 'closed_at', None) else None,
    }
    return render(request, "stats/asset_view.html", context)
