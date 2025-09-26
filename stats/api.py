from datetime import datetime
from collections import defaultdict
from django.utils import timezone
from django.db.models import Sum, Count, Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.contrib.auth.decorators import login_required

from core.models import Trade
from django.db.models import F
from datetime import timedelta


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
    min_conf = request.GET.get('min_confidence')
    industry = request.GET.get('industry')
    sector = request.GET.get('sector')
    source = request.GET.get('source')
    if start:
        qs = qs.filter(created_at__gte=start)
    if end:
        qs = qs.filter(created_at__lte=end)
    if symbol:
        qs = qs.filter(symbol__iexact=symbol)
    if min_conf:
        try:
            mc = float(min_conf)
            qs = qs.filter(analysis__confidence__gte=mc)
        except Exception:
            pass
    if industry:
        qs = qs.filter(tracked_company__industry__iexact=industry)
    if sector:
        qs = qs.filter(tracked_company__sector__iexact=sector)
    if source:
        qs = qs.filter(analysis__post__source__name__iexact=source)
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
    by_day_count = defaultdict(int)
    for t in qs:
        day = (t.closed_at or t.created_at).date().isoformat()
        by_day[day] += _commission_adjusted_realized_pnl(t)
        by_day_count[day] += 1
    labels = sorted(by_day.keys())
    pnl = [by_day[d] for d in labels]
    counts = [by_day_count[d] for d in labels]
    # 7D MA
    ma7 = []
    for i in range(len(pnl)):
        w = pnl[max(0, i-6):i+1]
        ma7.append(sum(w)/len(w))

    # Projection (daily): average daily PnL across available days, project forward
    proj_days = int(request.GET.get('projection_days', '7') or '7')
    proj_days = max(0, min(proj_days, 14))
    avg_daily = (sum(pnl)/len(pnl)) if pnl else 0.0
    proj_labels = []
    proj_values = []
    if proj_days > 0 and labels:
        try:
            last = datetime.fromisoformat(labels[-1])
        except Exception:
            last = (timezone.now()).date()
            last = datetime(year=last.year, month=last.month, day=last.day)
        cur = last
        for _ in range(proj_days):
            cur = cur + timedelta(days=1)
            proj_labels.append(cur.date().isoformat())
            proj_values.append(round(avg_daily, 4))

    return JsonResponse({
        'labels': labels,
        'pnl': pnl,
        'ma7': ma7,
        'projection_labels': proj_labels,
        'projection': proj_values,
        'avg_daily_pnl': round(avg_daily, 4),
        'counts': counts,
    })


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



@login_required
@require_GET
def confidence_distribution_api(request):
    qs = _filtered_trades(request).filter(status='closed', realized_pnl__isnull=False, analysis__isnull=False)
    # Bins: 0.50-0.60 ... 0.90-1.00
    edges = [0.5, 0.6, 0.7, 0.8, 0.9, 1.01]
    labels = ["0.50-0.60","0.60-0.70","0.70-0.80","0.80-0.90","0.90-1.00"]
    all_counts = [0]*5
    win_counts = [0]*5
    lose_counts = [0]*5
    for t in qs.select_related('analysis'):
        c = float(getattr(t.analysis, 'confidence', 0.0) or 0.0)
        idx = None
        for i in range(5):
            if edges[i] <= c < edges[i+1]:
                idx = i
                break
        if idx is None:
            continue
        all_counts[idx] += 1
        pnl = _commission_adjusted_realized_pnl(t)
        if pnl > 0:
            win_counts[idx] += 1
        elif pnl < 0:
            lose_counts[idx] += 1
    return JsonResponse({ 'bins': labels, 'all_counts': all_counts, 'win_counts': win_counts, 'lose_counts': lose_counts })


@login_required
@require_GET
def calibration_api(request):
    qs = _filtered_trades(request).filter(status='closed', realized_pnl__isnull=False, analysis__isnull=False)
    edges = [0.5, 0.6, 0.7, 0.8, 0.9, 1.01]
    labels = ["0.50-0.60","0.60-0.70","0.70-0.80","0.80-0.90","0.90-1.00"]
    wins = [0]*5
    counts = [0]*5
    for t in qs.select_related('analysis'):
        c = float(getattr(t.analysis, 'confidence', 0.0) or 0.0)
        idx = None
        for i in range(5):
            if edges[i] <= c < edges[i+1]:
                idx = i
                break
        if idx is None:
            continue
        counts[idx] += 1
        if _commission_adjusted_realized_pnl(t) > 0:
            wins[idx] += 1
    win_rate = [round((wins[i]/counts[i])*100.0, 2) if counts[i] else 0.0 for i in range(5)]
    return JsonResponse({ 'bins': labels, 'win_rate': win_rate, 'counts': counts })


