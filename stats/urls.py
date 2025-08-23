from django.urls import path
from . import views
from . import api

urlpatterns = [
    path('', views.stats_page, name='stats_page'),
    path('api/summary', api.summary_api, name='stats_summary'),
    path('api/equity', api.equity_api, name='stats_equity'),
    path('api/pnl-by-day', api.pnl_by_day_api, name='stats_pnl_by_day'),
    path('api/direction-breakdown', api.direction_breakdown_api, name='stats_direction_breakdown'),
    path('api/per-symbol', api.per_symbol_api, name='stats_per_symbol'),
    path('api/heatmap', api.heatmap_api, name='stats_heatmap'),
]


