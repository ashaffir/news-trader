from datetime import datetime
from collections import defaultdict
from django.utils import timezone
from django.db.models import Sum, Count, Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.contrib.auth.decorators import login_required

from core.models import Trade


def _parse_dt(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except Exception:
        return None


def _filtered_trades(request):
    qs = Trade.objects.all()
    start = _parse_dt(request.GET.get('start'))
    end = _parse_dt(request.GET.get('end'))
    symbol = request.GET.get('symbol')
    if start:
        qs = qs.filter(created_at__gte=start)
    if end:
        qs = qs.filter(created_at__lte=end)
    if symbol:
        qs = qs.filter(symbol__iexact=symbol)
    return qs


def _commission_adjusted_realized_pnl(trade: Trade) -> float:
    realized = float(trade.realized_pnl or 0.0)
    commission = float(trade.commission or 0.0)
    return realized - commission


@login_required
@require_GET
def summary_api(request):
    qs = _filtered_trades(request)
    closed = list(qs.filter(status='closed', realized_pnl__isnull=False))
    total_trades = qs.count()
    total_pnl_adj = sum(_commission_adjusted_realized_pnl(t) for t in closed)
    wins = sum(1 for t in closed if _commission_adjusted_realized_pnl(t) > 0)
    win_rate = (wins / len(closed) * 100.0) if closed else 0.0

    # Equity curve on trade close time for max drawdown and Sharpe
    closes = sorted(closed, key=lambda t: (t.closed_at or t.created_at))
    equity = []
    cur = 0.0
    for t in closes:
        cur += _commission_adjusted_realized_pnl(t)
        equity.append(cur)
    # Drawdown
    peak = -1e18
    max_dd = 0.0
    for e in equity:
        peak = max(peak, e)
        if peak > 0:
            dd = (peak - e) / peak * 100.0
            max_dd = max(max_dd, dd)
    # Daily Sharpe from daily returns (difference of equity)
    daily = defaultdict(float)
    for t in closes:
        d = (t.closed_at or t.created_at).date().isoformat()
        daily[d] += _commission_adjusted_realized_pnl(t)
    daily_series = [daily[k] for k in sorted(daily.keys())]
    sharpe = 0.0
    if len(daily_series) >= 2:
        import statistics
        mean = statistics.mean(daily_series)
        stdev = statistics.pstdev(daily_series) or 1e-9
        sharpe = mean / stdev

    # Avg R/trade: fallback to pnl/entry_price if no explicit R; simple proxy
    # Use absolute pnl divided by entry_price * 0.02 (assuming 2% SL) as heuristic R
    r_vals = []
    for t in closed:
        if t.entry_price:
            denom = float(t.entry_price) * 0.02
            if denom > 0:
                r_vals.append(_commission_adjusted_realized_pnl(t) / denom)
    avg_r = sum(r_vals)/len(r_vals) if r_vals else 0.0

    return JsonResponse({
        'total_trades': total_trades,
        'total_pnl_adjusted': total_pnl_adj,
        'win_rate': round(win_rate, 2),
        'max_drawdown': round(max_dd, 2),
        'sharpe_daily': round(sharpe, 3),
        'avg_r_per_trade': round(avg_r, 3),
    })


@login_required
@require_GET
def equity_api(request):
    qs = _filtered_trades(request).filter(status='closed', realized_pnl__isnull=False)
    closes = sorted(qs, key=lambda t: (t.closed_at or t.created_at))
    labels, equity, drawdown_pct = [], [], []
    cur = 0.0
    peak = 0.0
    for t in closes:
        cur += _commission_adjusted_realized_pnl(t)
        labels.append((t.closed_at or t.created_at).strftime('%Y-%m-%d'))
        equity.append(cur)
        peak = max(peak, cur)
        dd = ((peak - cur) / peak * 100.0) if peak > 0 else 0.0
        drawdown_pct.append(round(dd, 2))
    return JsonResponse({ 'labels': labels, 'equity': equity, 'drawdown_pct': drawdown_pct })


@login_required
@require_GET
def pnl_by_day_api(request):
    qs = _filtered_trades(request).filter(status='closed', realized_pnl__isnull=False)
    by_day = defaultdict(float)
    for t in qs:
        day = (t.closed_at or t.created_at).date().isoformat()
        by_day[day] += _commission_adjusted_realized_pnl(t)
    labels = sorted(by_day.keys())
    pnl = [by_day[d] for d in labels]
    # 7D MA
    ma7 = []
    for i in range(len(pnl)):
        w = pnl[max(0, i-6):i+1]
        ma7.append(sum(w)/len(w))
    return JsonResponse({ 'labels': labels, 'pnl': pnl, 'ma7': ma7 })


@login_required
@require_GET
def direction_breakdown_api(request):
    qs = _filtered_trades(request).filter(status='closed', realized_pnl__isnull=False)
    out = { 'buy': { 'count': 0, 'pnl_adjusted': 0.0 }, 'sell': { 'count': 0, 'pnl_adjusted': 0.0 } }
    for t in qs:
        d = (t.direction or 'buy').lower()
        d = 'buy' if d not in ('buy', 'sell') else d
        out[d]['count'] += 1
        out[d]['pnl_adjusted'] += _commission_adjusted_realized_pnl(t)
    return JsonResponse(out)


@login_required
@require_GET
def per_symbol_api(request):
    qs = _filtered_trades(request).filter(status='closed', realized_pnl__isnull=False)
    agg = defaultdict(lambda: { 'symbol': '', 'count': 0, 'total_pnl_adjusted': 0.0 })
    for t in qs:
        sym = (t.symbol or '').upper()
        a = agg[sym]
        a['symbol'] = sym
        a['count'] += 1
        a['total_pnl_adjusted'] += _commission_adjusted_realized_pnl(t)
    # sort by pnl desc, take top 15
    items = sorted(agg.values(), key=lambda x: x['total_pnl_adjusted'], reverse=True)[:15]
    return JsonResponse(items, safe=False)


@login_required
@require_GET
def heatmap_api(request):
    qs = _filtered_trades(request)
    # Build weekday x hour matrix by trade count
    # weekday: Mon..Sun -> 0..6, hour 0..23
    matrix = [[0 for _ in range(7)] for _ in range(24)]
    for t in qs:
        dt = (t.opened_at or t.created_at)
        if not dt:
            continue
        wd = int(dt.weekday())
        hr = int(dt.hour)
        matrix[hr][wd] += 1
    hours = [f"{h:02d}:00" for h in range(24)]
    weekdays = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    # Chart.js stacked bars want datasets per hour (rows)
    return JsonResponse({ 'hours': hours, 'weekdays': weekdays, 'matrix': matrix })