@login_required
@require_GET
def confidence_pnl_buckets_api(request):
    qs = _filtered_trades(request).filter(status='closed', realized_pnl__isnull=False, analysis__isnull=False)
    edges = [0.5, 0.6, 0.7, 0.8, 0.9, 1.01]
    labels = ["0.50-0.60","0.60-0.70","0.70-0.80","0.80-0.90","0.90-1.00"]
    totals = [0.0]*5
    counts = [0]*5
    for t in qs.select_related('analysis'):
        c = float(getattr(t.analysis, 'confidence', 0.0) or 0.0)
        idx = None
        for i in range(5):
            if edges[i] <= c < edges[i+1]:
                idx = i
                break
        if idx is None:
            continue
        totals[idx] += _commission_adjusted_realized_pnl(t)
        counts[idx] += 1
    avg = [ (totals[i]/counts[i]) if counts[i] else 0.0 for i in range(5) ]
    return JsonResponse({ 'bins': labels, 'avg_pnl': avg, 'total_pnl': totals, 'counts': counts })


def _aggregate_dimension(qs, key_name, min_trades=5):
    # Build aggregates safely in Python to account for commission adjustment
    from collections import defaultdict
    by = defaultdict(lambda: { 'name': '', 'count': 0, 'wins': 0, 'total_pnl_adjusted': 0.0 })
    for t in qs:
        key = getattr(t, key_name, None)
        if key_name == 'tracked_company':
            key = getattr(getattr(t, 'tracked_company', None), 'industry', '')
        if key is None:
            key = ''
        name = key if isinstance(key, str) else str(key)
        pnl = _commission_adjusted_realized_pnl(t)
        item = by[name]
        item['name'] = name or '(Unknown)'
        item['count'] += 1
        if pnl > 0:
            item['wins'] += 1
        item['total_pnl_adjusted'] += pnl
    items = []
    for v in by.values():
        if v['count'] >= min_trades:
            v['win_rate'] = round((v['wins']/v['count'])*100.0, 2)
            items.append(v)
    items.sort(key=lambda x: x['total_pnl_adjusted'], reverse=True)
    return items


@login_required
@require_GET
def industry_performance_api(request):
    qs = _filtered_trades(request).filter(status='closed', realized_pnl__isnull=False)
    # Only trades linked to tracked_company to access industry
    qs = qs.filter(tracked_company__isnull=False)
    # Attach industry name onto trade instance for aggregation
    trades = list(qs.select_related('tracked_company'))
    for t in trades:
        setattr(t, 'industry', getattr(getattr(t, 'tracked_company', None), 'industry', ''))
    items = _aggregate_dimension(trades, 'industry', min_trades=5)
    return JsonResponse({ 'items': items })


@login_required
@require_GET
def sector_performance_api(request):
    qs = _filtered_trades(request).filter(status='closed', realized_pnl__isnull=False)
    qs = qs.filter(tracked_company__isnull=False)
    trades = list(qs.select_related('tracked_company'))
    for t in trades:
        setattr(t, 'sector', getattr(getattr(t, 'tracked_company', None), 'sector', ''))
    items = _aggregate_dimension(trades, 'sector', min_trades=5)
    return JsonResponse({ 'items': items })


@login_required
@require_GET
def source_performance_api(request):
    qs = _filtered_trades(request).filter(status='closed', realized_pnl__isnull=False, analysis__isnull=False)
    trades = list(qs.select_related('analysis__post__source'))
    for t in trades:
        src_name = ''
        try:
            src_name = t.analysis.post.source.name
        except Exception:
            src_name = ''
        setattr(t, 'source_name', src_name)
    items = _aggregate_dimension(trades, 'source_name', min_trades=5)
    return JsonResponse({ 'items': items })


@login_required
@require_GET
def model_performance_api(request):
    qs = _filtered_trades(request).filter(status='closed', realized_pnl__isnull=False, analysis__isnull=False)
    trades = list(qs.select_related('analysis__trading_config_used'))
    for t in trades:
        model = ''
        try:
            # Prefer explicit model recorded on analysis, fallback to config
            model = (t.analysis.used_llm_model or '').strip()
            if not model:
                model = (t.analysis.trading_config_used.llm_model if t.analysis.trading_config_used else '') or ''
            model = (model or '').strip()
        except Exception:
            model = ''
        setattr(t, 'llm_model', model)
    # Include any model that appears (>=1 trade) so all used models are visible
    items = _aggregate_dimension(trades, 'llm_model', min_trades=1)
    return JsonResponse({ 'items': items })


