from django.urls import path
from . import views
from . import api

urlpatterns = [
    path('', views.stats_page, name='stats_page'),
    path('analysis/', views.analysis_page, name='analysis_page'),
    path('api/summary', api.summary_api, name='stats_summary'),
    path('api/equity', api.equity_api, name='stats_equity'),
    path('api/pnl-by-day', api.pnl_by_day_api, name='stats_pnl_by_day'),
    path('api/direction-breakdown', api.direction_breakdown_api, name='stats_direction_breakdown'),
    path('api/per-symbol', api.per_symbol_api, name='stats_per_symbol'),
    path('api/heatmap', api.heatmap_api, name='stats_heatmap'),
    # Analysis-focused APIs
    path('api/analysis/confidence-distribution', api.confidence_distribution_api, name='analysis_confidence_distribution'),
    path('api/analysis/calibration', api.calibration_api, name='analysis_calibration'),
    path('api/analysis/confidence-pnl-buckets', api.confidence_pnl_buckets_api, name='analysis_confidence_pnl_buckets'),
    path('api/analysis/industry-performance', api.industry_performance_api, name='analysis_industry_performance'),
    path('api/analysis/sector-performance', api.sector_performance_api, name='analysis_sector_performance'),
    path('api/analysis/source-performance', api.source_performance_api, name='analysis_source_performance'),
    path('api/analysis/model-performance', api.model_performance_api, name='analysis_model_performance'),
    path('api/analysis/behavior', api.behavior_api, name='analysis_behavior'),
    path('api/analysis/threshold-simulation', api.threshold_simulation_api, name='analysis_threshold_simulation'),
    path('api/analysis/symbols', api.symbols_api, name='analysis_symbols'),
    path('api/analysis/confidence-pnl-scatter', api.confidence_pnl_scatter_api, name='analysis_confidence_pnl_scatter'),
    path('api/analysis/duration-pnl-scatter', api.duration_pnl_scatter_api, name='analysis_duration_pnl_scatter'),
]


