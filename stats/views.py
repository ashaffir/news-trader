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