@login_required
@require_GET
def behavior_api(request):
    qs = _filtered_trades(request).filter(status='closed', realized_pnl__isnull=False, analysis__isnull=False)
    edges = [0.5, 0.6, 0.7, 0.8, 0.9, 1.01]
    labels = ["0.50-0.60","0.60-0.70","0.70-0.80","0.80-0.90","0.90-1.00"]
    buy_wins = [0]*5; buy_counts = [0]*5
    sell_wins = [0]*5; sell_counts = [0]*5
    for t in qs.select_related('analysis'):
        c = float(getattr(t.analysis, 'confidence', 0.0) or 0.0)
        idx = None
        for i in range(5):
            if edges[i] <= c < edges[i+1]:
                idx = i
                break
        if idx is None:
            continue
        is_win = _commission_adjusted_realized_pnl(t) > 0
        if (t.direction or 'buy').lower() == 'sell':
            sell_counts[idx] += 1
            if is_win:
                sell_wins[idx] += 1
        else:
            buy_counts[idx] += 1
            if is_win:
                buy_wins[idx] += 1
    buy_win_rate = [ round((buy_wins[i]/buy_counts[i])*100.0, 2) if buy_counts[i] else 0.0 for i in range(5) ]
    sell_win_rate = [ round((sell_wins[i]/sell_counts[i])*100.0, 2) if sell_counts[i] else 0.0 for i in range(5) ]
    return JsonResponse({ 'conf_bins': labels, 'buy_win_rate': buy_win_rate, 'sell_win_rate': sell_win_rate })


@login_required
@require_GET
def threshold_simulation_api(request):
    qs = _filtered_trades(request).filter(status='closed', realized_pnl__isnull=False)
    closed = list(qs)
    trades = len(closed)
    total = sum(_commission_adjusted_realized_pnl(t) for t in closed)
    wins = sum(1 for t in closed if _commission_adjusted_realized_pnl(t) > 0)
    win_rate = (wins / trades * 100.0) if trades else 0.0
    avg = (total / trades) if trades else 0.0
    return JsonResponse({ 'trades': trades, 'total_pnl_adjusted': round(total, 4), 'win_rate': round(win_rate, 2), 'avg_pnl': round(avg, 4) })


@login_required
@require_GET
def symbols_api(request):
    qs = _filtered_trades(request).filter(status='closed', realized_pnl__isnull=False)
    from collections import defaultdict
    agg = defaultdict(lambda: { 'name': '', 'count': 0, 'wins': 0, 'total_pnl_adjusted': 0.0 })
    for t in qs:
        sym = (t.symbol or '').upper()
        pnl = _commission_adjusted_realized_pnl(t)
        a = agg[sym]
        a['name'] = sym
        a['count'] += 1
        if pnl > 0:
            a['wins'] += 1
        a['total_pnl_adjusted'] += pnl
    items = []
    for v in agg.values():
        v['win_rate'] = round((v['wins']/v['count'])*100.0, 2) if v['count'] else 0.0
        items.append(v)
    items.sort(key=lambda x: x['total_pnl_adjusted'], reverse=True)
    return JsonResponse({ 'items': items[:30] })


@login_required
@require_GET
def confidence_pnl_scatter_api(request):
    qs = _filtered_trades(request).filter(status='closed', realized_pnl__isnull=False, analysis__isnull=False)
    points = []
    for t in qs.select_related('analysis'):
        try:
            c = float(t.analysis.confidence or 0.0)
            pnl = _commission_adjusted_realized_pnl(t)
            points.append({ 'x': round(c, 4), 'y': round(pnl, 4), 'symbol': (t.symbol or '').upper(), 'dir': (t.direction or '').lower() })
        except Exception:
            continue
    return JsonResponse({ 'points': points })


@login_required
@require_GET
def duration_pnl_scatter_api(request):
    qs = _filtered_trades(request).filter(status='closed', realized_pnl__isnull=False, opened_at__isnull=False, closed_at__isnull=False)
    points = []
    for t in qs:
        try:
            duration_min = t.duration_minutes
            if duration_min is None:
                continue
            pnl = _commission_adjusted_realized_pnl(t)
            points.append({ 'x': int(duration_min), 'y': round(pnl, 4), 'symbol': (t.symbol or '').upper(), 'dir': (t.direction or '').lower() })
        except Exception:
            continue
    return JsonResponse({ 'points': points })


