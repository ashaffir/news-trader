from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from .api import TradingConfigViewSet, SourceViewSet, PostViewSet, AnalysisViewSet, TradeViewSet, ApiResponseViewSet
from django.http import JsonResponse

# Health check endpoint for Docker
def health_check(request):
    return JsonResponse({"status": "healthy"})

router = DefaultRouter()
router.register(r'trading-configs', TradingConfigViewSet)
router.register(r'sources', SourceViewSet)
router.register(r'posts', PostViewSet)
router.register(r'analyses', AnalysisViewSet)
router.register(r'trades', TradeViewSet)
router.register(r'api-responses', ApiResponseViewSet)

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    path('dashboard/', views.dashboard_view, name='dashboard_alt'),  # Alternative dashboard URL
    path('health/', health_check, name='health'),  # Health check for Docker
    path('trigger_scrape/', views.trigger_scrape_ajax, name='trigger_scrape'),
    path('trigger_analysis/', views.trigger_analysis_ajax, name='trigger_analysis'),
    path('test/', views.test_page_view, name='test'),
    path('test-page/', views.test_page_view, name='test_page'),  # Alternative URL
    path('close-trade/', views.manual_close_trade_view, name='close_trade'),  # Unified close trade page
    path('alerts/', views.alerts_view, name='alerts'),
    path('alerts/send-test/', views.alerts_send_test, name='alerts_send_test'),
    path('toggle_bot_status/', views.toggle_bot_status, name='toggle_bot_status'),
    path('system_status/', views.system_status_api, name='system_status'),
    # API endpoints for dashboard
    path('api/system-status/', views.system_status_api, name='api_system_status'),
    path('api/recent-activities/', views.recent_activities_api, name='api_recent_activities'),
    path('api/close-trade/', views.close_trade_api, name='api_close_trade'),
    path('api/cancel-trade/', views.cancel_trade_api, name='api_cancel_trade'),
    path('api/trade-status/<int:trade_id>/', views.trade_status_api, name='api_trade_status'),
    path('api/check-connection/<str:service>/', views.check_single_connection, name='check_single_connection'),
    path('api/trigger-scrape/', views.trigger_scrape_api, name='api_trigger_scrape'),
    path('api/trigger-analysis/', views.trigger_analysis_ajax, name='api_trigger_analysis'),
    path('api/add-source/', views.add_source_api, name='api_add_source'),
    path('api/post-analysis/<int:post_id>/', views.get_post_analysis_ajax, name='api_post_analysis'),
    path('api/public-posts/', views.public_posts_api, name='public_posts_api'),
    path('api/toggle-bot-status/', views.toggle_bot_status, name='api_toggle_bot_status'),
    # Deprecated analyze-source endpoints kept temporarily (to be removed after UI consolidation)
    # path('analyze-source/', views.analyze_source_page, name='analyze_source'),
    # path('api/analyze-source/', views.analyze_source_api, name='analyze_source_api'),
    # path('api/create-source-from-analysis/', views.create_source_from_analysis_api, name='create_source_from_analysis'),
    path('api/', include(router.urls)),
]
