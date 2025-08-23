from django.shortcuts import render
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth.decorators import login_required


@login_required
def stats_page(request):
    """Render Stats page shell; data loaded via JS."""
    # Default date range: last 30 days
    end = timezone.now()
    start = end - timedelta(days=30)
    context = {
        "default_start": start.isoformat(),
        "default_end": end.isoformat(),
    }
    return render(request, "stats/stats.html", context)

# Create your views here.