@login_required
@require_GET
def pnl_by_month_api(request):
    """Monthly commission-adjusted PnL and simple projection for up to 12 months.

    Projection: linear extrapolation based on average monthly PnL of available months
    within the requested date range. We cap output to 12 months max for clarity.
    """
    # Start with closed, realized trades only
    qs = Trade.objects.filter(status='closed', realized_pnl__isnull=False, closed_at__isnull=False)

    # Determine month buckets between start and end (defaults to last 12 closed months)
    start = _parse_dt(request.GET.get('start'))
    end = _parse_dt(request.GET.get('end'))
    now = timezone.now()
    if not end:
        end = now

    def month_key(dt):
        return f"{dt.year:04d}-{dt.month:02d}"

    # Normalize to month starts
    try:
        end_month = end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    except Exception:
        end_month = end

    if not start:
        # Last 12 months inclusive, in chronological order
        months = []
        ey, em = end_month.year, end_month.month
        for delta in range(11, -1, -1):
            y = ey
            m = em - delta
            while m <= 0:
                y -= 1
                m += 12
            months.append(f"{y:04d}-{m:02d}")
    else:
        try:
            start_month = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        except Exception:
            start_month = start
        months = []
        cur = start_month
        safeguard = 0
        while cur <= end_month and safeguard < 36:
            months.append(month_key(cur))
            if cur.month == 12:
                cur = cur.replace(year=cur.year + 1, month=1)
            else:
                cur = cur.replace(month=cur.month + 1)
            safeguard += 1
        # Trim to last 12 if user gave large range
        if len(months) > 12:
            months = months[-12:]

    # Apply date filter on closed_at within span
    span_start_str = months[0] + "-01"
    # compute next month start for span end bound
    last_year = int(months[-1].split('-')[0])
    last_month = int(months[-1].split('-')[1])
    if last_month == 12:
        span_end_year = last_year + 1
        span_end_month = 1
    else:
        span_end_year = last_year
        span_end_month = last_month + 1
    span_end_str = f"{span_end_year:04d}-{span_end_month:02d}-01"

    try:
        span_start = datetime.fromisoformat(span_start_str)
        span_end = datetime.fromisoformat(span_end_str)
        qs = qs.filter(closed_at__gte=span_start, closed_at__lt=span_end)
    except Exception:
        pass

    # Aggregate PnL and counts by close month
    by_month_sum = { m: 0.0 for m in months }
    by_month_count = { m: 0 for m in months }
    for t in qs:
        dt = t.closed_at
        if not dt:
            continue
        k = month_key(dt)
        if k in by_month_sum:
            pnl = _commission_adjusted_realized_pnl(t)
            by_month_sum[k] += pnl
            by_month_count[k] += 1

    labels_all = months
    pnl_vals = [ round(by_month_sum[m], 4) for m in labels_all ]

    # Projection: average of complete months only (exclude current partial month if end is within current month)
    projection_months = int(request.GET.get('projection_months', '3') or '3')
    projection_months = max(0, min(projection_months, 6))
    treat_partial = (end.year == now.year and end.month == now.month)
    months_for_avg = [m for m in labels_all if (not treat_partial or m != month_key(end)) and by_month_count[m] > 0]
    if not months_for_avg:
        # Fallback: include any months with data (e.g., only current month has trades)
        months_for_avg = [m for m in labels_all if by_month_count[m] > 0]
    avg = sum(by_month_sum[m] for m in months_for_avg) / float(len(months_for_avg)) if months_for_avg else 0.0

    proj_labels = []
    proj_values = []
    if projection_months > 0 and labels_all:
        # derive next month after last label
        last_label = labels_all[-1]
        year = int(last_label.split('-')[0])
        month = int(last_label.split('-')[1])
        for _ in range(projection_months):
            if month == 12:
                year += 1
                month = 1
            else:
                month += 1
            proj_labels.append(f"{year:04d}-{month:02d}")
            proj_values.append(round(avg, 4))

    return JsonResponse({
        'labels': labels_all,
        'pnl': pnl_vals,
        'projection_labels': proj_labels,
        'projection': proj_values,
        'avg_monthly_pnl': round(avg, 4),
    })


@login_required
@require_GET
def close_reasons_api(request):
    """Aggregate closed trades by close_reason with counts, win rate, and pnl.

    Returns a list of { reason, count, wins, win_rate, total_pnl_adjusted } sorted by count desc.
    """
    qs = _filtered_trades(request).filter(status='closed', realized_pnl__isnull=False)
    from collections import defaultdict
    agg = defaultdict(lambda: { 'reason': '', 'count': 0, 'wins': 0, 'total_pnl_adjusted': 0.0 })
    for t in qs:
        reason = getattr(t, 'close_reason', '') or '(Unknown)'
        pnl = _commission_adjusted_realized_pnl(t)
        a = agg[reason]
        a['reason'] = reason
        a['count'] += 1
        if pnl > 0:
            a['wins'] += 1
        a['total_pnl_adjusted'] += pnl
    items = []
    for v in agg.values():
        v['win_rate'] = round((v['wins']/v['count'])*100.0, 2) if v['count'] else 0.0
        items.append(v)
    items.sort(key=lambda x: x['count'], reverse=True)
    return JsonResponse({ 'items': items })
